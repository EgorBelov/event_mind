import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.core.config import BOT_TOKEN, API_HOST
from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.inline import ai_recommendation_keyboard


api_client = EventMindAPIClient()


def format_ai_event_card(event: dict) -> str:
    topics = ", ".join(event.get("topics", []))

    return (
        f"🔥 *Новая AI-рекомендация*\n\n"
        f"*{event['title']}*\n\n"
        f"Тема: {topics}\n"
        f"Формат: {event['format']}\n"
        f"Город: {event['city']}\n"
        f"Уровень: {event['level']}\n"
        f"Дата: {event['date']}\n\n"
        f"{event['description']}\n\n"
        f"{event['explanation']}"
    )


async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="Markdown"),
    )

    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_HOST}/subscriptions/users")
        response.raise_for_status()
        users = response.json()

    for user in users:
        telegram_id = user["telegram_id"]

        try:
            result = await api_client.get_agent_recommendation_cards(telegram_id)
            cards = result.get("cards", [])

            if not cards:
                continue

            event = cards[0]

            interactions_data = await api_client.get_event_interactions(
                telegram_id,
                event["event_id"],
            )
            actions = set(interactions_data.get("actions", []))

            await bot.send_message(
                chat_id=telegram_id,
                text=format_ai_event_card(event),
                reply_markup=ai_recommendation_keyboard(
                    event["event_id"],
                    actions,
                ),
            )

        except Exception as error:
            print(f"Не удалось отправить {telegram_id}: {error}")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())