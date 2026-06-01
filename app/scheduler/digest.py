"""Планировщик ежедневного AI-дайджеста и периодического ingestion.

Берёт список подписчиков из API, затем каждому отправляет его топ-карточку
AI-рекомендации через Telegram. Параллельно с этим раз в N часов дёргает
`/ingestion/load-habr` и `/ingestion/load-rss`, чтобы лента событий
пополнялась автоматически. Всё на APScheduler.

Запуск:
    python -m app.scheduler.digest
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

from app.bot.utils import esc, to_plain
from app.core.config import API_HOST, settings

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logger = logging.getLogger(__name__)


def _api_headers() -> dict[str, str]:
    """Shared-secret для запросов scheduler'а к нашему же API.

    Без него на проде middleware вернёт 401 на /ingestion/... и /subscriptions.
    Пустой dict в dev-режиме (api_shared_secret="") — middleware пропускает.
    """
    secret = settings.api_shared_secret
    return {"X-API-Key": secret} if secret else {}


def format_card(card: dict) -> str:
    topics = ", ".join(card.get("topics", []))
    return (
        f"🤖 <b>AI-дайджест</b>\n\n"
        f"<b>{esc(card['title'])}</b>\n\n"
        f"Тема: {esc(topics)}\n"
        f"Формат: {esc(card['format'])}\n"
        f"Город: {esc(card['city'])}\n"
        f"Дата: {esc(card['date'])}\n\n"
        f"{esc(card.get('explanation', ''))}"
    )


async def send_digest_once() -> None:
    """Получить список подписчиков и отправить каждому его топ-карточку AI-дайджеста."""
    async with httpx.AsyncClient(base_url=API_HOST, timeout=60.0, headers=_api_headers()) as client:
        resp = await client.get("/subscriptions/users")
        if resp.status_code != 200:
            logger.warning(f"[digest] subscribers fetch failed: {resp.status_code}")
            return
        users = resp.json()

    if not users:
        logger.info("[digest] no subscribers")
        return

    for user in users:
        telegram_id = user.get("telegram_id")
        if not telegram_id:
            continue
        try:
            async with httpx.AsyncClient(base_url=API_HOST, timeout=60.0, headers=_api_headers()) as client:
                cards_resp = await client.get(
                    f"/agent-recommendations/{telegram_id}/cards"
                )
                if cards_resp.status_code != 200:
                    continue
                data = cards_resp.json()
                cards = data.get("cards", [])
                if not cards:
                    continue
                card = cards[0]

            text = format_card(card)
            if not BOT_TOKEN:
                logger.warning("[digest] BOT_TOKEN not set, skipping send")
                continue
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            async with httpx.AsyncClient(timeout=20.0) as tg:
                r = await tg.post(
                    url,
                    json={
                        "chat_id": telegram_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
                # При сбое парсинга HTML — повтор без разметки,
                # чтобы дайджест не потерялся (как в bot.utils.send).
                if r.status_code != 200:
                    await tg.post(
                        url,
                        json={"chat_id": telegram_id, "text": to_plain(text)},
                    )
        except Exception as e:
            logger.warning(f"[digest] Error for user {telegram_id}: {e}")


async def ingest_habr_once() -> None:
    """Дёрнуть API `/ingestion/load-habr?limit=N` и залогировать результат."""
    limit = settings.ingest_habr_limit
    try:
        async with httpx.AsyncClient(base_url=API_HOST, timeout=120.0, headers=_api_headers()) as client:
            r = await client.post(f"/ingestion/load-habr?limit={limit}")
            if r.status_code != 200:
                logger.warning(f"[ingest:habr] non-200: {r.status_code}")
                return
            data = r.json()
        logger.info(
            f"[ingest:habr] new={data.get('new', 0)} "
            f"normalized={data.get('normalized', 0)} "
            f"non_it={data.get('non_it', 0)} failed={data.get('failed', 0)}"
        )
    except Exception as e:
        logger.warning(f"[ingest:habr] error: {e}")


async def ingest_rss_once() -> None:
    """Дёрнуть API `/ingestion/load-rss` для пополнения из RSS-лент."""
    if not settings.rss_feeds_list:
        logger.info("[ingest:rss] RSS_FEEDS пуст, пропускаю")
        return
    limit = settings.ingest_rss_limit_per_feed
    try:
        async with httpx.AsyncClient(base_url=API_HOST, timeout=180.0, headers=_api_headers()) as client:
            r = await client.post(f"/ingestion/load-rss?limit_per_feed={limit}")
            if r.status_code != 200:
                logger.warning(f"[ingest:rss] non-200: {r.status_code}")
                return
            data = r.json()
        logger.info(
            f"[ingest:rss] feeds={data.get('feeds', 0)} "
            f"new={data.get('new', 0)} normalized={data.get('normalized', 0)} "
            f"non_it={data.get('non_it', 0)} failed={data.get('failed', 0)}"
        )
    except Exception as e:
        logger.warning(f"[ingest:rss] error: {e}")


def backfill_event_embeddings_once() -> None:
    """Догнать события без `embedding` (пакетно, пишет в БД).

    Read-path `/recommendations` намеренно read-only — он не записывает
    недостающие векторы, чтобы не превращать GET в writer под Supabase.
    Этот джоб берёт на себя backfill: на каждом тике подбирает события
    с `embedding IS NULL` и считает вектор одним батчем.
    """
    try:
        from app.db.models.event import Event
        from app.db.session import SessionLocal
        from app.recommender.embeddings import ensure_event_embeddings

        db = SessionLocal()
        try:
            # Не выгребаем весь каталог за раз — иначе при росте каталога
            # один тик зависнет на encode'е. 200 хватает с запасом против
            # реального темпа ingestion'а.
            events = (
                db.query(Event).filter(Event.embedding.is_(None)).limit(200).all()
            )
            if not events:
                logger.info("[backfill:embeddings] nothing to do")
                return
            added = ensure_event_embeddings(db, events)
            logger.info("[backfill:embeddings] filled=%d/%d", added, len(events))
        finally:
            db.close()
    except Exception as e:
        logger.warning("[backfill:embeddings] error: %s", e)


def backfill_user_embeddings_once() -> None:
    """Догнать пользователей без `embedding` (батч, пишет в БД).

    Симметрично к backfill_event_embeddings: если у части старых юзеров
    `users.embedding IS NULL` (до того, как refresh_user_embedding стал
    вызываться на пишущих путях), их вектор сейчас пересчитывается
    in-memory на каждый /recommendations. Этот джоб закрывает дыру.
    """
    try:
        from app.api.services.recommendation_service import refresh_user_embedding
        from app.db.models.user import User
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            users = (
                db.query(User).filter(User.embedding.is_(None)).limit(200).all()
            )
            if not users:
                logger.info("[backfill:user_emb] nothing to do")
                return
            done = 0
            for user in users:
                refresh_user_embedding(db, user)
                if user.embedding is not None:
                    done += 1
            logger.info("[backfill:user_emb] filled=%d/%d", done, len(users))
        finally:
            db.close()
    except Exception as e:
        logger.warning("[backfill:user_emb] error: %s", e)


def compact_memories_once() -> None:
    """Прогнать compaction по всем пользователям с разросшейся памятью.

    Sync (не async): дёргает БД напрямую через общий SessionLocal —
    важно, чтобы применились WAL/busy_timeout PRAGMA из app.db.session.
    """
    try:
        from app.db.models.user import User
        from app.db.session import SessionLocal
        from app.recommender.memory import compact_user_memories

        db = SessionLocal()
        try:
            total_removed = total_added = 0
            for user in db.query(User).all():
                r = compact_user_memories(db, user.id)
                if r["status"] == "ok":
                    total_removed += r["removed"]
                    total_added += r["added"]
            db.commit()
            logger.info(f"[compact:memory] removed={total_removed} added={total_added}")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[compact:memory] error: {e}")


async def ingest_telegram_once() -> None:
    """Дёрнуть API `/ingestion/load-telegram` для пополнения из TG-каналов."""
    channels = (getattr(settings, "tg_ingest_channels", "") or "").strip()
    if not channels:
        logger.info("[ingest:tg] TG_INGEST_CHANNELS пуст, пропускаю")
        return
    limit = settings.ingest_rss_limit_per_feed  # переиспользуем тот же лимит
    try:
        async with httpx.AsyncClient(base_url=API_HOST, timeout=180.0, headers=_api_headers()) as client:
            r = await client.post(f"/ingestion/load-telegram?limit_per_channel={limit}")
            if r.status_code != 200:
                logger.warning(f"[ingest:tg] non-200: {r.status_code}")
                return
            data = r.json()
        logger.info(
            f"[ingest:tg] new={data.get('new', 0)} "
            f"normalized={data.get('normalized', 0)} "
            f"non_it={data.get('non_it', 0)} failed={data.get('failed', 0)}"
        )
    except Exception as e:
        logger.warning(f"[ingest:tg] error: {e}")


def build_scheduler():
    """Собрать (но не запускать) BlockingScheduler с дайджестом и ingestion.

    Дайджест шлётся раз в 24 ч и НЕ запускается на старте (иначе при каждом
    рестарте процесса подписчики получали бы повторную рассылку).

    `ingest_habr` / `ingest_rss` при `INGEST_ENABLED=true` запускаются сразу
    при старте процесса (`next_run_time`), а затем повторяются каждые
    `INGEST_INTERVAL_HOURS` часов — лента наполняется немедленно, а не через
    N часов после рестарта. RSS сдвинут на 30 c, чтобы не стартовать
    одновременно с habr.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    digest_minutes = max(1, settings.digest_interval_minutes)
    digest_kwargs: dict = {
        "trigger": "interval",
        "minutes": digest_minutes,
        "id": "daily_digest",
    }
    if settings.digest_run_on_startup:
        digest_kwargs["next_run_time"] = datetime.now()
    scheduler.add_job(
        lambda: asyncio.run(send_digest_once()),
        **digest_kwargs,
    )
    logger.info(
        f"[scheduler] daily_digest: every {digest_minutes}m"
        f"{' (run on startup)' if settings.digest_run_on_startup else ' (no run on startup)'}"
    )

    if settings.ingest_enabled:
        interval = max(1, settings.ingest_interval_hours)
        now = datetime.now()
        scheduler.add_job(
            lambda: asyncio.run(ingest_habr_once()),
            "interval",
            hours=interval,
            id="ingest_habr",
            next_run_time=now,
        )
        scheduler.add_job(
            lambda: asyncio.run(ingest_rss_once()),
            "interval",
            hours=interval,
            id="ingest_rss",
            next_run_time=now + timedelta(seconds=30),
            # джиттер на последующих тиках, чтобы не совпадать с habr
            jitter=1800,
        )
        tg_channels = (getattr(settings, "tg_ingest_channels", "") or "").strip()
        if tg_channels:
            scheduler.add_job(
                lambda: asyncio.run(ingest_telegram_once()),
                "interval",
                hours=interval,
                id="ingest_telegram",
                next_run_time=now + timedelta(seconds=60),
                jitter=1800,
            )
        logger.info(
            f"[scheduler] ingest_habr + ingest_rss"
            f"{' + ingest_telegram' if tg_channels else ''}: "
            f"run on startup, then every {interval}h "
            f"(rss feeds: {len(settings.rss_feeds_list)}, "
            f"tg channels: {len([c for c in tg_channels.split(',') if c.strip()])})"
        )
    else:
        logger.info("[scheduler] INGEST_ENABLED=false — periodic ingestion disabled")

    # Memory compaction — раз в неделю; не на старте, чтобы не блокировать boot.
    scheduler.add_job(
        compact_memories_once,
        "interval",
        hours=24 * 7,
        id="compact_memories",
    )
    logger.info("[scheduler] compact_memories: every 7d (no run on startup)")

    # Backfill пустых event.embedding — раз в час, маленькими батчами.
    # На старте запускаем сразу + сдвиг 90 с от ingest_rss, чтобы не дрались
    # за encode'модель в первые секунды процесса.
    scheduler.add_job(
        backfill_event_embeddings_once,
        "interval",
        hours=1,
        id="backfill_event_embeddings",
        next_run_time=datetime.now() + timedelta(seconds=90),
        jitter=600,
    )
    logger.info("[scheduler] backfill_event_embeddings: every 1h (first run +90s)")

    # Backfill пустых user.embedding — реже (раз в 4 ч), пользователей мало.
    # Сдвиг 150 с — чтобы не пересечься с event-backfill'ом по encode-модели.
    scheduler.add_job(
        backfill_user_embeddings_once,
        "interval",
        hours=4,
        id="backfill_user_embeddings",
        next_run_time=datetime.now() + timedelta(seconds=150),
        jitter=900,
    )
    logger.info("[scheduler] backfill_user_embeddings: every 4h (first run +150s)")

    return scheduler


def run_scheduler() -> None:
    """Запустить блокирующий scheduler: дайджест + (опционально) ingestion."""
    scheduler = build_scheduler()
    logger.info("[scheduler] starting...")
    scheduler.start()


if __name__ == "__main__":
    # На старте процесса жёстко проверяем DATABASE_URL/API_HOST — иначе
    # тики будут падать с PG-connection-refused и зашумлять логи.
    from app.core.config_validate import validate_or_exit
    validate_or_exit("scheduler")
    run_scheduler()
