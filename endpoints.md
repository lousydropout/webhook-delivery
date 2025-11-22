# API Endpoints

## Webhook Delivery API

**Base URL:** `https://hooks.vincentchan.cloud`

### Event Ingestion

#### Create Event

```http
POST /events
```

Ingest an event for webhook delivery.

**Headers:**
- `Authorization: Bearer <api-key>` (required)
- `Content-Type: application/json` (required)

**Request Body:**

Free-form JSON payload. Any valid JSON object will be accepted and delivered as-is to the tenant's webhook endpoint.

```json
{
  "event": "user.signup",
  "user_id": "123",
  "email": "user@example.com",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

**Response:**

Status: `201 Created`

```json
{
  "event_id": "evt_abc123def456",
  "status": "PENDING"
}
```

**Errors:**

- `401 Unauthorized` - Invalid or missing API key
- `500 Internal Server Error` - Failed to enqueue event

**Example:**

```bash
curl -X POST https://hooks.vincentchan.cloud/events \
  -H "Authorization: Bearer tenant_acme_live_abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "order.created",
    "order_id": "ord_789",
    "amount": 99.99,
    "currency": "USD"
  }'
```

---

## Test Webhook Receiver

**Base URL:** `http://localhost:5000` (local testing only)

### Receive Webhook

#### Webhook Endpoint

```http
POST /webhook
```

Test endpoint for receiving and validating webhooks with HMAC signatures.

**Headers:**
- `Content-Type: application/json` (required)
- `Stripe-Signature: t=<timestamp>,v1=<hmac_signature>` (required)

**Request Body:**

The original event payload (JSON).

**Response:**

Status: `200 OK`

```json
{
  "status": "received"
}
```

**Errors:**

- `401 Unauthorized` - Missing or invalid signature

**Example:**

```bash
# This endpoint is called automatically by the Worker Lambda
# Manual testing requires computing HMAC signature
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: t=1700000000,v1=abc123..." \
  -d '{"event": "test.event"}'
```

#### Health Check

```http
GET /health
```

Check if the webhook receiver is running.

**Response:**

Status: `200 OK`

```json
{
  "status": "ok"
}
```

**Example:**

```bash
curl http://localhost:5000/health
```

---

## AWS Service Endpoints

These endpoints are accessed programmatically by the Lambda functions.

### DynamoDB

**TenantApiKeys Table:** `Vincent-TriggerApi-TenantApiKeys`
- Partition Key: `apiKey` (string)
- Attributes: `tenantId`, `targetUrl`, `webhookSecret`, `isActive`, `createdAt`, `displayName`

**Events Table:** `Vincent-TriggerApi-Events`
- Partition Key: `tenantId` (string)
- Sort Key: `eventId` (string)
- GSI: `status-index` (status, createdAt)
- Attributes: `status`, `payload`, `targetUrl`, `attempts`, `lastAttemptAt`, `ttl`

### SQS Queues

**Events Queue:** `Vincent-TriggerApi-EventsQueue`
- Visibility Timeout: 60 seconds
- Max Receive Count: 5
- Message Format: `{"tenantId": "...", "eventId": "..."}`

**Events DLQ:** `Vincent-TriggerApi-EventsDlq`
- Retention Period: 14 days

### Lambda Functions

**API Lambda:** `Vincent-TriggerApi-ApiHandler`
- Trigger: API Gateway (proxy integration)
- Function: Event ingestion and SQS enqueuing

**Worker Lambda:** `Vincent-TriggerApi-WorkerHandler`
- Trigger: SQS EventsQueue
- Function: Webhook delivery with HMAC signatures

**DLQ Processor Lambda:** `Vincent-TriggerApi-DlqProcessor`
- Trigger: Manual invocation
- Function: Requeue messages from DLQ to main queue
- Payload: `{"batchSize": 10, "maxMessages": 100}`

---

## Webhook Signature Verification

All webhooks include a `Stripe-Signature` header for verification:

**Format:**
```
Stripe-Signature: t=<timestamp>,v1=<signature>
```

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
- Always verify signatures before processing webhooks
- Reject signatures older than 5 minutes to prevent replay attacks
- Use constant-time comparison for security
- Log verification failures for monitoring

---

## Rate Limits

**API Gateway:**
- Rate Limit: 500 requests/second
- Burst Limit: 1000 requests

**SQS:**
- Default: 3000 messages/second (unlimited with batching)

**Lambda:**
- Concurrent Executions: 1000 (default account limit)
- Can be increased via AWS Support

---

## Monitoring Endpoints

### CloudWatch Logs

**API Lambda Logs:**
```bash
/aws/lambda/Vincent-TriggerApi-ApiHandler
```

**Worker Lambda Logs:**
```bash
/aws/lambda/Vincent-TriggerApi-WorkerHandler
```

**DLQ Processor Logs:**
```bash
/aws/lambda/Vincent-TriggerApi-DlqProcessor
```

### CloudFormation Stack

**Stack Name:** `WebhookDeliveryStack`

**Key Outputs:**
- `CustomDomainUrl`: API custom domain URL
- `TenantApiKeysTableName`: DynamoDB table name
- `EventsTableName`: Events table name
- `EventsQueueUrl`: SQS queue URL
- `EventsDlqUrl`: DLQ URL

---

## Response Codes

### API Lambda

| Code | Status | Description |
|------|--------|-------------|
| 201 | Created | Event successfully ingested |
| 401 | Unauthorized | Invalid or missing API key |
| 500 | Internal Server Error | Failed to process event |

### Webhook Delivery (Worker Lambda)

| Code | Status | Action |
|------|--------|--------|
| 2xx | Success | Mark event as DELIVERED |
| 4xx | Client Error | Mark as FAILED, retry via SQS |
| 5xx | Server Error | Mark as FAILED, retry via SQS |
| Timeout | Request Timeout | Mark as FAILED, retry via SQS |

**Retry Schedule:**
- Attempt 1: Immediate
- Attempt 2: ~1 minute later
- Attempt 3: ~2 minutes later
- Attempt 4: ~4 minutes later
- Attempt 5: ~8 minutes later
- After 5 failures: Move to DLQ

---

## Environment Variables

### API Lambda

- `TENANT_API_KEYS_TABLE`: DynamoDB table for tenant configs
- `EVENTS_TABLE`: DynamoDB table for events
- `EVENTS_QUEUE_URL`: SQS queue URL for webhook delivery

### Worker Lambda

- `TENANT_API_KEYS_TABLE`: DynamoDB table for tenant configs
- `EVENTS_TABLE`: DynamoDB table for events

### DLQ Processor Lambda

- `EVENTS_DLQ_URL`: Dead letter queue URL
- `EVENTS_QUEUE_URL`: Main queue URL for requeuing
