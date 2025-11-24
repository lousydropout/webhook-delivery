import os
import time
import boto3

dynamodb = boto3.resource("dynamodb")
events_table = dynamodb.Table(os.environ["EVENTS_TABLE"])
tenant_webhook_config_table = dynamodb.Table(
    os.environ["TENANT_WEBHOOK_CONFIG_TABLE"]
)


def get_event(tenant_id: str, event_id: str):
    """Retrieve event from DynamoDB"""
    response = events_table.get_item(Key={"tenantId": tenant_id, "eventId": event_id})
    return response.get("Item")


def get_tenant_by_id(tenant_id: str):
    """
    Get tenant webhook configuration by tenantId.

    Reads from TenantWebhookConfig table (contains targetUrl and webhookSecret).
    Does not access TenantIdentity table (authentication data).
    """
    try:
        response = tenant_webhook_config_table.get_item(Key={"tenantId": tenant_id})
        return response.get("Item")
    except Exception as e:
        print(f"Error retrieving tenant webhook config for {tenant_id}: {e}")
        return None


def update_event_status(
    tenant_id: str, event_id: str, status: str, attempts: int, error_message: str = None
):
    """Update event delivery status"""
    update_expr = (
        "SET #status = :status, attempts = :attempts, lastAttemptAt = :last_attempt"
    )
    expr_values = {
        ":status": status,
        ":attempts": attempts,
        ":last_attempt": str(int(time.time())),
    }
    expr_names = {"#status": "status"}

    if error_message:
        update_expr += ", errorMessage = :error"
        expr_values[":error"] = error_message

    events_table.update_item(
        Key={"tenantId": tenant_id, "eventId": event_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
