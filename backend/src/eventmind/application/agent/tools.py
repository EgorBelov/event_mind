"""Инструменты агента (A2) — тонкие обёртки над существующими use-case'ами.

Правила (A3):
- `user_id` берётся только из контекста хода, никогда из аргументов модели;
- аргументы валидируются pydantic-схемой инструмента, ошибка возвращается
  модели текстом (она может исправиться на следующем шаге);
- изменения модели пользователя (профиль, город/формат) — только после
  подтверждения пользователем (`requires_confirmation`);
- оценивать можно только события, показанные в этом диалоге (модель не
  должна ставить лайки по выдуманным id);
- тексты событий — недоверенные данные со сторонних сайтов: в ответ модели
  они идут урезанными и очищенными от управляющих символов.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from eventmind.application.accounts.use_cases import UpdateProfile
from eventmind.application.agent.session import AgentSession
from eventmind.application.ports.cache import Cache
from eventmind.application.ports.llm import ToolSpec
from eventmind.application.ports.recommender import RecommendationUnitOfWorkFactory, UserPrefs
from eventmind.application.ports.search import SearchRepository
from eventmind.application.recommender.explain import ExplainEvent
from eventmind.application.recommender.profile import ApplyProfileChanges, GetUserProfile
from eventmind.application.recommender.use_cases import (
    GetRecommendations,
    RecordInteraction,
    recommendation_cache_key,
)
from eventmind.application.search.schemas import SearchFilters
from eventmind.application.search.use_cases import NlSearch
from eventmind.domain.events.entities import Event
from eventmind.domain.events.taxonomy import (
    canonicalize_city,
    city_label,
    slugify_code,
    topic_title,
)
from eventmind.domain.recommender.user_model import ProfileChanges, UserProfile

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SUMMARY_LEN = 240
_DESCRIPTION_LEN = 1500

FormatArg = Literal["online", "offline", "hybrid"]
EventTypeArg = Literal["meetup", "conference", "webinar", "workshop", "hackathon", "lecture"]
FORMAT_LABELS = {"online": "онлайн", "offline": "офлайн", "hybrid": "гибрид", "": "не важно"}


class ToolError(Exception):
    """Ошибка, которую модель должна увидеть текстом (правило, нет события и т.п.)."""


@dataclass(slots=True)
class ToolContext:
    user_id: int
    session: AgentSession
    now: datetime


@dataclass(slots=True)
class ToolOutput:
    data: dict[str, Any]  # ответ модели (сериализуется в JSON)
    events: list[Event] = field(default_factory=list)  # карточки для интерфейса


def clean_text(value: str | None, limit: int) -> str:
    text = _CONTROL_RE.sub(" ", value or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def event_brief(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": clean_text(event.title, 200),
        "date": event.date,
        "city": event.city,
        "format": event.format,
        "type": event.event_type,
        "level": event.seniority or event.level,
        "topics": event.topics,
        "summary": clean_text(event.summary or event.description, _SUMMARY_LEN),
    }


def profile_data(profile: UserProfile, prefs: UserPrefs | None) -> dict[str, Any]:
    return {
        "role": profile.role,
        "level": profile.level,
        "stack": profile.stack,
        "interests": profile.interests,
        "anti_interests": profile.anti_interests,
        "goals": profile.goals,
        "city": prefs.city if prefs else None,
        "preferred_format": prefs.preferred_format if prefs else None,
    }


def _strip_titles(node: Any) -> Any:
    """Упростить JSON Schema pydantic под всех провайдеров: без `title`, без
    `anyOf [X, null]` (необязательность задаётся отсутствием в `required`)."""
    if isinstance(node, dict):
        node = {k: _strip_titles(v) for k, v in node.items() if k != "title"}
        variants = node.get("anyOf")
        if isinstance(variants, list):
            non_null = [v for v in variants if v != {"type": "null"}]
            if len(non_null) == 1:
                node.pop("anyOf")
                node = {**non_null[0], **node}
        if node.get("default") is None:
            node.pop("default", None)
        return node
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


class AgentTool:
    """Базовый инструмент: имя, описание, схема аргументов, выполнение."""

    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]
    requires_confirmation: ClassVar[bool] = False

    @classmethod
    def spec(cls) -> ToolSpec:
        """Схема для модели — без зависимостей инструмента (нужна и офлайн-оценке)."""
        schema = _strip_titles(cls.args_model.model_json_schema())
        schema.setdefault("properties", {})
        return ToolSpec(name=cls.name, description=cls.description, parameters=schema)

    def describe(self, args: BaseModel) -> str:
        """Человеческое описание действия — для запроса подтверждения."""
        return self.name

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        raise NotImplementedError


# ── чтение: поиск, выдача, карточка, объяснение, профиль ──────────────────────
class SearchArgs(BaseModel):
    query: str = Field(
        default="", max_length=200, description="Ключевые слова, которые не легли в фильтры"
    )
    topics: list[str] = Field(
        default_factory=list, max_length=8, description="Темы — slug'и каталога (ai_ml, backend…)"
    )
    city: str | None = Field(default=None, description="Город (moscow, spb, perm…)")
    format: FormatArg | None = None
    event_type: EventTypeArg | None = None
    date_from: str | None = Field(default=None, description="Начало диапазона, YYYY-MM-DD")
    date_to: str | None = Field(default=None, description="Конец диапазона, YYYY-MM-DD")
    limit: int = Field(default=5, ge=1, le=10)


class SearchEventsTool(AgentTool):
    name = "search_events"
    description = (
        "Поиск предстоящих IT-мероприятий по фильтрам. Если строгих совпадений нет, "
        "фильтры ослабляются и возвращается одно ближайшее событие (relaxed=true)."
    )
    args_model = SearchArgs

    def __init__(self, search: NlSearch) -> None:
        self._search = search

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        assert isinstance(args, SearchArgs)
        filters = SearchFilters(
            date_from=args.date_from,
            date_to=args.date_to,
            city=args.city,
            event_type=args.event_type,
            format=args.format,
            topics=args.topics,
            free_text=args.query,
        )
        result = await self._search.search_filters(filters, limit=args.limit)
        data: dict[str, Any] = {
            "relaxed": result.relaxed,
            "count": len(result.results),
            "events": [event_brief(e) for e in result.results],
        }
        if result.relaxed and result.results:
            data["note"] = "Точных совпадений нет — показано ближайшее после ослабления фильтров"
        return ToolOutput(data=data, events=result.results)


class RecommendArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=10)
    format: FormatArg | None = Field(default=None, description="Оставить только этот формат")
    topics: list[str] = Field(
        default_factory=list, max_length=8, description="Оставить события с этими темами"
    )
    exclude_shown: bool = Field(
        default=True, description="Не повторять события, уже показанные в диалоге"
    )


class RecommendTool(AgentTool):
    name = "recommend"
    description = (
        "Персональная подборка под модель пользователя (интересы, оценки, город, формат). "
        "Для «что посоветуешь», «подбери мне»."
    )
    args_model = RecommendArgs

    def __init__(self, recommendations: GetRecommendations, events: SearchRepository) -> None:
        self._recommendations = recommendations
        self._events = events

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        assert isinstance(args, RecommendArgs)
        items = await self._recommendations.execute(ctx.user_id)
        topics = {slugify_code(t) for t in args.topics if slugify_code(t)}
        shown = set(ctx.session.shown_event_ids) if args.exclude_shown else set()
        chosen = [
            it
            for it in items
            if it.event_id not in shown
            and (args.format is None or it.format == args.format)
            and (not topics or topics & set(it.topics))
        ][: args.limit]
        events = await self._events.get_events([it.event_id for it in chosen])
        data: dict[str, Any] = {"count": len(events), "events": [event_brief(e) for e in events]}
        if not events:
            data["note"] = (
                "В персональной выдаче нет подходящих событий — попробуй search_events "
                "или ослабь условия"
            )
        return ToolOutput(data=data, events=events)


class EventIdArgs(BaseModel):
    event_id: int = Field(ge=1, description="id события из результатов инструментов")


class GetEventTool(AgentTool):
    name = "get_event"
    description = "Подробности о событии: описание, аудитория, стек, ссылка."
    args_model = EventIdArgs

    def __init__(self, events: SearchRepository) -> None:
        self._events = events

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        assert isinstance(args, EventIdArgs)
        event = await self._events.get_event(args.event_id)
        if event is None:
            raise ToolError(f"Событие {args.event_id} не найдено")
        data = {
            **event_brief(event),
            "description": clean_text(event.description, _DESCRIPTION_LEN),
            "audience": clean_text(event.target_audience, 300),
            "tech_stack": event.tech_stack,
            "url": event.source_url,
        }
        return ToolOutput(data=data, events=[event])


class ExplainEventTool(AgentTool):
    name = "explain_event"
    description = (
        "Почему событие подходит (или не подходит) пользователю: совпадение тем, "
        "близость к профилю, город, формат, дата. Для вопросов «почему это?»."
    )
    args_model = EventIdArgs

    def __init__(self, explain: ExplainEvent) -> None:
        self._explain = explain

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        assert isinstance(args, EventIdArgs)
        result = await self._explain.execute(
            args.event_id, user_id=ctx.user_id, with_summary=False
        )
        if result is None:
            raise ToolError(f"Событие {args.event_id} не найдено")
        data = {
            "event": event_brief(result.event),
            "description": clean_text(result.event.description, _DESCRIPTION_LEN),
            "reasons": result.reasons,
            # что реально подняло событие в подборке: доля компоненты в балле
            "contributions": {c.label: f"{c.share:.0%}" for c in result.contributions[:4]},
        }
        return ToolOutput(data=data, events=[result.event])


class NoArgs(BaseModel):
    pass


class GetProfileTool(AgentTool):
    name = "get_profile"
    description = "Текущая модель пользователя: роль, уровень, стек, интересы, анти-интересы, цели."
    args_model = NoArgs

    def __init__(
        self, profiles: GetUserProfile, uow_factory: RecommendationUnitOfWorkFactory
    ) -> None:
        self._profiles = profiles
        self._uow_factory = uow_factory

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        profile = await self._profiles.execute(ctx.user_id)
        async with self._uow_factory() as uow:
            prefs = await uow.get_user_prefs(ctx.user_id)
        return ToolOutput(data=profile_data(profile, prefs))


# ── действия: оценка (сразу), правка профиля и настроек (с подтверждением) ───
class FeedbackArgs(BaseModel):
    event_id: int = Field(ge=1)
    action: Literal["like", "dislike", "save"] = Field(
        description="like — нравится, save — сохранить, dislike — не показывать похожее"
    )


class RecordFeedbackTool(AgentTool):
    name = "record_feedback"
    description = (
        "Оценка события, которое пользователь видел в этом диалоге: нравится, сохранить "
        "или не интересно. Меняет модель пользователя."
    )
    args_model = FeedbackArgs

    def __init__(self, record: RecordInteraction) -> None:
        self._record = record

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        assert isinstance(args, FeedbackArgs)
        if args.event_id not in ctx.session.shown_event_ids:
            raise ToolError("Оценивать можно только события, показанные в этом диалоге")
        await self._record.execute(ctx.user_id, args.event_id, args.action)
        return ToolOutput(data={"ok": True, "event_id": args.event_id, "action": args.action})


def _topics(values: Sequence[str]) -> str:
    return ", ".join(topic_title(slugify_code(v)) for v in values)


class ProfileChangeArgs(BaseModel):
    add_interests: list[str] = Field(default_factory=list, max_length=10)
    remove_interests: list[str] = Field(default_factory=list, max_length=10)
    add_anti_interests: list[str] = Field(
        default_factory=list, max_length=10, description="Темы, которые НЕ интересны"
    )
    remove_anti_interests: list[str] = Field(default_factory=list, max_length=10)
    add_goals: list[str] = Field(
        default_factory=list, max_length=5, description="Цели своими словами («перейти в ML»)"
    )
    remove_goals: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _not_empty(self) -> ProfileChangeArgs:
        if self.to_changes().is_empty:
            raise ValueError("Нужно хотя бы одно изменение")
        return self

    def to_changes(self) -> ProfileChanges:
        return ProfileChanges(
            add_interests=tuple(self.add_interests),
            remove_interests=tuple(self.remove_interests),
            add_anti_interests=tuple(self.add_anti_interests),
            remove_anti_interests=tuple(self.remove_anti_interests),
            add_goals=tuple(g.strip()[:200] for g in self.add_goals),
            remove_goals=tuple(self.remove_goals),
        )


class UpdateProfileTool(AgentTool):
    name = "update_profile"
    description = (
        "Изменить модель пользователя: интересы, анти-интересы (темы — slug'и каталога), "
        "цели. Применяется только после подтверждения пользователем."
    )
    args_model = ProfileChangeArgs
    requires_confirmation = True

    def __init__(self, apply: ApplyProfileChanges) -> None:
        self._apply = apply

    def describe(self, args: BaseModel) -> str:
        assert isinstance(args, ProfileChangeArgs)
        lines = []
        for label, values in (
            ("добавить в интересы", args.add_interests),
            ("убрать из интересов", args.remove_interests),
            ("не показывать темы", args.add_anti_interests),
            ("снова показывать темы", args.remove_anti_interests),
        ):
            if values:
                lines.append(f"• {label}: {_topics(values)}")
        if args.add_goals:
            lines.append("• добавить цели: " + "; ".join(args.add_goals))
        if args.remove_goals:
            lines.append("• убрать цели: " + "; ".join(args.remove_goals))
        return "Изменить профиль:\n" + "\n".join(lines)

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        assert isinstance(args, ProfileChangeArgs)
        profile = await self._apply.execute(ctx.user_id, args.to_changes())
        return ToolOutput(data={"ok": True, "profile": profile_data(profile, None)})


class SettingsArgs(BaseModel):
    city: str | None = Field(default=None, max_length=64, description="Город; «any» — не важно")
    format: Literal["online", "offline", "hybrid", "any"] | None = Field(
        default=None, description="Предпочитаемый формат; «any» — не важно"
    )

    @model_validator(mode="after")
    def _not_empty(self) -> SettingsArgs:
        if self.city is None and self.format is None:
            raise ValueError("Нужно указать город или формат")
        return self


def _setting(value: str | None) -> str | None:
    if value is None:
        return None
    return "" if value.strip().lower() in ("any", "") else value.strip()


class UpdateSettingsTool(AgentTool):
    name = "update_settings"
    description = (
        "Изменить город или предпочитаемый формат пользователя (влияет на подборку). "
        "Применяется только после подтверждения пользователем."
    )
    args_model = SettingsArgs
    requires_confirmation = True

    def __init__(self, update: UpdateProfile, cache: Cache) -> None:
        self._update = update
        self._cache = cache

    def describe(self, args: BaseModel) -> str:
        assert isinstance(args, SettingsArgs)
        parts = []
        city = _setting(args.city)
        if city is not None:
            parts.append(f"город → {city_label(canonicalize_city(city)) if city else 'не важно'}")
        fmt = _setting(args.format)
        if fmt is not None:
            parts.append(f"формат → {FORMAT_LABELS.get(fmt, fmt)}")
        return "Изменить настройки: " + "; ".join(parts)

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolOutput:
        assert isinstance(args, SettingsArgs)
        user = await self._update.execute(
            ctx.user_id, city=_setting(args.city), preferred_format=_setting(args.format)
        )
        await self._cache.delete(recommendation_cache_key(ctx.user_id))
        return ToolOutput(
            data={"ok": True, "city": user.city, "preferred_format": user.preferred_format}
        )


class AgentToolbox:
    """Реестр инструментов + белый список (A3)."""

    def __init__(
        self, tools: Sequence[AgentTool], *, allowed: frozenset[str] | None = None
    ) -> None:
        self._tools = {
            t.name: t for t in tools if allowed is None or t.name in allowed
        }

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    @property
    def names(self) -> list[str]:
        return list(self._tools)


# Все инструменты агента в порядке регистрации (для оценки A6 — схемы без зависимостей).
ALL_TOOLS: tuple[type[AgentTool], ...] = (
    SearchEventsTool,
    RecommendTool,
    GetEventTool,
    ExplainEventTool,
    GetProfileTool,
    RecordFeedbackTool,
    UpdateProfileTool,
    UpdateSettingsTool,
)
