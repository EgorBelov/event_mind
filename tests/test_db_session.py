"""Sanity-проверки на SQLite-настройки в app.db.session.

WAL + busy_timeout критичны для одновременной работы API, scheduler'а и
CLI-скриптов с одной SQLite-БД. Если эти PRAGMA отвалятся (например,
кто-то выпилит event-listener), вернутся ошибки 'database is locked'.
"""
from app.db.session import engine


def test_sqlite_journal_mode_is_wal():
    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert (mode or "").lower() == "wal"


def test_sqlite_busy_timeout_is_set():
    with engine.connect() as conn:
        busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    # Допускаем любое разумно большое значение; главное — не 0 (мгновенный fail).
    assert int(busy) >= 5000


def test_sqlite_synchronous_is_normal():
    with engine.connect() as conn:
        sync = conn.exec_driver_sql("PRAGMA synchronous").scalar()
    # NORMAL = 1 (FULL = 2, OFF = 0). На WAL быстрее и безопасно.
    assert int(sync) == 1
