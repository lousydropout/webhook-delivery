# Lambda Authorizer Separation Implementation Plan

## Overview

Separate authentication logic from the API Lambda into a dedicated Lambda authorizer that runs at the API Gateway level. This improves security, enables caching of authorization decisions, and separates concerns between authentication and business logic.

## Current State Analysis

The webhook delivery system currently implements authentication within the API Lambda using FastAPI's dependency injection:

- Authentication logic in [src/api/auth.py:37-47](../../../src/api/auth.py#L37-L47)
- Route integration via `Depends(verify_api_key)` in [src/api/routes.py:18](../../../src/api/routes.py#L18)
- DynamoDB lookup on every request with no caching
- API Gateway uses `LambdaRestApi` with `proxy=True` - no authorizer configured
- Bearer token validation happens inside Lambda cold starts

### Key Components:
- **TenantApiKeys Table** ([cdk/stacks/webhook_delivery_stack.py:67-78](../../../cdk/stacks/webhook_delivery_stack.py#L67-L78)): Stores API key → tenant mapping
- **API Lambda** ([cdk/stacks/webhook_delivery_stack.py:145-174](../../../cdk/stacks/webhook_delivery_stack.py#L145-L174)): Currently handles both auth and business logic
- **Auth Module** ([src/api/auth.py](../../../src/api/auth.py)): HTTPBearer + DynamoDB lookup

## Desired End State

After implementation:
- Dedicated authorizer Lambda validates API keys at API Gateway level
- Authorization results cached for 5 minutes
- API Lambda receives pre-validated tenant context via `event['requestContext']['authorizer']`
- Reduced latency (cached auth decisions)
- Cleaner separation of concerns

### Verification:
- API requests with valid Bearer tokens succeed (200/201)
- Invalid tokens return 401 Unauthorized
- Authorization caching reduces DynamoDB read units
- Tenant context available in API Lambda without additional lookups
- All existing tests pass with updated mocking patterns

## What We're NOT Doing

- NOT changing Worker Lambda authentication (no internet-facing security concern)
- NOT modifying the TenantApiKeys table schema
- NOT changing the Bearer token format or client integration
- NOT switching away from `LambdaRestApi` construct (using `defaultMethodOptions` instead)
- NOT implementing additional authorization logic beyond API key validation

## Implementation Approach

Create a new authorizer Lambda that:
1. Extracts Bearer token from `Authorization` header
2. Validates against TenantApiKeys DynamoDB table
3. Returns IAM Allow/Deny policy with tenant context
4. Integrates via API Gateway's `TokenAuthorizer` with result caching

Modify API Lambda to:
1. Extract tenant context from API Gateway authorizer context
2. Remove FastAPI dependency injection for auth
3. Simplify route handlers

## Phase 1: Create Authorizer Lambda

### Overview
Build a standalone Lambda function that validates Bearer tokens and returns IAM policies with tenant context.

### Changes Required:

#### 1. Create Authorizer Directory Structure
**New Directory**: `src/authorizer/`

Create the following files:
- `handler.py` - Main Lambda handler
- `requirements.txt` - Dependencies (boto3)
- `__init__.py` - Empty file for Python module

#### 2. Implement Authorizer Handler
**File**: `src/authorizer/handler.py`

```python
import os
import boto3
from typing import Dict, Any, Optional

dynamodb = boto3.resource("dynamodb")
api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])


def get_tenant_from_api_key(api_key: str) -> Optional[Dict]:
    """
    Look up tenant from API key in DynamoDB.

    Returns tenant item if valid and active, None otherwise.
    """
    try:
        response = api_keys_table.get_item(Key={"apiKey": api_key})
        item = response.get("Item")

        if not item or not item.get("isActive"):
            return None

        return item
    except Exception as e:
        print(f"Error looking up API key: {e}")
        return None


def generate_policy(principal_id: str, effect: str, resource: str, context: Dict[str, Any] = None) -> Dict:
    """
    Generate IAM policy document for API Gateway.

    Args:
        principal_id: Identifier for the authenticated principal (tenantId)
        effect: "Allow" or "Deny"
        resource: ARN of the API Gateway method
        context: Additional context to pass to the Lambda (must be string values)
    """
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource
                }
            ]
        }
    }

    if context:
        # API Gateway requires all context values to be strings
        policy["context"] = {k: str(v) for k, v in context.items()}

    return policy


def handler(event: Dict, context: Any) -> Dict:
    """
    Lambda authorizer for API Gateway TOKEN type.

    Event structure:
    {
        "type": "TOKEN",
        "authorizationToken": "Bearer <api-key>",
        "methodArn": "arn:aws:execute-api:..."
    }

    Returns IAM policy with tenant context or Deny policy.
    """
    token = event.get("authorizationToken", "")
    method_arn = event["methodArn"]

    # Extract Bearer token
    if not token.startswith("Bearer "):
        print("Missing or invalid Authorization header format")
        return generate_policy("anonymous", "Deny", method_arn)

    api_key = token[7:]  # Remove "Bearer " prefix

    # Validate API key
    tenant = get_tenant_from_api_key(api_key)

    if not tenant:
        print(f"Invalid or inactive API key")
        return generate_policy("anonymous", "Deny", method_arn)

    # Generate Allow policy with tenant context
    tenant_id = tenant["tenantId"]
    context_data = {
        "tenantId": tenant["tenantId"],
        "targetUrl": tenant["targetUrl"],
        "webhookSecret": tenant["webhookSecret"],
        "isActive": tenant["isActive"]
    }

    print(f"Authorized tenant: {tenant_id}")
    return generate_policy(tenant_id, "Allow", method_arn, context_data)
```

#### 3. Add Dependencies
**File**: `src/authorizer/requirements.txt`

```
boto3==1.34.0
```

#### 4. Add Python Module Init
**File**: `src/authorizer/__init__.py`

```python
# Empty file to make this a Python module
```

### Success Criteria:

#### Automated Verification:
- [x] Directory structure created: `ls -la src/authorizer/`
- [x] Handler file exists with correct function signature
- [x] Requirements.txt specifies boto3
- [x] Code passes syntax check: `python3 -m py_compile src/authorizer/handler.py`

#### Manual Verification:
- [ ] Review handler code for correctness
- [ ] Verify Bearer token extraction logic
- [ ] Confirm policy structure matches AWS requirements
- [ ] Check that all tenant context fields are included

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Update CDK Infrastructure

### Overview
Add the authorizer Lambda to the CDK stack and configure API Gateway to use it with caching.

### Changes Required:

#### 1. Add Authorizer Lambda Function
**File**: `cdk/stacks/webhook_delivery_stack.py`

Add after the API Lambda definition (after line 174):

```python
# ============================================================
# Authorizer Lambda
# Validates Bearer tokens and returns tenant context
# ============================================================
self.authorizer_lambda = lambda_.Function(
    self,
    "AuthorizerLambda",
    function_name=f"{prefix}-Authorizer",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="handler.handler",
    code=lambda_.Code.from_asset(
        "../src/authorizer",
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
    memory_size=256,
    environment={
        "TENANT_API_KEYS_TABLE": self.tenant_api_keys_table.table_name,
    },
)

self.tenant_api_keys_table.grant_read_data(self.authorizer_lambda)
```

#### 2. Create TokenAuthorizer Construct
**File**: `cdk/stacks/webhook_delivery_stack.py`

Add before the API Gateway definition (before line 253):

```python
# ============================================================
# API Gateway Token Authorizer
# ============================================================
self.token_authorizer = apigateway.TokenAuthorizer(
    self,
    "ApiTokenAuthorizer",
    handler=self.authorizer_lambda,
    identity_source="method.request.header.Authorization",
    results_cache_ttl=Duration.minutes(5),
)
```

#### 3. Update LambdaRestApi Configuration
**File**: `cdk/stacks/webhook_delivery_stack.py`

Modify the existing `LambdaRestApi` definition (lines 253-276) to add `default_method_options`:

```python
self.api = apigateway.LambdaRestApi(
    self,
    "TriggerApi",
    handler=self.api_lambda,
    proxy=True,
    rest_api_name="Webhook Delivery API",
    description="Multi-tenant webhook delivery with SQS-backed processing",
    deploy_options=apigateway.StageOptions(
        stage_name="prod",
        throttling_rate_limit=500,
        throttling_burst_limit=1000,
    ),
    default_method_options=apigateway.MethodOptions(
        authorizer=self.token_authorizer,
        authorization_type=apigateway.AuthorizationType.CUSTOM,
    ),
    default_cors_preflight_options=apigateway.CorsOptions(
        allow_origins=["*"],
        allow_methods=apigateway.Cors.ALL_METHODS,
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Amz-Date",
            "X-Api-Key",
            "X-Amz-Security-Token",
        ],
    ),
)
```

### Success Criteria:

#### Automated Verification:
- [ ] CDK synth succeeds: `cd cdk && cdk synth` (deferred - requires AWS credentials)
- [ ] No CDK diff errors: `cd cdk && cdk diff` (deferred - requires AWS credentials)
- [x] Python syntax valid: `python3 -m py_compile cdk/stacks/webhook_delivery_stack.py`

#### Manual Verification:
- [ ] Review generated CloudFormation template for authorizer Lambda
- [ ] Verify TokenAuthorizer configuration in template
- [ ] Confirm API Gateway method has authorizer attached
- [ ] Check that cache TTL is set to 5 minutes

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Modify API Lambda to Use Authorizer Context

### Overview
Update the API Lambda to extract tenant context from the API Gateway authorizer instead of using FastAPI dependency injection.

### Changes Required:

#### 1. Create Context Extraction Utility
**File**: `src/api/context.py` (new file)

```python
from typing import Dict, Any


def get_tenant_from_context(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract tenant context from API Gateway authorizer.

    When using Lambda authorizer, API Gateway adds the authorizer's
    context to event['requestContext']['authorizer'].

    Args:
        event: Lambda event from API Gateway

    Returns:
        Tenant context dict with tenantId, targetUrl, webhookSecret, isActive

    Raises:
        KeyError: If authorizer context is missing (should not happen with proper config)
    """
    authorizer = event.get("requestContext", {}).get("authorizer", {})

    if not authorizer:
        raise ValueError("Missing authorizer context - authentication required")

    return {
        "tenantId": authorizer["tenantId"],
        "targetUrl": authorizer["targetUrl"],
        "webhookSecret": authorizer["webhookSecret"],
        "isActive": authorizer["isActive"] == "True",  # API GW context is all strings
    }
```

#### 2. Update Routes to Use Context
**File**: `src/api/routes.py`

Replace the dependency injection pattern:

```python
import os
import json
import boto3
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any

from context import get_tenant_from_context
from dynamo import create_event
from models import EventCreateResponse

router = APIRouter()

sqs = boto3.client("sqs")
EVENTS_QUEUE_URL = os.environ["EVENTS_QUEUE_URL"]


@router.post("/events", status_code=201, response_model=EventCreateResponse)
async def ingest_event(request: Request, payload: Dict[str, Any]):
    """
    Ingest event: store in DynamoDB and enqueue to SQS for delivery.

    Authentication is handled by API Gateway Lambda authorizer.
    Tenant context is extracted from request.scope["aws.event"].
    """
    # Extract Lambda event from Mangum
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    tenant_id = tenant["tenantId"]
    target_url = tenant["targetUrl"]

    # Store event in DynamoDB
    event_id = create_event(tenant_id, payload, target_url)

    # Enqueue to SQS for worker to process
    message_body = json.dumps(
        {
            "tenantId": tenant_id,
            "eventId": event_id,
        }
    )

    try:
        sqs.send_message(
            QueueUrl=EVENTS_QUEUE_URL,
            MessageBody=message_body,
        )
    except Exception as e:
        print(f"Error enqueuing to SQS: {e}")
        raise HTTPException(status_code=500, detail="Failed to enqueue event")

    return EventCreateResponse(event_id=event_id, status="PENDING")
```

### Success Criteria:

#### Automated Verification:
- [x] Python syntax valid: `python3 -m py_compile src/api/context.py`
- [x] Python syntax valid: `python3 -m py_compile src/api/routes.py`
- [x] No import errors when importing routes module (boto3 dependency expected in Lambda only)

#### Manual Verification:
- [ ] Review context extraction logic
- [ ] Verify all tenant fields are extracted correctly
- [ ] Confirm boolean conversion for isActive field
- [ ] Check error handling for missing context

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: Update Tests

### Overview
Update unit and integration tests to work with the new authorizer pattern.

### Changes Required:

#### 1. Add Authorizer Lambda Tests
**File**: `tests/test_authorizer.py` (new file)

```python
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add src/authorizer to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'authorizer'))


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table for authorizer"""
    with patch("handler.api_keys_table") as mock_table:
        yield mock_table


@pytest.fixture
def authorizer_event():
    """Mock API Gateway authorizer event"""
    return {
        "type": "TOKEN",
        "authorizationToken": "Bearer test_key_123",
        "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/POST/events"
    }


@pytest.fixture
def lambda_context():
    """Mock Lambda context"""
    context = MagicMock()
    context.function_name = "test-authorizer"
    context.request_id = "test-request-id"
    return context


def test_authorizer_valid_token(mock_dynamodb_table, authorizer_event, lambda_context):
    """Test authorizer with valid API key"""
    from handler import handler

    mock_dynamodb_table.get_item.return_value = {
        "Item": {
            "apiKey": "test_key_123",
            "tenantId": "acme",
            "targetUrl": "https://example.com/webhook",
            "webhookSecret": "secret123",
            "isActive": True,
        }
    }

    result = handler(authorizer_event, lambda_context)

    assert result["principalId"] == "acme"
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert result["context"]["tenantId"] == "acme"
    assert result["context"]["targetUrl"] == "https://example.com/webhook"


def test_authorizer_invalid_token(mock_dynamodb_table, authorizer_event, lambda_context):
    """Test authorizer with invalid API key"""
    from handler import handler

    mock_dynamodb_table.get_item.return_value = {}

    result = handler(authorizer_event, lambda_context)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_authorizer_inactive_key(mock_dynamodb_table, authorizer_event, lambda_context):
    """Test authorizer with inactive API key"""
    from handler import handler

    mock_dynamodb_table.get_item.return_value = {
        "Item": {
            "apiKey": "test_key_123",
            "tenantId": "acme",
            "isActive": False,
        }
    }

    result = handler(authorizer_event, lambda_context)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_authorizer_missing_bearer_prefix(authorizer_event, lambda_context):
    """Test authorizer with missing Bearer prefix"""
    from handler import handler

    authorizer_event["authorizationToken"] = "test_key_123"  # No "Bearer "

    result = handler(authorizer_event, lambda_context)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_authorizer_missing_token(lambda_context):
    """Test authorizer with missing token"""
    from handler import handler

    event = {
        "type": "TOKEN",
        "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/POST/events"
    }

    result = handler(event, lambda_context)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"
```

#### 2. Update API Lambda Tests
**File**: `tests/test_events.py`

Update to mock authorizer context in the request scope. Note: The exact implementation depends on how Mangum exposes the event. This may need adjustment during implementation.

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'api'))

from main import app


@pytest.fixture
def mock_sqs():
    """Mock SQS client"""
    with patch("routes.sqs") as mock:
        mock.send_message.return_value = {}
        yield mock


@pytest.fixture
def mock_create_event():
    """Mock create_event function"""
    with patch("routes.create_event") as mock:
        mock.return_value = "evt_test123"
        yield mock


@pytest.fixture
def mock_authorizer_context():
    """Mock the request to include API Gateway authorizer context"""
    mock_event = {
        "requestContext": {
            "authorizer": {
                "tenantId": "test_tenant",
                "targetUrl": "https://example.com/webhook",
                "webhookSecret": "test_secret",
                "isActive": "True"
            }
        }
    }

    with patch("routes.Request") as mock_request_class:
        mock_request_instance = MagicMock()
        mock_request_instance.scope = {"aws.event": mock_event}
        mock_request_class.return_value = mock_request_instance
        yield mock_request_instance


def test_create_event(mock_authorizer_context, mock_sqs, mock_create_event):
    """Test event creation with authorizer context"""
    client = TestClient(app)

    response = client.post(
        "/events",
        json={"event_type": "test.event", "data": "foo"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["event_id"] == "evt_test123"
    assert data["status"] == "PENDING"

    # Verify create_event was called with correct tenant_id
    mock_create_event.assert_called_once()
```

### Success Criteria:

#### Automated Verification:
- [x] Authorizer tests created and syntax valid
- [x] Updated API tests created and syntax valid
- [ ] All tests pass: `pytest tests/ -v` (requires pytest installation)

#### Manual Verification:
- [ ] Review test coverage for authorizer Lambda
- [ ] Verify mock patterns match new architecture
- [ ] Confirm edge cases are tested (invalid token, inactive key, etc.)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 5: Deployment

### Overview
Deploy the infrastructure changes to AWS.

### Changes Required:

#### 1. Deploy Infrastructure
Run CDK deployment:

```bash
cd cdk
cdk deploy
```

### Success Criteria:

#### Automated Verification:
- [ ] CDK deployment succeeds: `cd cdk && cdk deploy`
- [ ] CloudFormation stack update completes successfully
- [ ] All Lambda functions are healthy

#### Manual Verification:
- [ ] Review CloudFormation changeset before applying
- [ ] Verify all new resources created (Authorizer Lambda, TokenAuthorizer)
- [ ] Check API Gateway configuration in AWS Console

**Implementation Note**: After deployment succeeds, proceed to Phase 6 for seeding and validation testing.

---

## Phase 6: Seeding and Validation Testing

### Overview
Seed test data and validate the authorizer works end-to-end with actual API Gateway.

### Changes Required:

#### 1. Seed Test Data
Ensure TenantApiKeys table has test data:

```bash
# Example using AWS CLI
aws dynamodb put-item \
  --table-name <PREFIX>-TenantApiKeys \
  --item '{
    "apiKey": {"S": "test_api_key_123"},
    "tenantId": {"S": "test_tenant"},
    "targetUrl": {"S": "https://webhook.site/your-unique-id"},
    "webhookSecret": {"S": "test_secret"},
    "isActive": {"BOOL": true}
  }'
```

#### 2. Run Integration Tests
Use curl or similar tools to test the live API.

### Success Criteria:

#### Automated Verification:
- [ ] API Gateway endpoint is accessible
- [ ] Health check passes (if implemented)

#### Manual Verification:
- [ ] Valid API key returns 201 Created
  ```bash
  curl -X POST https://hooks.vincentchan.cloud/v1/events \
    -H "Authorization: Bearer test_api_key_123" \
    -H "Content-Type: application/json" \
    -d '{"event_type": "test.event", "data": "foo"}'
  ```
- [ ] Invalid API key returns 401 Unauthorized
  ```bash
  curl -X POST https://hooks.vincentchan.cloud/v1/events \
    -H "Authorization: Bearer invalid_key" \
    -H "Content-Type: application/json" \
    -d '{"event_type": "test.event", "data": "foo"}'
  ```
- [ ] Missing auth header returns 401 Unauthorized
  ```bash
  curl -X POST https://hooks.vincentchan.cloud/v1/events \
    -H "Content-Type: application/json" \
    -d '{"event_type": "test.event", "data": "foo"}'
  ```
- [ ] Authorizer caching works (check CloudWatch logs - second request within 5 min doesn't invoke authorizer)
- [ ] DynamoDB read units decrease compared to before (check CloudWatch metrics)
- [ ] End-to-end flow works: ingest → SQS → worker → delivery (check webhook.site or target URL)
- [ ] No regressions in existing functionality

**Implementation Note**: This is the final phase. After all verification passes and manual testing confirms the system works correctly, the implementation is complete.

---

## Testing Strategy

### Unit Tests

**Authorizer Lambda**:
- Valid API key → Allow policy with context
- Invalid API key → Deny policy
- Inactive API key → Deny policy
- Missing Bearer prefix → Deny policy
- Missing token → Deny policy

**API Lambda Context Extraction**:
- Valid authorizer context → Correct tenant extraction
- Missing context → ValueError
- Boolean string conversion for isActive

### Integration Tests

**End-to-End**:
- Deploy to test/staging environment
- Use actual API Gateway + Authorizer
- Verify real-world behavior with valid/invalid tokens

### Manual Testing Steps

1. **Valid Authentication**: POST to /events with valid Bearer token → 201
2. **Invalid Authentication**: Test invalid key, missing Bearer, no header → 401
3. **Caching**: First request invokes authorizer, second (within 5 min) uses cache
4. **Performance**: Compare latency and DynamoDB metrics before/after

## Performance Considerations

- **Caching**: 5-minute TTL reduces DynamoDB reads by ~95% for repeated calls
- **Authorizer Lambda**: 256MB memory, 10s timeout (completes in <1s)
- **API Lambda**: Faster cold starts (removed auth dependency and DynamoDB lookup)

## Migration Notes

- **No Data Migration**: TenantApiKeys schema unchanged
- **No Client Changes**: Bearer token format unchanged
- **Rollback**: Revert CDK stack if issues arise

## References

- Research: [thoughts/shared/research/2025-11-22-auth-lambda-authorizer-separation.md](../research/2025-11-22-auth-lambda-authorizer-separation.md)
- Current auth: [src/api/auth.py](../../../src/api/auth.py)
- CDK stack: [cdk/stacks/webhook_delivery_stack.py](../../../cdk/stacks/webhook_delivery_stack.py)
