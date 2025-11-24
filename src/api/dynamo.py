import os
import uuid
import time
import boto3
from typing import Dict, Any, Optional

dynamodb = boto3.resource("dynamodb")
events_table = dynamodb.Table(os.environ["EVENTS_TABLE"])


def create_event(tenant_id: str, payload: Dict[str, Any], target_url: str) -> str:
    """
    Create event in DynamoDB with PENDING status.

    Returns: event_id
    """
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    created_at = time.time()

    # TTL: 1 year from now (365 days for auditing purposes)
    ttl = int(created_at + (365 * 24 * 60 * 60))

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


def list_events(
    tenant_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    last_evaluated_key: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    List events for a tenant with optional status filtering and pagination.

    Args:
        tenant_id: Tenant identifier
        status: Optional status filter (PENDING, DELIVERED, FAILED)
        limit: Maximum number of events to return (default 50, max 100)
        last_evaluated_key: Pagination token from previous response

    Returns:
        {
            "events": [...],
            "lastEvaluatedKey": {...} or None
        }
    """
    limit = min(limit, 100)  # Cap at 100

    if status:
        # Query using GSI when filtering by status
        query_params = {
            "IndexName": "status-index",
            "KeyConditionExpression": "#status = :status",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {":status": status, ":tid": tenant_id},
            "FilterExpression": "tenantId = :tid",
            "Limit": limit,
            "ScanIndexForward": False,  # Newest first (descending by createdAt)
        }

        if last_evaluated_key:
            query_params["ExclusiveStartKey"] = last_evaluated_key

        response = events_table.query(**query_params)
    else:
        # Query by tenant_id without status filter
        query_params = {
            "KeyConditionExpression": "tenantId = :tid",
            "ExpressionAttributeValues": {":tid": tenant_id},
            "Limit": limit,
            "ScanIndexForward": False,  # Newest first
        }

        if last_evaluated_key:
            query_params["ExclusiveStartKey"] = last_evaluated_key

        response = events_table.query(**query_params)

    return {
        "events": response.get("Items", []),
        "lastEvaluatedKey": response.get("LastEvaluatedKey"),
    }


def get_event(tenant_id: str, event_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single event by tenantId and eventId.

    Args:
        tenant_id: Tenant identifier
        event_id: Event identifier

    Returns:
        Event dict or None if not found
    """
    try:
        response = events_table.get_item(
            Key={
                "tenantId": tenant_id,
                "eventId": event_id,
            }
        )
        return response.get("Item")
    except Exception as e:
        print(f"Error retrieving event {event_id} for tenant {tenant_id}: {e}")
        return None


def reset_event_for_retry(tenant_id: str, event_id: str) -> bool:
    """
    Reset a FAILED event to PENDING status for manual retry.

    Args:
        tenant_id: Tenant identifier
        event_id: Event identifier

    Returns:
        True if event was reset, False if event not found or not in FAILED status
    """
    try:
        # Update only if status is FAILED (prevent retrying PENDING/DELIVERED events)
        response = events_table.update_item(
            Key={
                "tenantId": tenant_id,
                "eventId": event_id,
            },
            UpdateExpression="SET #status = :pending, attempts = :zero REMOVE errorMessage",
            ConditionExpression="#status = :failed",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":failed": "FAILED",
                ":zero": 0,
            },
            ReturnValues="ALL_NEW",
        )
        return True
    except events_table.meta.client.exceptions.ConditionalCheckFailedException:
        # Event is not in FAILED status
        return False
    except Exception as e:
        print(f"Error resetting event {event_id} for retry: {e}")
        return False


def create_tenant(
    tenant_id: str, target_url: str, webhook_secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new tenant with API key.

    Args:
        tenant_id: Unique tenant identifier (e.g., "acme", "globex")
        target_url: Webhook delivery URL
        webhook_secret: HMAC secret (auto-generated if not provided)

    Returns:
        {
            "tenant_id": "...",
            "api_key": "tenant_..._key",
            "target_url": "...",
            "webhook_secret": "...",
            "created_at": "..."
        }

    Raises:
        ValueError: If tenant already exists
    """
    import secrets
    import string

    tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])

    # Generate API key
    api_key = f"tenant_{tenant_id}_key"

    # Generate webhook secret if not provided
    if not webhook_secret:
        # Generate 32-character random secret
        alphabet = string.ascii_letters + string.digits
        webhook_secret = "whsec_" + "".join(secrets.choice(alphabet) for _ in range(32))

    timestamp = str(int(time.time()))

    try:
        # Use ConditionExpression to ensure tenant doesn't already exist
        tenant_api_keys_table.put_item(
            Item={
                "apiKey": api_key,
                "tenantId": tenant_id,
                "targetUrl": target_url,
                "webhookSecret": webhook_secret,
                "createdAt": timestamp,
                "updatedAt": timestamp,
            },
            ConditionExpression="attribute_not_exists(apiKey)",
        )

        return {
            "tenant_id": tenant_id,
            "api_key": api_key,
            "target_url": target_url,
            "webhook_secret": webhook_secret,
            "created_at": timestamp,
        }
    except tenant_api_keys_table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Tenant with ID '{tenant_id}' already exists")
    except Exception as e:
        print(f"Error creating tenant {tenant_id}: {e}")
        raise


def get_tenant_by_id(tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Get tenant details by tenant ID.

    Uses GSI on tenantId for efficient lookups.

    Args:
        tenant_id: Tenant identifier

    Returns:
        Tenant data (excluding webhook secret for security) or None if not found
    """
    tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])

    try:
        # Use GSI query instead of scan for efficient lookup
        response = tenant_api_keys_table.query(
            IndexName="tenantId-index",
            KeyConditionExpression="tenantId = :tid",
            ExpressionAttributeValues={":tid": tenant_id},
        )

        items = response.get("Items", [])
        if not items:
            return None

        tenant = items[0]

        # Remove webhook secret from response for security
        # (only return it on creation or when explicitly updated)
        tenant_safe = {
            "tenant_id": tenant["tenantId"],
            "target_url": tenant["targetUrl"],
            "created_at": tenant.get("createdAt", ""),
            "updated_at": tenant.get("updatedAt", ""),
        }

        return tenant_safe
    except Exception as e:
        print(f"Error retrieving tenant {tenant_id}: {e}")
        return None


def update_tenant_config_by_id(
    tenant_id: str,
    target_url: Optional[str] = None,
    webhook_secret: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update tenant configuration by tenant ID.

    Uses GSI on tenantId to find API key efficiently.

    Args:
        tenant_id: Tenant identifier
        target_url: New webhook URL (optional)
        webhook_secret: New webhook secret (optional)

    Returns:
        Updated tenant configuration

    Raises:
        ValueError: If tenant not found or no fields to update
    """
    tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])

    # Use GSI query to find API key for this tenant
    response = tenant_api_keys_table.query(
        IndexName="tenantId-index",
        KeyConditionExpression="tenantId = :tid",
        ExpressionAttributeValues={":tid": tenant_id},
    )

    items = response.get("Items", [])
    if not items:
        raise ValueError(f"Tenant {tenant_id} not found")

    api_key = items[0]["apiKey"]

    # Build update expression dynamically
    update_parts = []
    attr_values = {}

    if target_url:
        update_parts.append("targetUrl = :url")
        attr_values[":url"] = target_url

    if webhook_secret:
        update_parts.append("webhookSecret = :secret")
        attr_values[":secret"] = webhook_secret

    if not update_parts:
        raise ValueError("At least one field must be updated")

    # Add updatedAt timestamp
    update_parts.append("updatedAt = :timestamp")
    attr_values[":timestamp"] = str(int(time.time()))

    update_expression = "SET " + ", ".join(update_parts)

    try:
        response = tenant_api_keys_table.update_item(
            Key={"apiKey": api_key},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=attr_values,
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]
    except Exception as e:
        print(f"Error updating tenant config for tenant {tenant_id}: {e}")
        raise
