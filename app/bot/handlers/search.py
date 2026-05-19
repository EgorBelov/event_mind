from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.services.api_client import EventMindAPIClient
from app.bot.keyboards.inline import TOPIC_LABELS, FORMAT_LABELS, CITY_LABELS
from app.bot.utils import esc, send
from app.core.topics import topic_title, format_label, city_label

router = Router()
api_client = EventMindAPIClient()


def _format_search_result(events: list[dict], show_similarity: bool = False) -> str:
    if not events:
        return "Ничего не нашлось по этому запросу."

    chunks = []
    for event in events[:5]:
        topics = ", ".join(
            TOPIC_LABELS.get(t) or topic_title(t) for t in event.get("topics", [])
        )
        fmt = FORMAT_LABELS.get(event.get("format")) or format_label(event.get("format"))
        city = CITY_LABELS.get(event.get("city")) or city_label(event.get("city"))
        summary = event.get("summary") or event.get("description", "")
        summary = summary[:200]

        sim_text = ""
        if show_similarity and event.get("similarity") is not None:
            sim_text = f"\nСходство: {event['similarity']:.0%}"

        chunks.append(
            f"<b>{esc(event['title'])}</b>\n"
            f"Темы: {esc(topics)}\n"
            f"Формат: {esc(fmt)} | Город: {esc(city)}\n"
            f"Дата: {esc(event.get('date', ''))}{esc(sim_text)}\n"
            f"{esc(summary)}"
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
    await send(message, _format_search_result(events))


@router.message(Command("semantic"))
async def cmd_semantic_search(message: Message, command: CommandObject):
    """Семантический (AI) поиск: находит события по смыслу, а не только по ключевым словам."""
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
    await send(message, _format_search_result(events, show_similarity=True))


@router.message(F.text.startswith("Найти:"))
async def msg_search_prefix(message: Message):
    query = message.text.split(":", 1)[1].strip()
    if not query:
        await send(message, "Уточни запрос после двоеточия. Пример: <code>Найти: AI</code>")
        return
    events = await api_client.search_events(query=query)
    await send(message, _format_search_result(events))


@router.message(F.text == "🔍 Поиск")
async def msg_search_help(message: Message):
    await send(
        message,
        "Чтобы найти событие, отправь:\n"
        "<code>Найти: python</code>\n"
        "или используй команды:\n"
        "/search &lt;запрос&gt; — поиск по ключевым словам\n"
        "/semantic &lt;запрос&gt; — AI-поиск по смыслу",
    )
