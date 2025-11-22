import os
import json
import boto3
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any

from context import get_tenant_from_context
from dynamo import create_event
from models import EventCreateResponse

router = APIRouter()

sqs = boto3.client("sqs")
EVENTS_QUEUE_URL = os.environ["EVENTS_QUEUE_URL"]


@router.post("/events", status_code=201, response_model=EventCreateResponse)
async def ingest_event(request: Request, payload: Dict[str, Any]):
    """
    Ingest event: store in DynamoDB and enqueue to SQS for delivery.

    Authentication is handled by API Gateway Lambda authorizer.
    Tenant context is extracted from request.scope["aws.event"].
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
