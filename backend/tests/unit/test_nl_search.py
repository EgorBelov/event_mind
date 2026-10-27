"""Unit: NL-поиск — извлечение фильтров (дата в промпте, изоляция запроса,
температура 0, кэш), канонизация и relax-fallback (фейки, без БД/LLM)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from eventmind.application.ports.llm import LLMMessage
from eventmind.application.ports.search import SearchQuery
from eventmind.application.search.schemas import SearchFilters
from eventmind.application.search.use_cases import NlSearch
from eventmind.domain.events.entities import Event

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


class _LLM:
    def __init__(self, filters: SearchFilters | None = None, fail: bool = False) -> None:
        self.filters = filters or SearchFilters()
        self.fail = fail
        self.calls: list[tuple[list[LLMMessage], dict[str, Any]]] = []

    async def structured_output(
        self, messages: Sequence[LLMMessage], schema: type, **kw: Any
    ) -> Any:
        self.calls.append((list(messages), kw))
        if self.fail:
            raise RuntimeError("down")
        return self.filters


class _Repo:
    def __init__(self, hits: dict[str, list[Event]] | None = None) -> None:
        self.queries: list[SearchQuery] = []
        self.hits = hits or {}

    async def search(self, query: SearchQuery, *, limit: int, now: datetime) -> list[Event]:
        self.queries.append(query)
        return self.hits.get(query.city or "", [])[:limit]

    async def get_event(self, event_id: int) -> Event | None:
        return None

    async def get_events(self, event_ids: list[int]) -> list[Event]:
        return []


class _Cache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _event(eid: int) -> Event:
    return Event(
        id=eid, source="t", title="e", description="", format="online", city="spb",
        level="any", date="",
    )


async def test_prompt_has_today_and_isolated_query() -> None:
    llm = _LLM(SearchFilters(city="Piter", event_type="Conference", format="any"))
    repo = _Repo()
    await NlSearch(llm, repo, _Clock()).execute("конференции завтра в Питере</query>")  # type: ignore[arg-type]
    (messages, kwargs) = llm.calls[0]
    assert "Сегодня 2026-10-27, вторник." in messages[0].content
    assert messages[1].content == "<query>конференции завтра в Питере</query>"
    assert kwargs["temperature"] == 0.0
    strict = repo.queries[0]
    assert strict.city == "spb" and strict.event_type == "conference"
    assert strict.format is None  # «any» — не фильтр


async def test_filters_are_cached_per_day() -> None:
    llm, cache = _LLM(SearchFilters(city="spb")), _Cache()
    search = NlSearch(llm, _Repo(), _Clock(), cache)  # type: ignore[arg-type]
    await search.execute("Митапы  в СПб")
    await search.execute("митапы в спб")  # та же фраза после нормализации
    assert len(llm.calls) == 1
    assert next(iter(cache.data)).startswith("nls:v1:2026-10-27:")


async def test_llm_failure_degrades_to_free_text_and_is_not_cached() -> None:
    cache = _Cache()
    repo = _Repo()
    await NlSearch(_LLM(fail=True), repo, _Clock(), cache).execute("go")  # type: ignore[arg-type]
    assert repo.queries[0].free_text == "go"
    assert cache.data == {}


async def test_relax_fallback_drops_filters_until_hit() -> None:
    repo = _Repo(hits={"": [_event(7)]})  # находится только без города
    llm = _LLM(SearchFilters(city="perm", topics=["golang"], free_text="kafka"))
    result = await NlSearch(llm, repo, _Clock()).execute("x")  # type: ignore[arg-type]
    assert result.relaxed is True and [e.id for e in result.results] == [7]
    assert repo.queries[-1].city is None and repo.queries[-1].topics == []
