"""Планировщик ежедневного AI-дайджеста.

Берёт список подписчиков из API, затем каждому отправляет его топ-карточку
AI-рекомендации через Telegram. Работает на APScheduler.

Запуск:
    python -m app.scheduler.digest
"""

import asyncio
import os

import httpx
from dotenv import load_dotenv

from app.core.config import API_HOST


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


def run_scheduler() -> None:
    """Запустить блокирующий scheduler, который вызывает `send_digest_once` раз в 24 часа."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(
        lambda: asyncio.run(send_digest_once()),
        "interval",
        hours=24,
        id="daily_digest",
    )
    print("[scheduler] Starting digest scheduler (every 24h)...")
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
