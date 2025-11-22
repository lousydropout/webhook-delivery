---
date: 2025-11-22T13:26:11-0600
researcher: lousydropout
git_commit: 8e340353b4f7cadbc29e7a8fe314bdcaa32acd4b
branch: main
repository: zapier
topic: "Separating current authentication into a separate Lambda as custom authorizer"
tags: [research, codebase, authentication, api-gateway, lambda-authorizer, fastapi, bearer-token]
status: complete
last_updated: 2025-11-22
last_updated_by: lousydropout
---

# Research: Separating Current Authentication into a Separate Lambda as Custom Authorizer

**Date**: 2025-11-22T13:26:11-0600
**Researcher**: lousydropout
**Git Commit**: 8e340353b4f7cadbc29e7a8fe314bdcaa32acd4b
**Branch**: main
**Repository**: zapier

## Research Question
Separate out the current auth into a separate lambda as the custom authorizer. Review codebase for file+line numbers relevant to the topic.

## Summary
The webhook delivery system currently implements authentication within the API Lambda using FastAPI's dependency injection system with Bearer token validation against a DynamoDB table. The authentication logic resides in `src/api/auth.py:37-47` and is injected into routes via `Depends(verify_api_key)` in `src/api/routes.py:18`. The system uses API Gateway with Lambda proxy integration (`cdk/stacks/webhook_delivery_stack.py:253-276`) where all authentication happens inside the Lambda function rather than at the API Gateway level. No custom authorizers are currently configured in the infrastructure.

## Detailed Findings

### Current Authentication Implementation

#### Core Authentication Module
The authentication logic is implemented in [`src/api/auth.py`](src/api/auth.py):

**Bearer Token Extraction** (Lines 7, 37-38):
- Uses FastAPI's `HTTPBearer` security scheme
- Automatically extracts and validates Bearer token format from Authorization header
- Token extraction happens via `Security(security)` dependency

**API Key Validation** (Lines 13-34):
- Function `get_tenant_from_api_key()` performs DynamoDB lookup
- Queries `TenantApiKeys` table using API key as partition key (Line 25)
- Returns tenant configuration including `tenantId`, `targetUrl`, `webhookSecret`, and `isActive` status
- Validates both existence and `isActive` flag (Line 28)

**FastAPI Dependency** (Lines 37-47):
- `verify_api_key()` function serves as FastAPI dependency
- Raises `HTTPException(401)` for invalid keys (Line 45)
- Returns tenant dictionary for injection into route handlers

#### Route Integration
Authentication is integrated at the route level in [`src/api/routes.py`](src/api/routes.py):

**Dependency Injection** (Line 18):
```python
async def ingest_event(payload: Dict[str, Any], tenant: Dict = Depends(verify_api_key)):
```
- Uses `Depends(verify_api_key)` pattern
- Tenant context automatically injected into route handler
- Authentication occurs before route logic executes

**Tenant Data Usage** (Lines 22-23):
- Extracts `tenantId` and `targetUrl` from authenticated tenant
- Passes tenant context to downstream operations

#### FastAPI Application Setup
The main application entry point is in [`src/api/main.py`](src/api/main.py):

**Mangum Handler** (Line 14):
- Wraps FastAPI app with Mangum for Lambda compatibility
- Converts Lambda proxy events to ASGI format

**Router Inclusion** (Line 11):
- Includes authenticated routes from `routes.py`
- No global authentication middleware configured

### Infrastructure Configuration

#### API Gateway Setup
The API Gateway configuration is in [`cdk/stacks/webhook_delivery_stack.py`](cdk/stacks/webhook_delivery_stack.py):

**LambdaRestApi Configuration** (Lines 253-276):
- Uses `LambdaRestApi` construct with `proxy=True` (Line 257)
- All requests forwarded to Lambda for processing
- No custom authorizers configured
- CORS allows `Authorization` header (Line 270)

**API Lambda Definition** (Lines 145-174):
- Handler: `main.handler` (Line 150)
- Runtime: Python 3.12
- Environment variables include `TENANT_API_KEYS_TABLE` (Line 166)
- IAM permissions grant read access to TenantApiKeys table (Line 172)

#### DynamoDB Tables

**TenantApiKeys Table** (Lines 67-78):
- Table name: `{PREFIX}-TenantApiKeys`
- Partition key: `apiKey` (STRING)
- Stores: API key → tenant configuration mapping
- Pay-per-request billing mode

**Events Table** (Lines 86-102):
- Stores webhook events with tenant context
- Partition key: `tenantId`, Sort key: `eventId`

### Authentication Flow

1. **Request Arrival**: Client sends request with `Authorization: Bearer <api-key>` header
2. **API Gateway**: Forwards entire request to Lambda via proxy integration
3. **Lambda Invocation**: Mangum converts Lambda event to ASGI
4. **FastAPI Routing**: Matches `/events` endpoint with `Depends(verify_api_key)`
5. **Token Extraction**: `Security(security)` extracts Bearer token
6. **DynamoDB Lookup**: Queries TenantApiKeys table by API key
7. **Validation**: Checks existence and `isActive` status
8. **Injection**: Returns tenant dict or raises 401 error
9. **Route Execution**: Handler receives authenticated tenant context

### Dependencies and Connections

#### API Lambda Dependencies
Located in [`src/api/requirements.txt`](src/api/requirements.txt):
- `fastapi==0.104.1` - Web framework with dependency injection
- `mangum==0.17.0` - Lambda adapter for ASGI
- `boto3==1.34.0` - AWS SDK for DynamoDB access
- `pydantic==2.5.0` - Data validation

#### Worker Lambda Access to Tenant Data
The Worker Lambda also accesses tenant data for webhook delivery:

**Tenant Lookup by ID** ([`src/worker/dynamo.py:16-23`](src/worker/dynamo.py#L16-L23)):
- Scans TenantApiKeys table filtering by `tenantId`
- Retrieves `webhookSecret` for HMAC signing
- Uses same table but different access pattern than API Lambda

**Webhook Signature Generation** ([`src/worker/signatures.py:6-22`](src/worker/signatures.py#L6-L22)):
- Generates Stripe-style HMAC-SHA256 signatures
- Uses `webhookSecret` from tenant configuration
- Format: `t={timestamp},v1={signature}`

### Test Patterns

**Mocking Authentication** ([`tests/test_events.py:8-18`](tests/test_events.py#L8-L18)):
- Uses `app.dependency_overrides` to replace `verify_api_key`
- Mock returns simplified tenant data for testing
- Fixture pattern for setup/teardown

**DynamoDB Mocking** ([`tests/test_auth.py:7-65`](tests/test_auth.py#L7-L65)):
- Uses `@patch` decorator to mock table operations
- Tests success, not found, revoked, and exception cases

## Code References

### Authentication Core
- `src/api/auth.py:7` - HTTPBearer security scheme initialization
- `src/api/auth.py:10` - DynamoDB table reference from environment
- `src/api/auth.py:13-34` - API key lookup function
- `src/api/auth.py:37-47` - FastAPI dependency for API key verification

### Route Integration
- `src/api/routes.py:7` - Import of verify_api_key
- `src/api/routes.py:18` - Dependency injection in route handler
- `src/api/routes.py:22-23` - Tenant data extraction

### Infrastructure
- `cdk/stacks/webhook_delivery_stack.py:67-78` - TenantApiKeys table definition
- `cdk/stacks/webhook_delivery_stack.py:145-174` - API Lambda configuration
- `cdk/stacks/webhook_delivery_stack.py:172` - IAM permission for table read
- `cdk/stacks/webhook_delivery_stack.py:253-276` - API Gateway configuration
- `cdk/stacks/webhook_delivery_stack.py:257` - Lambda proxy integration setting
- `cdk/stacks/webhook_delivery_stack.py:270` - CORS Authorization header

### Application Entry
- `src/api/main.py:11` - Router inclusion
- `src/api/main.py:14` - Mangum handler for Lambda

### Worker Lambda
- `src/worker/handler.py:31-36` - Tenant retrieval for webhook secret
- `src/worker/dynamo.py:16-23` - Tenant lookup by ID
- `src/worker/signatures.py:6-22` - HMAC signature generation
- `src/worker/delivery.py:20` - Signature header attachment

### Testing
- `tests/test_auth.py:7-65` - Authentication unit tests
- `tests/test_events.py:8-18` - Dependency override pattern

## Architecture Documentation

### Current Authentication Pattern
The system implements **in-Lambda authentication** using FastAPI's dependency injection:

1. **No API Gateway authorizer** - Authentication happens inside Lambda
2. **Bearer token pattern** - Standard Authorization header with Bearer scheme
3. **DynamoDB-backed** - API keys stored in dedicated table
4. **Dependency injection** - Authentication injected per-route, not globally
5. **Tenant isolation** - Each API key maps to a single tenant with specific configuration

### Data Flow
```
Client → API Gateway (proxy) → Lambda → FastAPI → Auth Dependency → DynamoDB → Route Handler
```

### Key Components for Separation
To separate authentication into a custom Lambda authorizer, the following components would need modification:

1. **New Lambda Function**: Custom authorizer implementation
   - Would need to extract and validate Bearer token
   - Query same TenantApiKeys DynamoDB table
   - Return IAM policy and context (tenantId, targetUrl, etc.)

2. **API Gateway Changes** (`cdk/stacks/webhook_delivery_stack.py`):
   - Add authorizer configuration to API Gateway
   - Switch from `LambdaRestApi` to manual API Gateway setup
   - Configure authorizer caching

3. **API Lambda Modifications**:
   - Remove `auth.py` module or repurpose for context extraction
   - Modify `routes.py` to get tenant from Lambda event context
   - Remove `verify_api_key` dependency from routes

4. **Shared Table Access**:
   - Custom authorizer Lambda needs read access to TenantApiKeys table
   - Same DynamoDB table, different Lambda function

## Related Research
- Authentication flow documentation in `README.md:73-101`
- API endpoints documentation in `endpoints.md:18-47`
- Phase 3 authentication implementation notes in `thoughts/shared/handoffs/general/2025-11-21_08-44-25_phase-3-authentication-complete.md`

## Open Questions
1. How would tenant context be passed from custom authorizer to API Lambda?
2. Would the custom authorizer cache API key lookups for performance?
3. Should the Worker Lambda authentication pattern change to match?
4. How would local testing work with a custom authorizer?