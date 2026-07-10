"""Роутер каналов доставки: привязка Telegram к аккаунту через deep-link токен.

- `POST /api/v1/channels/telegram/link-token` — пользователь (JWT) получает
  одноразовый токен и deep-link `https://t.me/<bot>?start=<token>`.
- `POST /api/v1/channels/telegram/confirm` — вызывает **бот** (внутренний
  API-key) при `/start <token>`, связывая chat_id с аккаунтом.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eventmind.application.accounts.use_cases import (
    ConfirmTelegramLink,
    CreateTelegramLinkToken,
)
from eventmind.interfaces.api.dependencies import (
    ContainerDep,
    CurrentUser,
    get_confirm_telegram_link,
    get_create_telegram_link,
    require_internal_api_key,
)
from eventmind.interfaces.api.schemas import (
    MessageResponse,
    TelegramConfirmRequest,
    TelegramLinkTokenResponse,
)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


def _deep_link(bot_username: str, raw_token: str) -> str:
    # Полноценный deep-link требует username бота (TELEGRAM_BOT_USERNAME).
    # Без него отдаём только start-параметр — веб подставит username сам.
    if bot_username:
        return f"https://t.me/{bot_username.lstrip('@')}?start={raw_token}"
    return f"?start={raw_token}"


@router.post("/telegram/link-token", response_model=TelegramLinkTokenResponse)
async def create_telegram_link_token(
    current_user: CurrentUser,
    container: ContainerDep,
    use_case: Annotated[CreateTelegramLinkToken, Depends(get_create_telegram_link)],
) -> TelegramLinkTokenResponse:
    assert current_user.id is not None
    raw = await use_case.execute(user_id=current_user.id)
    return TelegramLinkTokenResponse(
        token=raw, deep_link=_deep_link(container.settings.telegram_bot_username, raw)
    )


@router.post(
    "/telegram/confirm",
    response_model=MessageResponse,
    dependencies=[Depends(require_internal_api_key)],
)
async def confirm_telegram_link(
    payload: TelegramConfirmRequest,
    use_case: Annotated[ConfirmTelegramLink, Depends(get_confirm_telegram_link)],
) -> MessageResponse:
    user_id = await use_case.execute(raw_token=payload.token, chat_id=payload.chat_id)
    return MessageResponse(detail=f"Telegram привязан к аккаунту {user_id}")
