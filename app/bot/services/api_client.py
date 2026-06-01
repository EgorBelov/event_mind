import httpx

from app.core.config import API_HOST, settings

# Дефолтный таймаут httpx — 5 c, а /recommendations при пересчёте эмбеддингов
# по всем событиям легко уходит за 15 c. Без явного таймаута бот ловил
# ReadTimeout → except httpx.HTTPError → [] → «Пока нет рекомендаций».
_TIMEOUT = httpx.Timeout(30.0)


def _auth_headers() -> dict[str, str]:
    """Заголовки для каждого запроса к API. Если shared-secret задан —
    кладём `X-API-Key`. Иначе пустой dict (dev/тестовый режим)."""
    secret = settings.api_shared_secret
    return {"X-API-Key": secret} if secret else {}


class EventMindAPIClient:
    def __init__(self, base_url: str = API_HOST):
        self.base_url = base_url.rstrip("/")
        self._headers = _auth_headers()

    async def register_user(self, telegram_id, username, preferred_format, city, topics) -> dict:
        payload = {"telegram_id": telegram_id, "username": username,
                   "preferred_format": preferred_format, "city": city, "topics": topics}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.post(f"{self.base_url}/users/register", json=payload)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def get_user(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/users/{telegram_id}")
                if r.status_code == 404:
                    return {}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def get_event(self, event_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/events/{event_id}")
                if r.status_code == 404:
                    return {}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def undo_last_interaction(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.post(f"{self.base_url}/recommendations/{telegram_id}/undo")
                if r.status_code == 404:
                    return {}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def get_recommendations(self, telegram_id: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/recommendations/{telegram_id}")
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def get_feed_cursor(self, telegram_id: int) -> int:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/recommendations/{telegram_id}/cursor")
                if r.status_code == 404:
                    return 0
                r.raise_for_status()
                return int(r.json().get("index", 0))
        except httpx.HTTPError:
            return 0

    async def reset_feed_cursor(self, telegram_id: int) -> int:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.post(f"{self.base_url}/recommendations/{telegram_id}/cursor/reset")
                if r.status_code == 404:
                    return 0
                r.raise_for_status()
                return int(r.json().get("index", 0))
        except httpx.HTTPError:
            return 0

    async def advance_feed_cursor(self, telegram_id: int) -> int:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.post(f"{self.base_url}/recommendations/{telegram_id}/cursor/advance")
                if r.status_code == 404:
                    return 0
                r.raise_for_status()
                return int(r.json().get("index", 0))
        except httpx.HTTPError:
            return 0

    async def save_interaction(self, telegram_id: int, event_id: int, action: str) -> dict:
        payload = {"telegram_id": telegram_id, "event_id": event_id, "action": action}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.post(f"{self.base_url}/recommendations/interactions", json=payload)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def get_why_explanation(self, telegram_id: int, event_id: int) -> dict:
        """Получить объяснение «почему рекомендовано» — {short, full}."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(
                    f"{self.base_url}/recommendations/{telegram_id}/why/{event_id}"
                )
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"short": "", "full": ""}

    async def get_event_interactions(self, telegram_id: int, event_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(
                    f"{self.base_url}/recommendations/{telegram_id}/event/{event_id}/interactions"
                )
                if r.status_code == 404:
                    return {"actions": []}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"actions": []}

    async def get_saved_events(self, telegram_id: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/recommendations/{telegram_id}/saved")
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def subscribe(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.post(f"{self.base_url}/subscriptions/{telegram_id}/subscribe")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"message": "Не удалось оформить подписку. Попробуй позже."}

    async def unsubscribe(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.post(f"{self.base_url}/subscriptions/{telegram_id}/unsubscribe")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"message": "Не удалось отписаться. Попробуй позже."}

    async def get_agent_recommendation_cards(self, telegram_id: int, limit: int = 5) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60.0, headers=self._headers) as c:
                r = await c.get(
                    f"{self.base_url}/agent-recommendations/{telegram_id}/cards",
                    params={"limit": limit},
                )
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"success": False, "message": "Не удалось получить AI-рекомендации."}

    async def get_user_stats(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/users/{telegram_id}/stats")
                if r.status_code == 404:
                    return {"success": False}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"success": False}

    async def analyze_bio(self, telegram_id: int, bio: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60.0, headers=self._headers) as c:
                r = await c.post(
                    f"{self.base_url}/users/{telegram_id}/analyze-bio", json={"bio": bio}
                )
                if r.status_code == 404:
                    return {"success": False, "message": "Пользователь не найден"}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"success": False, "message": "Сервис недоступен."}

    async def search_events(self, query=None, topics=None, format=None, city=None) -> list[dict]:
        params: dict = {}
        if query:
            params["q"] = query
        if topics:
            params["topics"] = ",".join(topics)
        if format:
            params["format"] = format
        if city:
            params["city"] = city
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/events/search", params=params)
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def get_similar_events(self, event_id: int, limit: int = 3) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(
                    f"{self.base_url}/events/{event_id}/similar", params={"limit": limit}
                )
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def combined_search(
        self,
        query: str,
        keyword_limit: int = 3,
        semantic_limit: int = 5,
    ) -> dict:
        """Объединённый поиск: keyword + semantic параллельно, с дедупом.

        Возвращает {keyword: [...], semantic: [...]}. semantic уже отфильтрован
        от event_id, попавших в keyword-блок.
        """
        params = {"q": query, "keyword_limit": keyword_limit, "semantic_limit": semantic_limit}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/events/combined-search", params=params)
                if r.status_code == 404:
                    return {"keyword": [], "semantic": [], "goal_intent": False}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"keyword": [], "semantic": [], "goal_intent": False}

    async def semantic_search_events(self, query: str, limit: int = 5) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=self._headers) as c:
                r = await c.get(
                    f"{self.base_url}/events/semantic-search",
                    params={"q": query, "limit": limit},
                )
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def get_trending(self, days: int = 7) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/analytics/trending", params={"days": days})
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def copilot(self, telegram_id: int, goal: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60.0, headers=self._headers) as c:
                r = await c.post(
                    f"{self.base_url}/copilot/{telegram_id}",
                    json={"goal": goal},
                )
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"success": False, "message": "Copilot временно недоступен."}

    async def copilot_turn(
        self,
        telegram_id: int,
        message: str,
        session_id: int | None = None,
    ) -> dict:
        """Мульти-туровый Copilot: новый message в (опц.) существующей сессии.

        Возвращает {success, session_id, answer, cards, specialist, ...}.
        Сессия сохраняется в copilot_sessions на бэкенде, контекст подхватывается.
        """
        payload: dict = {"message": message}
        if session_id is not None:
            payload["session_id"] = session_id
        try:
            async with httpx.AsyncClient(timeout=60.0, headers=self._headers) as c:
                r = await c.post(
                    f"{self.base_url}/copilot/{telegram_id}/turn",
                    json=payload,
                )
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"success": False, "message": "Copilot временно недоступен."}

    async def get_vocabulary(self, kind: str) -> list[dict]:
        """Получить динамический словарь: topics / cities / formats / levels."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as c:
                r = await c.get(f"{self.base_url}/vocabulary/{kind}")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []
