"""LLM-нормализатор события: structured_output + пост-обработка.

Системный промпт и пост-обработка (enum-валидация, строгая ISO-дата,
defence-in-depth «это вообще IT-событие?») портированы из
`legacy/app/agents/event_normalization/agent.py` — они ловились эмпирически и
критичны для качества. В v2 извлечение делает `LLMGateway.structured_output`
(pydantic-схема), а не ручной JSON-парсинг.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

from eventmind.application.ingestion.schemas import NormalizedEvent
from eventmind.application.ports.llm import LLMGateway, LLMMessage
from eventmind.domain.events.taxonomy import (
    SEED_CITY_LABELS,
    SEED_FORMAT_LABELS,
    SEED_LEVEL_LABELS,
    SEED_TOPICS,
    canonicalize_city,
    slugify_code,
)
from eventmind.domain.events.value_objects import (
    ALLOWED_EVENT_TYPE,
    ALLOWED_FORMAT,
    ALLOWED_SENIORITY,
)

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ]|$)")
_DATE_YEAR_MIN = 2020
_DATE_YEAR_MAX = 2035
_OPEN_SLUG_MAX_LEN = 32


@dataclass(slots=True)
class NormalizedResult:
    """Результат нормализации: чистые поля + признак «это IT-событие»."""

    is_event: bool
    title: str
    description: str
    format: str
    city: str
    level: str
    date: str
    topics: list[str]
    event_type: str
    target_audience: str
    tech_stack: list[str]
    seniority: str
    quality_score: int | None
    hype_score: int | None
    start_at: _dt.datetime | None = None


def _normalize_enum_field(value: object, *, allowed: frozenset[str] | None, default: str) -> str:
    if value is None or not isinstance(value, str):
        return default
    v = value.strip()
    if not v:
        return default
    if allowed is not None:
        return v if v in allowed else default
    if len(v) > _OPEN_SLUG_MAX_LEN or any(ch in v for ch in (" ", "/", "\\", "\n", "\t")):
        return default
    return v


def _validate_iso_date(raw: object) -> str:
    """Строгий YYYY-MM-DD (терпим `...T18:00`), календарная валидация, год в [2020..2035]."""
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    m = _ISO_DATE_RE.match(s)
    if not m:
        return ""
    try:
        d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return ""
    if not (_DATE_YEAR_MIN <= d.year <= _DATE_YEAR_MAX):
        return ""
    return d.isoformat()


def _slug_list(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            continue
        slug = slugify_code(v)
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def postprocess(raw: NormalizedEvent) -> NormalizedResult:
    """Канонизировать поля LLM-ответа + defence-in-depth «событие vs не-событие»."""
    topics = _slug_list(list(raw.topics))

    fmt = _normalize_enum_field(
        slugify_code(raw.format) or raw.format, allowed=ALLOWED_FORMAT, default="unknown"
    )
    event_type = _normalize_enum_field(
        slugify_code(raw.event_type) or raw.event_type,
        allowed=ALLOWED_EVENT_TYPE,
        default="unknown",
    )
    seniority = _normalize_enum_field(
        slugify_code(raw.seniority) or raw.seniority, allowed=ALLOWED_SENIORITY, default="any"
    )
    city_slug = canonicalize_city(raw.city) or raw.city
    city = _normalize_enum_field(city_slug, allowed=None, default="unknown")
    level = _normalize_enum_field(
        slugify_code(raw.level) or raw.level, allowed=None, default="unknown"
    )

    def _clamp(v: object) -> int | None:
        return max(1, min(10, int(v))) if isinstance(v, int | float) else None

    date = _validate_iso_date(raw.date)

    # Defence-in-depth: «не событие» = одновременно нет даты/формата/города/типа.
    if topics:
        no_date = not date
        no_format = fmt in ("", "unknown")
        no_city = city in ("", "unknown", "any")
        no_type = event_type in ("", "unknown")
        if no_date and no_format and no_city and no_type:
            topics = []

    start_at = _dt.datetime.fromisoformat(date) if date else None

    return NormalizedResult(
        is_event=bool(topics),
        title=raw.title.strip(),
        description=raw.description.strip(),
        format=fmt,
        city=city,
        level=level,
        date=date,
        topics=topics,
        event_type=event_type,
        target_audience=raw.target_audience.strip(),
        tech_stack=[t for t in raw.tech_stack if isinstance(t, str)],
        seniority=seniority,
        quality_score=_clamp(raw.quality_score),
        hype_score=_clamp(raw.hype_score),
        start_at=start_at,
    )


_PREFERRED_TOPICS = ", ".join(SEED_TOPICS)
_PREFERRED_CITIES = ", ".join(SEED_CITY_LABELS.keys())
_PREFERRED_LEVELS = ", ".join(SEED_LEVEL_LABELS.keys())
_PREFERRED_FORMATS = ", ".join(SEED_FORMAT_LABELS.keys())

_SYSTEM_PROMPT = f"""
Ты EventNormalizerAgent для системы рекомендаций IT-событий.

Задача: проанализировать сырое описание события, извлечь и нормализовать поля.
Не придумывай факты, если данных недостаточно.

Предпочитаемые значения (используй, когда подходят):
format: {_PREFERRED_FORMATS}
city: {_PREFERRED_CITIES}
level: {_PREFERRED_LEVELS}
topics: {_PREFERRED_TOPICS}
event_type: meetup | conference | webinar | workshop | hackathon | lecture | unknown
seniority: junior | middle | senior | any

Новые значения: если событие не попадает в списки — создай короткий латинский
slug в snake_case (topic "mlops", city "barnaul"). Не плоди дубли ("ml" вместо
"ai_ml" недопустимо). format: вебинар/трансляция → "online"; физический адрес →
"offline"; оба → "hybrid".

ГОРОД (важно для UI/фильтрации):
- Ищи город в location/address/venue и в тексте («г. X», «в X», «X, ул…»).
- Для офлайна ВСЕГДА пытайся определить город из адреса, не сваливай в "unknown".
- Для онлайна с привязкой к городу («Moscow Python онлайн») — город организатора.
- "any" — только глобально-онлайн без города. "unknown" — если города нет нигде.
- Канонические slug'и крупных городов: Москва→"moscow", Санкт-Петербург→"spb",
  Новосибирск→"novosibirsk", Екатеринбург→"ekb", Казань→"kazan",
  Нижний Новгород→"nizhny_novgorod", Челябинск→"chelyabinsk". НЕ эмить "msk",
  "piter", "yekaterinburg" — только канонический slug. Прочие города — короткий
  латинский snake_case транслит (Омск→"omsk").

date — строго YYYY-MM-DD (для диапазона — дата начала); неизвестна → "".
topics — список slug'ов, минимум 1 для IT-событий.
tech_stack — конкретные технологии (["Python","FastAPI","Docker"]).
quality_score (1-10) — информативность для IT-специалиста.
hype_score (1-10) — актуальность темы в IT сейчас.

ФИЛЬТР «ЭТО ВООБЩЕ МЕРОПРИЯТИЕ?»:
Перед IT-фильтром проверь: это дискретное мероприятие (митап/конференция/
вебинар/воркшоп/хакатон/лекция)? Если это пресс-релиз/новость/запуск продукта/
вакансия/поиск партнёров/статья/подкаст/реклама — topics = [] (даже если про IT).
Событие = есть дата ИЛИ площадка ИЛИ программа ИЛИ спикеры (достаточно одного).

ФИЛЬТР НЕ-IT (строгий): если событие не про разработку ПО / данные /
инфраструктуру / кибербезопасность / IT-продукт — topics = [] (даже со словами
«инновации/технологии/AI» без сути). НЕ IT: PR/маркетинг/SMM, HR/рекрутинг,
продажи/сейлз, soft skills/коучинг, мода/фитнес/медицина без IT, бухгалтерия/
финансы/трейдинг без AI/ML, крипта как актив, бизнес-завтраки без техпрограммы.
IT (≥1 тема): разработка (backend/frontend/mobile), DevOps/SRE/облака,
AI/ML/LLM/Data, кибербезопасность, хакатоны/CTF, IT-конференции/митапы.
Граница: «AI в маркетинге» — IT, только если программа содержит технический
контент (модели/инструменты/интеграции), иначе НЕ-IT.
""".strip()

_USER_PROMPT = "Сырое событие:\ntitle: {title}\nописание: {description}\nисточник: {source_url}"


class EventNormalizer:
    """Нормализатор одного события через LLMGateway.structured_output."""

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def normalize(
        self, *, title: str, raw_description: str, source_url: str | None
    ) -> NormalizedResult:
        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=_USER_PROMPT.format(
                    title=title, description=raw_description, source_url=source_url or ""
                ),
            ),
        ]
        extracted = await self._llm.structured_output(messages, NormalizedEvent)
        return postprocess(extracted)
