from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime


class EventCreateRequest(BaseModel):
    """Free-form JSON payload for event creation"""
    class Config:
        extra = "allow"  # Allow arbitrary fields


class EventResponse(BaseModel):
    id: str
    created_at: int  # epoch_ms
    status: str


class EventDetail(BaseModel):
    id: str
    created_at: int
    status: str
    payload: Dict[str, Any]


class AckRequest(BaseModel):
    pass  # No body needed, event_id in path


class AckResponse(BaseModel):
    status: str = "acknowledged"


class EventListResponse(BaseModel):
    events: list[EventDetail]
