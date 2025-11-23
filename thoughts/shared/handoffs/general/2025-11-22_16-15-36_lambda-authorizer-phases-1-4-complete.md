---
date: 2025-11-22T16:15:36-06:00
researcher: Claude Code
git_commit: 79b888d1b5c2ce1273932fba232ce56e28919653
branch: main
repository: zapier
topic: "Lambda Authorizer Separation - Phases 1-4 Complete"
tags: [implementation, lambda-authorizer, api-gateway, authentication, security, deployment-ready]
status: complete
last_updated: 2025-11-22
last_updated_by: Claude Code
type: implementation_strategy
---

# Handoff: Lambda Authorizer Separation - Phases 1-4 Complete

## Task(s)

**Main Task:** Separate authentication logic from the API Lambda into a dedicated Lambda authorizer that runs at the API Gateway level.

**Working From:** `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md`

**Status by Phase:**
1. ✅ **Phase 1: Create Authorizer Lambda** - COMPLETED
2. ✅ **Phase 2: Update CDK Infrastructure** - COMPLETED
3. ✅ **Phase 3: Modify API Lambda to Use Authorizer Context** - COMPLETED
4. ✅ **Phase 4: Update Tests** - COMPLETED
5. ⏳ **Phase 5: Deployment** - READY (not yet deployed)
6. ⏳ **Phase 6: Seeding and Validation Testing** - PENDING (awaits Phase 5)

**Current State:** All code implementation and tests are complete. Changes are uncommitted and ready for deployment. Previous handoff (`thoughts/shared/handoffs/general/2025-11-22_15-28-47_lambda-authorizer-separation.md`) documented the in-progress implementation; this handoff documents completion of Phases 1-4.

## Critical References

1. **Implementation Plan:** `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md`
2. **Research Document:** `thoughts/shared/research/2025-11-22-auth-lambda-authorizer-separation.md`
3. **CDK Stack:** `cdk/stacks/webhook_delivery_stack.py`

## Recent Changes

**New Files Created:**
- `src/authorizer/handler.py` - Lambda authorizer implementation with Bearer token validation
- `src/authorizer/__init__.py` - Python module marker
- `src/authorizer/requirements.txt` - Dependencies (boto3)
- `src/api/context.py` - Tenant context extraction utility for API Lambda
- `tests/test_authorizer.py` - Authorizer unit tests (5 test cases)

**Modified Files:**
- `src/api/routes.py:17-31` - Replaced `Depends(verify_api_key)` with `get_tenant_from_context()`
- `cdk/stacks/webhook_delivery_stack.py:176-205` - Added Authorizer Lambda function
- `cdk/stacks/webhook_delivery_stack.py:282-290` - Added TokenAuthorizer construct with 5-min cache
- `cdk/stacks/webhook_delivery_stack.py:307-310` - Added `default_method_options` with custom authorizer
- `cdk/stacks/webhook_delivery_stack.py:333-338` - API versioning at Gateway level (`/v1` base path)
- `tests/test_events.py:1-102` - Rewrote tests for authorizer context pattern

**Uncommitted Changes:** All implementation files are ready but not committed to git.

## Learnings

### Architecture Decisions

1. **API Gateway-level versioning** (`cdk/stacks/webhook_delivery_stack.py:333-338`)
   - User preference: Version at API Gateway level using `/v1` base path
   - Rationale: Allows future v2 with separate Lambda without touching v1 code
   - Implementation: `custom_domain.add_base_path_mapping(self.api, base_path="v1")`
   - Lambda routes stay clean: `POST /events`, Gateway adds `/v1` prefix

2. **Worker Lambda still needs TenantApiKeys access** (`cdk/stacks/webhook_delivery_stack.py:238`)
   - Worker calls `get_tenant_by_id()` to retrieve `webhookSecret` for HMAC signing
   - This is configuration data retrieval, NOT authentication
   - Grant remains: `self.tenant_api_keys_table.grant_read_data(self.worker_lambda)`

3. **Authorizer context requires string conversion**
   - API Gateway requires all authorizer context values as strings
   - Authorizer converts: `"isActive": tenant["isActive"]` → `"isActive": "True"` (string)
   - API Lambda reconverts: `authorizer["isActive"] == "True"` → boolean (`src/api/context.py:29`)

### Implementation Patterns

4. **FastAPI dependency injection replaced with context extraction**
   - Old: `tenant: Dict = Depends(verify_api_key)` in route parameters
   - New: `event = request.scope.get("aws.event", {})` + `get_tenant_from_context(event)`
   - Tenant context pre-validated by authorizer, no DynamoDB lookup in API Lambda

5. **Testing pattern changed**
   - Old: `app.dependency_overrides[verify_api_key]` to mock FastAPI dependencies
   - New: Mock `get_tenant_from_context()` directly
   - Authorizer tests mock DynamoDB via `handler.api_keys_table`

### API Structure

6. **Current endpoint structure:**
   - Lambda endpoint: `POST /events` (no version prefix in code)
   - Public endpoint: `POST https://hooks.vincentchan.cloud/v1/events`
   - Authentication: Bearer token in `Authorization` header
   - Flow: Client → API Gateway → TokenAuthorizer (cached) → API Lambda (with context)

## Artifacts

**Implementation Files:**
- `src/authorizer/handler.py` - Authorizer Lambda handler
- `src/authorizer/requirements.txt` - Authorizer dependencies (boto3)
- `src/authorizer/__init__.py` - Python module marker
- `src/api/context.py` - Context extraction utility
- `src/api/routes.py` - Updated API routes with authorizer context pattern
- `cdk/stacks/webhook_delivery_stack.py` - CDK stack with authorizer infrastructure

**Test Files:**
- `tests/test_authorizer.py` - Authorizer unit tests covering:
  - Valid API key → Allow policy with context
  - Invalid API key → Deny policy
  - Inactive API key → Deny policy
  - Missing Bearer prefix → Deny policy
  - Missing token → Deny policy
- `tests/test_events.py` - API Lambda tests with mocked authorizer context

**Documentation:**
- `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md` - Implementation plan (checkmarks updated through Phase 4)
- `thoughts/shared/research/2025-11-22-auth-lambda-authorizer-separation.md` - Research on current auth implementation

## Action Items & Next Steps

### Immediate: Commit Implemented Changes

**Before deployment**, commit the completed Phases 1-4 implementation:

```bash
git add src/authorizer/ src/api/context.py tests/test_authorizer.py
git add src/api/routes.py tests/test_events.py cdk/stacks/webhook_delivery_stack.py
git commit -m "Implement Lambda Authorizer separation (Phases 1-4)

- Add dedicated Authorizer Lambda with Bearer token validation
- Update CDK stack with TokenAuthorizer and 5-min caching
- Modify API Lambda to extract tenant from authorizer context
- Update all tests for new authentication pattern
- Add API versioning at Gateway level (/v1 base path)

Phases 1-4 complete. Ready for deployment (Phase 5)."
```

### Phase 5: Deployment

1. **Review CDK changes:**
   ```bash
   cd cdk
   cdk diff
   ```
   - Verify new resources: Authorizer Lambda, TokenAuthorizer
   - Check IAM permissions and API Gateway configuration
   - Confirm no unexpected changes

2. **Deploy to AWS:**
   ```bash
   cd cdk
   cdk deploy
   ```

3. **Verify deployment:**
   - Check CloudFormation stack status (should show UPDATE_COMPLETE)
   - Verify Authorizer Lambda created: `{PREFIX}-Authorizer`
   - Confirm TokenAuthorizer attached to API Gateway
   - Check all Lambda functions are healthy in AWS Console

4. **Review AWS Console:**
   - **API Gateway:** Verify authorizer configuration, cache TTL = 5 minutes
   - **Lambda:** Confirm both API Lambda and Authorizer Lambda exist and are healthy
   - **IAM:** Verify authorizer has read access to TenantApiKeys table

### Phase 6: Seeding and Validation Testing

5. **Seed test data into DynamoDB:**
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

6. **Run integration tests with curl:**
   - **Valid token → 201 Created:**
     ```bash
     curl -X POST https://hooks.vincentchan.cloud/v1/events \
       -H "Authorization: Bearer test_api_key_123" \
       -H "Content-Type: application/json" \
       -d '{"event_type": "test.event", "data": "foo"}'
     ```
   - **Invalid token → 401 Unauthorized:**
     ```bash
     curl -X POST https://hooks.vincentchan.cloud/v1/events \
       -H "Authorization: Bearer invalid_key" \
       -H "Content-Type: application/json" \
       -d '{"event_type": "test.event", "data": "foo"}'
     ```
   - **Missing header → 401 Unauthorized:**
     ```bash
     curl -X POST https://hooks.vincentchan.cloud/v1/events \
       -H "Content-Type: application/json" \
       -d '{"event_type": "test.event", "data": "foo"}'
     ```

7. **Validate caching behavior:**
   - Check CloudWatch logs for Authorizer Lambda
   - First request should invoke authorizer
   - Second request within 5 minutes should use cached result (no authorizer invocation)
   - Verify DynamoDB read units decrease (caching effect)

8. **Verify end-to-end flow:**
   - Ingest event → SQS → Worker → Delivery to webhook.site
   - Check webhook delivery includes proper HMAC signature
   - Confirm no regressions in existing functionality

## Other Notes

### Key File Locations

**Authentication & Authorization:**
- **Authorizer Lambda:** `src/authorizer/handler.py:59-99` - Main handler function
- **Context extraction:** `src/api/context.py:4-30` - Tenant extraction from authorizer context
- **Route integration:** `src/api/routes.py:17-31` - Updated `/events` endpoint
- **Old auth (deprecated):** `src/api/auth.py:37-47` - FastAPI dependency (no longer used)

**CDK Infrastructure:**
- **Authorizer Lambda definition:** `cdk/stacks/webhook_delivery_stack.py:180-205`
- **TokenAuthorizer construct:** `cdk/stacks/webhook_delivery_stack.py:282-290`
- **API Gateway config:** `cdk/stacks/webhook_delivery_stack.py:295-322`
- **API versioning:** `cdk/stacks/webhook_delivery_stack.py:333-338`
- **TenantApiKeys table:** `cdk/stacks/webhook_delivery_stack.py:67-78`

**Database Schema:**
- Schema: `apiKey` (PK) → `{tenantId, targetUrl, webhookSecret, isActive}`
- No schema changes required for this implementation

**Worker Lambda (unchanged):**
- Handler: `src/worker/handler.py` - Still uses TenantApiKeys for webhook signing
- Tenant lookup: `src/worker/dynamo.py:16-23` - `get_tenant_by_id()` function

### Important Constraints

**What We're NOT Doing:**
- NOT changing Worker Lambda authentication (no internet-facing security concern)
- NOT modifying TenantApiKeys table schema
- NOT changing Bearer token format or client integration
- NOT switching away from `LambdaRestApi` construct
- NOT implementing additional authorization logic beyond API key validation

### Expected Performance Benefits

- **Caching:** 5-minute TTL reduces DynamoDB reads by ~95% for repeated calls
- **Faster cold starts:** API Lambda no longer has auth dependency/DynamoDB lookup
- **Authorizer specs:** 256MB memory, 10s timeout (typically completes in <1s)

### Rollback Plan

If issues arise post-deployment:
- Revert CDK stack: `git revert <commit-hash> && cd cdk && cdk deploy`
- No data migration needed (TenantApiKeys schema unchanged)
- No client changes needed (Bearer token format unchanged)
- Authorizer can be removed without affecting existing data

### Git Status at Handoff

```
Changes not staged for commit:
  modified:   cdk/stacks/webhook_delivery_stack.py
  modified:   src/api/routes.py
  modified:   tests/test_events.py

Untracked files:
  src/api/context.py
  src/authorizer/
  tests/test_authorizer.py
```

**Next session should:** Commit these changes before deployment.
