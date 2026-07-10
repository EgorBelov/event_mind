"""Установка/снятие httpOnly-cookie с JWT.

access — короткий, refresh — длинный. `secure` включается на проде;
`samesite=lax` — разумный дефолт для веб-клиента на том же сайте.
"""
from __future__ import annotations

from fastapi import Response

from eventmind.interfaces.api.dependencies import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME

ACCESS_MAX_AGE = 15 * 60
REFRESH_MAX_AGE = 30 * 24 * 3600


def set_auth_cookies(
    response: Response, *, access_token: str, refresh_token: str, secure: bool
) -> None:
    common = {"httponly": True, "secure": secure, "samesite": "lax", "path": "/"}
    response.set_cookie(ACCESS_COOKIE_NAME, access_token, max_age=ACCESS_MAX_AGE, **common)  # type: ignore[arg-type]
    response.set_cookie(REFRESH_COOKIE_NAME, refresh_token, max_age=REFRESH_MAX_AGE, **common)  # type: ignore[arg-type]


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
