from pydantic import BaseModel
from typing import Any, Dict


class EventCreateRequest(BaseModel):
    """Free-form JSON payload for event creation"""

    class Config:
        extra = "allow"


class EventCreateResponse(BaseModel):
    event_id: str
    status: str  # "PENDING"
