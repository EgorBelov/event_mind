import asyncio

from aiogram import Bot, Dispatcher

from app.bot.handlers.copilot import router as copilot_router
from app.bot.handlers.profile import router as profile_router
from app.bot.handlers.recommendations import router as recommendations_router
from app.bot.handlers.search import router as search_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.subscriptions import router as subscriptions_router
from app.core.config import BOT_TOKEN


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден в .env")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Порядок важен: точные F.text-фильтры срабатывают раньше catch-all с
    # фильтрами по pending-state. start/profile/recommendations/subscriptions
    # содержат точные совпадения (reply-кнопки и slash-команды). search и
    # copilot — catch-all для продолжения диалога, регистрируются последними.
    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(recommendations_router)
    dp.include_router(subscriptions_router)
    dp.include_router(search_router)
    dp.include_router(copilot_router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())