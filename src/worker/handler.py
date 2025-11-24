import json
import os
import boto3
from delivery import deliver_webhook
from dynamo import get_event, update_event_status, get_tenant_by_id

sqs = boto3.client("sqs")
EVENTS_DLQ_URL = os.environ.get("EVENTS_DLQ_URL")
MAX_RETRY_ATTEMPTS = 5


def main(event, context):
    """
    Process SQS messages for webhook delivery.

    Triggered by SQS event source with:
    - Max batching window: 0s (messages processed immediately when Lambda polls)
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

        # Check if event has already exceeded max retry attempts BEFORE attempting delivery
        # If so, send directly to DLQ without attempting delivery
        # This prevents processing events that should already be in DLQ
        if current_attempts >= MAX_RETRY_ATTEMPTS and EVENTS_DLQ_URL:
            try:
                # Construct message body explicitly to ensure correct tenantId/eventId
                dlq_message_body = json.dumps(
                    {
                        "tenantId": tenant_id,
                        "eventId": event_id,
                    }
                )

                # Send message directly to DLQ
                sqs.send_message(
                    QueueUrl=EVENTS_DLQ_URL,
                    MessageBody=dlq_message_body,
                )
                print(
                    f"→ Sent to DLQ (skipped delivery): {tenant_id}/{event_id} (attempts={current_attempts} >= {MAX_RETRY_ATTEMPTS})"
                )
                # Don't re-raise - message handled, delete from main queue
                continue
            except Exception as e:
                print(f"Error sending to DLQ: {e}")
                # Fall through to attempt delivery if DLQ send fails

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
            # Mark as FAILED
            update_event_status(tenant_id, event_id, "FAILED", new_attempts, error_msg)
            print(f"✗ Failed: {tenant_id}/{event_id} - {error_msg}")

            # Check if event has exceeded max retry attempts after this failed attempt
            # If so, send directly to DLQ instead of letting SQS retry
            if new_attempts >= MAX_RETRY_ATTEMPTS and EVENTS_DLQ_URL:
                try:
                    # Construct message body explicitly to ensure correct tenantId/eventId
                    dlq_message_body = json.dumps(
                        {
                            "tenantId": tenant_id,
                            "eventId": event_id,
                        }
                    )

                    # Send message directly to DLQ
                    sqs.send_message(
                        QueueUrl=EVENTS_DLQ_URL,
                        MessageBody=dlq_message_body,
                    )
                    print(
                        f"→ Sent to DLQ: {tenant_id}/{event_id} (attempts={new_attempts} >= {MAX_RETRY_ATTEMPTS})"
                    )
                    # Don't re-raise - message handled, delete from main queue
                    continue
                except Exception as e:
                    print(f"Error sending to DLQ: {e}")
                    # Fall through to SQS retry if DLQ send fails

            # Re-raise to trigger SQS retry (for attempts < MAX_RETRY_ATTEMPTS)
            raise Exception(f"Webhook delivery failed: {error_msg}")

    return {"statusCode": 200}
