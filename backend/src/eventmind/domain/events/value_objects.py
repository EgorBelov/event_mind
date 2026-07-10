"""Value-objects/enum'ы событий (closed-domain поля скоринга и UI)."""
from __future__ import annotations

from enum import Enum


class RawEventStatus(str, Enum):
    RAW = "raw"                # сырое, ждёт нормализации
    NORMALIZED = "normalized"  # успешно превращено в Event
    NON_IT = "non_it"          # не IT / не событие — отброшено нормализатором
    FAILED = "failed"          # нормализация упала (DLQ при исчерпании ретраев)


class EventFormat(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    HYBRID = "hybrid"
    ANY = "any"
    UNKNOWN = "unknown"


class EventType(str, Enum):
    MEETUP = "meetup"
    CONFERENCE = "conference"
    WEBINAR = "webinar"
    WORKSHOP = "workshop"
    HACKATHON = "hackathon"
    LECTURE = "lecture"
    UNKNOWN = "unknown"


class Seniority(str, Enum):
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    ANY = "any"


# Closed-домены для boundary-валидации значений от LLM (см. application/normalizer).
ALLOWED_FORMAT: frozenset[str] = frozenset(e.value for e in EventFormat)
ALLOWED_EVENT_TYPE: frozenset[str] = frozenset(e.value for e in EventType)
ALLOWED_SENIORITY: frozenset[str] = frozenset(e.value for e in Seniority)
