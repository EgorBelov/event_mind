"""NL-поиск: LLM-extract фильтров → канонизация → строгий поиск → relax-fallback.

Портирует логику `legacy/app/api/services/nl_search_service.py`: строгий проход,
при 0 совпадений поэтапно снимаем фильтры (free_text → topics → format →
event_type → city → date) и показываем 1 ближайшее событие.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as _date

import structlog

from eventmind.application.ports.llm import LLMGateway, LLMMessage
from eventmind.application.ports.search import SearchQuery, SearchRepository
from eventmind.application.ports.security import Clock
from eventmind.application.search.schemas import SearchFilters
from eventmind.domain.events.entities import Event
from eventmind.domain.events.taxonomy import canonicalize_city, slugify_code
from eventmind.domain.events.value_objects import ALLOWED_EVENT_TYPE, ALLOWED_FORMAT

_logger = structlog.get_logger("eventmind.search")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

# Порядок снятия фильтров при relax (от наименее до наиболее важного).
_RELAX_ORDER = ("free_text", "topics", "format", "event_type", "city", "date")

_SYSTEM_PROMPT = (
    "Ты извлекаешь структурированные фильтры из фразы поиска IT-событий. "
    "Правила: «конференции»→event_type=conference, «митапы»→meetup, «вебинары»→webinar. "
    "«онлайн»→format=online (НЕ в free_text), «офлайн»→offline. Город→city. "
    "Даты: «завтра/на этой неделе/с 3 по 10 июня»→date_from/date_to (YYYY-MM-DD); "
    "точная дата→date_from==date_to; нет дат→null. Темы→topics (slug'и). "
    "free_text — остаток без дат/города/типа/формата. Не придумывай фильтры, "
    "которых нет в запросе."
)


@dataclass(slots=True)
class SearchResult:
    results: list[Event] = field(default_factory=list)
    relaxed: bool = False
    filters: dict[str, object] = field(default_factory=dict)


def _valid_iso(raw: str | None) -> str | None:
    if not raw:
        return None
    m = _ISO_RE.match(raw.strip())
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _canonicalize(filters: SearchFilters) -> SearchQuery:
    city = canonicalize_city(filters.city) or None if filters.city else None
    etype = slugify_code(filters.event_type) if filters.event_type else None
    if etype not in ALLOWED_EVENT_TYPE or etype in (None, "unknown"):
        etype = None
    fmt = slugify_code(filters.format) if filters.format else None
    if fmt not in ALLOWED_FORMAT or fmt in (None, "unknown", "any"):
        fmt = None
    topics = [slugify_code(t) for t in filters.topics if t and slugify_code(t)]
    return SearchQuery(
        date_from=_valid_iso(filters.date_from),
        date_to=_valid_iso(filters.date_to),
        city=city,
        event_type=etype,
        format=fmt,
        topics=topics,
        free_text=filters.free_text.strip(),
    )


def _drop(query: SearchQuery, key: str) -> SearchQuery:
    q = SearchQuery(**vars(query))
    if key == "free_text":
        q.free_text = ""
    elif key == "topics":
        q.topics = []
    elif key == "date":
        q.date_from = q.date_to = None
    else:
        setattr(q, key, None)
    return q


class NlSearch:
    def __init__(self, llm: LLMGateway, repository: SearchRepository, clock: Clock) -> None:
        self._llm = llm
        self._repo = repository
        self._clock = clock

    async def execute(self, query_text: str, *, limit: int = 5) -> SearchResult:
        now = self._clock.now()
        filters = await self._extract(query_text)
        query = _canonicalize(filters)

        strict = await self._repo.search(query, limit=limit, now=now)
        filters_dict = vars(query).copy()
        if strict:
            return SearchResult(results=strict, relaxed=False, filters=filters_dict)

        # relax: поэтапно снимаем фильтры, показываем 1 ближайшее событие
        relaxed_query = query
        for key in _RELAX_ORDER:
            relaxed_query = _drop(relaxed_query, key)
            found = await self._repo.search(relaxed_query, limit=1, now=now)
            if found:
                return SearchResult(results=found, relaxed=True, filters=filters_dict)
        return SearchResult(results=[], relaxed=True, filters=filters_dict)

    async def _extract(self, query_text: str) -> SearchFilters:
        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=query_text),
        ]
        try:
            return await self._llm.structured_output(messages, SearchFilters)
        except Exception as exc:
            _logger.warning("nl_search_extract_failed", error=str(exc))
            return SearchFilters(free_text=query_text)


class GetEvent:
    def __init__(self, repository: SearchRepository) -> None:
        self._repo = repository

    async def execute(self, event_id: int) -> Event | None:
        return await self._repo.get_event(event_id)
