"""Доменные сущности событий (чистые, без ORM/I-O)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from eventmind.domain.events.value_objects import RawEventStatus


@dataclass
class RawEvent:
    """Сырое событие из источника — до LLM-нормализации."""

    source: str
    title: str
    raw_description: str
    source_url: str | None = None
    id: int | None = None
    status: RawEventStatus = RawEventStatus.RAW
    error: str | None = None
    retry_count: int = 0
    created_at: datetime | None = None

    def mark_normalized(self) -> None:
        self.status = RawEventStatus.NORMALIZED
        self.error = None

    def mark_non_it(self) -> None:
        self.status = RawEventStatus.NON_IT
        self.error = None

    def mark_failed(self, error: str, *, max_retries: int) -> None:
        """Зафиксировать сбой нормализации. При исчерпании ретраев остаётся failed (DLQ)."""
        self.retry_count += 1
        self.status = RawEventStatus.FAILED
        self.error = error[:2000]

    def can_retry(self, *, max_retries: int) -> bool:
        return self.retry_count < max_retries


@dataclass
class Event:
    """Нормализованное IT-событие для рекомендаций/выдачи."""

    source: str
    title: str
    description: str
    format: str
    city: str
    level: str
    date: str  # человекочитаемая строка/ISO для UI
    id: int | None = None
    start_at: datetime | None = None  # распарсенная дата начала (freshness/сортировка)
    event_type: str | None = None
    target_audience: str | None = None
    source_url: str | None = None
    summary: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    seniority: str | None = None
    quality_score: int | None = None
    hype_score: int | None = None
    series_slug: str | None = None
    topics: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    created_at: datetime | None = None
