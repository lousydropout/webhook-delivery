import os
import json
import boto3
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any

from auth import verify_api_key
from dynamo import create_event
from models import EventCreateResponse

router = APIRouter()

sqs = boto3.client('sqs')
EVENTS_QUEUE_URL = os.environ['EVENTS_QUEUE_URL']


@router.post("/events", status_code=201, response_model=EventCreateResponse)
async def ingest_event(
    payload: Dict[str, Any],
    tenant: Dict = Depends(verify_api_key)
):
    """
    Ingest event: store in DynamoDB and enqueue to SQS for delivery.
    """
    tenant_id = tenant['tenantId']
    target_url = tenant['targetUrl']

    # Store event in DynamoDB
    event_id = create_event(tenant_id, payload, target_url)

    # Enqueue to SQS for worker to process
    message_body = json.dumps({
        'tenantId': tenant_id,
        'eventId': event_id,
    })

    try:
        sqs.send_message(
            QueueUrl=EVENTS_QUEUE_URL,
            MessageBody=message_body,
        )
    except Exception as e:
        print(f"Error enqueuing to SQS: {e}")
        raise HTTPException(status_code=500, detail="Failed to enqueue event")

    return EventCreateResponse(
        event_id=event_id,
        status="PENDING"
    )
