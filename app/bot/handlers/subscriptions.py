from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.services.api_client import EventMindAPIClient

router = Router()
api_client = EventMindAPIClient()


@router.message(Command("subscribe"))
@router.message(F.text == "Подписаться на AI")
async def cmd_subscribe(message: Message):
    result = await api_client.subscribe(message.from_user.id)
    await message.answer(result.get("message", "Подписка обновлена."))


@router.message(Command("unsubscribe"))
@router.message(F.text == "Отписаться")
async def cmd_unsubscribe(message: Message):
    result = await api_client.unsubscribe(message.from_user.id)
    await message.answer(result.get("message", "Подписка отключена."))