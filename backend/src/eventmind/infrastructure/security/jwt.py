"""Пользовательские JWT на PyJWT (порт `TokenService`).

access — короткоживущий (в httpOnly-cookie); refresh — длинный, с `type=refresh`.
Подпись HS256 секретом `JWT_SECRET`. Клеймы: sub (user_id), type, exp, iat.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt


class JwtTokenService:
    def __init__(
        self,
        secret: str,
        *,
        access_ttl_seconds: int = 15 * 60,
        refresh_ttl_seconds: int = 30 * 24 * 3600,
        algorithm: str = "HS256",
    ) -> None:
        if not secret:
            raise ValueError("JWT_SECRET пуст — нельзя выпускать токены")
        self._secret = secret
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds
        self._alg = algorithm

    def _encode(self, subject: str, token_type: str, ttl: int, extra: dict[str, str]) -> str:
        now = datetime.now(UTC)
        payload: dict[str, object] = {
            "sub": subject,
            "type": token_type,
            "iat": now,
            "exp": now + timedelta(seconds=ttl),
            **extra,
        }
        return jwt.encode(payload, self._secret, algorithm=self._alg)

    def create_access_token(self, subject: str, extra: dict[str, str] | None = None) -> str:
        return self._encode(subject, "access", self._access_ttl, extra or {})

    def create_refresh_token(self, subject: str) -> str:
        return self._encode(subject, "refresh", self._refresh_ttl, {})

    def create_purpose_token(self, subject: str, purpose: str, *, ttl_seconds: int) -> str:
        return self._encode(subject, purpose, ttl_seconds, {})

    def decode(self, token: str) -> dict[str, object]:
        # Бросает jwt.ExpiredSignatureError / jwt.InvalidTokenError — ловит интерфейс.
        return jwt.decode(token, self._secret, algorithms=[self._alg])
