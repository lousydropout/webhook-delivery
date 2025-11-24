import os
import uuid
import time
import boto3
from decimal import Decimal
from typing import Dict, Any, Optional

dynamodb = boto3.resource("dynamodb")
events_table = dynamodb.Table(os.environ["EVENTS_TABLE"])


def convert_floats_to_decimals(obj: Any) -> Any:
    """
    Recursively convert float values to Decimal for DynamoDB compatibility.
    DynamoDB requires Decimal type for numbers, not Python float.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimals(item) for item in obj]
    else:
        return obj


def create_event(tenant_id: str, payload: Dict[str, Any], target_url: str) -> str:
    """
    Create event in DynamoDB with PENDING status.

    Returns: event_id
    """
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    created_at = time.time()

    # TTL: 1 year from now (365 days for auditing purposes)
    ttl = int(created_at + (365 * 24 * 60 * 60))

    # Convert floats to Decimals for DynamoDB compatibility
    payload_decimal = convert_floats_to_decimals(payload)

    item = {
        "tenantId": tenant_id,
        "eventId": event_id,
        "status": "PENDING",
        "createdAt": str(int(created_at)),
        "payload": payload_decimal,
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


def mark_event_as_purged(tenant_id: str, event_id: str) -> bool:
    """
    Mark an event as PURGED status.
    Used when DLQ messages are purged.

    Args:
        tenant_id: Tenant identifier
        event_id: Event identifier

    Returns:
        True if event was updated, False if event not found
    """
    try:
        events_table.update_item(
            Key={
                "tenantId": tenant_id,
                "eventId": event_id,
            },
            UpdateExpression="SET #status = :purged",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":purged": "PURGED"},
        )
        return True
    except Exception as e:
        print(f"Error marking event {event_id} as purged: {e}")
        return False


def reset_event_for_retry(tenant_id: str, event_id: str) -> bool:
    """
    Reset a FAILED event to PENDING status for manual retry.
    Preserves attempt count to maintain retry history.

    Args:
        tenant_id: Tenant identifier
        event_id: Event identifier

    Returns:
        True if event was reset, False if event not found or not in FAILED status
    """
    try:
        # Update only if status is FAILED (prevent retrying PENDING/DELIVERED events)
        # Keep attempts count to preserve retry history
        response = events_table.update_item(
            Key={
                "tenantId": tenant_id,
                "eventId": event_id,
            },
            UpdateExpression="SET #status = :pending REMOVE errorMessage",
            ConditionExpression="#status = :failed",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":failed": "FAILED",
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

    Writes to two separate tables:
    - TenantIdentity: API key → tenant identity (for authentication)
    - TenantWebhookConfig: tenantId → webhook config (for delivery)

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

    tenant_identity_table = dynamodb.Table(os.environ["TENANT_IDENTITY_TABLE"])
    tenant_webhook_config_table = dynamodb.Table(
        os.environ["TENANT_WEBHOOK_CONFIG_TABLE"]
    )

    # Generate API key
    api_key = f"tenant_{tenant_id}_key"

    # Generate webhook secret if not provided
    if not webhook_secret:
        # Generate 32-character random secret
        alphabet = string.ascii_letters + string.digits
        webhook_secret = "whsec_" + "".join(secrets.choice(alphabet) for _ in range(32))

    timestamp = str(int(time.time()))

    try:
        # Write to TenantIdentity table (authentication data)
        tenant_identity_table.put_item(
            Item={
                "apiKey": api_key,
                "tenantId": tenant_id,
                "status": "active",
                "plan": "free",  # Default plan
                "createdAt": timestamp,
            },
            ConditionExpression="attribute_not_exists(apiKey)",
        )

        # Write to TenantWebhookConfig table (webhook delivery data)
        tenant_webhook_config_table.put_item(
            Item={
                "tenantId": tenant_id,
                "targetUrl": target_url,
                "webhookSecret": webhook_secret,
                "lastUpdated": timestamp,
            },
            ConditionExpression="attribute_not_exists(tenantId)",
        )

        return {
            "tenant_id": tenant_id,
            "api_key": api_key,
            "target_url": target_url,
            "webhook_secret": webhook_secret,
            "created_at": timestamp,
        }
    except tenant_identity_table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Tenant with ID '{tenant_id}' already exists")
    except Exception as e:
        print(f"Error creating tenant {tenant_id}: {e}")
        # Cleanup: if one table write succeeded, try to rollback
        try:
            tenant_identity_table.delete_item(Key={"apiKey": api_key})
        except:
            pass
        try:
            tenant_webhook_config_table.delete_item(Key={"tenantId": tenant_id})
        except:
            pass
        raise


def get_tenant_by_id(tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Get tenant details by tenant ID.

    Reads from TenantWebhookConfig table (does not include webhook secret in response).

    Args:
        tenant_id: Tenant identifier

    Returns:
        Tenant data (excluding webhook secret for security) or None if not found
    """
    tenant_webhook_config_table = dynamodb.Table(
        os.environ["TENANT_WEBHOOK_CONFIG_TABLE"]
    )

    try:
        # Query TenantWebhookConfig table directly (tenantId is PK)
        response = tenant_webhook_config_table.get_item(Key={"tenantId": tenant_id})

        item = response.get("Item")
        if not item:
            return None

        # Return tenant config without webhook secret
        tenant_safe = {
            "tenant_id": tenant_id,
            "target_url": item.get("targetUrl", ""),
            "created_at": item.get(
                "lastUpdated", ""
            ),  # Use lastUpdated as created_at proxy
            "updated_at": item.get("lastUpdated", ""),
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
    Update tenant webhook configuration by tenant ID.

    Updates TenantWebhookConfig table only (webhook delivery config).
    Does not modify TenantIdentity (authentication data).

    Args:
        tenant_id: Tenant identifier
        target_url: New webhook URL (optional)
        webhook_secret: New webhook secret (optional)

    Returns:
        Updated tenant configuration

    Raises:
        ValueError: If tenant not found or no fields to update
    """
    tenant_webhook_config_table = dynamodb.Table(
        os.environ["TENANT_WEBHOOK_CONFIG_TABLE"]
    )

    # Check if tenant exists
    try:
        response = tenant_webhook_config_table.get_item(Key={"tenantId": tenant_id})
        if not response.get("Item"):
            raise ValueError(f"Tenant {tenant_id} not found")
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Tenant {tenant_id} not found")

    # Build update expression dynamically
    update_parts = []
    attr_values = {}

    if target_url:
        update_parts.append("targetUrl = :url")
        attr_values[":url"] = target_url

    if webhook_secret:
        update_parts.append("webhookSecret = :secret")
        # Optionally track rotation history
        update_parts.append("lastUpdated = :timestamp")
        attr_values[":secret"] = webhook_secret
        attr_values[":timestamp"] = str(int(time.time()))

    if not update_parts:
        raise ValueError("At least one field must be updated")

    # Add lastUpdated timestamp if not already added
    if "lastUpdated" not in update_parts:
        update_parts.append("lastUpdated = :timestamp")
        attr_values[":timestamp"] = str(int(time.time()))

    update_expression = "SET " + ", ".join(update_parts)

    try:
        response = tenant_webhook_config_table.update_item(
            Key={"tenantId": tenant_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=attr_values,
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]
    except Exception as e:
        print(f"Error updating tenant config for tenant {tenant_id}: {e}")
        raise
