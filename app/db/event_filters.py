"""Общие SQL-фильтры для Event-запросов.

Сейчас содержит только `upcoming_only` — отсечь прошедшие события из
выдачи рекомендаций/поиска. БД ничего не удаляет: история взаимодействий
с прошедшими событиями сохраняется (LinUCB/Bayesian/GNN продолжают учить
веса), но в UI они уже не показываются.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_

from app.core.utils import utcnow_naive
from app.db.models.event import Event

# Грейс-период: показываем события, которые начались до 6 часов назад.
# Это покрывает оффлайн-конференции, идущие весь день — иначе утренний
# дайджест выкидывал бы их сразу после полуночи.
_DEFAULT_GRACE_HOURS = 6


def upcoming_only(query, *, grace_hours: int = _DEFAULT_GRACE_HOURS):
    """Отфильтровать прошедшие события.

    Сохраняем события с NULL `start_at` — у них дата неизвестна,
    выкидывать «на всякий случай» неправильно (источник просто не отдал
    время). Они отсортируются по `created_at` / freshness и постепенно
    уйдут вниз выдачи естественным путём.
    """
    cutoff = utcnow_naive() - timedelta(hours=grace_hours)
    return query.filter(or_(Event.start_at.is_(None), Event.start_at >= cutoff))
