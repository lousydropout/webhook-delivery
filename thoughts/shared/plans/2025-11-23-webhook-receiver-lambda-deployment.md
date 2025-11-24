# Webhook Receiver Lambda Deployment Implementation Plan

## Overview

Deploy the existing `tests/webhook_receiver.py` as a Lambda function with API Gateway integration, enabling it to receive webhooks from the main webhook delivery system while dynamically retrieving webhook secrets from DynamoDB for multi-tenant HMAC signature validation.

## Current State Analysis

**What exists now:**
- Local test webhook receiver ([tests/webhook_receiver.py](tests/webhook_receiver.py)) using FastAPI with hardcoded secret
- Complete Lambda patterns with Mangum adapter ([src/api/main.py:17](src/api/main.py#L17))
- DynamoDB TenantApiKeys table with webhook secrets ([cdk/stacks/webhook_delivery_stack.py:67-77](cdk/stacks/webhook_delivery_stack.py#L67-L77))
- CDK infrastructure patterns for Lambda deployment ([cdk/stacks/webhook_delivery_stack.py:145-174](cdk/stacks/webhook_delivery_stack.py#L145-L174))
- HMAC signature generation/validation patterns ([src/worker/signatures.py:6-22](src/worker/signatures.py#L6-L22))

**What's missing:**
- Lambda-compatible version of webhook_receiver.py with Mangum
- DynamoDB integration for dynamic secret retrieval
- Multi-tenant support (path-based or header-based)
- CDK infrastructure definition for receiver Lambda
- Public API Gateway endpoint for webhook reception

### Key Discoveries:
- All Lambda functions use module-level DynamoDB initialization ([src/api/dynamo.py:7-8](src/api/dynamo.py#L7-L8))
- Environment variables passed via CDK `environment` parameter ([cdk/stacks/webhook_delivery_stack.py:165-169](cdk/stacks/webhook_delivery_stack.py#L165-L169))
- Docker-based bundling pattern for dependencies ([cdk/stacks/webhook_delivery_stack.py:151-162](cdk/stacks/webhook_delivery_stack.py#L151-L162))
- Grant methods for IAM permissions ([cdk/stacks/webhook_delivery_stack.py:172-174](cdk/stacks/webhook_delivery_stack.py#L172-L174))

## Desired End State

A production-ready webhook receiver Lambda that:
- Accepts webhooks at `/v1/receiver/{tenantId}/webhook` endpoint
- Dynamically retrieves webhook secrets from DynamoDB based on tenant ID
- Validates HMAC signatures using Stripe-style format
- Returns appropriate HTTP status codes (200 for valid, 401 for invalid)
- Operates within the existing API Gateway at `hooks.vincentchan.cloud`
- Supports multi-tenant webhook reception without code changes

### Success Verification:
- Lambda function deployed and accessible via API Gateway
- Webhook signature validation works with dynamic secrets
- Multi-tenant support via path parameters
- Proper error handling and logging
- Performance within acceptable limits (<1s response time)

## What We're NOT Doing

- Creating a separate API Gateway (will use existing one)
- Adding authentication to the receiver endpoint (webhooks are validated via HMAC)
- Storing received webhooks (only validation and response)
- Creating a UI or dashboard
- Implementing webhook replay functionality
- Adding custom domain (uses existing hooks.vincentchan.cloud)

## Implementation Approach

Transform the existing webhook_receiver.py into a Lambda-compatible function using established patterns from the codebase. Add DynamoDB integration for secret retrieval, deploy via CDK following existing Lambda patterns, and integrate with the current API Gateway.

## Phase 1: Create Lambda-Compatible Webhook Receiver

### Overview
Transform the FastAPI webhook receiver to work as a Lambda function with Mangum adapter and DynamoDB secret retrieval.

### Changes Required:

#### 1. Create Webhook Receiver Lambda Directory
**Directory Structure**: `src/webhook_receiver/`

```bash
mkdir -p src/webhook_receiver
```

#### 2. Lambda Handler with FastAPI and Mangum
**File**: `src/webhook_receiver/main.py`

```python
#!/usr/bin/env python3
"""
Lambda webhook receiver that validates HMAC signatures.
FastAPI-based receiver for webhook delivery validation.
"""
import os
import hmac
import hashlib
import json
import boto3
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional, Dict, Any
from mangum import Mangum

# Initialize FastAPI app
app = FastAPI(
    title="Webhook Receiver",
    description="Multi-tenant webhook receiver with HMAC validation",
    version="2.0.0",
    docs_url="/v1/receiver/docs",
    redoc_url="/v1/receiver/redoc",
    openapi_url="/v1/receiver/openapi.json",
)

# Module-level DynamoDB initialization (Lambda best practice)
dynamodb = boto3.resource("dynamodb")
tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])


def get_webhook_secret_for_tenant(tenant_id: str) -> Optional[str]:
    """
    Retrieve webhook secret for a tenant from DynamoDB.
    Uses scan with filter (table is small enough for this pattern).
    """
    try:
        response = tenant_api_keys_table.scan(
            FilterExpression="tenantId = :tid",
            ExpressionAttributeValues={":tid": tenant_id}
        )

        items = response.get("Items", [])
        if items and items[0].get("isActive"):
            return items[0].get("webhookSecret")

        return None
    except Exception as e:
        print(f"Error retrieving webhook secret for tenant {tenant_id}: {e}")
        return None


def verify_signature(payload: str, signature_header: str, webhook_secret: str) -> bool:
    """
    Verify Stripe-style HMAC signature.
    Format: t={timestamp},v1={signature}
    """
    try:
        parts = dict(item.split("=") for item in signature_header.split(","))
        timestamp = parts.get("t")
        signature = parts.get("v1")

        if not timestamp or not signature:
            return False

        signed_payload = f"{timestamp}.{payload}"
        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
    except Exception as e:
        print(f"Error verifying signature: {e}")
        return False


@app.post("/v1/receiver/{tenant_id}/webhook")
async def receive_webhook(
    tenant_id: str,
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """
    Receive and validate webhook for a specific tenant.
    Path parameter identifies the tenant for secret lookup.
    """
    # Validate signature header presence
    if not stripe_signature:
        print(f"Missing Stripe-Signature header for tenant: {tenant_id}")
        raise HTTPException(status_code=401, detail="Missing Stripe-Signature header")

    # Read raw body for signature verification
    body = await request.body()
    payload = body.decode("utf-8")

    # Retrieve webhook secret from DynamoDB
    webhook_secret = get_webhook_secret_for_tenant(tenant_id)
    if not webhook_secret:
        print(f"No active webhook secret found for tenant: {tenant_id}")
        raise HTTPException(status_code=404, detail="Tenant not found or inactive")

    # Verify HMAC signature
    if not verify_signature(payload, stripe_signature, webhook_secret):
        print(f"Invalid signature for tenant: {tenant_id}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload for logging
    try:
        payload_json = json.loads(payload)
        event_id = payload_json.get("eventId") or payload_json.get("event_id")
        print(f"✓ Valid webhook received for tenant {tenant_id}, event: {event_id}")
    except json.JSONDecodeError:
        print(f"✓ Valid webhook received for tenant {tenant_id} (non-JSON payload)")

    return {"status": "received", "tenant_id": tenant_id}


@app.get("/v1/receiver/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "service": "webhook-receiver"}


# Lambda handler using Mangum adapter
handler = Mangum(app)
```

#### 3. Dependencies Configuration
**File**: `src/webhook_receiver/requirements.txt`

```txt
fastapi==0.104.1
mangum==0.17.0
boto3==1.34.0
```

### Success Criteria:

#### Automated Verification:
- [x] Module imports successfully: `python -c "from src.webhook_receiver.main import handler"`
- [x] FastAPI app initializes: `python -c "from src.webhook_receiver.main import app"`
- [x] DynamoDB client creation doesn't error at import time

#### Manual Verification:
- [x] Signature verification logic correctly validates known test cases
- [x] DynamoDB lookup returns correct webhook secrets (tested with mock)
- [x] Error handling provides appropriate HTTP status codes

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to the next phase.

---

## Phase 2: Add Lambda to CDK Infrastructure

### Overview
Integrate the webhook receiver Lambda into the existing CDK stack following established patterns.

### Changes Required:

#### 1. Add Webhook Receiver Lambda Definition
**File**: `cdk/stacks/webhook_delivery_stack.py`
**Location**: After DLQ Processor Lambda (around line 280)

```python
# ============================================================
# Webhook Receiver Lambda (Multi-tenant Webhook Validation)
# ============================================================
self.webhook_receiver_lambda = lambda_.Function(
    self,
    "WebhookReceiverLambda",
    function_name=f"{prefix}-WebhookReceiver",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="main.handler",
    code=lambda_.Code.from_asset(
        "../src/webhook_receiver",
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
    timeout=Duration.seconds(10),  # Webhook validation should be fast
    memory_size=256,  # Minimal memory needed for signature validation
    environment={
        "TENANT_API_KEYS_TABLE": self.tenant_api_keys_table.table_name,
    },
)

# Grant read access to tenant API keys table
self.tenant_api_keys_table.grant_read_data(self.webhook_receiver_lambda)
```

#### 2. Add API Gateway Resources
**File**: `cdk/stacks/webhook_delivery_stack.py`
**Location**: After existing API resources (around line 345)

```python
# ============================================================
# Webhook Receiver Endpoints (No Authentication Required)
# ============================================================
# Create /v1/receiver resource
receiver_resource = v1_resource.add_resource("receiver")

# Health check endpoint
health_resource = receiver_resource.add_resource("health")
health_resource.add_method(
    "GET",
    apigateway.LambdaIntegration(
        self.webhook_receiver_lambda,
        proxy=True,
    ),
)

# Tenant-specific webhook endpoint: /v1/receiver/{tenantId}/webhook
tenant_resource = receiver_resource.add_resource("{tenantId}")
webhook_resource = tenant_resource.add_resource("webhook")

# POST method for webhook reception (no auth - validated via HMAC)
webhook_resource.add_method(
    "POST",
    apigateway.LambdaIntegration(
        self.webhook_receiver_lambda,
        proxy=True,
        request_templates={
            "application/json": '{"statusCode": 200}'
        },
    ),
    request_parameters={
        "method.request.path.tenantId": True,
        "method.request.header.Stripe-Signature": False,
    },
)

# Documentation endpoints (if needed)
docs_resource = receiver_resource.add_resource("docs")
docs_resource.add_method(
    "GET",
    apigateway.LambdaIntegration(
        self.webhook_receiver_lambda,
        proxy=True,
    ),
)
```

#### 3. Add CloudFormation Outputs
**File**: `cdk/stacks/webhook_delivery_stack.py`
**Location**: At the end of the stack (after line 406)

```python
# Webhook Receiver Outputs
CfnOutput(
    self,
    "WebhookReceiverFunctionName",
    value=self.webhook_receiver_lambda.function_name,
    description="Webhook receiver Lambda function name",
)

CfnOutput(
    self,
    "WebhookReceiverEndpoint",
    value=f"https://hooks.vincentchan.cloud/v1/receiver/{{tenantId}}/webhook",
    description="Webhook receiver endpoint URL template",
)

CfnOutput(
    self,
    "WebhookReceiverHealthEndpoint",
    value=f"https://hooks.vincentchan.cloud/v1/receiver/health",
    description="Webhook receiver health check endpoint",
)
```

### Success Criteria:

#### Automated Verification:
- [ ] CDK synthesizes without errors: `cd cdk && cdk synth`
- [ ] CDK diff shows new Lambda and API resources: `cd cdk && cdk diff`
- [ ] No circular dependencies or reference errors

#### Manual Verification:
- [ ] CDK deployment plan looks correct
- [ ] IAM permissions are properly scoped
- [ ] Environment variables are correctly configured

**Implementation Note**: Review CDK diff output carefully before deployment.

---

## Phase 3: Deploy and Configure

### Overview
Deploy the infrastructure and update webhook configurations to use the new receiver endpoint.

### Changes Required:

#### 1. Deploy CDK Stack
**Commands**:

```bash
cd cdk

# Synthesize to verify
cdk synth

# Deploy with approval
cdk deploy --require-approval broadening

# Note the outputs, especially WebhookReceiverEndpoint
```

#### 2. Update Seed Script for Testing
**File**: `scripts/seed_webhooks.py`
**Changes**: Add a test tenant pointing to the new receiver (line 44)

```python
# Add after existing test tenants
{
    "name": "receiver-test",
    "display": "Webhook Receiver Test",
    "targetUrl": "https://hooks.vincentchan.cloud/v1/receiver/receiver-test/webhook",
},
```

### Success Criteria:

#### Automated Verification:
- [ ] Lambda function exists: `aws lambda get-function --function-name {prefix}-WebhookReceiver`
- [ ] API Gateway resources created: `aws apigateway get-resources --rest-api-id {api-id}`
- [ ] Lambda has correct environment variables: `aws lambda get-function-configuration --function-name {prefix}-WebhookReceiver`
- [ ] IAM role has DynamoDB permissions

#### Manual Verification:
- [ ] Health endpoint responds: `curl https://hooks.vincentchan.cloud/v1/receiver/health`
- [ ] Webhook endpoint accessible: `curl -X POST https://hooks.vincentchan.cloud/v1/receiver/test/webhook`
- [ ] CloudWatch logs created for Lambda function

**Implementation Note**: Monitor CloudWatch logs during initial testing for any errors.

---

## Phase 4: Integration Testing

### Overview
Validate the complete webhook flow with the new receiver Lambda.

### Changes Required:

#### 1. Create Integration Test
**File**: `tests/test_webhook_receiver_lambda.py`

```python
#!/usr/bin/env python3
"""
Integration test for webhook receiver Lambda.
Tests the complete flow from API to receiver.
"""
import time
import hmac
import hashlib
import json
import requests
import boto3
from typing import Dict, Any


def generate_stripe_signature(payload: str, secret: str) -> str:
    """Generate Stripe-style webhook signature"""
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_webhook_receiver_flow():
    """Test complete webhook delivery to receiver Lambda"""

    # Test configuration
    api_base = "https://hooks.vincentchan.cloud"
    tenant_id = "receiver-test"
    api_key = f"tenant_{tenant_id}_test"  # From seed script

    # 1. Send event to trigger webhook
    print("1. Sending event to trigger webhook delivery...")
    event_payload = {
        "test": "webhook_receiver_lambda",
        "timestamp": time.time(),
        "message": "Testing Lambda receiver",
    }

    response = requests.post(
        f"{api_base}/v1/events",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=event_payload,
    )

    assert response.status_code == 201, f"Failed to create event: {response.text}"
    event_id = response.json()["event_id"]
    print(f"✓ Event created: {event_id}")

    # 2. Wait for webhook delivery (SQS processing)
    print("2. Waiting for webhook processing...")
    time.sleep(5)

    # 3. Test receiver health endpoint
    print("3. Testing receiver health endpoint...")
    response = requests.get(f"{api_base}/v1/receiver/health")
    assert response.status_code == 200, "Health check failed"
    print("✓ Health endpoint responding")

    # 4. Test webhook endpoint with valid signature
    print("4. Testing webhook with valid signature...")

    # Get webhook secret from DynamoDB
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table("Vincent-TriggerApi-TenantApiKeys")  # Adjust prefix

    response = table.scan(
        FilterExpression="tenantId = :tid",
        ExpressionAttributeValues={":tid": tenant_id}
    )

    assert response["Items"], f"Tenant {tenant_id} not found"
    webhook_secret = response["Items"][0]["webhookSecret"]

    # Create test payload and signature
    test_payload = json.dumps({"eventId": event_id, "test": True})
    signature = generate_stripe_signature(test_payload, webhook_secret)

    # Send to receiver
    response = requests.post(
        f"{api_base}/v1/receiver/{tenant_id}/webhook",
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": signature,
        },
        data=test_payload,
    )

    assert response.status_code == 200, f"Valid webhook rejected: {response.text}"
    print("✓ Valid signature accepted")

    # 5. Test with invalid signature
    print("5. Testing webhook with invalid signature...")
    bad_signature = "t=12345,v1=invalid"

    response = requests.post(
        f"{api_base}/v1/receiver/{tenant_id}/webhook",
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": bad_signature,
        },
        data=test_payload,
    )

    assert response.status_code == 401, "Invalid signature not rejected"
    print("✓ Invalid signature rejected")

    # 6. Test with missing signature
    print("6. Testing webhook without signature...")
    response = requests.post(
        f"{api_base}/v1/receiver/{tenant_id}/webhook",
        headers={"Content-Type": "application/json"},
        data=test_payload,
    )

    assert response.status_code == 401, "Missing signature not rejected"
    print("✓ Missing signature rejected")

    # 7. Test with non-existent tenant
    print("7. Testing with non-existent tenant...")
    response = requests.post(
        f"{api_base}/v1/receiver/nonexistent/webhook",
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": signature,
        },
        data=test_payload,
    )

    assert response.status_code == 404, "Non-existent tenant not handled"
    print("✓ Non-existent tenant returns 404")

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    test_webhook_receiver_flow()
```

### Success Criteria:

#### Automated Verification:
- [ ] Integration test passes: `python tests/test_webhook_receiver_lambda.py`
- [ ] All test cases complete successfully
- [ ] CloudWatch logs show successful executions

#### Manual Verification:
- [ ] Lambda cold start time is acceptable (<3 seconds)
- [ ] Webhook validation completes within timeout
- [ ] Error messages are properly logged
- [ ] No memory or timeout issues under load

**Implementation Note**: Run tests multiple times to ensure consistency and check for any intermittent issues.

---

## Phase 5: Production Configuration

### Overview
Configure monitoring, alarms, and documentation for production use.

### Changes Required:

#### 1. Add CloudWatch Alarms
**File**: `cdk/stacks/webhook_delivery_stack.py`
**Location**: After Lambda definition

```python
# Add Lambda error alarm
lambda_error_alarm = cloudwatch.Alarm(
    self,
    "WebhookReceiverErrors",
    metric=self.webhook_receiver_lambda.metric_errors(),
    threshold=5,
    evaluation_periods=1,
    alarm_description="Webhook receiver Lambda errors",
)

# Add Lambda throttle alarm
lambda_throttle_alarm = cloudwatch.Alarm(
    self,
    "WebhookReceiverThrottles",
    metric=self.webhook_receiver_lambda.metric_throttles(),
    threshold=1,
    evaluation_periods=1,
    alarm_description="Webhook receiver Lambda throttles",
)
```

#### 2. Update Documentation
**File**: `README.md`
**Section**: Add after architecture section

```markdown
## Webhook Receiver

The system includes a webhook receiver Lambda for validating delivered webhooks:

### Endpoint
```
POST https://hooks.vincentchan.cloud/v1/receiver/{tenantId}/webhook
```

### Features
- Dynamic webhook secret retrieval from DynamoDB
- Stripe-style HMAC signature validation
- Multi-tenant support via path parameters
- No authentication required (validated via HMAC)

### Testing
```bash
# Send a test webhook with valid signature
curl -X POST https://hooks.vincentchan.cloud/v1/receiver/test/webhook \
  -H "Stripe-Signature: t=1234567890,v1=..." \
  -H "Content-Type: application/json" \
  -d '{"event": "test"}'
```

### Integration
Update your tenant configuration to point to:
```
https://hooks.vincentchan.cloud/v1/receiver/{your-tenant-id}/webhook
```
```

### Success Criteria:

#### Automated Verification:
- [ ] CloudWatch alarms created successfully
- [ ] Metrics are being collected
- [ ] Documentation builds without errors

#### Manual Verification:
- [ ] Alarms trigger appropriately
- [ ] Logs are searchable in CloudWatch Insights
- [ ] Documentation accurately reflects implementation

---

## Testing Strategy

### Unit Tests:
- Signature validation with test vectors
- DynamoDB lookup error handling
- Request parsing edge cases

### Integration Tests:
- End-to-end webhook delivery and validation
- Multi-tenant isolation
- Error scenarios (invalid signature, missing tenant)
- Performance under concurrent requests

### Manual Testing Steps:
1. Deploy infrastructure with CDK
2. Run seed script to create test tenants
3. Send test webhook to receiver endpoint
4. Verify signature validation (valid and invalid cases)
5. Check CloudWatch logs for proper logging
6. Test with multiple tenants simultaneously
7. Monitor Lambda performance metrics

## Performance Considerations

- **Lambda Configuration**: 256 MB memory, 10-second timeout (validation should be <1s)
- **Cold Start**: ~1-2 seconds for Python with Mangum
- **Concurrent Executions**: Default 1000 concurrent (sufficient for webhook receipt)
- **DynamoDB**: Scan operation is acceptable for small tenant table (<100 items)
- **Optimization**: Consider adding GSI on tenantId if table grows large

## Migration Notes

For existing systems:
1. Deploy new Lambda and API resources (no breaking changes)
2. Test with dedicated test tenant first
3. Gradually migrate tenants to use receiver endpoint
4. Monitor CloudWatch metrics during migration
5. Keep fallback to external URLs if needed

## References

- Original receiver: [tests/webhook_receiver.py](tests/webhook_receiver.py)
- Lambda patterns: [src/api/main.py](src/api/main.py)
- CDK Lambda definition: [cdk/stacks/webhook_delivery_stack.py:145-174](cdk/stacks/webhook_delivery_stack.py#L145-L174)
- DynamoDB patterns: [src/authorizer/handler.py:16-24](src/authorizer/handler.py#L16-L24)
- Environment variables: [cdk/stacks/webhook_delivery_stack.py:165-169](cdk/stacks/webhook_delivery_stack.py#L165-L169)
- IAM permissions: [cdk/stacks/webhook_delivery_stack.py:172-174](cdk/stacks/webhook_delivery_stack.py#L172-L174)