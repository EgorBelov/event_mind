from typing import Literal

from pydantic import BaseModel


class InteractionCreate(BaseModel):
    telegram_id: int
    event_id: int
    action: Literal["like", "dislike", "save"]
