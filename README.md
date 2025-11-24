# Webhook Delivery System

Production-ready serverless webhook delivery platform built on AWS. Transform event ingestion into reliable push-based webhook delivery with automatic retries, HMAC signatures, and comprehensive observability.

## Overview

This system provides a complete webhook delivery infrastructure that:
- Ingests events via REST API
- Queues events for reliable async processing
- Delivers webhooks to tenant-configured endpoints
- Validates deliveries with Stripe-style HMAC signatures
- Automatically retries failed deliveries with exponential backoff
- Routes permanently failed messages to a Dead Letter Queue

## Architecture

**Components:**
- **Lambda Authorizer**: API Gateway authorizer for Bearer token validation (5-min cache)
- **API Lambda** (FastAPI): Event ingestion with tenant context from authorizer
- **SQS Queue**: Reliable message queue with 5 retry attempts
- **Worker Lambda**: Webhook delivery with HMAC signature generation
- **Webhook Receiver Lambda** (FastAPI): Multi-tenant webhook validation with HMAC verification
- **DLQ Processor Lambda**: Manual requeue for failed deliveries
- **DynamoDB**: Event and tenant data with TTL support
- **Custom Domain**: hooks.vincentchan.cloud (REGIONAL endpoint with ACM SSL)

**System Diagram:**

```mermaid
graph LR
    A[External System] -->|POST /v1/events<br/>Bearer Token| B[API Gateway<br/>Authorizer]
    B -->|Validate Token| C[(DynamoDB<br/>TenantApiKeys)]
    B -->|Authorized| D[API Lambda<br/>FastAPI]
    D -->|Store Event| E[(DynamoDB<br/>Events)]
    D -->|Enqueue| F[SQS Queue]
    F -->|Trigger| G[Worker Lambda]
    G -->|Read Event| E
    G -->|Deliver with<br/>HMAC| H[Tenant Webhook<br/>Endpoint]
    F -->|After 5 Retries| I[Dead Letter<br/>Queue]
    I -.->|Manual Requeue| J[DLQ Processor<br/>Lambda]
    J -.->|Requeue| F

    style B fill:#f9f,stroke:#333,color:#000
    style D fill:#f9f,stroke:#333,color:#000
    style G fill:#f9f,stroke:#333,color:#000
    style J fill:#f9f,stroke:#333,color:#000
    style C fill:#bbf,stroke:#333,color:#000
    style E fill:#bbf,stroke:#333,color:#000
    style F fill:#bfb,stroke:#333,color:#000
    style I fill:#fbb,stroke:#333,color:#000
```

**Event Lifecycle:**

```mermaid
stateDiagram-v2
    [*] --> PENDING: Event Created
    PENDING --> DELIVERED: Webhook 2xx Response
    PENDING --> FAILED: Webhook Error
    FAILED --> PENDING: SQS Retry (1-4)
    FAILED --> DLQ: 5th Failure
    DLQ --> PENDING: Manual Requeue
    DELIVERED --> [*]: TTL Cleanup (30d)
    DLQ --> [*]: TTL Cleanup (14d)
```

**Delivery Sequence:**

```mermaid
sequenceDiagram
    participant Ext as External System
    participant AGW as API Gateway
    participant Auth as Authorizer Lambda
    participant API as API Lambda
    participant DB as DynamoDB
    participant SQS as SQS Queue
    participant Worker as Worker Lambda
    participant Tenant as Tenant Server

    Ext->>AGW: POST /v1/events + Bearer Token
    AGW->>Auth: Validate Token
    Auth->>DB: Lookup API Key
    DB-->>Auth: Tenant Config
    Auth-->>AGW: Allow + Tenant Context (cached 5min)
    AGW->>API: Invoke with Tenant Context
    API->>DB: Create Event (PENDING)
    API->>SQS: Enqueue {tenantId, eventId}
    API-->>Ext: 201 {event_id, status}

    SQS->>Worker: Trigger with Message
    Worker->>DB: Get Event Details
    DB-->>Worker: Event + Tenant Config
    Worker->>Worker: Generate HMAC Signature
    Worker->>Tenant: POST Webhook + Stripe-Signature

    alt Success
        Tenant-->>Worker: 200 OK
        Worker->>DB: Update Status: DELIVERED
    else Failure
        Tenant-->>Worker: 5xx Error
        Worker->>DB: Update Status: FAILED
        Worker->>SQS: Return Error (Retry)
    end
```

## Features

- ✅ **Reliable Delivery**: SQS-backed processing with automatic retries
- ✅ **Security**: Stripe-style HMAC-SHA256 webhook signatures
- ✅ **API Gateway Authorizer**: Lambda authorizer with 5-minute caching for performance
- ✅ **Interactive API Docs**: Public Swagger UI and ReDoc documentation
- ✅ **Retry Logic**: Exponential backoff (1min, 2min, 4min, 8min, 16min)
- ✅ **Multi-tenant**: Isolated API keys and webhook endpoints per tenant
- ✅ **Custom Domain**: Professional SSL-enabled REGIONAL endpoint
- ✅ **Auto-cleanup**: 30-day TTL on delivered events
- ✅ **DLQ Management**: Manual requeue of failed messages
- ✅ **No Lambda Layers**: Dependencies bundled directly for simplicity

## API Documentation

Interactive API documentation is available at:
- **Swagger UI**: https://hooks.vincentchan.cloud/v1/docs
- **ReDoc**: https://hooks.vincentchan.cloud/v1/redoc
- **OpenAPI Schema**: https://hooks.vincentchan.cloud/v1/openapi.json

These endpoints are publicly accessible (no authentication required) for easy integration.

## Quick Start

### Prerequisites

- AWS CLI configured with credentials
- Python 3.12+
- Node.js 18+ (for CDK)
- Environment variables in `.env`:
  ```bash
  HOSTED_ZONE_ID=Z00669322LNYAWLYNIHGN
  HOSTED_ZONE_URL=vincentchan.cloud
  ```

### Deploy

```bash
# Deploy infrastructure and seed test data
./scripts/deploy.sh
```

This will:
1. Install CDK dependencies
2. Bootstrap CDK (if needed)
3. Deploy all AWS resources (DynamoDB, Lambda, SQS, API Gateway, Custom Domain)
4. Seed 3 test tenants with API keys

### Send Your First Event

```bash
# Get API key from deploy output, then:
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer <api-key-from-deploy>" \
  -H "Content-Type: application/json" \
  -d '{"event": "user.signup", "user_id": "123", "email": "test@example.com"}'

# Response:
# {"event_id": "evt_abc123", "status": "PENDING"}
```

### Receive Webhooks

See [Webhook Integration Guide](docs/WEBHOOK_INTEGRATION.md) for complete receiver implementation with signature verification.

## Webhook Receiver Lambda

The system includes a production-ready webhook receiver Lambda for end-to-end testing and demonstration. This receiver validates HMAC signatures and can be used as a reference implementation or actual webhook endpoint.

### Endpoints

**Health Check:**
```bash
GET https://hooks.vincentchan.cloud/v1/receiver/health
# Response: {"status": "healthy", "service": "webhook-receiver"}
```

**Webhook Reception:**
```bash
POST https://hooks.vincentchan.cloud/v1/receiver/{tenantId}/webhook
# Headers: Stripe-Signature: t={timestamp},v1={signature}
# Response: {"status": "received", "tenant_id": "{tenantId}"}
```

**API Documentation:**
```bash
GET https://hooks.vincentchan.cloud/v1/receiver/docs  # Swagger UI
```

### Features

- ✅ **Multi-tenant Support**: Each tenant has unique URL path
- ✅ **Dynamic Secret Retrieval**: Webhook secrets fetched from DynamoDB per request
- ✅ **HMAC Signature Validation**: Stripe-style signature verification
- ✅ **No Authentication Required**: Security via HMAC signatures only
- ✅ **Automatic Tenant Lookup**: Validates tenant exists and is active
- ✅ **Performance**: <200ms validation time, 256MB memory footprint

### User Flow: Complete End-to-End Webhook Delivery

Here's how the entire system works from event creation to webhook validation:

#### Step 1: Create Event via API

```bash
# Tenant sends event to API
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer tenant_test-tenant_key" \
  -H "Content-Type: application/json" \
  -d '{"type": "user.signup", "user_id": "123", "email": "user@example.com"}'

# Response: {"event_id": "evt_abc123", "status": "PENDING"}
```

**What happens:**
1. API Gateway validates Bearer token via Lambda Authorizer
2. Authorizer looks up API key in DynamoDB, returns tenant context
3. API Lambda creates event in DynamoDB with status `PENDING`
4. API Lambda enqueues message to SQS: `{tenantId, eventId}`
5. Returns 201 response to caller

#### Step 2: Worker Processes Event

```bash
# Automatic - SQS triggers Worker Lambda
```

**What happens:**
1. Worker Lambda receives SQS message
2. Worker reads event from DynamoDB (gets payload, targetUrl, webhookSecret)
3. Worker generates Stripe-style HMAC signature:
   - Signed payload: `{timestamp}.{json_payload}`
   - Signature: `HMAC-SHA256(signed_payload, webhookSecret)`
   - Header: `Stripe-Signature: t={timestamp},v1={signature}`
4. Worker makes HTTP POST to tenant's `targetUrl`

#### Step 3: Receiver Validates Webhook

If tenant's `targetUrl` is set to the receiver Lambda:

```bash
# targetUrl: https://hooks.vincentchan.cloud/v1/receiver/test-tenant/webhook
```

**What happens:**
1. Receiver extracts `tenant_id` from URL path
2. Receiver looks up webhook secret from DynamoDB for that tenant
3. Receiver validates HMAC signature:
   - Extracts timestamp and signature from `Stripe-Signature` header
   - Reconstructs signed payload: `{timestamp}.{request_body}`
   - Computes expected signature: `HMAC-SHA256(signed_payload, webhookSecret)`
   - Compares using constant-time comparison
4. Receiver returns:
   - `200 OK` if signature valid: `{"status": "received", "tenant_id": "test-tenant"}`
   - `401 Unauthorized` if signature invalid or missing
   - `404 Not Found` if tenant doesn't exist

#### Step 4: Worker Updates Status

**What happens:**
1. Worker receives 200 response from receiver
2. Worker updates DynamoDB event status: `PENDING` → `DELIVERED`
3. Worker deletes message from SQS (successful processing)
4. Event remains in DynamoDB until TTL expires (30 days)

### Complete Flow Diagram

```mermaid
sequenceDiagram
    participant Client as External Client
    participant API as API Gateway + Lambda
    participant DB as DynamoDB
    participant SQS as SQS Queue
    participant Worker as Worker Lambda
    participant Receiver as Receiver Lambda

    Note over Client,Receiver: Step 1: Event Creation
    Client->>API: POST /v1/events + Bearer Token
    API->>DB: Validate API Key
    API->>DB: Create Event (PENDING)
    API->>SQS: Enqueue {tenantId, eventId}
    API-->>Client: 201 {event_id, status: PENDING}

    Note over Client,Receiver: Step 2: Async Processing (12-18s later)
    SQS->>Worker: Trigger with Message
    Worker->>DB: Get Event + Tenant Config
    DB-->>Worker: {payload, targetUrl, webhookSecret}
    Worker->>Worker: Generate HMAC Signature

    Note over Client,Receiver: Step 3: Webhook Delivery
    Worker->>Receiver: POST /v1/receiver/{tenantId}/webhook<br/>Stripe-Signature: t=...,v1=...
    Receiver->>DB: Lookup Webhook Secret
    DB-->>Receiver: webhookSecret
    Receiver->>Receiver: Validate HMAC Signature
    Receiver-->>Worker: 200 OK {"status": "received"}

    Note over Client,Receiver: Step 4: Status Update
    Worker->>DB: Update Status: DELIVERED
    Worker->>SQS: Delete Message (Success)
```

### Testing the Receiver

**Test with curl:**

```bash
# 1. Generate valid signature
python3 << 'EOF'
import time, hmac, hashlib, json

secret = "whsec_test123"  # Your webhook secret
payload = json.dumps({"test": True, "event_id": "evt_123"})
timestamp = str(int(time.time()))
signed = f"{timestamp}.{payload}"
signature = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
print(f"Stripe-Signature: t={timestamp},v1={signature}")
print(f"Payload: {payload}")
EOF

# 2. Send webhook with valid signature
curl -X POST https://hooks.vincentchan.cloud/v1/receiver/test-tenant/webhook \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: t=1700000000,v1=..." \
  -d '{"test": true, "event_id": "evt_123"}'

# Expected: 200 {"status":"received","tenant_id":"test-tenant"}

# 3. Test invalid signature (should fail)
curl -X POST https://hooks.vincentchan.cloud/v1/receiver/test-tenant/webhook \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: t=12345,v1=invalid" \
  -d '{"test": true}'

# Expected: 401 {"detail":"Invalid signature"}
```

**Run integration tests:**

```bash
# Comprehensive end-to-end test
python3 tests/test_webhook_receiver_integration.py

# Tests:
# ✓ Health endpoint responding
# ✓ Event creation via API
# ✓ Webhook delivery to receiver
# ✓ HMAC signature validation
# ✓ Status updates in DynamoDB
# ✓ Concurrent event handling
```

### Configuration

To use the receiver Lambda as your webhook endpoint, update your tenant configuration:

```bash
aws dynamodb update-item \
  --table-name Vincent-TriggerApi-TenantApiKeys \
  --key '{"apiKey": {"S": "tenant_test-tenant_key"}}' \
  --update-expression "SET targetUrl = :url" \
  --expression-attribute-values '{
    ":url": {"S": "https://hooks.vincentchan.cloud/v1/receiver/test-tenant/webhook"}
  }'
```

### Monitoring Receiver

```bash
# View receiver logs
aws logs tail /aws/lambda/Vincent-TriggerApi-WebhookReceiver --follow

# Check recent successful validations
aws logs filter-log-events \
  --log-group-name /aws/lambda/Vincent-TriggerApi-WebhookReceiver \
  --filter-pattern "Valid webhook received" \
  --start-time $(($(date +%s - 3600) * 1000))

# Check signature validation failures
aws logs filter-log-events \
  --log-group-name /aws/lambda/Vincent-TriggerApi-WebhookReceiver \
  --filter-pattern "Invalid signature" \
  --start-time $(($(date +%s - 3600) * 1000))
```

### Performance Characteristics

- **Cold Start**: ~1.7 seconds (Python 3.12 + FastAPI + Mangum)
- **Warm Execution**: 2-177ms (typically <50ms)
- **Memory Usage**: 105-107 MB / 256 MB allocated
- **Timeout**: 10 seconds (validation completes in <1s)
- **Concurrent Capacity**: 1000 concurrent executions (AWS default)
- **DynamoDB Scan**: Acceptable for <100 tenants (add GSI if scaling beyond)

### Security Notes

- **No API Authentication**: Receiver endpoints are public (HMAC provides security)
- **Signature Validation**: Uses constant-time comparison to prevent timing attacks
- **Timestamp Included**: Signature includes timestamp to prevent replay attacks
- **Tenant Isolation**: Each tenant has unique URL and secret
- **No Secrets Logged**: Webhook secrets never appear in CloudWatch logs

## Monitoring

```bash
# Check event status
aws dynamodb get-item \
  --table-name Vincent-TriggerApi-Events \
  --key '{"tenantId": {"S": "acme"}, "eventId": {"S": "evt_123"}}'

# View DLQ messages
aws sqs receive-message \
  --queue-url <dlq-url> \
  --max-number-of-messages 10
```

## Project Structure

```
zapier/
├── cdk/
│   ├── app.py                          # CDK application entry
│   ├── stacks/
│   │   └── webhook_delivery_stack.py  # Infrastructure definition
│   └── requirements.txt
├── src/
│   ├── authorizer/                     # API Gateway Authorizer Lambda
│   │   ├── handler.py                  # Bearer token validation
│   │   └── requirements.txt            # boto3
│   ├── api/                            # Event Ingestion Lambda
│   │   ├── main.py                     # FastAPI app + Mangum handler
│   │   ├── context.py                  # Extract tenant from authorizer context
│   │   ├── routes.py                   # POST /v1/events endpoint
│   │   ├── dynamo.py                   # DynamoDB operations
│   │   ├── models.py                   # Pydantic request/response models
│   │   └── requirements.txt            # FastAPI, Mangum, boto3, pydantic
│   ├── worker/                         # Webhook Delivery Lambda
│   │   ├── handler.py                  # SQS event processor
│   │   ├── delivery.py                 # HTTP webhook delivery (with DecimalEncoder)
│   │   ├── signatures.py               # HMAC signature generation
│   │   ├── dynamo.py                   # Event status updates
│   │   └── requirements.txt            # boto3, requests
│   ├── webhook_receiver/               # Webhook Receiver Lambda
│   │   ├── main.py                     # FastAPI app + Mangum handler
│   │   └── requirements.txt            # fastapi, mangum, boto3
│   └── dlq_processor/                  # DLQ Requeue Lambda
│       ├── handler.py                  # Manual DLQ requeue
│       └── requirements.txt
├── scripts/
│   ├── deploy.sh                       # Automated deployment
│   └── seed_webhooks.py                # Test tenant seeding
├── tests/
│   ├── webhook_receiver.py             # Local FastAPI test receiver
│   ├── webhook_receiver_local.py       # Local test with mock DynamoDB
│   ├── test_webhook_receiver_manual.py # Unit tests for signature validation
│   ├── test_webhook_receiver_integration.py # End-to-end integration tests
│   ├── test_with_curl_simple.sh        # Curl-based testing script
│   └── requirements.txt
├── docs/
│   └── WEBHOOK_INTEGRATION.md          # Integration guide
└── README.md
```

## Configuration

### Tenant Setup

Each tenant needs:
- **API Key**: For authentication when posting events
- **Webhook Secret**: For HMAC signature generation
- **Target URL**: Where webhooks will be delivered

Add via DynamoDB or seeding script:

```python
# scripts/seed_webhooks.py creates test tenants
python scripts/seed_webhooks.py
```

### Event Schema

Events are stored with:
```python
{
    "tenantId": "acme",
    "eventId": "evt_abc123",
    "status": "PENDING" | "DELIVERED" | "FAILED",
    "createdAt": "1700000000",
    "payload": {...},           # Your event data
    "targetUrl": "https://...",
    "webhookSecret": "whsec_...",
    "attempts": 0,
    "lastAttemptAt": "1700000000",
    "ttl": 1702592000          # Auto-delete after 30 days
}
```

## Testing

### Local Webhook Receiver

Test webhook delivery with the included FastAPI receiver:

```bash
# Terminal 1: Start receiver
pip install -r tests/requirements.txt
python tests/webhook_receiver.py

# Terminal 2: Expose via ngrok
ngrok http 5000

# Terminal 3: Update tenant and send test event
aws dynamodb update-item \
  --table-name Vincent-TriggerApi-TenantApiKeys \
  --key '{"apiKey": {"S": "YOUR_API_KEY"}}' \
  --update-expression "SET targetUrl = :url" \
  --expression-attribute-values '{":url": {"S": "https://YOUR_NGROK_URL/webhook"}}'

curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"test": "event"}'
```

### Verify Signature

The test receiver validates HMAC signatures. Check the logs for:
```
✓ Valid webhook received: {"test": "event"}
```

## Monitoring & Operations

### Check Event Status

```bash
# Get specific event
aws dynamodb get-item \
  --table-name Vincent-TriggerApi-Events \
  --key '{"tenantId": {"S": "acme"}, "eventId": {"S": "evt_123"}}'

# Query by status
aws dynamodb query \
  --table-name Vincent-TriggerApi-Events \
  --index-name status-index \
  --key-condition-expression "#status = :status" \
  --expression-attribute-names '{"#status": "status"}' \
  --expression-attribute-values '{":status": {"S": "FAILED"}}'
```

### CloudWatch Logs

Monitor delivery in real-time:
```bash
# Worker Lambda logs
aws logs tail /aws/lambda/Vincent-TriggerApi-WorkerHandler --follow

# API Lambda logs
aws logs tail /aws/lambda/Vincent-TriggerApi-ApiHandler --follow
```

### DLQ Management

Requeue failed messages after fixing issues:

```bash
aws lambda invoke \
  --function-name Vincent-TriggerApi-DlqProcessor \
  --payload '{"batchSize": 10, "maxMessages": 100}' \
  response.json

cat response.json
# {"statusCode": 200, "body": "{\"requeued\": 5, \"failed\": 0}"}
```

### View DLQ Messages

```bash
aws sqs receive-message \
  --queue-url $(aws cloudformation describe-stacks \
    --stack-name WebhookDeliveryStack \
    --query 'Stacks[0].Outputs[?OutputKey==`EventsDlqUrl`].OutputValue' \
    --output text) \
  --max-number-of-messages 10
```

## Troubleshooting

### Event Not Delivered

1. **Check event status**: Should be PENDING → DELIVERED
2. **Check CloudWatch Logs**: Look for delivery errors
3. **Verify target URL**: Must be accessible from Lambda
4. **Check webhook secret**: Must match between tenant config and receiver

### Signature Validation Failing

1. **Time sync**: Signature includes timestamp, check clock skew
2. **Payload format**: Must be exact JSON string used in HMAC
3. **Secret mismatch**: Webhook secret must match exactly

### Messages in DLQ

1. **Review error logs**: Check why deliveries failed
2. **Fix root cause**: Update target URL, fix receiver, etc.
3. **Requeue**: Use DLQ Processor Lambda to retry

## Cleanup

```bash
# Destroy all AWS resources
cd cdk
cdk destroy

# Confirm destruction
# WARNING: This deletes all data including events and API keys
```

## Development

### Local Development

```bash
# Install dependencies
pip install -r cdk/requirements.txt

# Run CDK synth to validate
cd cdk && cdk synth

# Test Lambda locally (requires Docker)
sam local invoke ApiLambda -e test_event.json
```

### Code Style

All Python code formatted with Black:
```bash
black .
```

## Documentation

- [Webhook Integration Guide](docs/WEBHOOK_INTEGRATION.md) - Receiver implementation
- [Implementation Plan](thoughts/shared/plans/2025-11-21-webhook-delivery-system-rewrite.md) - Architecture decisions

## License

MIT
