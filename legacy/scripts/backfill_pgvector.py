"""Бэкфилл embedding_vec из JSON-колонки embedding.

Запускается ОДНОКРАТНО после миграции 9a1b2c3d4e5f_add_pgvector на
PostgreSQL-БД, в которой раньше работал dev на SQLite, либо после
полного переезда с импортом данных. Идемпотентен: запись пропускается,
если embedding_vec уже заполнен.

Использование:
    DATABASE_URL=postgresql+psycopg2://... python -m scripts.backfill_pgvector
"""
from __future__ import annotations

import json
import logging
import sys

from sqlalchemy import text

from app.db.backend import has_pgvector, is_postgres
from app.db.models.event import Event
from app.db.models.user import User
from app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _vec_literal(vec: list[float]) -> str:
    """pgvector принимает '[v1,v2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _backfill_table(db, table: str) -> int:
    """Перенести JSON embedding → vector embedding_vec по одной таблице."""
    rows = db.execute(
        text(
            f"SELECT id, embedding FROM {table} "
            f"WHERE embedding IS NOT NULL AND embedding_vec IS NULL"
        )
    ).all()
    count = 0
    for row in rows:
        try:
            vec = json.loads(row.embedding)
            if not isinstance(vec, list) or not vec:
                continue
            db.execute(
                text(
                    f"UPDATE {table} SET embedding_vec = CAST(:v AS vector) WHERE id = :id"
                ),
                {"v": _vec_literal(vec), "id": row.id},
            )
            count += 1
        except Exception as e:
            logger.warning("%s id=%s skipped: %s", table, row.id, e)
    db.commit()
    return count


def main() -> int:
    if not is_postgres():
        logger.error("DATABASE_URL is not PostgreSQL — nothing to do.")
        return 1
    if not has_pgvector():
        logger.error(
            "pgvector extension not enabled or `pgvector` package missing. "
            "Run `alembic upgrade head` first."
        )
        return 1

    db = SessionLocal()
    try:
        e_count = _backfill_table(db, Event.__tablename__)
        u_count = _backfill_table(db, User.__tablename__)
        logger.info("Backfilled embedding_vec: events=%d, users=%d", e_count, u_count)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
