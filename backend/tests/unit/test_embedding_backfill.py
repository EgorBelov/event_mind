"""Unit: backfill эмбеддингов (события + пользователи), расписание ingestion (фейки, без БД)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from eventmind.application.ingestion.use_cases import (
    BackfillEventEmbeddings,
    NormalizeResult,
    event_embedding_text,
)
from eventmind.application.ports.events import EventText
from eventmind.application.recommender.use_cases import RefreshUserEmbeddings
from eventmind.config import Settings


class _Events:
    def __init__(self, rows: dict[int, tuple[str, str, list[float] | None]]) -> None:
        self.rows = rows

    async def fetch_without_embedding(self, *, limit: int, after_id: int = 0) -> list[EventText]:
        ids = sorted(i for i, (_, _, emb) in self.rows.items() if emb is None and i > after_id)
        return [EventText(i, self.rows[i][0], self.rows[i][1]) for i in ids[:limit]]

    async def set_embedding(self, event_id: int, embedding: list[float]) -> None:
        title, description, _ = self.rows[event_id]
        self.rows[event_id] = (title, description, embedding)


class _EventsUow:
    def __init__(self, events: _Events, log: list[str]) -> None:
        self.events = events
        self._log = log

    async def __aenter__(self) -> _EventsUow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self._log.append("commit")


class _Embedding:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.batches: list[list[str]] = []
        self._fail_on_call = fail_on_call

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        if self._fail_on_call is not None and len(self.batches) == self._fail_on_call:
            raise RuntimeError("model unavailable")
        return [[float(len(t))] for t in texts]


def _backfill(
    rows: dict[int, tuple[str, str, list[float] | None]],
    embedding: _Embedding,
    *,
    batch_size: int = 2,
) -> tuple[BackfillEventEmbeddings, _Events, list[str]]:
    events = _Events(rows)
    log: list[str] = []
    use_case = BackfillEventEmbeddings(
        lambda: _EventsUow(events, log),  # type: ignore[arg-type,return-value]
        embedding,  # type: ignore[arg-type]
        batch_size=batch_size,
    )
    return use_case, events, log


async def test_backfill_fills_only_missing_in_batches() -> None:
    rows: dict[int, tuple[str, str, list[float] | None]] = {
        i: (f"T{i}", f"D{i}", None) for i in range(1, 6)
    }
    rows[3] = ("T3", "D3", [9.0])  # уже есть — не трогаем
    embedding = _Embedding()
    use_case, events, log = _backfill(rows, embedding)

    result = await use_case.execute()

    assert result.updated == 4
    assert result.failed == 0
    assert result.updated_event_ids == [1, 2, 4, 5]
    assert events.rows[3][2] == [9.0]
    assert all(events.rows[i][2] is not None for i in rows)
    # пачки по 2, текст — как при ingestion
    assert embedding.batches == [
        [event_embedding_text("T1", "D1"), event_embedding_text("T2", "D2")],
        [event_embedding_text("T4", "D4"), event_embedding_text("T5", "D5")],
    ]
    assert log == ["commit", "commit"]


async def test_backfill_respects_limit() -> None:
    rows: dict[int, tuple[str, str, list[float] | None]] = {
        i: (f"T{i}", "", None) for i in range(1, 6)
    }
    use_case, events, _ = _backfill(rows, _Embedding())
    result = await use_case.execute(limit=3)
    assert result.updated == 3
    assert [i for i in rows if events.rows[i][2] is None] == [4, 5]


async def test_backfill_stops_on_provider_failure_keeping_committed_batches() -> None:
    rows: dict[int, tuple[str, str, list[float] | None]] = {
        i: (f"T{i}", "", None) for i in range(1, 6)
    }
    use_case, events, log = _backfill(rows, _Embedding(fail_on_call=2))
    result = await use_case.execute()
    assert result.updated == 2
    assert result.failed == 2
    assert log == ["commit"]  # первая пачка сохранена, на второй — остановка
    assert [i for i in rows if events.rows[i][2] is None] == [3, 4, 5]


def test_event_embedding_text_joins_title_and_description() -> None:
    assert event_embedding_text("Title", "Body") == "Title\nBody"
    assert event_embedding_text("Title", "") == "Title"


# ── пользователи ──────────────────────────────────────────────────────────────
class _RecUow:
    def __init__(self, users: list[int], log: list[Any]) -> None:
        self._users = users
        self._log = log

    async def __aenter__(self) -> _RecUow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def users_with_positive_feedback_on(
        self, event_ids: list[int], *, limit: int
    ) -> list[int]:
        self._log.append(("query", event_ids))
        return self._users[:limit]

    async def recompute_user_embedding(self, user_id: int) -> None:
        self._log.append(("recompute", user_id))

    async def commit(self) -> None:
        self._log.append("commit")


class _Cache:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


async def test_refresh_users_recomputes_and_invalidates_cache() -> None:
    log: list[Any] = []
    cache = _Cache()
    use_case = RefreshUserEmbeddings(
        lambda: _RecUow([7, 9], log),  # type: ignore[arg-type,return-value]
        cache,  # type: ignore[arg-type]
    )
    assert await use_case.execute([1, 2]) == 2
    assert log == [("query", [1, 2]), ("recompute", 7), ("recompute", 9), "commit"]
    assert cache.deleted == ["reco:7", "reco:9"]


async def test_refresh_users_noop_without_backfilled_events() -> None:
    log: list[Any] = []
    use_case = RefreshUserEmbeddings(
        lambda: _RecUow([7], log),  # type: ignore[arg-type,return-value]
        _Cache(),  # type: ignore[arg-type]
    )
    assert await use_case.execute([]) == 0
    assert log == []  # даже не открываем UoW


# ── нормализация и расписание ─────────────────────────────────────────────────
def test_normalize_progress_flag() -> None:
    assert NormalizeResult(processed=20, events_created=3).made_progress
    assert NormalizeResult(processed=20, non_it=1).made_progress
    assert not NormalizeResult(processed=20, failed=20).made_progress


def test_ingest_schedule_hours_parsing() -> None:
    assert Settings(ingest_schedule_hours="0, 6,12").ingest_schedule_hour_set == {0, 6, 12}
    assert Settings(ingest_schedule_hours="").ingest_schedule_hour_set == set()
    with pytest.raises(ValueError, match="0..23"):
        _ = Settings(ingest_schedule_hours="3,25").ingest_schedule_hour_set


def test_worker_cron_includes_ingest_only_when_scheduled() -> None:
    from eventmind.interfaces.worker.main import build_cron_jobs

    names = {job.name for job in build_cron_jobs(Settings(ingest_schedule_hours=""))}
    assert names == {"cron:cron_schedule_digests", "cron:cron_backfill_embeddings"}
    names = {job.name for job in build_cron_jobs(Settings(ingest_schedule_hours="3,15"))}
    assert "cron:cron_ingest_all" in names
