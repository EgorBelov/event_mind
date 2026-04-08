import httpx

from app.core.config import API_HOST


class EventMindAPIClient:
    def __init__(self, base_url: str = API_HOST):
        self.base_url = base_url.rstrip("/")

    async def register_user(
        self,
        telegram_id: int,
        username: str | None,
        preferred_format: str | None,
        city: str | None,
        topics: list[str],
    ) -> dict:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "preferred_format": preferred_format,
            "city": city,
            "topics": topics,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.base_url}/users/register", json=payload)
            response.raise_for_status()
            return response.json()

    async def get_user(self, telegram_id: int) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/users/{telegram_id}")
            response.raise_for_status()
            return response.json()

    async def get_recommendations(self, telegram_id: int) -> list[dict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/recommendations/{telegram_id}")
            response.raise_for_status()
            return response.json()

    async def save_interaction(self, telegram_id: int, event_id: int, action: str) -> dict:
        payload = {
            "telegram_id": telegram_id,
            "event_id": event_id,
            "action": action,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.base_url}/recommendations/interactions", json=payload)
            response.raise_for_status()
            return response.json()

    async def get_event_interactions(self, telegram_id: int, event_id: int) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/recommendations/{telegram_id}/event/{event_id}/interactions"
            )
            response.raise_for_status()
            return response.json()