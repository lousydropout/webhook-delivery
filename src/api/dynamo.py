import os
import uuid
import time
import boto3
from typing import Dict, Any

dynamodb = boto3.resource("dynamodb")
events_table = dynamodb.Table(os.environ["EVENTS_TABLE"])


def create_event(tenant_id: str, payload: Dict[str, Any], target_url: str) -> str:
    """
    Create event in DynamoDB with PENDING status.

    Returns: event_id
    """
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    created_at = time.time()

    # TTL: 30 days from now
    ttl = int(created_at + (30 * 24 * 60 * 60))

    item = {
        "tenantId": tenant_id,
        "eventId": event_id,
        "status": "PENDING",
        "createdAt": str(int(created_at)),
        "payload": payload,
        "targetUrl": target_url,
        "attempts": 0,
        "ttl": ttl,
    }

    events_table.put_item(Item=item)
    return event_id
