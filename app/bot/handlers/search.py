from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.inline import TOPIC_LABELS, FORMAT_LABELS, CITY_LABELS

router = Router()
api_client = EventMindAPIClient()


def _format_search_result(events: list[dict]) -> str:
    if not events:
        return "Ничего не нашлось по этому запросу."

    chunks = []
    for event in events[:5]:
        topics = ", ".join(
            TOPIC_LABELS.get(t, t) for t in event.get("topics", [])
        )
        fmt = FORMAT_LABELS.get(event.get("format"), event.get("format", ""))
        city = CITY_LABELS.get(event.get("city"), event.get("city", ""))
        summary = event.get("summary") or event.get("description", "")
        summary = summary[:200]
        chunks.append(
            f"*{event['title']}*\n"
            f"Темы: {topics}\n"
            f"Формат: {fmt} | Город: {city}\n"
            f"Дата: {event.get('date', '')}\n"
            f"{summary}"
        )
    return "\n\n".join(chunks)


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject):
    query = (command.args or "").strip()
    if not query:
        await message.answer(
            "Использование: /search <запрос>\nНапример: /search python"
        )
        return

    events = await api_client.search_events(query=query)
    text = _format_search_result(events)
    await message.answer(text, parse_mode="Markdown")


@router.message(F.text.startswith("Найти:"))
async def msg_search_prefix(message: Message):
    query = message.text.split(":", 1)[1].strip()
    if not query:
        await message.answer("Уточни запрос после двоеточия. Пример: `Найти: AI`", parse_mode="Markdown")
        return
    events = await api_client.search_events(query=query)
    text = _format_search_result(events)
    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "Поиск")
async def msg_search_help(message: Message):
    await message.answer(
        "Чтобы найти событие, отправь сообщение в формате:\n"
        "`Найти: python`\n"
        "или используй команду `/search python`",
        parse_mode="Markdown",
    )
