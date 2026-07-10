"""GoogleTokenVerifier — проверка Google id_token через tokeninfo-эндпоинт.

Реализация порта `application.ports.oauth.GoogleTokenVerifier`. Для веб-входа
(«Sign in with Google») фронтенд получает `id_token` (JWT от Google) и шлёт его
на `POST /api/v1/auth/google`. Здесь мы валидируем токен, обращаясь к Google
tokeninfo, и сверяем `aud` с нашим `GOOGLE_OAUTH_CLIENT_ID`.

Осознанный trade-off: tokeninfo — сетевой вызов на каждый вход (Google советует
локальную проверку подписи по JWKS для нагруженного прод-трафика). Для нашего
объёма (вход раз в сессию) это проще и без кэша ключей; переход на локальную
JWKS-верификацию — за тем же портом, без правки ядра.
"""
from __future__ import annotations

import httpx
import structlog

from eventmind.application.ports.oauth import GoogleIdentity

_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
_logger = structlog.get_logger("eventmind.oauth")


class GoogleTokenVerifierHttp:
    def __init__(self, client_id: str, *, timeout: float = 10.0) -> None:
        self._client_id = client_id
        self._timeout = timeout

    async def verify(self, id_token: str) -> GoogleIdentity | None:
        if not self._client_id:
            _logger.warning("google_oauth_client_id_empty")
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(_TOKENINFO_URL, params={"id_token": id_token})
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception as exc:
            _logger.warning("google_tokeninfo_failed", error=str(exc))
            return None

        if data.get("aud") != self._client_id:
            _logger.warning("google_token_aud_mismatch")
            return None
        if data.get("email_verified") not in (True, "true"):
            return None
        email = data.get("email")
        sub = data.get("sub")
        if not isinstance(email, str) or not isinstance(sub, str):
            return None
        return GoogleIdentity(email=email, sub=sub)
