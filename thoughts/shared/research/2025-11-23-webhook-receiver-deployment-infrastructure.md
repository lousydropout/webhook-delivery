---
date: 2025-11-23T16:20:15-06:00
researcher: lousydropout
git_commit: c22a38e568678c9a40695abea3681b29f03164b5
branch: main
repository: zapier
topic: "Deploying tests/webhook_receiver.py as API Gateway + Lambda with DynamoDB webhook secrets"
tags: [research, codebase, webhook-receiver, api-gateway, lambda, dynamodb, cdk]
status: complete
last_updated: 2025-11-23
last_updated_by: lousydropout
---

# Research: Deploying tests/webhook_receiver.py as API Gateway + Lambda with DynamoDB webhook secrets

**Date**: 2025-11-23T16:20:15-06:00
**Researcher**: lousydropout
**Git Commit**: c22a38e568678c9a40695abea3681b29f03164b5
**Branch**: main
**Repository**: zapier

## Research Question
Since `tests/webhook_receiver.py` is meant to act as the mock mini-zapier, we should deploy this as well, maybe as APIGW (regional) + Lambda, read webhook_secret for each tenant via DynamoDB. Find all relevant files and line numbers.

## Summary
The codebase has a complete infrastructure pattern for deploying webhook receivers as API Gateway + Lambda with DynamoDB-stored webhook secrets. The current `tests/webhook_receiver.py` is a FastAPI application that validates Stripe-style HMAC signatures. The existing production infrastructure already implements this pattern with:
- Regional API Gateway REST API at `hooks.vincentchan.cloud`
- Lambda functions using FastAPI + Mangum adapter
- DynamoDB TenantApiKeys table storing webhook secrets per tenant
- CDK infrastructure-as-code for deployment
- HMAC-SHA256 signature generation and validation patterns

## Detailed Findings

### Current webhook_receiver.py Implementation
- **Location**: [tests/webhook_receiver.py](tests/webhook_receiver.py)
- **Type**: FastAPI application for testing webhook delivery
- **Features**:
  - Validates Stripe-style HMAC signatures (lines 22-42)
  - POST /webhook endpoint (lines 45-63)
  - GET /health endpoint (lines 66-69)
  - Hardcoded webhook secret: `whsec_test123` (line 19)
  - Runs on port 5000 with uvicorn (line 76)

### Existing API Gateway Infrastructure Pattern

#### CDK Stack Definition
- **Primary Stack**: [cdk/stacks/webhook_delivery_stack.py](cdk/stacks/webhook_delivery_stack.py)
  - RestApi definition (lines 296-309): Regional endpoint type
  - Custom domain configuration (lines 311-325): `hooks.vincentchan.cloud`
  - Resources and methods (lines 328-393): /v1/events, /v1/docs, /v1/redoc, /v1/openapi.json
  - Lambda integration pattern (lines 368-371)
  - Lambda authorizer (lines 284-290): REQUEST type with 5-minute cache TTL

#### Lambda Function Patterns
- **API Lambda with FastAPI + Mangum**: [src/api/main.py](src/api/main.py)
  - Mangum adapter for Lambda compatibility (line 17)
  - FastAPI app initialization (lines 7-15)
  - Handler export: `handler = Mangum(app)`

- **Lambda Authorizer**: [src/authorizer/handler.py](src/authorizer/handler.py)
  - Validates Bearer tokens (lines 73-75)
  - Returns webhook secret in context (lines 88-91)
  - IAM policy generation (lines 28-56)

### DynamoDB Webhook Secret Storage

#### Table Definition
- **Location**: [cdk/stacks/webhook_delivery_stack.py:67-77](cdk/stacks/webhook_delivery_stack.py#L67-L77)
- **Table Name**: `{PREFIX}-TenantApiKeys`
- **Schema**:
  ```
  apiKey (PK) → {
    tenantId: string,
    targetUrl: string,
    webhookSecret: string,
    isActive: boolean,
    createdAt: string,
    displayName: string
  }
  ```

#### Secret Generation Pattern
- **Location**: [scripts/seed_webhooks.py:20-23](scripts/seed_webhooks.py#L20-L23)
- **Format**: `whsec_{uuid.hex}` (32 character hex string)

#### Secret Retrieval Patterns

1. **In Lambda Authorizer**: [src/authorizer/handler.py:9-26](src/authorizer/handler.py#L9-L26)
   - Looks up by API key
   - Returns in authorizer context

2. **In Worker Lambda**: [src/worker/dynamo.py:16-24](src/worker/dynamo.py#L16-L24)
   - Scans by tenantId
   - Returns full tenant config with webhook secret

3. **In API Handler**: [src/api/auth.py:13-34](src/api/auth.py#L13-L34)
   - FastAPI dependency
   - Returns tenant with webhook secret

### HMAC Signature Implementation

#### Signature Generation
- **Location**: [src/worker/signatures.py:6-22](src/worker/signatures.py#L6-L22)
- **Algorithm**: HMAC-SHA256
- **Format**: `t={timestamp},v1={signature}`
- **Signed payload**: `{timestamp}.{payload}`

#### Signature Verification
- **Location**: [tests/webhook_receiver.py:22-42](tests/webhook_receiver.py#L22-L42)
- **Process**:
  1. Parse Stripe-Signature header
  2. Extract timestamp and signature
  3. Reconstruct signed payload
  4. Verify with HMAC
  5. Use constant-time comparison

### Webhook Delivery Pattern
- **Location**: [src/worker/delivery.py:7-39](src/worker/delivery.py#L7-L39)
- **Headers sent**:
  - `Content-Type: application/json`
  - `Stripe-Signature: {generated_signature}`
- **Error handling**: Timeout, connection errors, general exceptions

### Deployment Infrastructure

#### CDK Application
- **Entry point**: [cdk/app.py](cdk/app.py)
- **Configuration**: [cdk/.env](cdk/.env) - HOSTED_ZONE_ID, HOSTED_ZONE_URL, PREFIX
- **Stack name**: WebhookDeliveryStack

#### Deployment Script
- **Location**: [scripts/deploy.sh](scripts/deploy.sh)
- **Process**:
  1. Install CDK dependencies
  2. Bootstrap CDK
  3. Deploy stack
  4. Seed test tenants

#### Lambda Bundling Pattern
- **Example**: [cdk/stacks/webhook_delivery_stack.py:145-174](cdk/stacks/webhook_delivery_stack.py#L145-L174)
- **Runtime**: Python 3.12
- **Bundling**: Docker-based with requirements.txt
- **No Lambda layers used**

### To Deploy webhook_receiver.py as Lambda

Based on the existing patterns, deploying `tests/webhook_receiver.py` would require:

1. **Convert to Lambda Handler**:
   - Add Mangum adapter: `handler = Mangum(app)`
   - Remove uvicorn.run() block
   - Add requirements.txt with: fastapi, mangum, boto3

2. **Modify Secret Retrieval**:
   - Replace hardcoded `WEBHOOK_SECRET` with DynamoDB lookup
   - Add tenant identification (from path parameter or header)
   - Query TenantApiKeys table

3. **CDK Stack Addition** (add to webhook_delivery_stack.py):
   ```python
   # Around line 280, after DLQ processor
   receiver_lambda = lambda_.Function(
       self, f"{prefix}-WebhookReceiver",
       function_name=f"{prefix}-WebhookReceiver",
       runtime=lambda_.Runtime.PYTHON_3_12,
       handler="handler.handler",
       code=lambda_.Code.from_asset("../tests/webhook_receiver_lambda/"),
       timeout=Duration.seconds(30),
       memory_size=512,
       environment={
           "TENANT_API_KEYS_TABLE": tenant_api_keys_table.table_name,
       },
   )
   tenant_api_keys_table.grant_read_data(receiver_lambda)
   ```

4. **API Gateway Resource** (add after line 393):
   ```python
   # Webhook receiver endpoint (mock Zapier)
   receiver_resource = v1_resource.add_resource("receiver")
   tenant_resource = receiver_resource.add_resource("{tenantId}")
   webhook_resource = tenant_resource.add_resource("webhook")

   webhook_resource.add_method(
       "POST",
       apigateway.LambdaIntegration(receiver_lambda),
       authorization_type=apigateway.AuthorizationType.NONE,  # Public endpoint
   )
   ```

5. **Multi-tenant Support Options**:
   - **Path-based**: `/v1/receiver/{tenantId}/webhook`
   - **Header-based**: Custom header with tenant ID
   - **Subdomain-based**: `{tenantId}.hooks.vincentchan.cloud`

## Code References

### Key Implementation Files
- `tests/webhook_receiver.py:1-77` - Current webhook receiver implementation
- `cdk/stacks/webhook_delivery_stack.py:1-420` - Complete CDK infrastructure
- `src/api/main.py:1-17` - FastAPI + Mangum Lambda pattern
- `src/authorizer/handler.py:1-99` - Lambda authorizer with webhook secret
- `src/worker/signatures.py:1-22` - HMAC signature generation
- `src/worker/delivery.py:1-39` - Webhook delivery with signatures
- `scripts/seed_webhooks.py:1-74` - Tenant seeding with webhook secrets

### DynamoDB Operations
- `src/api/auth.py:13-34` - API key lookup
- `src/api/dynamo.py:11-27` - Event creation
- `src/worker/dynamo.py:10-44` - Event updates and tenant lookup

### Testing
- `tests/test_authorizer.py:1-96` - Authorizer tests with webhook secrets
- `tests/test_auth.py:1-75` - Authentication tests
- `tests/test_events.py:1-108` - Event API tests

## Architecture Documentation

### Current System Flow
1. Client sends request with Bearer token to API Gateway
2. Lambda Authorizer validates token against DynamoDB
3. Authorizer returns tenant context with webhook secret
4. API Lambda creates event in DynamoDB
5. Worker Lambda retrieves webhook secret from tenant config
6. Worker delivers webhook with HMAC signature to target URL
7. Target validates signature using shared webhook secret

### Deployment Pattern for webhook_receiver.py
1. Convert FastAPI app to Lambda function using Mangum
2. Add DynamoDB integration for dynamic webhook secret lookup
3. Deploy as new Lambda function via CDK
4. Add API Gateway resource for webhook receiver endpoint
5. Support multi-tenancy via path parameters or headers
6. Grant Lambda read access to TenantApiKeys table

### Existing Conventions
- Lambda naming: `{PREFIX}-FunctionPurpose`
- Table naming: `{PREFIX}-TableName`
- API resources under `/v1/` path
- Python 3.12 runtime standard
- Docker-based bundling for dependencies
- Regional API Gateway endpoints
- Custom domain with ACM certificates

## Related Research
- [2025-11-23-webhook-receiver-testing-workflow.md](thoughts/shared/research/2025-11-23-webhook-receiver-testing-workflow.md) - Testing workflow documentation
- [2025-11-22-auth-lambda-authorizer-separation.md](thoughts/shared/research/2025-11-22-auth-lambda-authorizer-separation.md) - Authorizer architecture
- [2025-11-23-demo-receiver-deployment.md](thoughts/shared/plans/2025-11-23-demo-receiver-deployment.md) - Demo deployment plan

## Open Questions
1. Should the webhook receiver Lambda support multiple webhook secrets per tenant?
2. Should webhook signature validation be optional for testing environments?
3. Should the receiver endpoint require authentication or remain public?
4. What logging/monitoring should be added for the receiver Lambda?
5. Should received webhooks be stored in DynamoDB for debugging?