"""Инструменты, которыми LLM-копилот может пользоваться через function calling.

Каждый tool — чистая функция, принимающая `db` и аргументы. LangGraph
оборачивает их в ToolNode; Groq вызывает через OpenAI-совместимый
tool-calling API.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.user import User
from app.recommender.retrieval import retrieve_events_for_query
from app.recommender.scoring import _get_event_topic_codes, _get_user_topic_codes
from app.recommender.user_model import parse_topic_weights


def tool_search_events(db: Session, telegram_id: int, query: str, k: int = 5) -> dict[str, Any]:
    """Семантический поиск событий — обёртка над retrieve_events_for_query."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"error": "user_not_found", "events": []}
    events = retrieve_events_for_query(db, user, query, k=k)
    return {"events": events, "count": len(events)}


def tool_get_user_profile(db: Session, telegram_id: int) -> dict[str, Any]:
    """Профиль пользователя: темы, веса, формат, город + skill-профиль если есть."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"error": "user_not_found"}

    profile: dict[str, Any] = {
        "topics": list(_get_user_topic_codes(user)),
        "preferred_format": user.preferred_format,
        "city": user.city,
        "topic_weights": parse_topic_weights(user.topic_weights),
    }
    try:
        from app.recommender.skill_gap import load_skill_profile
        sp = load_skill_profile(db, user.id)
        if sp:
            profile["skill_profile"] = sp
    except Exception:
        pass
    return profile


def tool_mark_saved(db: Session, telegram_id: int, event_id: int) -> dict[str, Any]:
    """Пометить событие как сохранённое (то же действие, что кнопка 'Сохранить')."""
    from app.api.services.recommendation_service import create_interaction
    try:
        return create_interaction(db, telegram_id, event_id, "save")
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_explain_event(db: Session, telegram_id: int, event_id: int) -> dict[str, Any]:
    """Объяснение, почему событие подходит пользователю — структурированное."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"error": "user_not_found"}
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return {"error": "event_not_found"}
    try:
        from app.recommender.explain import explain_event_detailed
        details = explain_event_detailed(user, event, db=db)
        # Свернём JSON-чтобы LLM лучше его читал.
        return {
            "event_id": event_id,
            "title": event.title,
            "text": details.get("text"),
            "topic_match": details.get("topic_match"),
            "format_match": details.get("format_match"),
            "city_match": details.get("city_match"),
            "semantic_similarity": details.get("semantic_similarity"),
            "history_signals": details.get("history_signals"),
            "bayesian_posterior": details.get("bayesian_posterior"),
            "counterfactual": details.get("counterfactual"),
            "score_breakdown": details.get("score_breakdown"),
        }
    except Exception as e:
        return {"error": str(e)}


def tool_recall_about_user(db: Session, telegram_id: int, query: str, k: int = 5) -> dict[str, Any]:
    """Long-term memory recall — top-k заметок по семантической близости к запросу."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"error": "user_not_found", "memories": []}
    try:
        from app.recommender.memory import recall
        items = recall(db, user.id, query, k=k)
        return {"memories": items, "count": len(items)}
    except Exception as e:
        return {"error": str(e), "memories": []}


def tool_get_interactions_summary(db: Session, telegram_id: int) -> dict[str, Any]:
    """Сводка истории взаимодействий: счётчики и топ-темы интереса."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"error": "user_not_found"}

    interactions = db.query(Interaction).filter(Interaction.user_id == user.id).all()
    likes = sum(1 for i in interactions if i.action == "like")
    saves = sum(1 for i in interactions if i.action == "save")
    dislikes = sum(1 for i in interactions if i.action == "dislike")

    # Топ-темы из лайкнутых событий
    liked_ids = [i.event_id for i in interactions if i.action in ("like", "save")]
    topic_counts: dict[str, int] = {}
    if liked_ids:
        for ev in db.query(Event).filter(Event.id.in_(liked_ids)).all():
            for code in _get_event_topic_codes(ev):
                topic_counts[code] = topic_counts.get(code, 0) + 1
    top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "likes": likes,
        "saves": saves,
        "dislikes": dislikes,
        "top_liked_topics": [{"topic": t, "count": c} for t, c in top_topics],
    }


# Tool-definition в OpenAI-tools формате (Groq совместим).
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_events",
            "description": "Найти IT-события, релевантные текстовому запросу (семантический поиск).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Запрос на естественном языке."},
                    "k": {"type": "integer", "description": "Сколько событий вернуть (1-10).", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "Получить профиль пользователя: темы, веса, город, формат, цели.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_saved",
            "description": "Пометить событие сохранённым (добавить в избранное пользователя).",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer", "description": "ID события."},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_interactions_summary",
            "description": "Сводка истории: сколько лайков/сейвов/дизлайков, какие темы пользователь предпочитает.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_event",
            "description": "Получить детальное объяснение, почему конкретное событие подходит пользователю.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer", "description": "ID события."},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_about_user",
            "description": (
                "Long-term memory: вспомнить накопленные заметки о пользователе "
                "(цели, предпочтения, ограничения, контекст). Используй когда "
                "запрос пользователя предполагает учёт его истории/целей."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "О чём вспомнить (запрос на естественном языке)."},
                    "k": {"type": "integer", "description": "Сколько заметок вернуть (1-10).", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
]


def filter_tools(names: list[str]) -> list[dict]:
    """Подмножество TOOL_DEFINITIONS по именам — для специалистов, которым нужны не все tools."""
    name_set = set(names)
    return [t for t in TOOL_DEFINITIONS if t["function"]["name"] in name_set]


def dispatch_tool(
    name: str,
    args: dict[str, Any],
    *,
    db: Session,
    telegram_id: int,
) -> dict[str, Any]:
    """Вызвать tool по имени; возвращает dict, который безопасно сериализуется в JSON."""
    if name == "search_events":
        return tool_search_events(db, telegram_id, query=args.get("query", ""), k=int(args.get("k", 5)))
    if name == "get_user_profile":
        return tool_get_user_profile(db, telegram_id)
    if name == "mark_saved":
        try:
            event_id = int(args.get("event_id"))
        except (TypeError, ValueError):
            return {"error": "invalid event_id"}
        return tool_mark_saved(db, telegram_id, event_id)
    if name == "get_interactions_summary":
        return tool_get_interactions_summary(db, telegram_id)
    if name == "explain_event":
        try:
            event_id = int(args.get("event_id"))
        except (TypeError, ValueError):
            return {"error": "invalid event_id"}
        return tool_explain_event(db, telegram_id, event_id)
    if name == "recall_about_user":
        return tool_recall_about_user(
            db, telegram_id,
            query=args.get("query", ""),
            k=int(args.get("k", 5)),
        )
    return {"error": f"unknown tool: {name}"}
