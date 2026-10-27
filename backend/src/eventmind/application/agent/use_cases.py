"""Use-case'ы агента (A1, A3): ход диалога, подтверждение изменения, сброс.

Ход (`AgentTurn`): реплика пользователя → цикл «LLM выбирает инструмент →
инструмент выполняется → результат возвращается модели» до текстового ответа
или до лимита (шаги, токены). Изменения модели пользователя не выполняются
сразу: ход останавливается с `pending` — интерфейс показывает «Да / Нет»,
подтверждение выполняет `ConfirmAgentAction`.

Деградация: LLM недоступна на первом шаге — `stop_reason="llm_unavailable"`,
интерфейс отвечает без агента (бот — прямым поиском); лента, поиск, кнопки и
дайджесты от агента не зависят.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import ValidationError

from eventmind.application.agent.config import AgentConfig
from eventmind.application.agent.prompts import build_system_prompt
from eventmind.application.agent.session import (
    AgentSession,
    AgentSessionStore,
    PendingAction,
    new_id,
)
from eventmind.application.agent.tools import (
    AgentToolbox,
    ToolContext,
    ToolError,
    ToolOutput,
    clean_text,
    profile_data,
)
from eventmind.application.ports.agent import (
    AgentJournal,
    AgentTurnRecord,
    StopReason,
    ToolCallRecord,
)
from eventmind.application.ports.cache import Cache
from eventmind.application.ports.llm import LLMMessage, ToolCall, ToolCallingLLM
from eventmind.application.ports.recommender import RecommendationUnitOfWorkFactory
from eventmind.application.ports.security import Clock
from eventmind.domain.events.entities import Event
from eventmind.domain.recommender.user_model import UserProfile

_logger = structlog.get_logger("eventmind.agent")

_TOPICS_KEY = "agent:topics:v1"
_TOPICS_TTL = 3600
_TOPICS_LIMIT = 60

_YES = {"да", "ага", "ок", "окей", "давай", "подтверждаю", "yes", "y", "+", "конечно"}
_NO = {"нет", "не", "не надо", "отмена", "отменить", "no", "n", "-"}
_PUNCT_RE = re.compile(r"[^\w\s+-]")

_EMPTY_REPLY = "Напишите, что ищете: тему, город, даты — или расскажите о своих интересах."
_UNAVAILABLE_REPLY = "Помощник сейчас недоступен. Лента и поиск работают как обычно."
_STEP_LIMIT_REPLY = "Не успел довести поиск до конца — вот что удалось найти."
_TOKEN_LIMIT_REPLY = "Запрос получился слишком длинным — вот что удалось найти."
_FALLBACK_ANSWER = "Готово."
_DROPPED_PENDING = "Предложенное изменение не применено: пользователь его не подтвердил."


@dataclass(slots=True)
class AgentReply:
    text: str
    events: list[Event] = field(default_factory=list)
    pending: PendingAction | None = None
    stop_reason: StopReason = "answer"
    steps: int = 0
    tokens: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return self.stop_reason == "llm_unavailable"


def confirmation_intent(text: str) -> bool | None:
    """«да» / «нет» текстом вместо кнопки; None — это новый запрос."""
    normalized = _PUNCT_RE.sub("", text.casefold()).strip()
    if normalized in _YES:
        return True
    if normalized in _NO:
        return False
    return None


def _tool_message(call: ToolCall, payload: dict[str, Any], limit: int) -> LLMMessage:
    content = json.dumps(payload, ensure_ascii=False, default=str)
    if len(content) > limit:
        content = content[:limit] + "…(обрезано)"
    return LLMMessage(role="tool", content=content, tool_call_id=call.id)


class _TopicCatalog:
    """Темы каталога для промпта (кэш на час — каталог меняется медленно)."""

    def __init__(self, uow_factory: RecommendationUnitOfWorkFactory, cache: Cache) -> None:
        self._uow_factory = uow_factory
        self._cache = cache

    async def get(self) -> list[str]:
        cached = await self._cache.get(_TOPICS_KEY)
        if cached:
            return list(json.loads(cached))
        async with self._uow_factory() as uow:
            topics = await uow.known_topic_codes(limit=_TOPICS_LIMIT)
        await self._cache.set(_TOPICS_KEY, json.dumps(topics), ttl_seconds=_TOPICS_TTL)
        return topics


class _AgentBase:
    def __init__(
        self,
        llm: ToolCallingLLM,
        toolbox: AgentToolbox,
        sessions: AgentSessionStore,
        journal: AgentJournal,
        uow_factory: RecommendationUnitOfWorkFactory,
        cache: Cache,
        clock: Clock,
        config: AgentConfig,
    ) -> None:
        self._llm = llm
        self._toolbox = toolbox
        self._sessions = sessions
        self._journal = journal
        self._uow_factory = uow_factory
        self._topics = _TopicCatalog(uow_factory, cache)
        self._clock = clock
        self._config = config

    async def _record(
        self,
        user_id: int,
        session: AgentSession,
        reply: AgentReply,
        *,
        channel: str,
        started: float,
    ) -> None:
        turn = AgentTurnRecord(
            user_id=user_id,
            session_id=session.session_id,
            channel=channel,
            stop_reason=reply.stop_reason,
            steps=reply.steps,
            tokens=reply.tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tool_calls=reply.tool_calls,
        )
        _logger.info(
            "agent_turn",
            user=user_id,
            session=session.session_id,
            channel=channel,
            stop=reply.stop_reason,
            steps=reply.steps,
            tokens=reply.tokens,
            tools=[f"{c.tool}:{c.status}" for c in reply.tool_calls],
        )
        try:
            await self._journal.record(turn)
        except Exception as exc:  # журнал не должен ломать ответ
            _logger.warning("agent_journal_failed", error=str(exc))

    async def _apply_pending(
        self, ctx: ToolContext, pending: PendingAction, *, approve: bool
    ) -> AgentReply:
        """Выполнить (или отклонить) отложенное изменение и дописать итог в историю
        ответом ассистента — он идёт сразу за ответом инструмента
        «awaiting_confirmation», так что история остаётся валидной для провайдеров."""
        session = ctx.session
        session.pending = None
        tool = self._toolbox.get(pending.tool)
        record = ToolCallRecord(
            tool=pending.tool, arguments=pending.arguments, status="declined", step=0
        )
        if not approve:
            text = "Хорошо, ничего не меняю."
        elif tool is None:
            record.status, record.error = "rejected", "tool_not_allowed"
            text = "Это действие больше недоступно."
        else:
            started = time.perf_counter()
            try:
                args = tool.args_model.model_validate(pending.arguments)
                await tool.run(ctx, args)
                record.status = "confirmed"
                text = "✅ Готово. " + pending.description
            except Exception as exc:
                _logger.warning("agent_pending_failed", tool=pending.tool, error=str(exc))
                record.status, record.error = "error", str(exc)[:500]
                text = "Не получилось применить изменение — попробуйте позже."
            record.latency_ms = int((time.perf_counter() - started) * 1000)
        session.messages.append(LLMMessage(role="assistant", content=text))
        return AgentReply(text=text, stop_reason="resolved", tool_calls=[record])


class AgentTurn(_AgentBase):
    async def execute(self, user_id: int, message: str, *, channel: str = "web") -> AgentReply:
        started = time.perf_counter()
        text = clean_text(message, self._config.message_max_chars)
        if not text:
            return AgentReply(text=_EMPTY_REPLY, stop_reason="empty")

        session = await self._sessions.load(user_id)
        ctx = ToolContext(user_id=user_id, session=session, now=self._clock.now())

        if session.pending is not None:
            decision = confirmation_intent(text)
            if decision is not None:
                session.messages.append(LLMMessage(role="user", content=text))
                reply = await self._apply_pending(ctx, session.pending, approve=decision)
                await self._sessions.save(user_id, session)
                await self._record(user_id, session, reply, channel=channel, started=started)
                return reply
            # новый запрос вместо ответа — предложенное изменение отменяется
            session.pending = None
            session.messages.append(LLMMessage(role="assistant", content=_DROPPED_PENDING))

        session.messages.append(LLMMessage(role="user", content=text))
        reply = await self._loop(ctx)
        if reply.stop_reason == "llm_unavailable" and reply.steps == 0:
            session.messages.pop()  # реплику обработает интерфейс без агента
        await self._sessions.save(user_id, session)
        await self._record(user_id, session, reply, channel=channel, started=started)
        return reply

    async def _system_prompt(self, ctx: ToolContext) -> str:
        try:
            async with self._uow_factory() as uow:
                profile = await uow.get_profile(ctx.user_id)
                prefs = await uow.get_user_prefs(ctx.user_id)
            topics = await self._topics.get()
        except Exception as exc:  # контекст — не критичен для ответа
            _logger.warning("agent_context_failed", error=str(exc))
            profile, prefs, topics = None, None, []
        data = profile_data(profile or UserProfile(user_id=ctx.user_id), prefs)
        return build_system_prompt(ctx.now, profile=data, topics=topics)

    async def _loop(self, ctx: ToolContext) -> AgentReply:
        cfg = self._config
        session = ctx.session
        system = LLMMessage(role="system", content=await self._system_prompt(ctx))
        specs = self._toolbox.specs()
        reply = AgentReply(text="")
        cards: list[Event] = []

        for step in range(1, cfg.max_steps + 1):
            try:
                out = await self._llm.complete_with_tools(
                    [system, *session.messages], specs, temperature=cfg.temperature
                )
            except Exception as exc:
                _logger.warning("agent_llm_failed", step=step, error=str(exc))
                reply.stop_reason = "llm_unavailable"
                reply.text = _UNAVAILABLE_REPLY
                break
            reply.steps = step
            reply.tokens += out.usage.total_tokens
            calls = out.tool_calls[: cfg.max_tool_calls_per_step]
            session.messages.append(
                LLMMessage(role="assistant", content=out.text, tool_calls=calls)
            )
            if not calls:
                reply.text = out.text.strip() or _FALLBACK_ANSWER
                break

            for call in calls:
                payload, output, record = await self._invoke(ctx, call, step)
                reply.tool_calls.append(record)
                session.messages.append(_tool_message(call, payload, cfg.tool_result_max_chars))
                if output is not None and output.events:
                    cards = output.events
                    session.remember_shown([e.id for e in output.events if e.id is not None])
                if record.status == "pending" and reply.pending is None:
                    reply.pending = session.pending

            if reply.pending is not None:
                reply.stop_reason = "confirmation"
                lead = out.text.strip()
                reply.text = f"{lead}\n\n{reply.pending.description}" if lead else (
                    reply.pending.description
                )
                break
            if reply.tokens >= cfg.max_tokens_per_turn:
                reply.stop_reason = "token_limit"
                reply.text = _TOKEN_LIMIT_REPLY
                break
        else:
            reply.stop_reason = "step_limit"
            reply.text = _STEP_LIMIT_REPLY

        reply.events = cards[: cfg.max_cards]
        return reply

    async def _invoke(
        self, ctx: ToolContext, call: ToolCall, step: int
    ) -> tuple[dict[str, Any], ToolOutput | None, ToolCallRecord]:
        record = ToolCallRecord(tool=call.name, arguments=call.arguments, status="ok", step=step)
        tool = self._toolbox.get(call.name)
        if tool is None:
            record.status, record.error = "rejected", "tool_not_allowed"
            return {"error": f"Инструмент {call.name} недоступен"}, None, record
        try:
            args = tool.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            record.status, record.error = "invalid", str(exc)[:500]
            details = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
            return {"error": "invalid_arguments", "details": details}, None, record

        if tool.requires_confirmation:
            if ctx.session.pending is not None:
                record.status, record.error = "rejected", "one_change_at_a_time"
                return {"error": "Одно изменение за раз — дождись подтверждения"}, None, record
            ctx.session.pending = PendingAction(
                id=new_id(),
                tool=tool.name,
                arguments=args.model_dump(),
                description=tool.describe(args),
            )
            record.status = "pending"
            return (
                {"status": "awaiting_confirmation", "description": ctx.session.pending.description},
                None,
                record,
            )

        started = time.perf_counter()
        try:
            output = await tool.run(ctx, args)
        except ToolError as exc:
            record.status, record.error = "error", str(exc)
            return {"error": str(exc)}, None, record
        except Exception as exc:
            _logger.warning("agent_tool_failed", tool=call.name, error=str(exc))
            record.status, record.error = "error", str(exc)[:500]
            return {"error": "Инструмент временно недоступен"}, None, record
        finally:
            record.latency_ms = int((time.perf_counter() - started) * 1000)
        return output.data, output, record


class ConfirmAgentAction(_AgentBase):
    """Кнопка «Да / Нет» под предложенным изменением."""

    async def execute(
        self, user_id: int, action_id: str, *, approve: bool, channel: str = "web"
    ) -> AgentReply:
        started = time.perf_counter()
        session = await self._sessions.load(user_id)
        pending = session.pending
        if pending is None or pending.id != action_id:
            return AgentReply(text="Это предложение уже неактуально.", stop_reason="resolved")
        ctx = ToolContext(user_id=user_id, session=session, now=self._clock.now())
        reply = await self._apply_pending(ctx, pending, approve=approve)
        await self._sessions.save(user_id, session)
        await self._record(user_id, session, reply, channel=channel, started=started)
        return reply


@dataclass(slots=True)
class AgentHistoryItem:
    role: str  # user | assistant
    text: str


class GetAgentHistory:
    """Видимая часть диалога (для перерисовки чата в вебе)."""

    def __init__(self, sessions: AgentSessionStore) -> None:
        self._sessions = sessions

    async def execute(self, user_id: int) -> tuple[list[AgentHistoryItem], PendingAction | None]:
        session = await self._sessions.load(user_id)
        items = [
            AgentHistoryItem(role=m.role, text=m.content)
            for m in session.messages
            if m.role in ("user", "assistant") and m.content.strip()
        ]
        return items, session.pending


class ResetAgentSession:
    def __init__(self, sessions: AgentSessionStore) -> None:
        self._sessions = sessions

    async def execute(self, user_id: int) -> None:
        await self._sessions.reset(user_id)
