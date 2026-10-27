"""Роутер диалогового агента для веба (JWT) — панель «Помощник» (A5).

- `POST   /api/v1/agent/messages` — реплика пользователя → ответ агента
  (текст, карточки событий, предложенное изменение);
- `POST   /api/v1/agent/confirm`  — «Да / Нет» под предложенным изменением;
- `GET    /api/v1/agent/session`  — видимая история диалога (перерисовка чата);
- `DELETE /api/v1/agent/session`  — начать диалог заново.

Агент работает поверх тех же use-case'ов, что лента и настройки: изменения из
чата сразу видны в профиле и выдаче. `AGENT_ENABLED=false` → 503.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eventmind.application.agent.use_cases import (
    AgentTurn,
    ConfirmAgentAction,
    GetAgentHistory,
    ResetAgentSession,
)
from eventmind.interfaces.api.dependencies import (
    CurrentUser,
    get_agent_history,
    get_agent_turn,
    get_confirm_agent_action,
    get_reset_agent,
)
from eventmind.interfaces.api.schemas import (
    AgentConfirmRequest,
    AgentHistoryMessage,
    AgentHistoryResponse,
    AgentMessageRequest,
    AgentPendingResponse,
    AgentReplyResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post("/messages", response_model=AgentReplyResponse)
async def message(
    payload: AgentMessageRequest,
    current_user: CurrentUser,
    use_case: Annotated[AgentTurn, Depends(get_agent_turn)],
) -> AgentReplyResponse:
    assert current_user.id is not None
    reply = await use_case.execute(current_user.id, payload.message, channel="web")
    return AgentReplyResponse.from_reply(reply)


@router.post("/confirm", response_model=AgentReplyResponse)
async def confirm(
    payload: AgentConfirmRequest,
    current_user: CurrentUser,
    use_case: Annotated[ConfirmAgentAction, Depends(get_confirm_agent_action)],
) -> AgentReplyResponse:
    assert current_user.id is not None
    reply = await use_case.execute(
        current_user.id, payload.action_id, approve=payload.approve, channel="web"
    )
    return AgentReplyResponse.from_reply(reply)


@router.get("/session", response_model=AgentHistoryResponse)
async def history(
    current_user: CurrentUser,
    use_case: Annotated[GetAgentHistory, Depends(get_agent_history)],
) -> AgentHistoryResponse:
    assert current_user.id is not None
    items, pending = await use_case.execute(current_user.id)
    return AgentHistoryResponse(
        messages=[AgentHistoryMessage(role=i.role, text=i.text) for i in items],
        pending=AgentPendingResponse.from_pending(pending),
    )


@router.delete("/session", response_model=MessageResponse)
async def reset(
    current_user: CurrentUser,
    use_case: Annotated[ResetAgentSession, Depends(get_reset_agent)],
) -> MessageResponse:
    assert current_user.id is not None
    await use_case.execute(current_user.id)
    return MessageResponse(detail="Диалог начат заново")
