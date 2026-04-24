import asyncio

from aiogram import Bot, Dispatcher

from app.core.config import BOT_TOKEN
from app.bot.handlers.start import router as start_router
from app.bot.handlers.profile import router as profile_router
from app.bot.handlers.recommendations import router as recommendations_router
from app.bot.handlers.subscriptions import router as subscriptions_router


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден в .env")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(recommendations_router)
    dp.include_router(subscriptions_router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())