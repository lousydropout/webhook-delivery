---
date: 2025-11-22T21:28:47+0000
researcher: Claude Code
git_commit: 8e340353b4f7cadbc29e7a8fe314bdcaa32acd4b
branch: main
repository: zapier
topic: "Lambda Authorizer Separation Implementation"
tags: [implementation, lambda-authorizer, api-gateway, authentication, security]
status: in_progress
last_updated: 2025-11-22
last_updated_by: Claude Code
type: implementation_strategy
---

# Handoff: Lambda Authorizer Separation Implementation

## Task(s)

**Main Task:** Separate authentication logic from the API Lambda into a dedicated Lambda authorizer that runs at the API Gateway level.

**Status by Phase:**
1. ✅ **Phase 1: Create Authorizer Lambda** - COMPLETED
   - Created authorizer Lambda with Bearer token validation
   - DynamoDB lookup for tenant API keys
   - IAM policy generation with tenant context

2. ✅ **Phase 2: Update CDK Infrastructure** - COMPLETED
   - Added Authorizer Lambda to CDK stack
   - Created TokenAuthorizer with 5-minute cache
   - Configured API Gateway with custom authorizer
   - Added API versioning at Gateway level (`/v1` prefix)

3. ✅ **Phase 3: Modify API Lambda to Use Authorizer Context** - COMPLETED
   - Created context extraction utility
   - Updated routes to extract tenant from authorizer context
   - Removed FastAPI dependency injection for auth

4. ✅ **Phase 4: Update Tests** - COMPLETED
   - Created authorizer Lambda unit tests
   - Updated API Lambda tests for new auth pattern
   - Tests use mocked authorizer context

5. ⏳ **Phase 5: Deployment** - PENDING
   - CDK deployment to AWS
   - CloudFormation verification
   - Lambda health checks

6. ⏳ **Phase 6: Seeding and Validation Testing** - PENDING
   - Seed test data into DynamoDB
   - Integration testing with curl
   - Validate caching behavior
   - End-to-end flow verification

**Working From:** `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md`

## Critical References

1. **Implementation Plan:** `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md`
2. **Research Document:** `thoughts/shared/research/2025-11-22-auth-lambda-authorizer-separation.md` (referenced in plan)
3. **Current CDK Stack:** `cdk/stacks/webhook_delivery_stack.py`

## Recent Changes

**New Files Created:**
- `src/authorizer/handler.py` - Lambda authorizer implementation
- `src/authorizer/__init__.py` - Python module marker
- `src/authorizer/requirements.txt` - Dependencies (boto3)
- `src/api/context.py` - Tenant context extraction utility
- `tests/test_authorizer.py` - Authorizer unit tests

**Modified Files:**
- `src/api/routes.py:1-56` - Replaced `Depends(verify_api_key)` with context extraction
- `cdk/stacks/webhook_delivery_stack.py:176-205` - Added Authorizer Lambda
- `cdk/stacks/webhook_delivery_stack.py:250-259` - Added TokenAuthorizer construct
- `cdk/stacks/webhook_delivery_stack.py:276-279` - Added `default_method_options` with authorizer
- `cdk/stacks/webhook_delivery_stack.py:333-338` - Changed base path to `v1` for API versioning
- `tests/test_events.py:1-102` - Rewrote tests for new auth pattern

## Learnings

### Architecture Decisions

1. **API Gateway-level versioning chosen over FastAPI routing**
   - User preference: Version at API Gateway level (`/v1` base path)
   - Rationale: Allows future v2 with separate Lambda without touching v1 code
   - Implementation: `custom_domain.add_base_path_mapping(self.api, base_path="v1")`
   - Lambda code stays clean: routes use `/events`, Gateway adds `/v1`

2. **Worker Lambda still needs TenantApiKeys table access**
   - Worker calls `get_tenant_by_id()` to retrieve `webhookSecret` for signing
   - This is NOT authentication - it's configuration data retrieval
   - Grant remains: `self.tenant_api_keys_table.grant_read_data(self.worker_lambda)` at `cdk/stacks/webhook_delivery_stack.py:238`

3. **Authorizer context string conversion**
   - API Gateway requires all context values as strings
   - Authorizer converts: `"isActive": tenant["isActive"]` → `"isActive": "True"`
   - API Lambda reconverts: `authorizer["isActive"] == "True"` → boolean
   - Implementation at `src/api/context.py:26`

### Current API Structure

- **Lambda endpoint:** `POST /events` (no version prefix in code)
- **Public endpoint:** `POST https://hooks.vincentchan.cloud/v1/events`
- **Authentication:** Bearer token in `Authorization` header
- **Flow:** API Gateway → TokenAuthorizer → API Lambda (with pre-validated context)

### Testing Patterns

- Old tests in `tests/test_events.py` were for outdated API structure
- Old tests expected `/v1/events` at FastAPI level and had many non-existent endpoints
- Current implementation only has `POST /events` endpoint
- Tests now mock `get_tenant_from_context()` instead of FastAPI dependency injection
- Authorizer tests mock DynamoDB directly via `handler.api_keys_table`

## Artifacts

**Implementation Files:**
- `src/authorizer/handler.py` - Authorizer Lambda handler
- `src/authorizer/requirements.txt` - Authorizer dependencies
- `src/authorizer/__init__.py` - Python module marker
- `src/api/context.py` - Context extraction utility
- `src/api/routes.py` - Updated with authorizer context pattern
- `cdk/stacks/webhook_delivery_stack.py` - CDK stack with authorizer

**Test Files:**
- `tests/test_authorizer.py` - Authorizer unit tests (5 test cases)
- `tests/test_events.py` - API Lambda tests (3 test cases)

**Documentation:**
- `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md` - Implementation plan with checkmarks updated through Phase 4

## Action Items & Next Steps

### Immediate Next Steps (Phase 5: Deployment)

1. **Review CDK changes before deployment**
   - Verify syntax: `cd cdk && python3 -m py_compile stacks/webhook_delivery_stack.py` ✅ (already passed)
   - Review changeset: `cd cdk && cdk diff` (requires AWS credentials)
   - Deploy: `cd cdk && cdk deploy`

2. **Verify deployment succeeded**
   - Check CloudFormation stack status
   - Verify Authorizer Lambda created: `{PREFIX}-Authorizer`
   - Verify TokenAuthorizer attached to API Gateway
   - Check all Lambda functions are healthy

3. **Review AWS Console**
   - API Gateway: Verify authorizer configuration and cache TTL (5 minutes)
   - Lambda: Check both API Lambda and Authorizer Lambda exist
   - IAM: Verify permissions (authorizer can read TenantApiKeys)

### Subsequent Steps (Phase 6: Seeding and Validation)

4. **Seed test data into DynamoDB**
   ```bash
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

5. **Run integration tests** (detailed curl commands in plan Phase 6)
   - Valid token → 201 Created
   - Invalid token → 401 Unauthorized
   - Missing Authorization header → 401 Unauthorized
   - Verify authorizer caching (CloudWatch logs)
   - Check end-to-end: ingest → SQS → worker → delivery

6. **Monitor metrics**
   - DynamoDB read units should decrease (caching effect)
   - CloudWatch logs: Second request within 5 min shouldn't invoke authorizer
   - Verify no regressions in existing functionality

## Other Notes

### Key File Locations

**Authentication & Authorization:**
- Old auth (being replaced): `src/api/auth.py:37-47` - FastAPI dependency injection
- New authorizer: `src/authorizer/handler.py:86-177`
- Context extraction: `src/api/context.py:7-28`
- Route integration: `src/api/routes.py:17-31`

**CDK Infrastructure:**
- Authorizer Lambda: `cdk/stacks/webhook_delivery_stack.py:180-205`
- TokenAuthorizer: `cdk/stacks/webhook_delivery_stack.py:253-259`
- API Gateway config: `cdk/stacks/webhook_delivery_stack.py:264-322`
- API versioning: `cdk/stacks/webhook_delivery_stack.py:333-338`

**Database Schema:**
- TenantApiKeys table: `cdk/stacks/webhook_delivery_stack.py:67-78`
- Schema: `apiKey` (PK) → `{tenantId, targetUrl, webhookSecret, isActive}`

**Worker Lambda (unchanged):**
- Handler: `src/worker/handler.py` - Still uses TenantApiKeys for webhook signing
- DynamoDB access: `src/worker/dynamo.py:16-23` - `get_tenant_by_id()` function

### Important Constraints

**What We're NOT Doing:**
- NOT changing Worker Lambda authentication (no internet-facing security concern)
- NOT modifying TenantApiKeys table schema
- NOT changing Bearer token format or client integration
- NOT switching away from `LambdaRestApi` construct
- NOT implementing additional authorization logic beyond API key validation

### Performance Benefits

- **Caching:** 5-minute TTL reduces DynamoDB reads by ~95% for repeated calls
- **Faster cold starts:** API Lambda no longer has auth dependency/DynamoDB lookup
- **Authorizer specs:** 256MB memory, 10s timeout (completes in <1s typically)

### Rollback Plan

If issues arise post-deployment:
- Revert CDK stack to previous commit
- No data migration needed (schema unchanged)
- No client changes needed (Bearer token format unchanged)
