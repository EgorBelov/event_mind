"""Общие хелперы для всех Copilot-специалистов: LLM tool-loop, форматирование,
парсинг recommended_ids. Чтобы специалисты не дублировали инфраструктуру.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agents.copilot.tools import dispatch_tool, filter_tools

MAX_TOOL_HOPS = 3


def format_history(history: list[dict] | None, window: int = 6) -> str:
    if not history:
        return "(первый turn)"
    parts = []
    for msg in history[-window:]:
        role = msg.get("role", "?")
        content = (msg.get("content") or "")[:500]
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def parse_recommended_ids(text: str, valid_ids: set[int] | None = None) -> list[int]:
    match = re.search(r"RECOMMENDED_IDS:\s*\[([^\]]*)\]", text or "")
    if not match:
        return []
    try:
        ids = [int(x.strip()) for x in match.group(1).split(",") if x.strip().isdigit()]
        return [i for i in ids if (valid_ids is None or i in valid_ids)]
    except Exception:
        return []


def strip_recommended_ids(text: str) -> str:
    return re.sub(r"RECOMMENDED_IDS:.*", "", text or "").strip()


def invoke_with_tools(
    *,
    system_prompt: str,
    user_prompt: str,
    db,
    telegram_id: int,
    tool_names: list[str] | None = None,
    tool_log: list[dict] | None = None,
    max_hops: int = MAX_TOOL_HOPS,
) -> str:
    """LLM-цикл с обработкой function calls; возвращает финальный текст.

    `tool_names=None` ⇒ tools не подключаются (чистый LLM-вызов).
    `tool_log` ⇒ если передан список, в него пишутся записи о вызовах tools.
    """
    if tool_log is None:
        tool_log = []

    # Импорт внутри функции, чтобы monkeypatch видел замену.
    from app.agents.recommendation.llm import llm

    if tool_names:
        tools = filter_tools(tool_names)
        try:
            bound = llm.bind_tools(tools)
        except Exception:
            bound = llm
    else:
        bound = llm

    messages: list = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

    for _hop in range(max_hops + 1):
        response = bound.invoke(messages)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls or not tool_names:
            return response.content or ""

        messages.append(response)
        for call in tool_calls:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            raw_args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
            tool_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            args = raw_args if isinstance(raw_args, dict) else {}
            result = dispatch_tool(name, args, db=db, telegram_id=telegram_id)
            tool_log.append({
                "name": name,
                "args": args,
                "result_keys": list(result.keys()) if isinstance(result, dict) else None,
            })
            messages.append(ToolMessage(
                content=json.dumps(result, ensure_ascii=False, default=str),
                tool_call_id=tool_id,
            ))

    from app.agents.recommendation.llm import llm as _llm_fresh
    final = _llm_fresh.invoke(messages)
    return final.content or ""


def build_user_profile_snapshot(db, user) -> dict[str, Any]:
    """Снимок профиля для подачи в LLM (всем специалистам)."""
    from app.recommender.scoring import _get_user_topic_codes
    from app.recommender.user_model import parse_topic_weights
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
