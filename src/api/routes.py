import os
import json
import boto3
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any, Optional

from context import get_tenant_from_context
from dynamo import (
    create_event,
    list_events,
    get_event,
    reset_event_for_retry,
    create_tenant,
    get_tenant_by_id,
    update_tenant_config_by_id,
)
from models import (
    EventCreateResponse,
    EventListResponse,
    EventListItem,
    EventDetailResponse,
    EventDetail,
    EventUpdate,
    TenantCreate,
    TenantCreateResponse,
    TenantConfigUpdate,
    TenantConfigResponse,
    TenantDetail,
    TenantDetailResponse,
    encode_pagination_token,
    decode_pagination_token,
)

router = APIRouter()

sqs = boto3.client("sqs")
EVENTS_QUEUE_URL = os.environ["EVENTS_QUEUE_URL"]


@router.post(
    "/v1/events", status_code=201, response_model=EventCreateResponse, tags=["Events"]
)
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


@router.get("/v1/events", response_model=EventListResponse, tags=["Events"])
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
            detail="Invalid status. Must be one of: PENDING, DELIVERED, FAILED",
        )

    # Validate and cap limit
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400, detail="Invalid limit. Must be between 1 and 100"
        )

    # Decode pagination token
    last_evaluated_key = decode_pagination_token(next_token) if next_token else None

    # Query DynamoDB
    try:
        result = list_events(
            tenant_id, status=status, limit=limit, last_evaluated_key=last_evaluated_key
        )
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


@router.get(
    "/v1/events/{event_id}", response_model=EventDetailResponse, tags=["Events"]
)
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
            detail=f"Event {event_id} not found or does not belong to your tenant",
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


@router.patch("/v1/events/{event_id}", response_model=EventDetail, tags=["Events"])
async def update_event(
    request: Request,
    event_id: str,
    update: EventUpdate,
):
    """
    Update an event's mutable fields.

    Currently supports:
    - status: Change to "PENDING" to retry a FAILED event

    Future: May support updating other fields like target_url, payload, etc.

    Path Parameters:
    - event_id: The unique event identifier

    Request Body:
    - status: New status ("PENDING" to trigger retry)

    Returns updated event details.
    Authentication via Bearer token required (API Gateway Lambda Authorizer).

    Raises:
    - 404: Event not found or does not belong to authenticated tenant
    - 400: Invalid status transition
    """
    # Extract tenant context from Lambda Authorizer
    event_context = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event_context)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    tenant_id = tenant["tenantId"]

    # First verify event exists and belongs to tenant
    event_data = get_event(tenant_id, event_id)

    if not event_data:
        raise HTTPException(
            status_code=404,
            detail=f"Event {event_id} not found or does not belong to your tenant",
        )

    # Handle status update (retry logic)
    if update.status:
        if update.status == "PENDING":
            # This is a retry operation
            if event_data["status"] != "FAILED":
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot retry event with status '{event_data['status']}'. Only FAILED events can be retried.",
                )

            # Reset event to PENDING in DynamoDB
            success = reset_event_for_retry(tenant_id, event_id)

            if not success:
                raise HTTPException(
                    status_code=500, detail="Failed to reset event status"
                )

            # Requeue to SQS
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
                print(f"Error requeuing event {event_id} to SQS: {e}")
                raise HTTPException(
                    status_code=500, detail="Failed to requeue event for delivery"
                )
        else:
            # Future: Handle other status transitions
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status transition to '{update.status}'",
            )

    # Fetch updated event
    updated_event_data = get_event(tenant_id, event_id)

    # Convert to response model
    event_detail = EventDetail(
        event_id=updated_event_data["eventId"],
        status=updated_event_data["status"],
        created_at=updated_event_data["createdAt"],
        payload=updated_event_data["payload"],
        target_url=updated_event_data["targetUrl"],
        attempts=updated_event_data.get("attempts", 0),
        last_attempt_at=updated_event_data.get("lastAttemptAt"),
        error_message=updated_event_data.get("errorMessage"),
    )

    return event_detail


@router.post(
    "/v1/tenants",
    response_model=TenantCreateResponse,
    status_code=201,
    tags=["Tenants"],
)
async def create_new_tenant(
    request: Request,
    tenant: TenantCreate,
):
    """
    Create a new tenant with auto-generated API key.

    Request Body:
    - tenant_id: Unique tenant identifier (lowercase alphanumeric + hyphens)
    - target_url: Webhook delivery URL (must be https)
    - webhook_secret: Optional HMAC secret (auto-generated if omitted)

    Returns the created tenant with API key and webhook secret.

    **Security Note**: Store the API key and webhook secret securely.
    The webhook secret cannot be retrieved later, only rotated.

    **Public Endpoint**: No authentication required for tenant creation.
    This enables self-service signup and simplifies demos/testing.
    In production, consider adding rate limiting or CAPTCHA to prevent abuse.
    """

    try:
        result = create_tenant(
            tenant_id=tenant.tenant_id,
            target_url=tenant.target_url,
            webhook_secret=tenant.webhook_secret,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        print(f"Error creating tenant {tenant.tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create tenant")

    return TenantCreateResponse(
        tenant_id=result["tenant_id"],
        api_key=result["api_key"],
        target_url=result["target_url"],
        webhook_secret=result["webhook_secret"],
        created_at=result["created_at"],
        message="Tenant created successfully. Store your API key and webhook secret securely.",
    )


@router.get(
    "/v1/tenants/{tenant_id}", response_model=TenantDetailResponse, tags=["Tenants"]
)
async def get_tenant(
    request: Request,
    tenant_id: str,
):
    """
    Get tenant details.

    Path Parameters:
    - tenant_id: Tenant identifier

    Returns tenant configuration (excluding webhook secret for security).

    Authentication via Bearer token required.
    Users can only access their own tenant details (enforced by authorizer context).

    Raises:
    - 403: Access denied - trying to access different tenant
    - 404: Tenant not found
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    auth_tenant_id = tenant["tenantId"]

    # Enforce tenant isolation: can only access own tenant
    if tenant_id != auth_tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access your own tenant details.",
        )

    # Retrieve tenant details
    tenant_data = get_tenant_by_id(tenant_id)

    if not tenant_data:
        raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

    # Convert to response model
    tenant_detail = TenantDetail(
        tenant_id=tenant_data["tenant_id"],
        target_url=tenant_data["target_url"],
        created_at=tenant_data["created_at"],
        updated_at=tenant_data["updated_at"],
    )

    return TenantDetailResponse(tenant=tenant_detail)


@router.patch(
    "/v1/tenants/{tenant_id}", response_model=TenantConfigResponse, tags=["Tenants"]
)
async def update_tenant(
    request: Request,
    tenant_id: str,
    config: TenantConfigUpdate,
):
    """
    Update tenant webhook configuration.

    Path Parameters:
    - tenant_id: Tenant identifier

    Request Body:
    - target_url: New webhook delivery URL (optional)
    - webhook_secret: New HMAC secret for signature validation (optional)

    At least one field must be provided. Changes take effect immediately for new events.
    Authentication via Bearer token required.
    Users can only update their own tenant configuration.

    Security Note: Updating webhook_secret will invalidate signatures on in-flight webhooks.

    Raises:
    - 400: No fields provided for update
    - 403: Access denied - trying to update different tenant
    - 404: Tenant not found
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    auth_tenant_id = tenant["tenantId"]

    # Enforce tenant isolation: can only update own tenant
    if tenant_id != auth_tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only update your own tenant configuration.",
        )

    # Validate at least one field is provided
    if not config.target_url and not config.webhook_secret:
        raise HTTPException(
            status_code=400,
            detail="At least one field (target_url or webhook_secret) must be provided",
        )

    # Update tenant configuration
    try:
        updated_config = update_tenant_config_by_id(
            tenant_id=tenant_id,
            target_url=config.target_url,
            webhook_secret=config.webhook_secret,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"Error updating tenant config for {tenant_id}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to update tenant configuration"
        )

    return TenantConfigResponse(
        tenant_id=tenant_id,
        target_url=updated_config["targetUrl"],
        updated_at=updated_config["updatedAt"],
        message="Tenant configuration updated successfully",
    )
