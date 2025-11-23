# Demo Webhook Receiver Deployment Implementation Plan

## Overview

Deploy a publicly accessible demo webhook receiver at `receiver.vincentchan.cloud` that validates incoming webhooks from the main webhook delivery system, allowing users to see the complete webhook delivery cycle without any local setup.

## Current State Analysis

**What exists now:**
- Local test webhook receiver ([tests/webhook_receiver.py](tests/webhook_receiver.py)) using FastAPI
- Main webhook delivery system at `hooks.vincentchan.cloud`
- Working webhook delivery with HMAC signature validation
- Test tenants seeded with `webhook.site` URLs

**What's missing:**
- Public endpoint for webhook reception
- Demo receiver infrastructure
- Visibility into received webhooks for demo purposes

## Desired End State

A publicly accessible webhook receiver that:
- Runs at `https://receiver.vincentchan.cloud/webhook`
- Validates HMAC signatures from incoming webhooks
- Returns proper status codes (200 for valid, 401 for invalid)
- Provides a simple GET endpoint to view recent webhooks
- Allows complete end-to-end demo without local setup

### Key Discoveries:
- Current test receiver uses Stripe-style HMAC validation ([tests/webhook_receiver.py:22-42](tests/webhook_receiver.py#L22-L42))
- Signature format: `t={timestamp},v1={hmac_sha256}`
- FastAPI can be deployed to Lambda using Mangum adapter (pattern in [src/api/main.py:17](src/api/main.py#L17))
- Existing CDK patterns for Lambda + API Gateway ([webhook_delivery_stack.py:145-174](cdk/stacks/webhook_delivery_stack.py#L145-L174))

## What We're NOT Doing

- Building a UI dashboard (just API endpoints)
- Storing webhooks persistently (in-memory only)
- Authentication for viewing received webhooks
- Rate limiting or IP allowlisting
- WebSocket real-time updates
- Webhook replay functionality

## Implementation Approach

Create a new Lambda function with its own API Gateway and custom domain, following the existing CDK patterns. The receiver will validate signatures and store recent webhooks in memory for demo visibility.

## Phase 1: Demo Receiver Lambda Function

### Overview
Create the Lambda function code that receives webhooks, validates signatures, and stores recent webhooks in memory.

### Changes Required:

#### 1. Create Demo Receiver Directory
**Directory**: `src/demo_receiver/`

```bash
src/demo_receiver/
├── handler.py        # FastAPI app with Mangum
├── models.py         # Pydantic models
├── storage.py        # In-memory webhook storage
└── requirements.txt  # Dependencies
```

#### 2. Dependencies
**File**: `src/demo_receiver/requirements.txt`
```txt
fastapi==0.104.1
mangum==0.17.0
pydantic==2.5.0
boto3==1.34.0
```

#### 3. Data Models
**File**: `src/demo_receiver/models.py`
```python
from pydantic import BaseModel
from typing import Any, Dict, Optional
from datetime import datetime


class WebhookReceived(BaseModel):
    timestamp: datetime
    signature_valid: bool
    signature_header: Optional[str]
    payload: Dict[str, Any]
    status_code: int
    tenant_id: Optional[str] = None
    event_id: Optional[str] = None


class WebhookList(BaseModel):
    count: int
    webhooks: list[WebhookReceived]


class HealthResponse(BaseModel):
    status: str = "ok"
    receiver_url: str = "https://receiver.vincentchan.cloud/webhook"
```

#### 4. In-Memory Storage
**File**: `src/demo_receiver/storage.py`
```python
from typing import List, Dict, Any
from datetime import datetime, timedelta
from models import WebhookReceived
import threading


class WebhookStorage:
    """Thread-safe in-memory storage for recent webhooks"""

    def __init__(self, max_webhooks: int = 100, ttl_minutes: int = 60):
        self._webhooks: List[WebhookReceived] = []
        self._max_webhooks = max_webhooks
        self._ttl_minutes = ttl_minutes
        self._lock = threading.Lock()

    def add_webhook(self, webhook: WebhookReceived) -> None:
        """Add webhook to storage, maintaining size limit"""
        with self._lock:
            self._webhooks.insert(0, webhook)
            # Keep only max_webhooks
            self._webhooks = self._webhooks[:self._max_webhooks]
            # Remove old webhooks beyond TTL
            cutoff = datetime.utcnow() - timedelta(minutes=self._ttl_minutes)
            self._webhooks = [w for w in self._webhooks if w.timestamp > cutoff]

    def get_recent(self, limit: int = 20) -> List[WebhookReceived]:
        """Get recent webhooks"""
        with self._lock:
            return self._webhooks[:limit]

    def clear(self) -> None:
        """Clear all stored webhooks"""
        with self._lock:
            self._webhooks = []


# Global storage instance (Lambda containers can be reused)
storage = WebhookStorage()
```

#### 5. FastAPI Handler
**File**: `src/demo_receiver/handler.py`
```python
import os
import hmac
import hashlib
import json
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, Header, Query
from mangum import Mangum
from typing import Optional, Dict, Any
import boto3

from models import WebhookReceived, WebhookList, HealthResponse
from storage import storage

app = FastAPI(
    title="Demo Webhook Receiver",
    description="Public webhook receiver for demonstrating webhook delivery",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# DynamoDB client
dynamodb = boto3.resource("dynamodb")
tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])


def get_webhook_secret_for_tenant(tenant_id: str) -> Optional[str]:
    """Look up webhook secret for a tenant from DynamoDB"""
    try:
        # Scan for tenant (could optimize with GSI on tenantId)
        response = tenant_api_keys_table.scan(
            FilterExpression="tenantId = :tid",
            ExpressionAttributeValues={":tid": tenant_id}
        )

        items = response.get("Items", [])
        if items and items[0].get("isActive"):
            return items[0].get("webhookSecret")
        return None
    except Exception as e:
        print(f"Error looking up webhook secret: {e}")
        return None


def verify_signature(payload: str, signature_header: str, secret: str) -> bool:
    """Verify Stripe-style signature"""
    try:
        parts = dict(item.split("=") for item in signature_header.split(","))
        timestamp = parts.get("t")
        signature = parts.get("v1")

        if not timestamp or not signature:
            return False

        signed_payload = f"{timestamp}.{payload}"
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


def extract_tenant_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    """Try to extract tenant ID from payload"""
    # Common patterns for tenant identification
    for key in ["tenant_id", "tenantId", "tenant", "source"]:
        if key in payload:
            return str(payload[key])
    return None


@app.get("/", response_model=HealthResponse)
async def health_check():
    """Health check and info endpoint"""
    return HealthResponse()


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """Receive and validate webhook"""
    # Read raw body
    body = await request.body()
    payload_str = body.decode("utf-8")

    # Parse payload
    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        payload = {"raw": payload_str}

    # Extract tenant if possible
    tenant_id = extract_tenant_from_payload(payload)

    # Look up webhook secret from DynamoDB and validate
    signature_valid = False
    if stripe_signature and tenant_id:
        secret = get_webhook_secret_for_tenant(tenant_id)
        if secret:
            signature_valid = verify_signature(payload_str, stripe_signature, secret)
        else:
            print(f"Warning: No webhook secret found for tenant: {tenant_id}")

    # Determine response
    if not stripe_signature:
        status_code = 401
        response_detail = "Missing Stripe-Signature header"
    elif not signature_valid:
        status_code = 401
        response_detail = "Invalid signature"
    else:
        status_code = 200
        response_detail = "Webhook received"

    # Store webhook
    webhook = WebhookReceived(
        timestamp=datetime.utcnow(),
        signature_valid=signature_valid,
        signature_header=stripe_signature,
        payload=payload,
        status_code=status_code,
        tenant_id=tenant_id,
        event_id=payload.get("event_id") or payload.get("eventId"),
    )
    storage.add_webhook(webhook)

    # Return appropriate response
    if status_code == 401:
        raise HTTPException(status_code=status_code, detail=response_detail)

    return {"status": "received", "signature_valid": signature_valid}


@app.get("/recent", response_model=WebhookList)
async def get_recent_webhooks(limit: int = Query(default=20, le=100)):
    """Get recently received webhooks"""
    webhooks = storage.get_recent(limit)
    return WebhookList(count=len(webhooks), webhooks=webhooks)


@app.delete("/clear")
async def clear_webhooks():
    """Clear all stored webhooks"""
    storage.clear()
    return {"status": "cleared"}


# Lambda handler
handler = Mangum(app)
```

### Success Criteria:

#### Automated Verification:
- [ ] Python imports work: `cd src/demo_receiver && python -c "from handler import app"`
- [ ] FastAPI app starts locally: `cd src/demo_receiver && uvicorn handler:app --reload`
- [ ] Signature validation logic works: `python -c "from handler import verify_signature"`

#### Manual Verification:
- [ ] POST to `/webhook` with valid signature returns 200
- [ ] POST to `/webhook` with invalid signature returns 401
- [ ] GET `/recent` returns list of received webhooks
- [ ] DELETE `/clear` clears webhook history

**Implementation Note**: Complete Lambda code before proceeding to infrastructure.

---

## Phase 2: CDK Infrastructure Updates

### Overview
Add demo receiver Lambda and API Gateway with custom domain `receiver.vincentchan.cloud` to the CDK stack.

### Changes Required:

#### 1. Update CDK Stack
**File**: `cdk/stacks/webhook_delivery_stack.py`

Add after DLQ Processor Lambda (around line 280):

```python
# ============================================================
# Demo Receiver Lambda (Public Webhook Receiver)
# ============================================================
self.demo_receiver_lambda = lambda_.Function(
    self,
    "DemoReceiverLambda",
    function_name=f"{prefix}-DemoReceiver",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="handler.handler",
    code=lambda_.Code.from_asset(
        "../src/demo_receiver",
        bundling=BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            command=[
                "bash",
                "-c",
                "pip install -r requirements.txt -t /asset-output && "
                + "cp -r . /asset-output",
            ],
        ),
    ),
    timeout=Duration.seconds(10),
    memory_size=512,
    environment={
        "TENANT_API_KEYS_TABLE": self.tenant_api_keys_table.table_name,
    },
)

# Grant DynamoDB read access
self.tenant_api_keys_table.grant_read_data(self.demo_receiver_lambda)

# ============================================================
# Demo Receiver API Gateway with Custom Domain
# ============================================================
# Certificate for receiver subdomain
receiver_certificate = acm.Certificate(
    self,
    "ReceiverApiCert",
    domain_name="receiver.vincentchan.cloud",
    validation=acm.CertificateValidation.from_dns(zone),
)

# Separate API for demo receiver
self.receiver_api = apigateway.LambdaRestApi(
    self,
    "ReceiverApi",
    handler=self.demo_receiver_lambda,
    proxy=True,
    rest_api_name="Demo Webhook Receiver",
    description="Public webhook receiver for demo purposes",
    deploy_options=apigateway.StageOptions(
        stage_name="prod",
        throttling_rate_limit=100,  # Lower rate limit for demo
        throttling_burst_limit=200,
    ),
    default_cors_preflight_options=apigateway.CorsOptions(
        allow_origins=["*"],
        allow_methods=apigateway.Cors.ALL_METHODS,
        allow_headers=["Content-Type", "Stripe-Signature"],
    ),
)

# Custom domain for receiver
receiver_domain = apigateway.DomainName(
    self,
    "ReceiverApiCustomDomain",
    domain_name="receiver.vincentchan.cloud",
    certificate=receiver_certificate,
    endpoint_type=apigateway.EndpointType.REGIONAL,
)

receiver_domain.add_base_path_mapping(
    self.receiver_api,
    base_path="",
    stage=self.receiver_api.deployment_stage,
)

# DNS record for receiver
route53.ARecord(
    self,
    "ReceiverApiAliasRecord",
    zone=zone,
    record_name="receiver",
    target=route53.RecordTarget.from_alias(
        targets.ApiGatewayDomain(receiver_domain)
    ),
)
```

Add outputs at the end of the stack:

```python
CfnOutput(
    self,
    "ReceiverUrl",
    value="https://receiver.vincentchan.cloud",
)

CfnOutput(
    self,
    "ReceiverWebhookEndpoint",
    value="https://receiver.vincentchan.cloud/webhook",
)

CfnOutput(
    self,
    "ReceiverRecentEndpoint",
    value="https://receiver.vincentchan.cloud/recent",
)
```

### Success Criteria:

#### Automated Verification:
- [ ] CDK synth runs without errors: `cd cdk && cdk synth`
- [ ] CDK deploy completes: `cd cdk && cdk deploy --require-approval never`
- [ ] Lambda deployed: `aws lambda get-function --function-name Vincent-TriggerApi-DemoReceiver`
- [ ] API Gateway created: `aws apigateway get-rest-apis | grep "Demo Webhook Receiver"`
- [ ] Custom domain exists: `aws apigateway get-domain-names | grep receiver.vincentchan.cloud`

#### Manual Verification:
- [ ] DNS resolves: `nslookup receiver.vincentchan.cloud`
- [ ] SSL certificate valid: `curl -I https://receiver.vincentchan.cloud`
- [ ] Swagger docs accessible: `https://receiver.vincentchan.cloud/docs`
- [ ] Health endpoint works: `curl https://receiver.vincentchan.cloud/`

**Implementation Note**: Wait for DNS propagation before testing (can take 5-15 minutes).

---

## Phase 3: Update Seed Script

### Overview
Update the seeding script to create demo tenants pointing to the new public receiver.

### Changes Required:

#### 1. Update Seed Script
**File**: `scripts/seed_webhooks.py`

Replace lines 27-43 with:

```python
def seed_tenants():
    """Seed 3 test tenants with webhook configs"""
    # Use public demo receiver for all demo tenants
    demo_receiver_base = "https://receiver.vincentchan.cloud/webhook"

    tenants = [
        {
            "name": "acme",
            "display": "Acme Corp (Demo)",
            "targetUrl": demo_receiver_base,
            # webhookSecret will be auto-generated
        },
        {
            "name": "globex",
            "display": "Globex Inc (Demo)",
            "targetUrl": demo_receiver_base,
            # webhookSecret will be auto-generated
        },
        {
            "name": "initech",
            "display": "Initech LLC (Demo)",
            "targetUrl": demo_receiver_base,
            # webhookSecret will be auto-generated
        },
    ]
```

Line 52 already generates unique secrets per tenant - no changes needed:

```python
        webhook_secret = generate_webhook_secret()  # Unique per tenant
```

Add at the end of the script (after line 93):

```python
    print("View received webhooks at:")
    print("https://receiver.vincentchan.cloud/recent")
    print()
    print("Or use the Swagger UI:")
    print("https://receiver.vincentchan.cloud/docs")
```

### Success Criteria:

#### Automated Verification:
- [ ] Seed script runs: `python scripts/seed_webhooks.py`
- [ ] Tenants created with correct targetUrl

#### Manual Verification:
- [ ] Send test event to API
- [ ] Webhook appears at `https://receiver.vincentchan.cloud/recent`
- [ ] Signature validation succeeds

**Implementation Note**: Test end-to-end flow after seeding.

---

## Phase 4: Integration Testing

### Overview
Test the complete webhook delivery flow with the public receiver.

### Changes Required:

#### 1. Create Integration Test Script
**File**: `tests/test_demo_flow.py`

```python
#!/usr/bin/env python3
"""
Test the complete demo webhook flow.
"""
import time
import requests
import sys


def test_demo_flow(api_key: str):
    """Test complete webhook delivery cycle"""

    # 1. Send event to main API
    print("1. Sending event to hooks.vincentchan.cloud...")
    response = requests.post(
        "https://hooks.vincentchan.cloud/v1/events",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "event": "demo.test",
            "timestamp": time.time(),
            "message": "Testing webhook delivery",
        },
    )

    if response.status_code != 201:
        print(f"❌ Failed to send event: {response.status_code}")
        print(response.text)
        return False

    event_data = response.json()
    event_id = event_data["event_id"]
    print(f"✅ Event created: {event_id}")

    # 2. Wait for delivery
    print("2. Waiting for webhook delivery...")
    time.sleep(5)

    # 3. Check receiver
    print("3. Checking receiver.vincentchan.cloud...")
    response = requests.get("https://receiver.vincentchan.cloud/recent")

    if response.status_code != 200:
        print(f"❌ Failed to get recent webhooks: {response.status_code}")
        return False

    webhooks = response.json()["webhooks"]

    # Find our event
    found = False
    for webhook in webhooks:
        if webhook.get("event_id") == event_id:
            found = True
            if webhook["signature_valid"]:
                print(f"✅ Webhook received with valid signature!")
            else:
                print(f"⚠️ Webhook received but signature invalid")
            break

    if not found:
        print(f"❌ Webhook not found in receiver")
        return False

    print("\n✅ Complete demo flow successful!")
    print(f"View all webhooks: https://receiver.vincentchan.cloud/recent")
    print(f"API docs: https://receiver.vincentchan.cloud/docs")

    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test_demo_flow.py <api-key>")
        print("Get API key from seed script output")
        sys.exit(1)

    api_key = sys.argv[1]
    success = test_demo_flow(api_key)
    sys.exit(0 if success else 1)
```

### Success Criteria:

#### Automated Verification:
- [ ] Test script completes successfully: `python tests/test_demo_flow.py <api-key>`

#### Manual Verification:
- [ ] Complete flow works end-to-end
- [ ] Multiple webhooks can be received
- [ ] Receiver handles concurrent requests
- [ ] Memory storage clears old webhooks

---

## Phase 5: Documentation Updates

### Overview
Update documentation to reflect the new public demo receiver.

### Changes Required:

#### 1. Update Main README
**File**: `README.md`

Add section after Quick Start:

```markdown
## Live Demo

Experience the complete webhook delivery flow without any setup:

### 1. Send a Test Event

```bash
# Use demo API key for "acme" tenant
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer tenant_acme_live_demo" \
  -H "Content-Type: application/json" \
  -d '{"event": "user.signup", "user_id": "123", "email": "demo@example.com"}'
```

### 2. View Delivered Webhook

Visit: https://receiver.vincentchan.cloud/recent

The webhook will appear within seconds with:
- ✅ Valid HMAC signature
- Full payload as sent
- Delivery timestamp

### 3. Explore the API

- **Receiver Swagger UI**: https://receiver.vincentchan.cloud/docs
- **Main API Docs**: https://hooks.vincentchan.cloud/v1/docs

### Demo Architecture

```
[Your App] → POST → [hooks.vincentchan.cloud] → SQS → [Worker Lambda]
                                                          ↓
                                                    Webhook + HMAC
                                                          ↓
                                              [receiver.vincentchan.cloud]
```

The demo receiver validates signatures and stores recent webhooks in memory for viewing.
```

#### 2. Update Webhook Integration Guide
**File**: `docs/WEBHOOK_INTEGRATION.md`

Add section:

```markdown
## Testing with Demo Receiver

For testing and development, use our public demo receiver:

```bash
# Update your tenant to use demo receiver
aws dynamodb update-item \
  --table-name Vincent-TriggerApi-TenantApiKeys \
  --key '{"apiKey": {"S": "your-api-key"}}' \
  --update-expression "SET targetUrl = :url" \
  --expression-attribute-values '{":url": {"S": "https://receiver.vincentchan.cloud/webhook"}}'
```

View received webhooks at: https://receiver.vincentchan.cloud/recent

The demo receiver:
- Validates HMAC signatures
- Returns proper HTTP status codes
- Stores last 100 webhooks for 60 minutes
- Provides Swagger documentation
```

### Success Criteria:

#### Automated Verification:
- [ ] Documentation builds without errors
- [ ] All links are valid

#### Manual Verification:
- [ ] Demo flow works as documented
- [ ] API documentation is accessible
- [ ] Examples work correctly

---

## Testing Strategy

### Unit Tests:
- Signature validation with known test vectors
- In-memory storage thread safety
- Webhook model validation

### Integration Tests:
- End-to-end webhook delivery
- Concurrent webhook reception
- Memory cleanup after TTL

### Manual Testing Steps:
1. Deploy infrastructure
2. Run seed script
3. Send test events via curl
4. View webhooks at receiver
5. Test signature validation (valid and invalid)
6. Verify memory cleanup

## Performance Considerations

- Lambda memory: 512 MB (sufficient for FastAPI + in-memory storage)
- Max 100 webhooks in memory (configurable)
- 60-minute TTL for stored webhooks
- Thread-safe storage for concurrent requests
- API Gateway throttling: 100 RPS for demo

## Migration Notes

For existing deployments:
1. Deploy new infrastructure (Phase 2)
2. Wait for DNS propagation
3. Run updated seed script (Phase 3)
4. Existing tenants continue using current URLs

## References

- Current test receiver: [tests/webhook_receiver.py](tests/webhook_receiver.py)
- FastAPI Lambda pattern: [src/api/main.py](src/api/main.py)
- CDK Lambda patterns: [cdk/stacks/webhook_delivery_stack.py:145-174](cdk/stacks/webhook_delivery_stack.py#L145-L174)
- Signature validation: [tests/webhook_receiver.py:22-42](tests/webhook_receiver.py#L22-L42)