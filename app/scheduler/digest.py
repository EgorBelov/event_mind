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

import httpx
from dotenv import load_dotenv

from app.core.config import API_HOST, settings


load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


def format_card(card: dict) -> str:
    topics = ", ".join(card.get("topics", []))
    return (
        f"🤖 *AI-дайджест*\n\n"
        f"*{card['title']}*\n\n"
        f"Тема: {topics}\n"
        f"Формат: {card['format']}\n"
        f"Город: {card['city']}\n"
        f"Дата: {card['date']}\n\n"
        f"{card.get('explanation', '')}"
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
            async with httpx.AsyncClient(timeout=20.0) as tg:
                await tg.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": telegram_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
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


def run_scheduler() -> None:
    """Запустить блокирующий scheduler: дайджест + (опционально) ingestion."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(
        lambda: asyncio.run(send_digest_once()),
        "interval",
        hours=24,
        id="daily_digest",
    )
    print("[scheduler] daily_digest: every 24h")

    if settings.ingest_enabled:
        interval = max(1, settings.ingest_interval_hours)
        scheduler.add_job(
            lambda: asyncio.run(ingest_habr_once()),
            "interval",
            hours=interval,
            id="ingest_habr",
        )
        scheduler.add_job(
            lambda: asyncio.run(ingest_rss_once()),
            "interval",
            hours=interval,
            id="ingest_rss",
            # сдвиг в полчаса, чтобы не стартовать одновременно с habr
            jitter=1800,
        )
        print(
            f"[scheduler] ingest_habr + ingest_rss: every {interval}h "
            f"(rss feeds configured: {len(settings.rss_feeds_list)})"
        )
    else:
        print("[scheduler] INGEST_ENABLED=false — periodic ingestion disabled")

    print("[scheduler] starting...")
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
