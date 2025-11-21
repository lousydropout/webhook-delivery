import os
import uuid
import time
import boto3
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any

from auth import verify_api_key
from models import EventCreateRequest, EventResponse

router = APIRouter(prefix="/v1/events", tags=["events"])

dynamodb = boto3.resource('dynamodb')
events_table = dynamodb.Table(os.environ.get('EVENTS_TABLE', 'TriggerApi-Events'))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EventResponse)
async def create_event(
    payload: Dict[str, Any],
    tenant_id: str = Depends(verify_api_key)
):
    """
    Ingest a new event for the authenticated tenant.

    The payload is free-form JSON and stored as-is.
    """
    event_id = f"evt_{uuid.uuid4().hex[:8]}"
    timestamp = int(time.time() * 1000)  # epoch_ms

    item = {
        'pk': tenant_id,
        'sk': event_id,
        'tenant_id': tenant_id,
        'event_id': event_id,
        'status': 'undelivered',
        'timestamp': timestamp,
        'payload': payload,
        # GSI attributes for status-index
        'gsi1pk': tenant_id,
        'gsi1sk': f"undelivered#{timestamp}"
    }

    try:
        events_table.put_item(Item=item)
    except Exception as e:
        print(f"Error storing event: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to store event"
        )

    return EventResponse(
        id=event_id,
        created_at=timestamp,
        status="undelivered"
    )
