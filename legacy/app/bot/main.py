import asyncio

from aiogram import Bot, Dispatcher

from app.bot.handlers.profile import router as profile_router
from app.bot.handlers.recommendations import router as recommendations_router
from app.bot.handlers.search import router as search_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.subscriptions import router as subscriptions_router
from app.core.config import BOT_TOKEN
from app.core.config_validate import validate_or_exit


async def main():
    # Жёсткая проверка ENV перед запуском polling. Раньше пустой BOT_TOKEN
    # просто давал ValueError, без подсказки что ещё нужно (API_HOST и т.п.).
    validate_or_exit("bot")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Порядок важен: точные F.text-фильтры срабатывают раньше catch-all с
    # фильтрами по pending-state. start/profile/recommendations/subscriptions
    # содержат точные совпадения (reply-кнопки и slash-команды). search —
    # catch-all для продолжения диалога, регистрируется последним.
    # Copilot временно отключён — кривой UX, прячем хендлеры до доработки.
    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(recommendations_router)
    dp.include_router(subscriptions_router)
    dp.include_router(search_router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())