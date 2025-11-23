---
date: 2025-11-22T18:04:11-06:00
researcher: Claude Code
git_commit: 964295ccb9ad3fea666d03647e40234b5c1dfad8
branch: main
repository: zapier
topic: "Test Option A: REGIONAL Endpoint Migration"
tags: [implementation, api-gateway, regional-endpoint, base-path-mapping, testing]
status: ready_to_implement
last_updated: 2025-11-22
last_updated_by: Claude Code
type: implementation_task
---

# Handoff: Test Option A - REGIONAL Endpoint Only

## Task(s)

**Main Task:** Test if changing EDGE → REGIONAL endpoint alone fixes the `/v1` base path mapping issue.

**Context:** During Phase 6 integration testing, custom domain `https://hooks.vincentchan.cloud/v1/events` returns 404. Investigation revealed base path mapping is not stripping `/v1` prefix on EDGE endpoints. User prefers moving `/v1` to API Gateway resource level (Option B), but we should first test if REGIONAL endpoint alone fixes the issue (Option A).

**Status:**
- ⏳ **Option A Implementation:** READY (1-line change)
- ⏳ **Option A Testing:** PENDING
- ⏳ **Option A Decision:** PENDING (determine if we need Option B)

**Working From:**
- Investigation findings: `thoughts/shared/handoffs/general/2025-11-22_17-57-54_custom-domain-v1-path-issue.md`
- Option A approach: `thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md`
- Option B approach: `thoughts/shared/plans/2025-11-22-edge-to-regional-with-v1-resource.md`

## Critical References

1. **Option A Plan:** `thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md`
2. **Option B Plan (if A fails):** `thoughts/shared/plans/2025-11-22-edge-to-regional-with-v1-resource.md`
3. **CDK Stack:** `cdk/stacks/webhook_delivery_stack.py:330`

## Recent Changes

**No changes yet** - Ready to implement Option A.

## Learnings

### Investigation Summary

1. **Problem:** Custom domain `https://hooks.vincentchan.cloud/v1/events` returns 404
2. **Direct URL works:** `https://1ptya5rgn5.execute-api.us-east-1.amazonaws.com/prod/events` ✅
3. **Root cause:** Base path mapping not stripping `/v1` on EDGE endpoint
4. **Contributing factor:** CloudFront adds caching and routing complexity

### Option A vs Option B

**Option A (Test First):**
- Change: EDGE → REGIONAL (1 line: `cdk/stacks/webhook_delivery_stack.py:330`)
- Keep: base path mapping `"v1"`
- Hypothesis: REGIONAL endpoints have better base path stripping behavior
- Pros: Minimal change, no Lambda code changes
- Cons: Still relies on base path stripping

**Option B (If A Fails):**
- Change: EDGE → REGIONAL + manual API Gateway with `/v1/{proxy+}` resource
- Remove: base path mapping (set to `""`)
- Requires: ~30 lines of code changes, replacing `LambdaRestApi` with `RestApi`
- **Issue:** Lambda will receive `/v1/events`, but FastAPI expects `/events`
- **Needs:** Either Mangum path stripping OR adding `/v1` to FastAPI routes

### Why Test Option A First

1. **Minimal risk:** 1-line change vs 30+ lines
2. **Quick validation:** Tests if issue is EDGE-specific
3. **AWS documentation:** REGIONAL endpoints better documented for base path stripping
4. **Avoids coupling:** If A works, no need to add `/v1` to FastAPI routes

## Artifacts

**Plans Created:**
- `thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md` - Option A detailed plan
- `thoughts/shared/plans/2025-11-22-edge-to-regional-with-v1-resource.md` - Option B detailed plan

**Previous Investigation:**
- `thoughts/shared/handoffs/general/2025-11-22_17-57-54_custom-domain-v1-path-issue.md`

## Action Items & Next Steps

### Phase 1: Implement Option A

**Step 1.1: Make code change**

File: `cdk/stacks/webhook_delivery_stack.py:330`

```python
# Change this line from:
endpoint_type=apigateway.EndpointType.EDGE,

# To:
endpoint_type=apigateway.EndpointType.REGIONAL,
```

**That's it!** Only 1 line changes.

**Step 1.2: Review changes**

```bash
cd cdk
cdk diff
```

**Expected changes:**
- `~` Update: `TriggerApiCustomDomain` - endpoint type EDGE → REGIONAL
- `~` Update: `TriggerApiAliasRecord` - target changes from CloudFront to Regional
- `-` Delete: CloudFront distribution
- No changes to base path mapping (stays `"v1"`)
- No changes to API Gateway resources (stays `/{proxy+}`)

**Step 1.3: Deploy**

```bash
cd cdk
cdk deploy
```

**Expected:** ~5-10 minutes deployment time, brief downtime during domain replacement.

**Step 1.4: Verify deployment**

```bash
# Check endpoint type changed to REGIONAL
aws apigateway get-domain-name \
  --domain-name hooks.vincentchan.cloud \
  --query '{type: endpointConfiguration.types[0], status: domainNameStatus}' \
  --output table
```

**Expected:**
```
-----------------------
|  GetDomainName      |
+--------+------------+
| status | AVAILABLE  |
| type   | REGIONAL   |
+--------+------------+
```

```bash
# Verify base path mapping unchanged
aws apigateway get-base-path-mappings \
  --domain-name hooks.vincentchan.cloud \
  --output table
```

**Expected:**
```
----------------------------------------
|       GetBasePathMappings            |
+----------+------------+-------------+
| basePath | restApiId  |   stage     |
+----------+------------+-------------+
|  v1      | 1ptya5rgn5 |   prod      |
+----------+------------+-------------+
```

---

### Phase 2: Test Option A

**Test 1: Valid Bearer token → 201 Created**

```bash
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "regional.option.a.test", "data": "testing"}' \
  -w "\nHTTP Status: %{http_code}\n"
```

**Expected if Option A works:**
```json
{"event_id":"evt_xxxxxxxx","status":"PENDING"}
HTTP Status: 201
```

**If still 404:** Option A failed, proceed to Option B.

**Test 2: Check Lambda logs**

```bash
aws logs tail /aws/lambda/Vincent-TriggerApi-ApiHandler --since 2m --format short
```

**Expected if Option A works:**
- Lambda invocation logs present
- Path received should be `/events` (NOT `/v1/events`)

**Test 3: Invalid token → 403**

```bash
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer invalid_token" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "test", "data": "fail"}' \
  -w "\nHTTP Status: %{http_code}\n"
```

**Expected:** `HTTP Status: 403`

**Test 4: Missing auth → 401**

```bash
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Content-Type: application/json" \
  -d '{"event_type": "test", "data": "fail"}' \
  -w "\nHTTP Status: %{http_code}\n"
```

**Expected:** `HTTP Status: 401`

**Test 5: Verify authorizer caching**

```bash
# First request
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "cache.test.1", "data": "first"}' \
  -s

# Second request (within 5 min)
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "cache.test.2", "data": "second"}' \
  -s

# Check authorizer logs - should only see ONE invocation
aws logs tail /aws/lambda/Vincent-TriggerApi-Authorizer --since 5m --format short | grep "Authorized tenant"
```

**Expected:** Only 1 log entry (second request used cache).

---

### Phase 3: Decision Point

**If Option A Works (all tests pass):**

✅ **Success!** The issue was EDGE/CloudFront specific.

Next steps:
1. Mark Phase 6 complete
2. Document REGIONAL endpoint choice in architecture docs
3. Clean up test data (optional)
4. Create final handoff documenting completion

**If Option A Fails (404 still occurs):**

❌ **Option A insufficient.** Proceed to Option B.

Next steps:
1. Rollback Option A if needed: `git checkout cdk/stacks/webhook_delivery_stack.py && cdk deploy`
2. Implement Option B: Manual API Gateway with `/v1/{proxy+}` resource
3. Follow plan: `thoughts/shared/plans/2025-11-22-edge-to-regional-with-v1-resource.md`
4. Decide: Add `/v1` to FastAPI routes OR investigate Mangum path stripping

---

### Phase 4: Rollback (if Option A causes issues)

**If deployment fails or breaks existing functionality:**

```bash
# Revert code change
git checkout HEAD -- cdk/stacks/webhook_delivery_stack.py

# Redeploy
cd cdk
cdk deploy
```

This restores EDGE endpoint with CloudFront.

---

## Other Notes

### Current System State

**Lambda Functions (All Healthy):**
- `Vincent-TriggerApi-Authorizer` - Authorizer Lambda
- `Vincent-TriggerApi-ApiHandler` - API Lambda
- `Vincent-TriggerApi-WorkerHandler` - Worker Lambda
- `Vincent-TriggerApi-DlqProcessor` - DLQ Processor

**Current Configuration (Before Option A):**
- Endpoint type: EDGE
- CloudFront: `dl595id3fbzt6.cloudfront.net`
- Base path: `v1` → `prod` stage
- API Gateway: `/{proxy+}` resource

**After Option A:**
- Endpoint type: REGIONAL (no CloudFront)
- Base path: `v1` → `prod` stage (unchanged)
- API Gateway: `/{proxy+}` resource (unchanged)

### Test Data Available

**Seeded in DynamoDB:**
```
Table: Vincent-TriggerApi-TenantApiKeys
apiKey: test_api_key_123
tenantId: test_tenant
targetUrl: https://webhook.site/unique-url-placeholder
webhookSecret: test_secret_456
isActive: true
```

### Key File Locations

**Code Change:**
- `cdk/stacks/webhook_delivery_stack.py:330` - Change EDGE → REGIONAL

**Plans:**
- Option A: `thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md`
- Option B: `thoughts/shared/plans/2025-11-22-edge-to-regional-with-v1-resource.md`

**Investigation:**
- `thoughts/shared/handoffs/general/2025-11-22_17-57-54_custom-domain-v1-path-issue.md`

### Success Criteria

**Option A is successful if:**
- [ ] Deployment completes without errors
- [ ] Custom domain returns REGIONAL (not EDGE)
- [ ] `https://hooks.vincentchan.cloud/v1/events` returns 201 with valid token
- [ ] Lambda receives `/events` (base path stripped correctly)
- [ ] Invalid token → 403
- [ ] Missing auth → 401
- [ ] Authorizer caching works (5-min TTL)
- [ ] No regressions in existing functionality

**Option A has failed if:**
- [ ] Still getting 404 on `/v1/events`
- [ ] Lambda receives `/v1/events` (base path NOT stripped)
- [ ] FastAPI returns 404 (can't match `/v1/events` to `/events` route)

### Decision Tree

```
Option A Implementation
  │
  ├─> Deploy successful?
  │   ├─> No → Rollback, investigate deployment error
  │   └─> Yes → Continue to testing
  │
  ├─> Test: /v1/events with valid token
  │   ├─> 201 ✅ → Option A SUCCESS! Done.
  │   └─> 404 ❌ → Option A FAILED, proceed to Option B
  │
  └─> Option B Required
      └─> Follow: thoughts/shared/plans/2025-11-22-edge-to-regional-with-v1-resource.md
```

### Expected Timeline

**Option A only:**
- Code change: 1 minute
- CDK diff review: 2 minutes
- Deployment: 5-10 minutes
- Testing: 5 minutes
- **Total: ~15-20 minutes**

**If Option B needed:**
- Additional code changes: 10 minutes
- Research Mangum path handling: 10 minutes
- Deployment: 5-10 minutes
- Testing + possible FastAPI route updates: 10 minutes
- **Additional: ~35-40 minutes**

### Commit Message (for Option A)

```
Migrate API Gateway custom domain from EDGE to REGIONAL

Test Option A: Change endpoint type to REGIONAL while keeping base
path mapping "v1" to determine if EDGE/CloudFront is the root cause
of base path stripping failure.

Changes:
- Update custom domain endpoint_type from EDGE to REGIONAL
- No changes to base path mapping (still "v1")
- No changes to API Gateway resources (still /{proxy+})
- No changes to Lambda/FastAPI code

Expected outcome:
- REGIONAL should properly strip /v1 prefix before Lambda
- FastAPI should receive /events and match route correctly

If this works: Problem solved with minimal change.
If this fails: Proceed to Option B (manual /v1/{proxy+} resource).

Related:
- Investigation: thoughts/shared/handoffs/general/2025-11-22_17-57-54_custom-domain-v1-path-issue.md
- Plan: thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

### Important Notes

**Why Option A first:**
1. Minimal change (1 line vs 30+ lines)
2. Quick to test (15 min vs 50+ min)
3. Low risk (easy rollback)
4. AWS docs suggest REGIONAL has better base path behavior
5. Avoids coupling FastAPI to API versioning

**User preference:**
- Prefers `/v1` at API Gateway level (Option B)
- But agreed to test Option A first to validate necessity

**Next session should:**
1. Implement Option A (1-line change)
2. Deploy and test thoroughly
3. If successful: Document and close
4. If failed: Implement Option B per plan
