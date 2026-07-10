from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


# ─── SQLite tuning ───────────────────────────────────────────────────────
# Глобальный listener на любом connect: применяется к engine API-сервера,
# scheduler'а и всех CLI-скриптов (train_gnn / eval_offline / compact_memories).
# Решает "database is locked", когда несколько процессов одновременно пишут.
@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    # Применяем только к SQLite-соединениям — не трогаем Postgres/прочие.
    import sqlite3
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        # WAL: читатели не блокируют писателей, разные процессы могут
        # одновременно читать пока один пишет.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Ждать до 10 секунд на занятой БД вместо моментального fail —
        # покрывает короткие пересечения с scheduler'ом и инжестом.
        cursor.execute("PRAGMA busy_timeout=10000")
        # NORMAL вместо FULL — заметно быстрее на записях, безопасно с WAL
        # (потеря последней транзакции при power-loss, для нашего use-case ок).
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    # pool_pre_ping: управляемый PG/пулер (Supabase, RDS) роняет простаивающие
    # соединения — без pre-ping первый запрос после паузы ловит "connection
    # closed". Проверка дешёвая (SELECT 1) и безвредна для SQLite.
    pool_pre_ping=True,
    # pool_recycle: Supabase pooler закрывает SSL-сокет, если транзакция
    # «висит» дольше idle_in_transaction_session_timeout (по умолчанию у
    # них 5 мин). При долгих LLM-вызовах внутри ingestion соединение
    # становилось «зомби» и db.commit() ловил SSL SYSCALL EOF →
    # PendingRollbackError. 1500s (25 мин) — компромисс ниже их таймаута.
    pool_recycle=1500,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
