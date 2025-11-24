import os
import json
import boto3
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any, Optional

from context import get_tenant_from_context
from dynamo import create_event, list_events, get_event, reset_event_for_retry, update_tenant_config
from models import (
    EventCreateResponse,
    EventListResponse,
    EventListItem,
    EventDetailResponse,
    EventDetail,
    RetryResponse,
    TenantConfigUpdate,
    TenantConfigResponse,
    encode_pagination_token,
    decode_pagination_token,
)

router = APIRouter()

sqs = boto3.client("sqs")
EVENTS_QUEUE_URL = os.environ["EVENTS_QUEUE_URL"]


@router.post("/v1/events", status_code=201, response_model=EventCreateResponse)
async def ingest_event(request: Request, payload: Dict[str, Any]):
    """
    Ingest event: store in DynamoDB and enqueue to SQS for delivery.

    Authentication is handled by API Gateway Lambda authorizer.
    Tenant context is extracted from request.scope["aws.event"].

    Note: /v1 prefix matches API Gateway resource structure.
    """
    # Extract Lambda event from Mangum
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    tenant_id = tenant["tenantId"]
    target_url = tenant["targetUrl"]

    # Store event in DynamoDB
    event_id = create_event(tenant_id, payload, target_url)

    # Enqueue to SQS for worker to process
    message_body = json.dumps(
        {
            "tenantId": tenant_id,
            "eventId": event_id,
        }
    )

    try:
        sqs.send_message(
            QueueUrl=EVENTS_QUEUE_URL,
            MessageBody=message_body,
        )
    except Exception as e:
        print(f"Error enqueuing to SQS: {e}")
        raise HTTPException(status_code=500, detail="Failed to enqueue event")

    return EventCreateResponse(event_id=event_id, status="PENDING")


@router.get("/v1/events", response_model=EventListResponse)
async def list_tenant_events(
    request: Request,
    status: Optional[str] = None,
    limit: int = 50,
    next_token: Optional[str] = None,
):
    """
    List all events for the authenticated tenant.

    Query Parameters:
    - status: Filter by event status (PENDING, DELIVERED, FAILED)
    - limit: Maximum number of events to return (default 50, max 100)
    - next_token: Pagination token from previous response

    Returns paginated list of events with summary information.
    Authentication via Bearer token required (API Gateway Lambda Authorizer).
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    tenant_id = tenant["tenantId"]

    # Validate status parameter if provided
    if status and status not in ["PENDING", "DELIVERED", "FAILED"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Must be one of: PENDING, DELIVERED, FAILED"
        )

    # Validate and cap limit
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="Invalid limit. Must be between 1 and 100"
        )

    # Decode pagination token
    last_evaluated_key = decode_pagination_token(next_token) if next_token else None

    # Query DynamoDB
    try:
        result = list_events(tenant_id, status=status, limit=limit, last_evaluated_key=last_evaluated_key)
    except Exception as e:
        print(f"Error listing events for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve events")

    # Convert to response model
    events_list = [
        EventListItem(
            event_id=item["eventId"],
            status=item["status"],
            created_at=item["createdAt"],
            attempts=item.get("attempts", 0),
            last_attempt_at=item.get("lastAttemptAt"),
        )
        for item in result["events"]
    ]

    # Encode next pagination token
    next_pagination_token = encode_pagination_token(result.get("lastEvaluatedKey"))

    return EventListResponse(
        events=events_list,
        next_token=next_pagination_token,
        total_count=len(events_list),
    )


@router.get("/v1/events/{event_id}", response_model=EventDetailResponse)
async def get_event_details(
    request: Request,
    event_id: str,
):
    """
    Get detailed information about a specific event.

    Path Parameters:
    - event_id: The unique event identifier

    Returns full event details including payload, delivery attempts, and error messages.
    Authentication via Bearer token required (API Gateway Lambda Authorizer).

    Raises:
    - 404: Event not found or does not belong to authenticated tenant
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    tenant_id = tenant["tenantId"]

    # Retrieve event from DynamoDB
    event_data = get_event(tenant_id, event_id)

    if not event_data:
        raise HTTPException(
            status_code=404,
            detail=f"Event {event_id} not found or does not belong to your tenant"
        )

    # Convert to response model
    event_detail = EventDetail(
        event_id=event_data["eventId"],
        status=event_data["status"],
        created_at=event_data["createdAt"],
        payload=event_data["payload"],
        target_url=event_data["targetUrl"],
        attempts=event_data.get("attempts", 0),
        last_attempt_at=event_data.get("lastAttemptAt"),
        error_message=event_data.get("errorMessage"),
    )

    return EventDetailResponse(event=event_detail)


@router.post("/v1/events/{event_id}/retry", response_model=RetryResponse)
async def retry_failed_event(
    request: Request,
    event_id: str,
):
    """
    Manually retry a failed event.

    Path Parameters:
    - event_id: The unique event identifier

    This endpoint resets a FAILED event to PENDING status and requeues it
    to SQS for immediate reprocessing. Only events with status=FAILED can be retried.

    Authentication via Bearer token required (API Gateway Lambda Authorizer).

    Raises:
    - 404: Event not found, belongs to different tenant, or not in FAILED status
    - 500: Failed to requeue event
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    tenant_id = tenant["tenantId"]

    # First verify event exists and belongs to tenant
    event_data = get_event(tenant_id, event_id)

    if not event_data:
        raise HTTPException(
            status_code=404,
            detail=f"Event {event_id} not found or does not belong to your tenant"
        )

    # Check current status
    if event_data["status"] != "FAILED":
        raise HTTPException(
            status_code=400,
            detail=f"Event {event_id} has status '{event_data['status']}'. Only FAILED events can be retried."
        )

    # Reset event to PENDING in DynamoDB
    success = reset_event_for_retry(tenant_id, event_id)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to reset event status"
        )

    # Requeue to SQS
    message_body = json.dumps({
        "tenantId": tenant_id,
        "eventId": event_id,
    })

    try:
        sqs.send_message(
            QueueUrl=EVENTS_QUEUE_URL,
            MessageBody=message_body,
        )
    except Exception as e:
        print(f"Error requeuing event {event_id} to SQS: {e}")
        raise HTTPException(status_code=500, detail="Failed to requeue event for delivery")

    return RetryResponse(
        event_id=event_id,
        status="PENDING",
        message="Event requeued for delivery"
    )


@router.patch("/v1/tenants/current", response_model=TenantConfigResponse)
async def update_tenant_configuration(
    request: Request,
    config: TenantConfigUpdate,
):
    """
    Update tenant webhook configuration.

    Request Body:
    - target_url: New webhook delivery URL (optional)
    - webhook_secret: New HMAC secret for signature validation (optional)

    At least one field must be provided. Changes take effect immediately for new events.
    Authentication via Bearer token required (API Gateway Lambda Authorizer).

    Security Note: Updating webhook_secret will invalidate signatures on in-flight webhooks.
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    tenant_id = tenant["tenantId"]

    # Get API key from authorizer context
    # The API key is not in authorizer context, but we can extract it from the Authorization header
    auth_header = event.get("headers", {}).get("authorization") or event.get("headers", {}).get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    api_key = auth_header[7:]  # Remove "Bearer " prefix

    # Validate at least one field is provided
    if not config.target_url and not config.webhook_secret:
        raise HTTPException(
            status_code=400,
            detail="At least one field (target_url or webhook_secret) must be provided"
        )

    # Update tenant configuration
    try:
        updated_config = update_tenant_config(
            api_key=api_key,
            target_url=config.target_url,
            webhook_secret=config.webhook_secret,
        )
    except Exception as e:
        print(f"Error updating tenant config for {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update tenant configuration")

    return TenantConfigResponse(
        tenant_id=tenant_id,
        target_url=updated_config["targetUrl"],
        updated_at=updated_config["updatedAt"],
        message="Tenant configuration updated successfully"
    )
