"""Unit: NL-поиск — извлечение фильтров (дата в промпте, изоляция запроса,
температура 0, кэш), канонизация и relax-fallback (фейки, без БД/LLM)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from eventmind.application.ports.llm import LLMMessage, LLMResult
from eventmind.application.ports.search import SearchQuery
from eventmind.application.search.config import SearchConfig
from eventmind.application.search.schemas import SearchFilters
from eventmind.application.search.use_cases import NlSearch, SimilarEvents
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

    async def complete(self, messages: Sequence[LLMMessage], **kw: Any) -> LLMResult:
        self.calls.append((list(messages), kw))
        if self.fail:
            raise RuntimeError("down")
        return LLMResult(text="Митап о Go и высоконагруженных сервисах.", provider="fake")


class _Repo:
    def __init__(
        self,
        hits: dict[str, list[Event]] | None = None,
        text: list[Event] | None = None,
        semantic: list[Event] | None = None,
    ) -> None:
        self.queries: list[SearchQuery] = []
        self.hits = hits or {}
        self.text = text or []
        self.semantic = semantic or []
        self.text_calls: list[tuple[SearchQuery, str]] = []
        self.semantic_calls: list[tuple[SearchQuery, list[float], float]] = []

    async def search(self, query: SearchQuery, *, limit: int, now: datetime) -> list[Event]:
        self.queries.append(query)
        return self.hits.get(query.city or "", [])[:limit]

    async def text_search(
        self, query: SearchQuery, text: str, *, limit: int, now: datetime
    ) -> list[Event]:
        self.text_calls.append((query, text))
        return self.text[:limit]

    async def semantic_search(
        self,
        query: SearchQuery,
        vector: list[float],
        *,
        limit: int,
        now: datetime,
        min_similarity: float,
    ) -> list[Event]:
        self.semantic_calls.append((query, vector, min_similarity))
        return self.semantic[:limit]

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


class _Embedding:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_text(self, text: str) -> list[float]:
        self.texts.append(text)
        return [1.0, 0.0]


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


# ── гибридный поиск (P1 №7) и HyDE (P1 №16) ──────────────────────────────────
async def test_hybrid_fuses_strict_text_and_semantic() -> None:
    e1, e2, e3 = _event(1), _event(2), _event(3)
    repo = _Repo(hits={"spb": [e1]}, text=[e2, e1], semantic=[e3, e1])
    embedding = _Embedding()
    llm = _LLM(SearchFilters(city="spb", topics=["golang"], free_text="kafka"))
    search = NlSearch(llm, repo, _Clock(), embedding=embedding)  # type: ignore[arg-type]
    result = await search.execute("Go и Kafka в Питере")

    assert result.mode == "hybrid" and not result.relaxed
    assert result.results[0].id == 1  # найдено всеми тремя ретриверами
    assert {e.id for e in result.results} == {1, 2, 3}
    # жёсткие фильтры общие, темы и слова — для релевантности, не фильтр
    hard, words = repo.text_calls[0]
    assert hard.city == "spb" and hard.topics == [] and hard.free_text == ""
    assert words == "kafka Golang"
    assert embedding.texts == ["Go и Kafka в Питере"]  # эмбеддинг исходной фразы
    assert repo.semantic_calls[0][2] == SearchConfig().min_similarity


async def test_only_hard_filters_use_strict_search_by_date() -> None:
    repo = _Repo(hits={"spb": [_event(1)]})
    llm = _LLM(SearchFilters(city="spb", event_type="conference"))
    search = NlSearch(llm, repo, _Clock(), embedding=_Embedding())  # type: ignore[arg-type]
    result = await search.search_filters(SearchFilters(city="spb", event_type="conference"))
    assert result.mode == "strict" and repo.text_calls == [] and repo.semantic_calls == []


async def test_hybrid_disabled_and_no_embedding_fallbacks() -> None:
    repo = _Repo(hits={"": [_event(1)]}, text=[_event(2)])
    off = NlSearch(  # type: ignore[arg-type]
        _LLM(SearchFilters(free_text="go")), repo, _Clock(), config=SearchConfig(hybrid=False)
    )
    assert (await off.execute("go")).mode == "strict" and repo.text_calls == []
    no_vec = NlSearch(_LLM(SearchFilters(free_text="go")), repo, _Clock())  # type: ignore[arg-type]
    result = await no_vec.execute("go")
    assert result.mode == "hybrid" and repo.semantic_calls == []  # без эмбеддингов — 2 ретривера


async def test_hyde_embeds_hypothetical_event_and_caches_it() -> None:
    repo, embedding, cache = _Repo(semantic=[_event(5)]), _Embedding(), _Cache()
    llm = _LLM(SearchFilters(free_text="highload"))
    search = NlSearch(  # type: ignore[arg-type]
        llm, repo, _Clock(), cache, embedding, SearchConfig(hyde=True)
    )
    await search.execute("про высокие нагрузки")
    await search.execute("про высокие нагрузки")
    assert embedding.texts[0] == "про высокие нагрузки\nМитап о Go и высоконагруженных сервисах."
    assert embedding.texts[1] == embedding.texts[0]
    hyde_calls = [c for c in llm.calls if "идеально" in c[0][0].content]
    assert len(hyde_calls) == 1 and hyde_calls[0][0][1].content.startswith("<query>")


# ── «🔍 Похожие» (P1 №13) ─────────────────────────────────────────────────────
class _SimilarRepo(_Repo):
    def __init__(self, event: Event | None, found: list[Event]) -> None:
        super().__init__(semantic=found)
        self.event = event
        self.hits = {"": found}

    async def get_event(self, event_id: int) -> Event | None:
        return self.event


async def test_similar_excludes_self_and_same_series() -> None:
    source = _event(1)
    source.embedding, source.series_slug = [1.0, 0.0], "go-meetup"
    same_series = _event(2)
    same_series.series_slug = "go-meetup"
    repo = _SimilarRepo(source, [source, same_series, _event(3), _event(4)])
    found = await SimilarEvents(repo, _Clock()).execute(1, limit=1)  # type: ignore[arg-type]
    assert found is not None and [e.id for e in found] == [3]
    assert repo.semantic_calls[0][1] == [1.0, 0.0] and repo.semantic_calls[0][2] == 0.5


async def test_similar_without_embedding_uses_topics_and_missing_event_is_none() -> None:
    source = _event(1)
    source.topics = ["golang"]
    repo = _SimilarRepo(source, [_event(5)])
    found = await SimilarEvents(repo, _Clock()).execute(1)  # type: ignore[arg-type]
    assert found is not None and [e.id for e in found] == [5]
    assert repo.queries[0].topics == ["golang"] and repo.semantic_calls == []
    assert await SimilarEvents(_SimilarRepo(None, []), _Clock()).execute(9) is None  # type: ignore[arg-type]
