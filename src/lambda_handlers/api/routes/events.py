import os
import uuid
import time
import boto3
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional

from ..auth import verify_api_key
from ..models import EventCreateRequest, EventResponse, EventDetail, EventListResponse, AckRequest, AckResponse

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


@router.get("", response_model=EventListResponse)
async def list_events(
    status: Optional[str] = None,
    limit: int = 50,
    tenant_id: str = Depends(verify_api_key)
):
    """
    List events for the authenticated tenant.

    Query parameters:
    - status: Filter by status ("undelivered" or "delivered")
    - limit: Maximum number of events to return (default 50, max 100)
    """
    if limit > 100:
        limit = 100

    try:
        if status:
            # Query using GSI for status filtering
            response = events_table.query(
                IndexName='status-index',
                KeyConditionExpression='gsi1pk = :tenant_id AND begins_with(gsi1sk, :status)',
                ExpressionAttributeValues={
                    ':tenant_id': tenant_id,
                    ':status': f"{status}#"
                },
                Limit=limit,
                ScanIndexForward=True  # Oldest first
            )
        else:
            # Query main table for all events
            response = events_table.query(
                KeyConditionExpression='pk = :tenant_id',
                ExpressionAttributeValues={
                    ':tenant_id': tenant_id
                },
                Limit=limit,
                ScanIndexForward=False  # Newest first
            )

        items = response.get('Items', [])

        events = [
            EventDetail(
                id=item['event_id'],
                created_at=item['timestamp'],
                status=item['status'],
                payload=item['payload']
            )
            for item in items
        ]

        return EventListResponse(events=events)

    except Exception as e:
        print(f"Error listing events: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to list events"
        )


@router.get("/{event_id}", response_model=EventDetail)
async def get_event(
    event_id: str,
    tenant_id: str = Depends(verify_api_key)
):
    """
    Retrieve a single event by ID.

    Returns 404 if event doesn't exist or doesn't belong to tenant.
    """
    try:
        response = events_table.get_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            }
        )

        item = response.get('Item')
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Event {event_id} not found"
            )

        return EventDetail(
            id=item['event_id'],
            created_at=item['timestamp'],
            status=item['status'],
            payload=item['payload']
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving event: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve event"
        )


@router.post("/{event_id}/ack", response_model=AckResponse)
async def acknowledge_event(
    event_id: str,
    tenant_id: str = Depends(verify_api_key)
):
    """
    Mark an event as delivered (acknowledged).

    Updates the status from "undelivered" to "delivered" and updates GSI attributes.
    This operation is idempotent - acknowledging an already-acknowledged event returns success.
    """
    try:
        # First verify the event exists and belongs to this tenant
        response = events_table.get_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            }
        )

        item = response.get('Item')
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Event {event_id} not found"
            )

        if item.get('status') == 'delivered':
            # Already acknowledged, return success (idempotent)
            return AckResponse()

        # Update status to delivered
        timestamp = item['timestamp']
        events_table.update_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            },
            UpdateExpression='SET #status = :delivered, gsi1sk = :gsi1sk',
            ExpressionAttributeNames={
                '#status': 'status'
            },
            ExpressionAttributeValues={
                ':delivered': 'delivered',
                ':gsi1sk': f"delivered#{timestamp}"
            }
        )

        return AckResponse()

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error acknowledging event: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to acknowledge event"
        )


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    tenant_id: str = Depends(verify_api_key)
):
    """
    Delete an event.

    Returns 204 No Content on success, 404 if event doesn't exist.
    """
    try:
        # Check if event exists first
        response = events_table.get_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            }
        )

        if not response.get('Item'):
            raise HTTPException(
                status_code=404,
                detail=f"Event {event_id} not found"
            )

        # Delete the event
        events_table.delete_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            }
        )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting event: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to delete event"
        )
