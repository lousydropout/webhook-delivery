---
date: 2025-11-23T01:10:00-06:00
researcher: Claude Code
git_commit: bab2cda8b206166ac98d5c945394334304d85016
branch: main
repository: zapier
topic: "How to Run webhook_receiver.py for Testing"
tags: [research, testing, webhook-receiver, mock-zapier, integration-testing]
status: complete
last_updated: 2025-11-23
last_updated_by: Claude Code
---

# Research: How to Run webhook_receiver.py for Testing

**Date**: 2025-11-23T01:10:00-06:00
**Researcher**: Claude Code
**Git Commit**: bab2cda8b206166ac98d5c945394334304d85016
**Branch**: main
**Repository**: zapier

## Research Question

How do I run `webhook_receiver.py`? It's meant to act as a mock mini-Zapier, ingesting and updating events.

## Summary

`webhook_receiver.py` is a **test webhook receiver** (not a mini-Zapier system) that validates HMAC signatures on incoming webhooks from the Webhook Delivery System. It's a FastAPI application that runs locally to test webhook delivery end-to-end.

**Key Purpose**: Acts as the **receiving endpoint** for testing webhook delivery with Stripe-style HMAC signature validation.

## Quick Start

### Prerequisites

```bash
# Install dependencies
pip install -r tests/requirements.txt
# Requirements: fastapi==0.104.1, uvicorn==0.24.0
```

### Run the Receiver

```bash
# Start the receiver on port 5000
python tests/webhook_receiver.py

# Or using python3
python3 tests/webhook_receiver.py
```

**Output:**
```
Starting webhook test receiver on http://localhost:5000
Webhook secret: whsec_test123
POST webhooks to: http://localhost:5000/webhook
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:5000
```

### Expose Locally (for AWS Lambda Testing)

Since the Worker Lambda needs to reach your local receiver, use ngrok:

```bash
# Terminal 2: Expose local port 5000
ngrok http 5000

# Note the public URL, e.g., https://abc123.ngrok.io
```

## Detailed Findings

### Component Analysis

#### 1. webhook_receiver.py - Test Receiver
**File**: [tests/webhook_receiver.py:1-77](tests/webhook_receiver.py#L1-L77)

**Purpose**: FastAPI-based test server that:
1. Receives webhook POST requests at `/webhook`
2. Validates Stripe-style HMAC signatures
3. Returns 200 for valid webhooks, 401 for invalid

**Key Components**:

**Webhook Secret** ([tests/webhook_receiver.py:19](tests/webhook_receiver.py#L19)):
```python
WEBHOOK_SECRET = "whsec_test123"  # Replace with actual secret
```
- **IMPORTANT**: This must match the `webhookSecret` stored in DynamoDB for the tenant
- Default is `whsec_test123` for testing
- Update this to match the secret from seed script output

**Signature Verification** ([tests/webhook_receiver.py:22-42](tests/webhook_receiver.py#L22-L42)):
```python
def verify_signature(payload: str, signature_header: str) -> bool:
    """Verify Stripe-style signature"""
    try:
        parts = dict(item.split("=") for item in signature_header.split(","))
        timestamp = parts.get("t")
        signature = parts.get("v1")

        if not timestamp or not signature:
            return False

        signed_payload = f"{timestamp}.{payload}"
        expected = hmac.new(
            WEBHOOK_SECRET.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
    except Exception as e:
        print(f"Error verifying signature: {e}")
        return False
```

**Webhook Endpoint** ([tests/webhook_receiver.py:45-63](tests/webhook_receiver.py#L45-L63)):
- **Path**: `/webhook`
- **Method**: POST
- **Header Required**: `Stripe-Signature`
- **Success**: Returns `{"status": "received"}` with 200
- **Failure**: Returns 401 with error message

**Health Check** ([tests/webhook_receiver.py:66-69](tests/webhook_receiver.py#L66-L69)):
- **Path**: `/health`
- **Method**: GET
- **Response**: `{"status": "ok"}`

#### 2. Seeding Script - Create Test Tenants
**File**: [scripts/seed_webhooks.py:1-98](scripts/seed_webhooks.py#L1-L98)

**Purpose**: Creates test tenant API keys in DynamoDB

**Creates 3 Tenants**:
- `acme` (Acme Corp)
- `globex` (Globex Inc)
- `initech` (Initech LLC)

**Generated Data** ([scripts/seed_webhooks.py:54-62](scripts/seed_webhooks.py#L54-L62)):
```python
item = {
    "apiKey": api_key,              # tenant_{name}_live_{random}
    "tenantId": tenant["name"],
    "targetUrl": tenant["targetUrl"],
    "webhookSecret": webhook_secret, # whsec_{uuid}
    "isActive": True,
    "createdAt": str(int(time.time())),
    "displayName": tenant["display"],
}
```

**Output**: Prints curl commands to test each tenant

## Complete Testing Workflow

### Step 1: Deploy Infrastructure

```bash
# Deploy the webhook delivery system
./scripts/deploy.sh
```

This creates:
- DynamoDB tables (TenantApiKeys, Events)
- Lambda functions (API, Worker, DLQ Processor, Authorizer)
- SQS queues (main + DLQ)
- API Gateway with custom domain
- Seeds test tenants

### Step 2: Start Local Webhook Receiver

```bash
# Terminal 1: Install dependencies
cd /home/lousydropout/src/gauntlet/zapier
pip install -r tests/requirements.txt

# Start the receiver
python tests/webhook_receiver.py
```

### Step 3: Expose Receiver to Internet

```bash
# Terminal 2: Start ngrok
ngrok http 5000

# Copy the public URL (e.g., https://abc123.ngrok.io)
```

### Step 4: Update Tenant Configuration

Get the webhook secret from seed output, then update a tenant's targetUrl:

```bash
# Option A: Update using AWS CLI
aws dynamodb update-item \
  --table-name Vincent-TriggerApi-TenantApiKeys \
  --key '{"apiKey": {"S": "YOUR_API_KEY_FROM_SEED_OUTPUT"}}' \
  --update-expression "SET targetUrl = :url" \
  --expression-attribute-values '{":url": {"S": "https://YOUR_NGROK_URL/webhook"}}'

# Option B: Get API key from table first
aws dynamodb scan \
  --table-name Vincent-TriggerApi-TenantApiKeys \
  --filter-expression "tenantId = :tid" \
  --expression-attribute-values '{":tid": {"S": "acme"}}'
```

**CRITICAL**: Update the `WEBHOOK_SECRET` in `webhook_receiver.py` to match the tenant's secret:

```python
# In tests/webhook_receiver.py line 19
WEBHOOK_SECRET = "whsec_abc123..."  # From seed output
```

Restart the receiver after updating the secret.

### Step 5: Send Test Event

```bash
# Terminal 3: Send event via API
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer YOUR_API_KEY_FROM_SEED_OUTPUT" \
  -H "Content-Type: application/json" \
  -d '{"event": "user.signup", "user_id": "123", "email": "test@example.com"}'

# Expected response:
# {"event_id": "evt_abc123", "status": "PENDING"}
```

### Step 6: Verify Webhook Delivery

**In Terminal 1** (webhook_receiver.py output):
```
✓ Valid webhook received: {"event": "user.signup", "user_id": "123", "email": "test@example.com"}
INFO:     127.0.0.1:54321 - "POST /webhook HTTP/1.1" 200 OK
```

**Check DynamoDB**:
```bash
# Event should be marked DELIVERED
aws dynamodb get-item \
  --table-name Vincent-TriggerApi-Events \
  --key '{"tenantId": {"S": "acme"}, "eventId": {"S": "evt_abc123"}}'

# Look for:
# "status": {"S": "DELIVERED"}
# "attempts": {"N": "1"}
```

**Check CloudWatch Logs**:
```bash
# Worker Lambda logs
aws logs tail /aws/lambda/Vincent-TriggerApi-WorkerHandler --follow

# Should show:
# ✓ Delivered: acme/evt_abc123 (status=200)
```

## Testing Failure Scenarios

### Test Invalid Signature

1. **Wrong Secret**: Change `WEBHOOK_SECRET` in receiver to something else
2. **Send Event**: Use same curl command
3. **Expected**: Receiver returns 401, Worker retries

**Receiver Output**:
```
✗ Invalid signature
INFO:     127.0.0.1:54321 - "POST /webhook HTTP/1.1" 401 Unauthorized
```

**DynamoDB**:
```
"status": {"S": "FAILED"}
"attempts": {"N": "1"}
```

**SQS**: Message returns to queue for retry

### Test Retry Logic

1. **Stop Receiver**: Kill the `webhook_receiver.py` process
2. **Send Event**: Worker will fail to connect
3. **Monitor Retries**: Check CloudWatch Logs for retry attempts
4. **After 5 Failures**: Message moves to DLQ

**Retry Timing** (from [README.md:113](README.md#L113)):
- Attempt 1: Immediate
- Attempt 2: ~1 minute later
- Attempt 3: ~2 minutes later
- Attempt 4: ~4 minutes later
- Attempt 5: ~8 minutes later
- **DLQ**: After 5th failure

### Test DLQ Requeue

```bash
# After messages are in DLQ, restart receiver
python tests/webhook_receiver.py

# Requeue from DLQ
aws lambda invoke \
  --function-name Vincent-TriggerApi-DlqProcessor \
  --payload '{"batchSize": 10, "maxMessages": 100}' \
  response.json

# Check response
cat response.json
# {"statusCode": 200, "body": "{\"requeued\": 5, \"failed\": 0}"}
```

## Code References

### Test Receiver
- [tests/webhook_receiver.py:1-77](tests/webhook_receiver.py#L1-L77) - Complete FastAPI test receiver
- [tests/webhook_receiver.py:19](tests/webhook_receiver.py#L19) - Webhook secret configuration
- [tests/webhook_receiver.py:22-42](tests/webhook_receiver.py#L22-L42) - HMAC signature verification
- [tests/webhook_receiver.py:45-63](tests/webhook_receiver.py#L45-L63) - `/webhook` POST endpoint
- [tests/webhook_receiver.py:72-76](tests/webhook_receiver.py#L72-L76) - Uvicorn server startup

### Seeding & Setup
- [scripts/seed_webhooks.py:1-98](scripts/seed_webhooks.py#L1-L98) - Tenant seeding script
- [scripts/seed_webhooks.py:14-17](scripts/seed_webhooks.py#L14-L17) - API key generation
- [scripts/seed_webhooks.py:20-22](scripts/seed_webhooks.py#L20-L22) - Webhook secret generation

### Dependencies
- [tests/requirements.txt:1-2](tests/requirements.txt#L1-L2) - FastAPI and Uvicorn

### Documentation
- [docs/WEBHOOK_INTEGRATION.md:1-102](docs/WEBHOOK_INTEGRATION.md#L1-L102) - Complete integration guide
- [docs/WEBHOOK_INTEGRATION.md:36-53](docs/WEBHOOK_INTEGRATION.md#L36-L53) - Signature verification algorithm
- [README.md:250-280](README.md#L250-L280) - Local testing workflow

## Architecture Insights

### Webhook Delivery Flow

1. **Event Ingestion**: External system POSTs to `/v1/events` with Bearer token
2. **Authorization**: Lambda Authorizer validates token (cached 5 min)
3. **Storage**: Event stored in DynamoDB with status=PENDING
4. **Queueing**: Message sent to SQS with `{tenantId, eventId}`
5. **Delivery**: Worker Lambda:
   - Reads event from DynamoDB
   - Generates HMAC signature using tenant's `webhookSecret`
   - POSTs to tenant's `targetUrl` with `Stripe-Signature` header
6. **Verification**: Receiver validates signature
7. **Status Update**: Event marked DELIVERED or FAILED

### Signature Algorithm (Stripe-Style)

**Generation** (Worker Lambda - [src/worker/signatures.py]()):
```python
timestamp = int(time.time())
signed_payload = f"{timestamp}.{json_payload}"
signature = hmac_sha256(webhook_secret, signed_payload)
header = f"t={timestamp},v1={signature}"
```

**Verification** (Test Receiver - [tests/webhook_receiver.py:22-42](tests/webhook_receiver.py#L22-L42)):
```python
parts = parse_header("t=123,v1=abc")  # {t: 123, v1: abc}
signed_payload = f"{parts['t']}.{request_body}"
expected = hmac_sha256(webhook_secret, signed_payload)
valid = constant_time_compare(expected, parts['v1'])
```

### Security Best Practices

1. **Always verify signatures** before processing webhooks
2. **Check timestamp** - reject if >5 minutes old (prevents replay attacks)
3. **Use constant-time comparison** (`hmac.compare_digest`)
4. **Secrets management** - never hardcode secrets in production
5. **HTTPS only** - webhook delivery only over TLS

## Common Issues & Solutions

### Issue 1: "Invalid signature" errors

**Cause**: Webhook secret mismatch

**Solution**:
1. Get webhook secret from seed output or DynamoDB
2. Update `WEBHOOK_SECRET` in `webhook_receiver.py`
3. Restart receiver

### Issue 2: "Connection refused" errors

**Cause**: Receiver not running or ngrok tunnel closed

**Solution**:
1. Verify receiver is running: `curl http://localhost:5000/health`
2. Verify ngrok is running: Check ngrok dashboard
3. Update targetUrl if ngrok URL changed

### Issue 3: Events stuck in PENDING

**Cause**: Worker Lambda can't reach targetUrl

**Solution**:
1. Check CloudWatch Logs: `aws logs tail /aws/lambda/Vincent-TriggerApi-WorkerHandler`
2. Verify targetUrl is publicly accessible
3. Check for network/firewall issues

### Issue 4: Receiver logs show requests but signature fails

**Cause**: Payload format mismatch

**Solution**:
1. Worker sends raw JSON string
2. Receiver must read raw body: `request.body()`
3. Don't parse JSON before verification

## Related Research

- [Implementation Plan](thoughts/shared/plans/2025-11-21-webhook-delivery-system-rewrite.md) - Complete architecture
- [Webhook Integration Guide](docs/WEBHOOK_INTEGRATION.md) - Production receiver setup
- [Phase 5 Handoff](thoughts/shared/handoffs/general/2025-11-21_09-22-19_phase-5-acknowledgment-deletion-complete.md) - Testing details

## Next Steps for User

Based on your question, here's what you should do:

1. **Install Dependencies**:
   ```bash
   pip install -r tests/requirements.txt
   ```

2. **Run the Receiver**:
   ```bash
   python tests/webhook_receiver.py
   ```

3. **Update the Secret** (from seed output):
   ```python
   # Edit tests/webhook_receiver.py line 19
   WEBHOOK_SECRET = "whsec_YOUR_ACTUAL_SECRET"
   ```

4. **Expose with ngrok** (if testing with AWS):
   ```bash
   ngrok http 5000
   ```

5. **Update Tenant's targetUrl** to ngrok URL

6. **Send Test Event**:
   ```bash
   curl -X POST https://hooks.vincentchan.cloud/v1/events \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"test": "data"}'
   ```

7. **Watch Receiver Logs** for validated webhook delivery

The receiver will print `✓ Valid webhook received: {...}` when it successfully validates and processes a webhook.
