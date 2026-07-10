"""Роутер аутентификации: регистрация, вход, верификация email, сброс пароля."""
from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Request, Response
from starlette.status import HTTP_201_CREATED, HTTP_401_UNAUTHORIZED

from eventmind.application.accounts.use_cases import (
    AuthenticateUser,
    AuthenticateWithGoogle,
    RegisterUser,
    RequestPasswordReset,
    ResetPassword,
    VerifyEmail,
)
from eventmind.domain.accounts.entities import User
from eventmind.interfaces.api.container import Container
from eventmind.interfaces.api.cookies import clear_auth_cookies, set_auth_cookies
from eventmind.interfaces.api.dependencies import (
    REFRESH_COOKIE_NAME,
    ContainerDep,
    CurrentUser,
    get_authenticate_user,
    get_authenticate_with_google,
    get_register_user,
    get_request_password_reset,
    get_reset_password,
    get_verify_email,
)
from eventmind.interfaces.api.errors import ApiError
from eventmind.interfaces.api.schemas import (
    AuthResponse,
    GoogleAuthRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    UserResponse,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _issue(response: Response, container: Container, user: User) -> AuthResponse:
    assert user.id is not None
    subject = str(user.id)
    access = container.token_service.create_access_token(subject)
    refresh = container.token_service.create_refresh_token(subject)
    set_auth_cookies(
        response,
        access_token=access,
        refresh_token=refresh,
        secure=container.settings.environment == "prod",
    )
    return AuthResponse(user=UserResponse.from_entity(user), access_token=access)


@router.post("/register", status_code=HTTP_201_CREATED, response_model=AuthResponse)
async def register(
    payload: RegisterRequest,
    response: Response,
    container: ContainerDep,
    use_case: Annotated[RegisterUser, Depends(get_register_user)],
) -> AuthResponse:
    user = await use_case.execute(email=str(payload.email), password=payload.password)
    return _issue(response, container, user)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    container: ContainerDep,
    use_case: Annotated[AuthenticateUser, Depends(get_authenticate_user)],
) -> AuthResponse:
    user = await use_case.execute(email=str(payload.email), password=payload.password)
    return _issue(response, container, user)


@router.post("/google", response_model=AuthResponse)
async def google_auth(
    payload: GoogleAuthRequest,
    response: Response,
    container: ContainerDep,
    use_case: Annotated[AuthenticateWithGoogle, Depends(get_authenticate_with_google)],
) -> AuthResponse:
    user = await use_case.execute(payload.id_token)
    return _issue(response, container, user)


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    use_case: Annotated[VerifyEmail, Depends(get_verify_email)],
) -> MessageResponse:
    await use_case.execute(raw_token=payload.token)
    return MessageResponse(detail="Email подтверждён")


@router.post("/password-reset", response_model=MessageResponse)
async def password_reset(
    payload: PasswordResetRequest,
    use_case: Annotated[RequestPasswordReset, Depends(get_request_password_reset)],
) -> MessageResponse:
    # Всегда одинаковый ответ — не раскрываем, существует ли аккаунт.
    await use_case.execute(email=str(payload.email))
    return MessageResponse(detail="Если аккаунт существует, письмо отправлено")


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def password_reset_confirm(
    payload: PasswordResetConfirm,
    use_case: Annotated[ResetPassword, Depends(get_reset_password)],
) -> MessageResponse:
    await use_case.execute(raw_token=payload.token, new_password=payload.new_password)
    return MessageResponse(detail="Пароль обновлён")


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    container: ContainerDep,
) -> AuthResponse:
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        raise ApiError(HTTP_401_UNAUTHORIZED, "not_authenticated", "Нет refresh-токена")
    try:
        claims = container.token_service.decode(token)
    except jwt.InvalidTokenError as exc:
        raise ApiError(HTTP_401_UNAUTHORIZED, "invalid_token", "Невалидный refresh") from exc
    if claims.get("type") != "refresh":
        raise ApiError(HTTP_401_UNAUTHORIZED, "invalid_token", "Ожидался refresh-токен")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise ApiError(HTTP_401_UNAUTHORIZED, "invalid_token", "Некорректный subject")

    async with container.uow_factory() as uow:
        user = await uow.users.get_by_id(int(subject))
    if user is None or not user.is_active:
        raise ApiError(HTTP_401_UNAUTHORIZED, "user_inactive", "Пользователь недоступен")
    return _issue(response, container, user)


@router.post("/logout", response_model=MessageResponse)
async def logout(response: Response) -> MessageResponse:
    clear_auth_cookies(response)
    return MessageResponse(detail="Выход выполнен")


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.from_entity(current_user)
