from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List
from decimal import Decimal
import base64
import json


class EventCreateRequest(BaseModel):
    """Free-form JSON payload for event creation"""

    class Config:
        extra = "allow"


class EventCreateResponse(BaseModel):
    event_id: str
    status: str  # "PENDING"


class EventDetail(BaseModel):
    """Single event with full details"""

    event_id: str
    status: str  # PENDING, DELIVERED, FAILED
    created_at: str  # Unix timestamp as string
    payload: Dict[str, Any]
    target_url: str
    attempts: int
    last_attempt_at: Optional[str] = None
    error_message: Optional[str] = None

    class Config:
        # Allow Decimal from DynamoDB
        json_encoders = {Decimal: lambda v: int(v) if v % 1 == 0 else float(v)}


class EventListItem(BaseModel):
    """Summary view of event for list endpoint"""

    event_id: str
    status: str
    created_at: str
    attempts: int
    last_attempt_at: Optional[str] = None

    class Config:
        json_encoders = {Decimal: lambda v: int(v) if v % 1 == 0 else float(v)}


class EventListResponse(BaseModel):
    """Response for GET /v1/events"""

    events: List[EventListItem]
    next_token: Optional[str] = None  # Base64-encoded pagination token
    total_count: int  # Number of events in this response


class EventDetailResponse(BaseModel):
    """Response for GET /v1/events/{eventId}"""

    event: EventDetail


class TenantConfigResponse(BaseModel):
    """Response for PATCH /v1/tenants/{tenant_id}"""

    tenant_id: str
    target_url: str
    updated_at: str
    message: str


class EventUpdate(BaseModel):
    """Request body for PATCH /v1/events/{event_id}"""

    status: Optional[str] = None

    class Config:
        extra = "forbid"


class TenantConfigUpdate(BaseModel):
    """Request body for PATCH /v1/tenants/{tenant_id}"""

    target_url: Optional[str] = None
    webhook_secret: Optional[str] = None

    class Config:
        # At least one field must be provided
        extra = "forbid"


class TenantCreate(BaseModel):
    """Request body for POST /v1/tenants"""

    tenant_id: str = Field(..., min_length=3, max_length=50, pattern="^[a-z0-9-]+$")
    target_url: str = Field(..., pattern="^https?://")
    webhook_secret: Optional[str] = None

    class Config:
        extra = "forbid"


class TenantCreateResponse(BaseModel):
    """Response for POST /v1/tenants"""

    tenant_id: str
    api_key: str
    target_url: str
    webhook_secret: str
    created_at: str
    message: str


class TenantDetail(BaseModel):
    """Tenant details (safe for GET responses)"""

    tenant_id: str
    target_url: str
    created_at: str
    updated_at: str


class TenantDetailResponse(BaseModel):
    """Response for GET /v1/tenants/{tenant_id}"""

    tenant: TenantDetail


def encode_pagination_token(last_evaluated_key: Dict[str, Any]) -> str:
    """Encode DynamoDB LastEvaluatedKey as base64 token"""
    if not last_evaluated_key:
        return None
    return base64.b64encode(json.dumps(last_evaluated_key).encode()).decode()


def decode_pagination_token(token: str) -> Dict[str, Any]:
    """Decode base64 pagination token to DynamoDB key"""
    if not token:
        return None
    try:
        return json.loads(base64.b64decode(token.encode()).decode())
    except Exception:
        return None
