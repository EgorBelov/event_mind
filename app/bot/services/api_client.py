import httpx

from app.core.config import API_HOST

# Дефолтный таймаут httpx — 5 c, а /recommendations при пересчёте эмбеддингов
# по всем событиям легко уходит за 15 c. Без явного таймаута бот ловил
# ReadTimeout → except httpx.HTTPError → [] → «Пока нет рекомендаций».
_TIMEOUT = httpx.Timeout(30.0)


class EventMindAPIClient:
    def __init__(self, base_url: str = API_HOST):
        self.base_url = base_url.rstrip("/")

    async def register_user(self, telegram_id, username, preferred_format, city, topics) -> dict:
        payload = {"telegram_id": telegram_id, "username": username,
                   "preferred_format": preferred_format, "city": city, "topics": topics}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.post(f"{self.base_url}/users/register", json=payload)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def get_user(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{self.base_url}/users/{telegram_id}")
                if r.status_code == 404:
                    return {}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def get_recommendations(self, telegram_id: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{self.base_url}/recommendations/{telegram_id}")
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def save_interaction(self, telegram_id: int, event_id: int, action: str) -> dict:
        payload = {"telegram_id": telegram_id, "event_id": event_id, "action": action}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.post(f"{self.base_url}/recommendations/interactions", json=payload)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def get_event_interactions(self, telegram_id: int, event_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
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
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{self.base_url}/recommendations/{telegram_id}/saved")
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def subscribe(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.post(f"{self.base_url}/subscriptions/{telegram_id}/subscribe")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"message": "Не удалось оформить подписку. Попробуй позже."}

    async def unsubscribe(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.post(f"{self.base_url}/subscriptions/{telegram_id}/unsubscribe")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"message": "Не удалось отписаться. Попробуй позже."}

    async def get_agent_recommendation_cards(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60.0) as c:
                r = await c.get(f"{self.base_url}/agent-recommendations/{telegram_id}/cards")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"success": False, "message": "Не удалось получить AI-рекомендации."}

    async def get_user_stats(self, telegram_id: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{self.base_url}/users/{telegram_id}/stats")
                if r.status_code == 404:
                    return {"success": False}
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"success": False}

    async def analyze_bio(self, telegram_id: int, bio: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60.0) as c:
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
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{self.base_url}/events/search", params=params)
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def get_similar_events(self, event_id: int, limit: int = 3) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(
                    f"{self.base_url}/events/{event_id}/similar", params={"limit": limit}
                )
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []

    async def semantic_search_events(self, query: str, limit: int = 5) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
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
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{self.base_url}/analytics/trending", params={"days": days})
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {}

    async def copilot(self, telegram_id: int, goal: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60.0) as c:
                r = await c.post(
                    f"{self.base_url}/copilot/{telegram_id}",
                    json={"goal": goal},
                )
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return {"success": False, "message": "Copilot временно недоступен."}

    async def get_vocabulary(self, kind: str) -> list[dict]:
        """Получить динамический словарь: topics / cities / formats / levels."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(f"{self.base_url}/vocabulary/{kind}")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            return []
