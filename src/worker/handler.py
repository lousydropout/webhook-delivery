import json
from delivery import deliver_webhook
from dynamo import get_event, update_event_status, get_tenant_by_id


def main(event, context):
    """
    Process SQS messages for webhook delivery.

    Triggered by SQS event source with:
    - Max batching window: 1s (messages processed within 1 second)
    - Batch size: 10 messages per invocation

    SQS will retry failed messages with exponential backoff:
    - Visibility timeout: 60s
    - Max receive count: 5
    - Backoff: ~1min, 2min, 4min, 8min, 16min
    """
    for record in event["Records"]:
        message_body = json.loads(record["body"])
        tenant_id = message_body["tenantId"]
        event_id = message_body["eventId"]

        # Get event details
        event_item = get_event(tenant_id, event_id)
        if not event_item:
            print(f"Event not found: {tenant_id}/{event_id}")
            continue

        target_url = event_item["targetUrl"]
        payload = event_item["payload"]
        current_attempts = event_item.get("attempts", 0)

        # Get webhook secret from tenant config
        tenant = get_tenant_by_id(tenant_id)
        if not tenant:
            print(f"Tenant not found: {tenant_id}")
            continue

        webhook_secret = tenant["webhookSecret"]

        # Attempt delivery
        success, status_code, error_msg = deliver_webhook(
            target_url, payload, webhook_secret
        )

        new_attempts = current_attempts + 1

        if success:
            # Mark as DELIVERED
            update_event_status(tenant_id, event_id, "DELIVERED", new_attempts)
            print(f"✓ Delivered: {tenant_id}/{event_id} (status={status_code})")
        else:
            # Mark as FAILED (will retry via SQS or go to DLQ)
            update_event_status(tenant_id, event_id, "FAILED", new_attempts, error_msg)
            print(f"✗ Failed: {tenant_id}/{event_id} - {error_msg}")

            # Re-raise to trigger SQS retry
            raise Exception(f"Webhook delivery failed: {error_msg}")

    return {"statusCode": 200}
