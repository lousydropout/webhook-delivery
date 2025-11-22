# Webhook Integration Guide

## Overview

The Webhook Delivery System automatically delivers events to tenant-configured endpoints with Stripe-style HMAC signatures for verification.

## Receiving Webhooks

### 1. Configure Target URL

Each tenant must provide a `targetUrl` where webhooks will be delivered:

```bash
# Update tenant configuration
aws dynamodb update-item \
  --table-name Vincent-TriggerApi-TenantApiKeys \
  --key '{"apiKey": {"S": "your-api-key"}}' \
  --update-expression "SET targetUrl = :url" \
  --expression-attribute-values '{":url": {"S": "https://your-domain.com/webhooks"}}'
```

### 2. Verify Webhook Signatures

All webhooks include a `Stripe-Signature` header:

```
Stripe-Signature: t=1234567890,v1=abc123...
```

Where:
- `t` = Unix timestamp
- `v1` = HMAC-SHA256 signature

**Verification Algorithm:**

```python
import hmac
import hashlib

def verify_signature(payload: str, signature_header: str, webhook_secret: str) -> bool:
    parts = dict(item.split('=') for item in signature_header.split(','))
    timestamp = parts['t']
    signature = parts['v1']

    signed_payload = f"{timestamp}.{payload}"
    expected = hmac.new(
        webhook_secret.encode('utf-8'),
        signed_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
```

**Best Practices:**
- Always verify signatures before processing
- Check timestamp to prevent replay attacks (reject if >5 minutes old)
- Use constant-time comparison (`hmac.compare_digest`)

### 3. Respond to Webhooks

Return a 2xx status code to acknowledge receipt:

```python
@app.route('/webhooks', methods=['POST'])
def handle_webhook():
    # Verify signature
    # Process event
    return '', 200  # Success
```

Non-2xx responses trigger retries with exponential backoff.

## Retry Logic

Failed deliveries retry automatically:
- **Attempts**: 5 total (1 initial + 4 retries)
- **Backoff**: ~1min, 2min, 4min, 8min, 16min
- **DLQ**: After 5 failures, messages move to Dead Letter Queue

## Manual Requeue from DLQ

If webhooks fail due to temporary issues, manually requeue from DLQ:

```bash
aws lambda invoke \
  --function-name Vincent-TriggerApi-DlqProcessor \
  --payload '{"batchSize": 10, "maxMessages": 100}' \
  response.json

cat response.json
```

## Monitoring

Check delivery status in DynamoDB Events table:
- `status`: PENDING → DELIVERED or FAILED
- `attempts`: Number of delivery attempts
- `lastAttemptAt`: Timestamp of last attempt

CloudWatch Logs provide detailed delivery information.
