"""Доменные сущности уведомлений."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class NotificationType(str, Enum):
    DIGEST = "digest"    # дайджест рекомендаций
    SYSTEM = "system"    # системные сообщения


@dataclass
class Notification:
    """Элемент in-app инбокса."""

    user_id: int
    type: NotificationType
    title: str
    body: str
    id: int | None = None
    payload: dict[str, object] = field(default_factory=dict)
    read: bool = False
    created_at: datetime | None = None
