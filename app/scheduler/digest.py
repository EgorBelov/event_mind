"""Планировщик ежедневного AI-дайджеста и периодического ingestion.

Берёт список подписчиков из API, затем каждому отправляет его топ-карточку
AI-рекомендации через Telegram. Параллельно с этим раз в N часов дёргает
`/ingestion/load-habr` и `/ingestion/load-rss`, чтобы лента событий
пополнялась автоматически. Всё на APScheduler.

Запуск:
    python -m app.scheduler.digest
"""

import asyncio
import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

from app.bot.utils import esc, to_plain
from app.core.config import API_HOST, settings

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


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
    async with httpx.AsyncClient(base_url=API_HOST, timeout=60.0) as client:
        resp = await client.get("/subscriptions/users")
        if resp.status_code != 200:
            print(f"[digest] subscribers fetch failed: {resp.status_code}")
            return
        users = resp.json()

    if not users:
        print("[digest] no subscribers")
        return

    for user in users:
        telegram_id = user.get("telegram_id")
        if not telegram_id:
            continue
        try:
            async with httpx.AsyncClient(base_url=API_HOST, timeout=60.0) as client:
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
                print("[digest] BOT_TOKEN not set, skipping send")
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
            print(f"[digest] Error for user {telegram_id}: {e}")


async def ingest_habr_once() -> None:
    """Дёрнуть API `/ingestion/load-habr?limit=N` и залогировать результат."""
    limit = settings.ingest_habr_limit
    try:
        async with httpx.AsyncClient(base_url=API_HOST, timeout=120.0) as client:
            r = await client.post(f"/ingestion/load-habr?limit={limit}")
            if r.status_code != 200:
                print(f"[ingest:habr] non-200: {r.status_code}")
                return
            data = r.json()
        print(
            f"[ingest:habr] new={data.get('new', 0)} "
            f"normalized={data.get('normalized', 0)} "
            f"non_it={data.get('non_it', 0)} failed={data.get('failed', 0)}"
        )
    except Exception as e:
        print(f"[ingest:habr] error: {e}")


async def ingest_rss_once() -> None:
    """Дёрнуть API `/ingestion/load-rss` для пополнения из RSS-лент."""
    if not settings.rss_feeds_list:
        print("[ingest:rss] RSS_FEEDS пуст, пропускаю")
        return
    limit = settings.ingest_rss_limit_per_feed
    try:
        async with httpx.AsyncClient(base_url=API_HOST, timeout=180.0) as client:
            r = await client.post(f"/ingestion/load-rss?limit_per_feed={limit}")
            if r.status_code != 200:
                print(f"[ingest:rss] non-200: {r.status_code}")
                return
            data = r.json()
        print(
            f"[ingest:rss] feeds={data.get('feeds', 0)} "
            f"new={data.get('new', 0)} normalized={data.get('normalized', 0)} "
            f"non_it={data.get('non_it', 0)} failed={data.get('failed', 0)}"
        )
    except Exception as e:
        print(f"[ingest:rss] error: {e}")


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
            print(f"[compact:memory] removed={total_removed} added={total_added}")
        finally:
            db.close()
    except Exception as e:
        print(f"[compact:memory] error: {e}")


async def ingest_telegram_once() -> None:
    """Дёрнуть API `/ingestion/load-telegram` для пополнения из TG-каналов."""
    channels = (getattr(settings, "tg_ingest_channels", "") or "").strip()
    if not channels:
        print("[ingest:tg] TG_INGEST_CHANNELS пуст, пропускаю")
        return
    limit = settings.ingest_rss_limit_per_feed  # переиспользуем тот же лимит
    try:
        async with httpx.AsyncClient(base_url=API_HOST, timeout=180.0) as client:
            r = await client.post(f"/ingestion/load-telegram?limit_per_channel={limit}")
            if r.status_code != 200:
                print(f"[ingest:tg] non-200: {r.status_code}")
                return
            data = r.json()
        print(
            f"[ingest:tg] new={data.get('new', 0)} "
            f"normalized={data.get('normalized', 0)} "
            f"non_it={data.get('non_it', 0)} failed={data.get('failed', 0)}"
        )
    except Exception as e:
        print(f"[ingest:tg] error: {e}")


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
    scheduler.add_job(
        lambda: asyncio.run(send_digest_once()),
        "interval",
        hours=24,
        id="daily_digest",
    )
    print("[scheduler] daily_digest: every 24h (no run on startup)")

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
        print(
            f"[scheduler] ingest_habr + ingest_rss"
            f"{' + ingest_telegram' if tg_channels else ''}: "
            f"run on startup, then every {interval}h "
            f"(rss feeds: {len(settings.rss_feeds_list)}, "
            f"tg channels: {len([c for c in tg_channels.split(',') if c.strip()])})"
        )
    else:
        print("[scheduler] INGEST_ENABLED=false — periodic ingestion disabled")

    # Memory compaction — раз в неделю; не на старте, чтобы не блокировать boot.
    scheduler.add_job(
        compact_memories_once,
        "interval",
        hours=24 * 7,
        id="compact_memories",
    )
    print("[scheduler] compact_memories: every 7d (no run on startup)")

    return scheduler


def run_scheduler() -> None:
    """Запустить блокирующий scheduler: дайджест + (опционально) ingestion."""
    scheduler = build_scheduler()
    print("[scheduler] starting...")
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
