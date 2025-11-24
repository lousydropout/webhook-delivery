# API Endpoints

## Webhook Delivery API

**Base URL:** `https://hooks.vincentchan.cloud`

### Event Management

#### Create Event

```http
POST /v1/events
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
curl -X POST https://hooks.vincentchan.cloud/v1/events \
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

#### List Events

```http
GET /v1/events
```

List all events for the authenticated tenant with optional filtering and pagination.

**Headers:**
- `Authorization: Bearer <api-key>` (required)

**Query Parameters:**
- `status` (optional) - Filter by event status: `PENDING`, `DELIVERED`, or `FAILED`
- `limit` (optional) - Maximum number of events to return (default: 50, max: 100)
- `next_token` (optional) - Pagination token from previous response

**Response:**

Status: `200 OK`

```json
{
  "events": [
    {
      "event_id": "evt_abc123",
      "status": "DELIVERED",
      "created_at": "1700000000",
      "attempts": 1,
      "last_attempt_at": "1700000010"
    }
  ],
  "next_token": "eyJ0ZW5hbnRJZCI6...",
  "total_count": 1
}
```

**Errors:**

- `401 Unauthorized` - Invalid or missing API key
- `400 Bad Request` - Invalid status or limit parameter

**Example:**

```bash
# List all events
curl -X GET "https://hooks.vincentchan.cloud/v1/events" \
  -H "Authorization: Bearer tenant_acme_live_abc123"

# List only failed events
curl -X GET "https://hooks.vincentchan.cloud/v1/events?status=FAILED" \
  -H "Authorization: Bearer tenant_acme_live_abc123"

# Paginated request
curl -X GET "https://hooks.vincentchan.cloud/v1/events?limit=10&next_token=eyJ0ZW5hbnRJZCI6..." \
  -H "Authorization: Bearer tenant_acme_live_abc123"
```

---

#### Get Event Details

```http
GET /v1/events/{event_id}
```

Retrieve detailed information about a specific event.

**Headers:**
- `Authorization: Bearer <api-key>` (required)

**Path Parameters:**
- `event_id` - The unique event identifier

**Response:**

Status: `200 OK`

```json
{
  "event": {
    "event_id": "evt_abc123",
    "status": "DELIVERED",
    "created_at": "1700000000",
    "payload": {
      "event": "user.signup",
      "user_id": "123"
    },
    "target_url": "https://example.com/webhook",
    "attempts": 1,
    "last_attempt_at": "1700000010",
    "error_message": null
  }
}
```

**Errors:**

- `401 Unauthorized` - Invalid or missing API key
- `404 Not Found` - Event not found or does not belong to authenticated tenant

**Example:**

```bash
curl -X GET "https://hooks.vincentchan.cloud/v1/events/evt_abc123" \
  -H "Authorization: Bearer tenant_acme_live_abc123"
```

---

#### Update Event

```http
PATCH /v1/events/{event_id}
```

Update an event's mutable fields. Currently supports retrying failed events by setting status to `PENDING`.

**Headers:**
- `Authorization: Bearer <api-key>` (required)
- `Content-Type: application/json` (required)

**Path Parameters:**
- `event_id` - The unique event identifier

**Request Body:**

```json
{
  "status": "PENDING"
}
```

**Response:**

Status: `200 OK`

```json
{
  "event_id": "evt_abc123",
  "status": "PENDING",
  "created_at": "1700000000",
  "payload": {...},
  "target_url": "https://example.com/webhook",
  "attempts": 0,
  "last_attempt_at": null,
  "error_message": null
}
```

**Errors:**

- `400 Bad Request` - Invalid status transition (only FAILED events can be retried)
- `401 Unauthorized` - Invalid or missing API key
- `404 Not Found` - Event not found or does not belong to authenticated tenant
- `500 Internal Server Error` - Failed to requeue event

**Example:**

```bash
# Retry a failed event
curl -X PATCH "https://hooks.vincentchan.cloud/v1/events/evt_abc123" \
  -H "Authorization: Bearer tenant_acme_live_abc123" \
  -H "Content-Type: application/json" \
  -d '{"status": "PENDING"}'
```

---

### Tenant Management

#### Create Tenant

```http
POST /v1/tenants
```

Create a new tenant with auto-generated API key and webhook secret.

**Headers:**
- `Authorization: Bearer <api-key>` (required)
- `Content-Type: application/json` (required)

**Request Body:**

```json
{
  "tenant_id": "acme",
  "target_url": "https://example.com/webhook",
  "webhook_secret": "whsec_optional_secret"
}
```

**Fields:**
- `tenant_id` (required) - Unique tenant identifier (lowercase alphanumeric + hyphens, 3-50 characters)
- `target_url` (required) - Webhook delivery URL (must start with `http://` or `https://`)
- `webhook_secret` (optional) - HMAC secret for signature validation (auto-generated if omitted)

**Response:**

Status: `201 Created`

```json
{
  "tenant_id": "acme",
  "api_key": "tenant_acme_key",
  "target_url": "https://example.com/webhook",
  "webhook_secret": "whsec_abc123...",
  "created_at": "1700000000",
  "message": "Tenant created successfully. Store your API key and webhook secret securely."
}
```

**Errors:**

- `401 Unauthorized` - Invalid or missing API key
- `409 Conflict` - Tenant with this ID already exists
- `422 Unprocessable Entity` - Invalid tenant_id format or target_url format
- `500 Internal Server Error` - Failed to create tenant

**Example:**

```bash
curl -X POST https://hooks.vincentchan.cloud/v1/tenants \
  -H "Authorization: Bearer tenant_existing_key" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "target_url": "https://example.com/webhook"
  }'
```

**Security Note:** The API key and webhook secret are only returned once on creation. Store them securely as they cannot be retrieved later.

---

#### Get Tenant Details

```http
GET /v1/tenants/{tenant_id}
```

Retrieve tenant configuration details. Webhook secret is excluded for security.

**Headers:**
- `Authorization: Bearer <api-key>` (required)

**Path Parameters:**
- `tenant_id` - Tenant identifier

**Response:**

Status: `200 OK`

```json
{
  "tenant": {
    "tenant_id": "acme",
    "target_url": "https://example.com/webhook",
    "created_at": "1700000000",
    "updated_at": "1700000100"
  }
}
```

**Errors:**

- `401 Unauthorized` - Invalid or missing API key
- `403 Forbidden` - Access denied (can only access own tenant)
- `404 Not Found` - Tenant not found

**Example:**

```bash
curl -X GET "https://hooks.vincentchan.cloud/v1/tenants/acme" \
  -H "Authorization: Bearer tenant_acme_key"
```


---

#### Update Tenant Configuration

```http
PATCH /v1/tenants/{tenant_id}
```

Update tenant webhook configuration (target URL and/or webhook secret).

**Headers:**
- `Authorization: Bearer <api-key>` (required)
- `Content-Type: application/json` (required)

**Path Parameters:**
- `tenant_id` - Tenant identifier

**Request Body:**

```json
{
  "target_url": "https://new-url.com/webhook",
  "webhook_secret": "whsec_new_secret"
}
```

**Fields:**
- `target_url` (optional) - New webhook delivery URL
- `webhook_secret` (optional) - New HMAC secret for signature validation

At least one field must be provided.

**Response:**

Status: `200 OK`

```json
{
  "tenant_id": "acme",
  "target_url": "https://new-url.com/webhook",
  "updated_at": "1700000200",
  "message": "Tenant configuration updated successfully"
}
```

**Errors:**

- `400 Bad Request` - No fields provided for update
- `401 Unauthorized` - Invalid or missing API key
- `403 Forbidden` - Access denied (can only update own tenant)
- `404 Not Found` - Tenant not found
- `500 Internal Server Error` - Failed to update tenant configuration

**Example:**

```bash
# Update webhook URL
curl -X PATCH "https://hooks.vincentchan.cloud/v1/tenants/acme" \
  -H "Authorization: Bearer tenant_acme_key" \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "https://new-url.com/webhook"
  }'

# Update webhook secret
curl -X PATCH "https://hooks.vincentchan.cloud/v1/tenants/acme" \
  -H "Authorization: Bearer tenant_acme_key" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_secret": "whsec_new_secret"
  }'
```

**Security Note:** Updating `webhook_secret` will invalidate signatures on in-flight webhooks. Changes take effect immediately for new events.


## Migration Notes

**Note**: The deprecated endpoints (`POST /v1/events/{event_id}/retry` and `PATCH /v1/tenants/current`) have been removed. Please use the RESTful alternatives:

- **Event Retry**: Use `PATCH /v1/events/{event_id}` with `{"status": "PENDING"}`
- **Tenant Configuration**: Use `PATCH /v1/tenants/{tenant_id}`

---

## Production Webhook Receiver

**Base URL:** `https://receiver.vincentchan.cloud`

The production webhook receiver validates HMAC signatures and can be used as a webhook endpoint for testing or production use.

### Receive Webhook

#### Webhook Endpoint

```http
POST /{tenantId}/webhook
```

Receive and validate webhooks with HMAC signatures. The `tenantId` in the path is used to look up the webhook secret from DynamoDB.

**Headers:**
- `Content-Type: application/json` (required)
- `Stripe-Signature: t=<timestamp>,v1=<hmac_signature>` (required)

**Request Body:**

The original event payload (JSON).

**Response:**

Status: `200 OK`

```json
{
  "status": "received",
  "tenant_id": "test-tenant"
}
```

**Errors:**

- `401 Unauthorized` - Missing or invalid signature
- `404 Not Found` - Tenant not found or inactive

**Example:**

```bash
curl -X POST https://receiver.vincentchan.cloud/test-tenant/webhook \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: t=1700000000,v1=abc123..." \
  -d '{"event": "test.event", "event_id": "evt_123"}'
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
  "status": "healthy",
  "service": "webhook-receiver"
}
```

**Example:**

```bash
curl https://receiver.vincentchan.cloud/health
```

#### API Documentation

```http
GET /docs
```

Swagger UI documentation for the receiver API.

**Example:**

```bash
# Open in browser:
https://receiver.vincentchan.cloud/docs
```

---

## Test Webhook Receiver (Local)

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

**Webhook Receiver Lambda:** `Vincent-TriggerApi-WebhookReceiver`
- Trigger: API Gateway (receiver.vincentchan.cloud)
- Function: Multi-tenant webhook validation with HMAC signature verification

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
