from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.inline import TOPIC_LABELS, FORMAT_LABELS, CITY_LABELS

router = Router()
api_client = EventMindAPIClient()


def _format_search_result(events: list[dict], show_similarity: bool = False) -> str:
    if not events:
        return "Ничего не нашлось по этому запросу."

    chunks = []
    for event in events[:5]:
        topics = ", ".join(TOPIC_LABELS.get(t, t) for t in event.get("topics", []))
        fmt = FORMAT_LABELS.get(event.get("format"), event.get("format", ""))
        city = CITY_LABELS.get(event.get("city"), event.get("city", ""))
        summary = event.get("summary") or event.get("description", "")
        summary = summary[:200]

        sim_text = ""
        if show_similarity and event.get("similarity") is not None:
            sim_text = f"\nСходство: {event['similarity']:.0%}"

        chunks.append(
            f"*{event['title']}*\n"
            f"Темы: {topics}\n"
            f"Формат: {fmt} | Город: {city}\n"
            f"Дата: {event.get('date', '')}{sim_text}\n"
            f"{summary}"
        )
    return "\n\n".join(chunks)


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject):
    query = (command.args or "").strip()
    if not query:
        await message.answer(
            "Использование: /search <запрос>\nНапример: /search python\n\n"
            "Для семантического поиска: /semantic <запрос>"
        )
        return

    events = await api_client.search_events(query=query)
    await message.answer(_format_search_result(events), parse_mode="Markdown")


@router.message(Command("semantic"))
async def cmd_semantic_search(message: Message, command: CommandObject):
    """Semantic (AI) search: finds events by meaning, not just keywords."""
    query = (command.args or "").strip()
    if not query:
        await message.answer(
            "Семантический поиск находит события по смыслу запроса.\n"
            "Использование: /semantic <запрос>\n"
            "Например: /semantic хочу научиться деплоить микросервисы"
        )
        return

    await message.answer("Ищу по смыслу запроса...")
    events = await api_client.semantic_search_events(query=query)
    await message.answer(_format_search_result(events, show_similarity=True), parse_mode="Markdown")


@router.message(F.text.startswith("Найти:"))
async def msg_search_prefix(message: Message):
    query = message.text.split(":", 1)[1].strip()
    if not query:
        await message.answer("Уточни запрос после двоеточия. Пример: `Найти: AI`", parse_mode="Markdown")
        return
    events = await api_client.search_events(query=query)
    await message.answer(_format_search_result(events), parse_mode="Markdown")


@router.message(F.text == "Поиск")
async def msg_search_help(message: Message):
    await message.answer(
        "Чтобы найти событие, отправь:\n"
        "`Найти: python`\n"
        "или используй команды:\n"
        "/search <запрос> — поиск по ключевым словам\n"
        "/semantic <запрос> — AI-поиск по смыслу",
        parse_mode="Markdown",
    )
