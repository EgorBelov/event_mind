"""Роутер уведомлений: in-app инбокс (JWT) + unsubscribe (публичный токен)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from starlette.status import HTTP_404_NOT_FOUND

from eventmind.application.notifications.use_cases import (
    ListInbox,
    MarkNotificationRead,
    Unsubscribe,
)
from eventmind.interfaces.api.dependencies import (
    CurrentUser,
    get_list_inbox,
    get_mark_read,
    get_unsubscribe,
)
from eventmind.interfaces.api.errors import ApiError
from eventmind.interfaces.api.schemas import (
    InboxResponse,
    MessageResponse,
    NotificationResponse,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=InboxResponse)
async def inbox(
    current_user: CurrentUser,
    use_case: Annotated[ListInbox, Depends(get_list_inbox)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InboxResponse:
    assert current_user.id is not None
    notifications, unread = await use_case.execute(current_user.id, limit=limit, offset=offset)
    return InboxResponse(
        unread=unread,
        items=[
            NotificationResponse(
                id=n.id or 0,
                type=n.type.value,
                title=n.title,
                body=n.body,
                payload=n.payload,
                read=n.read,
            )
            for n in notifications
        ],
    )


@router.post("/{notification_id}/read", response_model=MessageResponse)
async def mark_read(
    notification_id: int,
    current_user: CurrentUser,
    use_case: Annotated[MarkNotificationRead, Depends(get_mark_read)],
) -> MessageResponse:
    assert current_user.id is not None
    ok = await use_case.execute(current_user.id, notification_id)
    if not ok:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Уведомление не найдено")
    return MessageResponse(detail="Прочитано")


@router.get("/unsubscribe")
async def unsubscribe(
    token: Annotated[str, Query(min_length=1)],
    use_case: Annotated[Unsubscribe, Depends(get_unsubscribe)],
) -> Response:
    ok = await use_case.execute(token)
    body = (
        "<h2>Вы отписались от email-дайджеста EventMind</h2>"
        if ok
        else "<h2>Ссылка недействительна</h2>"
    )
    return Response(content=body, media_type="text/html", status_code=200 if ok else 400)
