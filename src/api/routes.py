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
    mark_event_as_purged,
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
    TenantCreate,
    TenantCreateResponse,
    TenantConfigUpdate,
    TenantConfigResponse,
    TenantDetail,
    TenantDetailResponse,
    encode_pagination_token,
    decode_pagination_token,
    DlqMessagesResponse,
    DlqMessage,
    DlqRequeueRequest,
    DlqRequeueResponse,
    DlqPurgeResponse,
)

router = APIRouter()

sqs = boto3.client("sqs")
lambda_client = boto3.client("lambda")
EVENTS_QUEUE_URL = os.environ["EVENTS_QUEUE_URL"]
EVENTS_DLQ_URL = os.environ.get("EVENTS_DLQ_URL")
DLQ_PROCESSOR_FUNCTION_NAME = os.environ.get("DLQ_PROCESSOR_FUNCTION_NAME")


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

    # Fetch targetUrl from TenantWebhookConfig (not available in authorizer context)
    tenant_config = get_tenant_by_id(tenant_id)
    if not tenant_config:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant {tenant_id} webhook configuration not found",
        )
    target_url = tenant_config["target_url"]

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
    - status: Filter by event status (PENDING, DELIVERED, FAILED, PURGED)
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
    if status and status not in ["PENDING", "DELIVERED", "FAILED", "PURGED"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Must be one of: PENDING, DELIVERED, FAILED, PURGED",
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


@router.post("/v1/events/{event_id}/retry", response_model=EventDetail, tags=["Events"])
async def retry_event(
    request: Request,
    event_id: str,
):
    """
    Retry a failed event.

    Manually retry a FAILED event by resetting its status to PENDING and requeuing it for delivery.
    The attempt count is preserved (not reset) to maintain retry history.

    Path Parameters:
    - event_id: The unique event identifier

    Returns updated event details with status set to PENDING.

    Authentication via Bearer token required (API Gateway Lambda Authorizer).

    Raises:
    - 404: Event not found or does not belong to authenticated tenant
    - 400: Event is not in FAILED status (only FAILED events can be retried)
    - 500: Failed to reset event status or requeue event
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

    # Verify event is in FAILED status
    if event_data["status"] != "FAILED":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry event with status '{event_data['status']}'. Only FAILED events can be retried.",
        )

    # Prevent excessive manual retries
    # Each manual retry creates a NEW SQS message (not a retry of existing message)
    # This can create many duplicate messages if retried repeatedly
    # After 5 manual retries, encourage using DLQ requeue endpoint instead
    attempts = event_data.get("attempts", 0)
    if attempts >= 5:
        raise HTTPException(
            status_code=400,
            detail=f"Event has {attempts} attempts. Manual retries create new SQS messages and can lead to duplicate processing. "
            f"For events with 5+ attempts, check DLQ first (GET /v1/admin/dlq/messages) and use POST /v1/admin/dlq/requeue if needed.",
        )

    # Reset event to PENDING in DynamoDB (preserves attempt count)
    success = reset_event_for_retry(tenant_id, event_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to reset event status")

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
    tags=["Demo Tenants"],
)
async def create_new_tenant(
    request: Request,
    tenant: TenantCreate,
):
    """
    Create a new tenant with auto-generated API key.

    ⚠️ **Demo Only**: Tenant creation is included for demo convenience and is not part of the production interface. Zapier would supply tenant records internally.

    Request Body:
    - tenant_id: Unique tenant identifier (lowercase alphanumeric + hyphens)
    - target_url: Webhook delivery URL (must be https). For the webhook receiver,
      use format: `https://receiver.vincentchan.cloud/{tenant_id}/webhook`
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
    "/v1/tenants/{tenant_id}",
    response_model=TenantDetailResponse,
    tags=["Demo Tenants"],
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
    "/v1/tenants/{tenant_id}",
    response_model=TenantConfigResponse,
    tags=["Demo Tenants"],
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


# ============================================================
# DLQ Management Endpoints (Admin)
# ============================================================


@router.get(
    "/v1/admin/dlq/messages",
    response_model=DlqMessagesResponse,
    tags=["DLQ Management"],
)
async def get_dlq_messages(request: Request, limit: int = 10):
    """
    List messages currently in the Dead Letter Queue.

    Query Parameters:
    - limit: Maximum number of messages to return (default 10, max 10)

    Returns raw DLQ messages with metadata (messageId, receiptHandle, body, attributes).
    Messages are NOT deleted from the DLQ by this endpoint.

    Authentication via Bearer token required (API Gateway Lambda Authorizer).
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    if not EVENTS_DLQ_URL:
        raise HTTPException(
            status_code=500, detail="DLQ URL not configured in environment"
        )

    # Validate limit
    if limit < 1 or limit > 10:
        raise HTTPException(
            status_code=400, detail="Invalid limit. Must be between 1 and 10"
        )

    try:
        # Receive messages from DLQ (without deleting them)
        response = sqs.receive_message(
            QueueUrl=EVENTS_DLQ_URL,
            MaxNumberOfMessages=limit,
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )

        messages = response.get("Messages", [])

        # Convert to response model
        dlq_messages = [
            DlqMessage(
                messageId=msg["MessageId"],
                receiptHandle=msg["ReceiptHandle"],
                body=json.loads(msg["Body"]),
                attributes=msg.get("Attributes", {}),
            )
            for msg in messages
        ]

        return DlqMessagesResponse(messages=dlq_messages)

    except Exception as e:
        print(f"Error retrieving DLQ messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve DLQ messages")


@router.post(
    "/v1/admin/dlq/requeue",
    response_model=DlqRequeueResponse,
    tags=["DLQ Management"],
)
async def requeue_dlq_messages(request: Request, req: DlqRequeueRequest):
    """
    Requeue messages from DLQ back to the main events queue.

    Request Body:
    - batchSize: Number of messages to process per batch (default 10, max 10)
    - maxMessages: Maximum total messages to requeue (default 100, max 1000)

    This endpoint invokes the DLQ Processor Lambda function, which:
    1. Reads messages from DLQ
    2. Validates message format
    3. Sends valid messages back to main queue
    4. Deletes processed messages from DLQ

    Returns the number of messages successfully requeued and failed.

    Authentication via Bearer token required (API Gateway Lambda Authorizer).
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    if not DLQ_PROCESSOR_FUNCTION_NAME:
        raise HTTPException(
            status_code=500,
            detail="DLQ Processor function name not configured in environment",
        )

    try:
        # Invoke DLQ Processor Lambda
        response = lambda_client.invoke(
            FunctionName=DLQ_PROCESSOR_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {
                    "batchSize": req.batchSize,
                    "maxMessages": req.maxMessages,
                }
            ),
        )

        # Parse response
        response_payload = json.loads(response["Payload"].read())
        if response.get("FunctionError"):
            raise Exception(f"Lambda error: {response_payload}")

        # DLQ Processor returns statusCode and body
        if isinstance(response_payload, dict) and "body" in response_payload:
            result = json.loads(response_payload["body"])
        else:
            result = response_payload

        return DlqRequeueResponse(
            requeued=result.get("requeued", 0), failed=result.get("failed", 0)
        )

    except Exception as e:
        print(f"Error invoking DLQ Processor: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to requeue DLQ messages: {str(e)}"
        )


@router.post(
    "/v1/admin/dlq/purge",
    response_model=DlqPurgeResponse,
    tags=["DLQ Management"],
)
async def purge_dlq(request: Request):
    """
    Completely purge all messages from the Dead Letter Queue.

    ⚠️ **Warning**: This operation is irreversible. All messages in the DLQ will be permanently deleted.

    Returns confirmation with the DLQ URL that was purged.

    Authentication via Bearer token required (API Gateway Lambda Authorizer).
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    if not EVENTS_DLQ_URL:
        raise HTTPException(
            status_code=500, detail="DLQ URL not configured in environment"
        )

    try:
        # First, read all DLQ messages to get event IDs before purging
        events_marked = 0
        events_failed = 0

        # Receive messages in batches to extract event IDs
        # Note: We don't delete messages here - purge_queue will delete all messages
        max_iterations = 100  # Safety limit to prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            response = sqs.receive_message(
                QueueUrl=EVENTS_DLQ_URL,
                MaxNumberOfMessages=10,  # Max batch size
                WaitTimeSeconds=0,  # Don't wait, return immediately
            )

            messages = response.get("Messages", [])
            if not messages:
                # No more messages
                break

            # Extract event IDs and mark events as PURGED
            for message in messages:
                try:
                    body = json.loads(message["Body"])
                    tenant_id = body.get("tenantId")
                    event_id = body.get("eventId")

                    if tenant_id and event_id:
                        if mark_event_as_purged(tenant_id, event_id):
                            events_marked += 1
                        else:
                            events_failed += 1
                    else:
                        print(f"Invalid message format in DLQ: {body}")
                        events_failed += 1
                except Exception as e:
                    print(f"Error processing DLQ message: {e}")
                    events_failed += 1

            # If we got fewer than max messages, we've read all available
            if len(messages) < 10:
                break

        # Now purge the DLQ (this deletes all messages)
        sqs.purge_queue(QueueUrl=EVENTS_DLQ_URL)

        print(
            f"Purged DLQ: marked {events_marked} events as PURGED, {events_failed} failed"
        )

        return DlqPurgeResponse(status="purged", queue=EVENTS_DLQ_URL)

    except Exception as e:
        print(f"Error purging DLQ: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to purge DLQ: {str(e)}")
