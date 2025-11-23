---
date: 2025-11-22T17:57:54-06:00
researcher: Claude Code
git_commit: 964295ccb9ad3fea666d03647e40234b5c1dfad8
branch: main
repository: zapier
topic: "Custom Domain /v1 Path Routing Issue Investigation"
tags: [investigation, api-gateway, custom-domain, edge-endpoint, regional-endpoint, base-path-mapping]
status: complete
last_updated: 2025-11-22
last_updated_by: Claude Code
type: investigation_and_planning
---

# Handoff: Custom Domain /v1 Path Routing Issue

## Task(s)

**Main Task:** Investigate and resolve custom domain `/v1` path routing issue discovered during Phase 6 integration testing.

**Status:**
- ✅ **Phase 5 (Deployment):** COMPLETED - Lambda Authorizer successfully deployed
- ✅ **Phase 6 (Integration Testing):** PARTIALLY COMPLETED - Direct API Gateway URL works, custom domain fails
- ✅ **Investigation:** COMPLETED - Root cause identified
- ✅ **Solution Planning:** COMPLETED - Migration plan created
- ⏳ **Implementation:** READY (awaiting user approval)

**Working From:**
- Previous implementation: `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md` (Phases 1-4 complete)
- Previous handoff: `thoughts/shared/handoffs/general/2025-11-22_16-15-36_lambda-authorizer-phases-1-4-complete.md`

## Critical References

1. **Investigation & Solution Plan:** `thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md`
2. **Original Implementation Plan:** `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md`
3. **CDK Stack Configuration:** `cdk/stacks/webhook_delivery_stack.py:325-349`

## Recent Changes

**No code changes in this session** - Investigation and planning only.

**Previous session changes (commit 964295c):**
- `src/authorizer/handler.py` - Lambda authorizer implementation (NEW)
- `src/api/context.py` - Tenant context extraction utility (NEW)
- `src/api/routes.py:17-31` - Updated with authorizer context pattern
- `cdk/stacks/webhook_delivery_stack.py:176-205` - Authorizer Lambda
- `cdk/stacks/webhook_delivery_stack.py:282-290` - TokenAuthorizer construct
- `cdk/stacks/webhook_delivery_stack.py:307-310` - Custom authorizer on methods
- `cdk/stacks/webhook_delivery_stack.py:330` - **EDGE endpoint** (issue source)
- `cdk/stacks/webhook_delivery_stack.py:336` - Base path mapping `"v1"`
- `tests/test_authorizer.py` - Authorizer unit tests (NEW)
- `tests/test_events.py` - Updated API tests

## Learnings

### Problem Discovery

1. **Phase 6 Integration Testing Results:**
   - ✅ Direct API Gateway URL works: `https://1ptya5rgn5.execute-api.us-east-1.amazonaws.com/prod/events`
   - ❌ Custom domain URL fails: `https://hooks.vincentchan.cloud/v1/events` → 404
   - All core functionality verified via direct URL (authorizer, caching, DynamoDB)

2. **Root Cause Analysis:**
   - **Problem:** Base path mapping not stripping `/v1` prefix on EDGE endpoint
   - **Evidence:**
     - Request to `https://hooks.vincentchan.cloud/v1/events` returns FastAPI 404
     - Direct test of `/v1/events` on API Gateway also returns 404
     - FastAPI route is `/events` (not `/v1/events`)
     - This proves Lambda receives `/v1/events` instead of `/events`
   - **Contributing Factor:** EDGE endpoints use CloudFront, which adds caching complexity

3. **Base Path Mapping Behavior:**
   - According to [AWS docs](https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-mappings.html), base path should be stripped
   - Expected: Request to `domain/v1/events` → API receives `/events`
   - Actual: Request to `domain/v1/events` → API receives `/v1/events` (NOT stripped)
   - EDGE endpoint behavior differs from documented REGIONAL behavior

4. **Current Infrastructure:**
   - Custom domain: EDGE type with CloudFront (`dl595id3fbzt6.cloudfront.net`)
   - Base path mapping: `v1` → `prod` stage
   - Routing mode: `BASE_PATH_MAPPING_ONLY`
   - API Gateway: `/{proxy+}` resource with Lambda proxy integration

### Technical Investigation Details

5. **Testing Performed:**
   ```
   ✅ Valid Bearer token → 201 Created (direct URL)
   ✅ Invalid Bearer token → 403 Forbidden (direct URL)
   ✅ Missing auth header → 401 Unauthorized (direct URL)
   ✅ Authorizer caching works (5-min TTL verified in logs)
   ✅ DynamoDB events stored (3 events confirmed)
   ❌ Custom domain /v1/events → 404
   ❌ Custom domain /events → 403 (no base path mapping)
   ```

6. **CloudWatch Logs Analysis:**
   - Authorizer logs show successful invocations for direct URL tests
   - No Lambda invocations for custom domain `/v1/events` requests
   - 404 response format is FastAPI's, but Lambda not invoked (CloudFront caching old error)

7. **AWS Configuration Verified:**
   - Base path mapping exists: `hooks.vincentchan.cloud|v1`
   - API Gateway methods have authorizer attached
   - Stage deployment is current (`zyurr9`, updated at deployment time)
   - Certificate is valid in us-east-1

### Solution Approach

8. **Proposed Solution: Migrate EDGE → REGIONAL**
   - Change `endpoint_type` from `EDGE` to `REGIONAL` (`cdk/stacks/webhook_delivery_stack.py:330`)
   - Keep base path mapping `"v1"` unchanged
   - REGIONAL endpoints have better documented base path stripping behavior
   - Eliminates CloudFront intermediary (simpler debugging, no caching issues)
   - No code changes needed in Lambda/FastAPI

9. **Why REGIONAL Over Other Approaches:**
   - **Simpler:** Single line change vs restructuring API Gateway resources
   - **No Lambda changes:** FastAPI routes stay `/events`
   - **Better documented:** AWS docs focus on REGIONAL for base path mappings
   - **No caching issues:** Direct to API Gateway, no CloudFront cache
   - **Easy rollback:** Revert one line and redeploy

10. **Trade-offs Accepted:**
    - No global edge caching (minimal impact - authorizer already caches 5 min)
    - Slightly higher latency for distant clients (acceptable for US-based traffic)

## Artifacts

**Investigation Documents:**
- `thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md` - Comprehensive migration plan

**Test Data Created:**
- DynamoDB test API key: `test_api_key_123` → tenant: `test_tenant`
- Target URL: `https://webhook.site/unique-url-placeholder`
- Webhook secret: `test_secret_456`

**Previous Implementation Artifacts:**
- `src/authorizer/handler.py` - Authorizer Lambda (Phase 1)
- `src/api/context.py` - Context extraction (Phase 3)
- `cdk/stacks/webhook_delivery_stack.py` - CDK stack with authorizer (Phase 2)
- `tests/test_authorizer.py` - Authorizer tests (Phase 4)
- `tests/test_events.py` - API tests (Phase 4)

## Action Items & Next Steps

### Immediate: Review Migration Plan

1. **Read migration plan:** `thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md`
   - Covers problem statement, solution overview, implementation steps
   - Includes deployment procedure, testing plan, and rollback steps
   - Risk assessment and expected outcomes

### Implementation Steps (When Ready)

2. **Make code change:**
   - File: `cdk/stacks/webhook_delivery_stack.py:330`
   - Change: `endpoint_type=apigateway.EndpointType.REGIONAL,` (from EDGE)
   - **That's it!** Only 1 line needs to change

3. **Review CDK diff:**
   ```bash
   cd cdk
   cdk diff
   ```
   - Verify endpoint type change
   - Confirm Route53 update
   - Check base path mapping preserved

4. **Deploy to AWS:**
   ```bash
   cd cdk
   cdk deploy
   ```
   - Expect ~5-10 minutes deployment time
   - Brief downtime during custom domain replacement
   - DNS propagation: 0-60 seconds

5. **Run integration tests:**
   - Test 1: Valid token → 201 (custom domain `/v1/events`)
   - Test 2: Invalid token → 403
   - Test 3: Missing auth → 401
   - Test 4: Verify Lambda receives `/events` (check logs)
   - Test 5: Verify authorizer caching (check CloudWatch)

6. **Verify base path stripping:**
   ```bash
   aws logs tail /aws/lambda/Vincent-TriggerApi-ApiHandler --since 2m
   ```
   - Confirm Lambda is invoked for `/v1/events` requests
   - Verify path received is `/events` (not `/v1/events`)

### If Successful

7. **Clean up test data** (optional):
   - Remove test API key from DynamoDB if no longer needed
   - Clear test events from Events table

8. **Update documentation:**
   - Mark Phase 6 as complete
   - Document REGIONAL endpoint architecture
   - Close Lambda Authorizer implementation task

### If Unsuccessful

9. **Iterate with alternative approaches:**
   - Option A: Explicitly create `/v1/{proxy+}` resource in API Gateway
   - Option B: Add `/v1` prefix to all FastAPI routes
   - Option C: Investigate API Gateway request transformation
   - See migration plan for detailed alternative approaches

10. **Rollback if needed:**
    - Revert line 330 to `endpoint_type=apigateway.EndpointType.EDGE,`
    - Run `cdk deploy`
    - Restores previous EDGE + CloudFront setup

## Other Notes

### Current System State

**Deployment Status:**
- CloudFormation stack: `WebhookDeliveryStack` - UPDATE_COMPLETE
- Deployment time: 2025-11-22 16:26:42 (local time)
- All Lambda functions healthy and running Python 3.12

**Lambda Functions:**
- `Vincent-TriggerApi-Authorizer` - NEW, working correctly
- `Vincent-TriggerApi-ApiHandler` - Updated with context extraction
- `Vincent-TriggerApi-WorkerHandler` - Unchanged
- `Vincent-TriggerApi-DlqProcessor` - Unchanged

**API Gateway Configuration:**
- API ID: `1ptya5rgn5`
- Stage: `prod`
- Authorizer: `bnsib8` (5-min cache, TOKEN type)
- Resources: `/` and `/{proxy+}` (both with CUSTOM auth)

**Custom Domain (Current - EDGE):**
- Domain: `hooks.vincentchan.cloud`
- CloudFront: `dl595id3fbzt6.cloudfront.net`
- Certificate: `arn:aws:acm:us-east-1:971422717446:certificate/64ca84e7-0929-4d0c-9f15-aea5159a0041`
- Base path: `v1` → API `1ptya5rgn5` stage `prod`

### Key File Locations

**CDK Infrastructure:**
- Main stack: `cdk/stacks/webhook_delivery_stack.py`
- Custom domain: Lines 325-349
- **Change needed:** Line 330 (EDGE → REGIONAL)

**Lambda Functions:**
- Authorizer: `src/authorizer/handler.py`
- API: `src/api/routes.py`, `src/api/context.py`
- Worker: `src/worker/handler.py` (unchanged)

**Tests:**
- Authorizer: `tests/test_authorizer.py` (5 tests)
- API: `tests/test_events.py` (3 tests)

### Working URLs

**Current (Working):**
- Direct API Gateway: `https://1ptya5rgn5.execute-api.us-east-1.amazonaws.com/prod/events`

**Current (Broken):**
- Custom domain: `https://hooks.vincentchan.cloud/v1/events` → 404

**Expected After Migration:**
- Custom domain: `https://hooks.vincentchan.cloud/v1/events` → 201 ✅

### Important Constraints

**What NOT to Change:**
- FastAPI routes (keep `/events`, no `/v1` prefix)
- Base path mapping value (keep `"v1"`)
- Lambda code (no changes needed)
- API Gateway resource structure (keep `/{proxy+}`)
- Authorizer configuration (working correctly)

**What Changes:**
- Only: `endpoint_type` from EDGE to REGIONAL (1 line)
- CloudFormation will handle: Deleting EDGE domain, creating REGIONAL domain, updating Route53

### Context from Previous Sessions

**Lambda Authorizer Implementation (Phases 1-4):**
- Separated authentication from API Lambda to API Gateway level
- Created dedicated Authorizer Lambda with Bearer token validation
- Updated CDK with TokenAuthorizer (5-min cache)
- Modified API Lambda to extract tenant from authorizer context
- All unit tests pass

**Deployment (Phase 5):**
- CDK deployment successful
- All infrastructure created correctly
- Authorizer configured with 5-min cache TTL

**Integration Testing (Phase 6 - Partial):**
- Direct API Gateway URL: All tests pass ✅
- Custom domain URL: 404 error discovered ❌
- Investigation revealed base path mapping issue with EDGE endpoints

### Resources and References

**AWS Documentation:**
- [API endpoint types for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-api-endpoint-types.html)
- [Use API mappings for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-mappings.html)
- [Set up edge-optimized custom domain](https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-edge-optimized-custom-domain-name.html)
- [Using multiple segments in base path mapping](https://aws.amazon.com/blogs/compute/using-multiple-segments-in-amazon-api-gateway-base-path-mapping/)

**Related Documents:**
- Original research: `thoughts/shared/research/2025-11-22-auth-lambda-authorizer-separation.md`
- Implementation plan: `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md`
- Migration plan: `thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md`

### Testing Credentials

**Test API Key (Seeded in DynamoDB):**
```
Table: Vincent-TriggerApi-TenantApiKeys
apiKey: test_api_key_123
tenantId: test_tenant
targetUrl: https://webhook.site/unique-url-placeholder
webhookSecret: test_secret_456
isActive: true
```

Use for integration testing after migration.

### Success Metrics

**Phase 6 will be complete when:**
- [ ] Custom domain URL returns 201 for valid requests
- [ ] Base path `/v1` is correctly stripped by API Gateway
- [ ] Lambda receives `/events` (verified in logs)
- [ ] All 5 integration tests pass via custom domain
- [ ] Authorizer caching continues to work (5-min TTL)
- [ ] End-to-end flow works (ingest → SQS → worker → delivery)

**Current Progress:**
- Phases 1-5: 100% complete ✅
- Phase 6: ~60% complete (direct URL tests pass, custom domain blocked by routing issue)
