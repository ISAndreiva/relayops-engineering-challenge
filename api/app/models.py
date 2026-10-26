from typing import Any

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]
