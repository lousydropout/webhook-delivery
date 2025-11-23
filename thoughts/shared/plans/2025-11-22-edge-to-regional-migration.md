# Implementation Plan: EDGE to REGIONAL Endpoint Migration

**Date:** 2025-11-22
**Purpose:** Migrate API Gateway custom domain from EDGE to REGIONAL endpoint to fix `/v1` base path mapping issue
**Related Investigation:** Phase 6 testing revealed custom domain `/v1` path not working with EDGE endpoint

---

## Problem Statement

After successful deployment of Lambda Authorizer (Phases 1-5), integration testing revealed:

- ✅ **Direct API Gateway URL works:** `https://1ptya5rgn5.execute-api.us-east-1.amazonaws.com/prod/events`
- ❌ **Custom domain URL fails:** `https://hooks.vincentchan.cloud/v1/events` returns 404
- **Root cause:** Base path mapping not stripping `/v1` prefix on EDGE endpoint before reaching Lambda
- **Contributing factor:** CloudFront (used by EDGE endpoints) adds complexity and caching issues

## Solution Overview

Migrate from EDGE-optimized to REGIONAL endpoint while maintaining base path mapping approach:

- Change custom domain `endpoint_type` from `EDGE` to `REGIONAL`
- Keep base path mapping `"v1"` (no changes to mapping logic)
- No changes to Lambda/FastAPI code required
- Route53 will automatically update to point to new REGIONAL endpoint

**Why REGIONAL?**
- Better documented base path stripping behavior
- No CloudFront intermediary (simpler debugging, no caching issues)
- More predictable routing
- Still supports base path mappings

## Current State

### CDK Configuration
**File:** `cdk/stacks/webhook_delivery_stack.py:325-349`

```python
# Current (EDGE)
custom_domain = apigateway.DomainName(
    self,
    "TriggerApiCustomDomain",
    domain_name=domain_name,
    certificate=certificate,
    endpoint_type=apigateway.EndpointType.EDGE,  # ← Change this
)

custom_domain.add_base_path_mapping(
    self.api,
    base_path="v1",
    stage=self.api.deployment_stage,
)

# Route53 A record
route53.ARecord(
    self,
    "TriggerApiAliasRecord",
    zone=zone,
    record_name="hooks",
    target=route53.RecordTarget.from_alias(
        targets.ApiGatewayDomain(custom_domain)
    ),
)
```

### Current AWS Resources

- **Custom domain:** `hooks.vincentchan.cloud`
  - Type: EDGE
  - CloudFront distribution: `dl595id3fbzt6.cloudfront.net`
  - Certificate: `arn:aws:acm:us-east-1:971422717446:certificate/64ca84e7-0929-4d0c-9f15-aea5159a0041`
  - Routing mode: `BASE_PATH_MAPPING_ONLY`

- **Base path mapping:**
  - `basePath: "v1"`
  - `restApiId: "1ptya5rgn5"`
  - `stage: "prod"`

- **Route53 record:**
  - Name: `hooks.vincentchan.cloud`
  - Type: A (Alias)
  - Target: CloudFront distribution

## Implementation Steps

### Phase 1: Code Changes

#### Step 1.1: Update Custom Domain Configuration

**File:** `cdk/stacks/webhook_delivery_stack.py`

**Change Line 330:**
```python
# Before
endpoint_type=apigateway.EndpointType.EDGE,

# After
endpoint_type=apigateway.EndpointType.REGIONAL,
```

**That's it!** No other code changes needed.

#### Step 1.2: Verify Certificate Region

**Prerequisite check:** ACM certificate must be in the same region as API Gateway.

```bash
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:971422717446:certificate/64ca84e7-0929-4d0c-9f15-aea5159a0041 \
  --region us-east-1 \
  --query 'Certificate.{Status:Status,Region:"us-east-1"}' \
  --output table
```

**Expected:** Status should be `ISSUED` in `us-east-1` ✅

---

### Phase 2: Deployment

#### Step 2.1: Review Changes

```bash
cd cdk
cdk diff
```

**Expected changes:**
- `~` Update: `TriggerApiCustomDomain` - endpoint configuration changes
- `~` Update: `TriggerApiAliasRecord` - target changes from CloudFront to Regional domain
- `-` Delete: CloudFront distribution (automatic, managed by CDK)
- `+` Create: New Regional domain endpoint

**Important:** CDK will replace the custom domain (delete + create), which will cause **brief downtime** during deployment.

#### Step 2.2: Deploy to AWS

```bash
cd cdk
cdk deploy
```

**Deployment time:** ~5-10 minutes
- CloudFormation will delete old EDGE domain
- Create new REGIONAL domain
- Update Route53 A record
- DNS propagation: 0-60 seconds (Route53 is fast)

**Expected output:**
```
✅  WebhookDeliveryStack

Outputs:
WebhookDeliveryStack.CustomDomainUrl = https://hooks.vincentchan.cloud
...
```

#### Step 2.3: Verify Deployment

```bash
# Check custom domain is REGIONAL
aws apigateway get-domain-name \
  --domain-name hooks.vincentchan.cloud \
  --output json | jq '{domainName, endpointType: .endpointConfiguration.types[0], status: .domainNameStatus}'
```

**Expected:**
```json
{
  "domainName": "hooks.vincentchan.cloud",
  "endpointType": "REGIONAL",
  "status": "AVAILABLE"
}
```

```bash
# Verify base path mapping still exists
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

### Phase 3: Integration Testing

#### Test 1: Valid Bearer Token → 201 Created

```bash
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "regional.test", "data": "success"}' \
  -w "\nHTTP Status: %{http_code}\n"
```

**Expected:**
```json
{"event_id":"evt_xxxxxxxx","status":"PENDING"}
HTTP Status: 201
```

#### Test 2: Invalid Bearer Token → 403 Forbidden

```bash
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer invalid_token" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "test", "data": "fail"}' \
  -w "\nHTTP Status: %{http_code}\n"
```

**Expected:**
```json
{"Message":"User is not authorized to access this resource..."}
HTTP Status: 403
```

#### Test 3: Missing Authorization Header → 401 Unauthorized

```bash
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Content-Type: application/json" \
  -d '{"event_type": "test", "data": "fail"}' \
  -w "\nHTTP Status: %{http_code}\n"
```

**Expected:**
```json
{"message":"Unauthorized"}
HTTP Status: 401
```

#### Test 4: Verify Base Path Stripping

Check API Lambda logs to confirm it receives `/events` (not `/v1/events`):

```bash
aws logs tail /aws/lambda/Vincent-TriggerApi-ApiHandler --since 2m --format short | grep -E "POST|path|route"
```

**Expected:** Lambda should be invoked (logs present), indicating path was correctly stripped and routed.

#### Test 5: Verify Authorizer Caching Still Works

```bash
# First request (should invoke authorizer)
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "cache.test.1", "data": "first"}' \
  -s -w "\nHTTP Status: %{http_code}\n"

# Second request within 5 minutes (should use cache)
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "cache.test.2", "data": "second"}' \
  -s -w "\nHTTP Status: %{http_code}\n"

# Check authorizer logs - should only see one invocation
aws logs tail /aws/lambda/Vincent-TriggerApi-Authorizer --since 5m --format short | grep "Authorized tenant"
```

**Expected:** Only one "Authorized tenant" log entry (second request used cache).

---

### Phase 4: Performance Comparison (Optional)

#### Latency Comparison

**Before (EDGE with CloudFront):**
```bash
curl -o /dev/null -s -w "Time: %{time_total}s\n" \
  -X POST https://1ptya5rgn5.execute-api.us-east-1.amazonaws.com/prod/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "perf.test", "data": "timing"}'
```

**After (REGIONAL):**
```bash
curl -o /dev/null -s -w "Time: %{time_total}s\n" \
  -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "perf.test", "data": "timing"}'
```

**Expected:** REGIONAL should be similar or slightly faster for US-based clients (no CloudFront hop).

---

## Success Criteria

### Automated Verification
- [x] `cdk diff` shows endpoint type change
- [ ] `cdk deploy` completes successfully
- [ ] Custom domain status: `AVAILABLE`
- [ ] Endpoint type: `REGIONAL`
- [ ] Base path mapping exists: `v1` → `prod`
- [ ] Route53 A record updated

### Manual Verification
- [ ] Valid token → 201 Created ✅
- [ ] Invalid token → 403 Forbidden ✅
- [ ] Missing auth → 401 Unauthorized ✅
- [ ] Lambda receives `/events` (not `/v1/events`) ✅
- [ ] Authorizer caching works (5 min TTL) ✅
- [ ] End-to-end flow works (event → SQS → worker → delivery) ✅

---

## Rollback Plan

If REGIONAL endpoint doesn't fix the issue or causes problems:

### Step 1: Revert Code Changes

```bash
git diff HEAD -- cdk/stacks/webhook_delivery_stack.py
```

**Revert line 330:**
```python
# Revert to EDGE
endpoint_type=apigateway.EndpointType.EDGE,
```

### Step 2: Redeploy

```bash
cd cdk
cdk deploy
```

This will:
- Delete REGIONAL domain
- Recreate EDGE domain with CloudFront
- Restore base path mapping
- Update Route53 A record

**Downtime:** ~5-10 minutes during rollback deployment

### Step 3: Verify Rollback

```bash
aws apigateway get-domain-name \
  --domain-name hooks.vincentchan.cloud \
  --query '{type: endpointConfiguration.types[0], cloudfront: distributionDomainName}' \
  --output table
```

**Expected:** Type should be `EDGE` with CloudFront distribution.

---

## Risk Assessment

### Low Risk
- ✅ Single line code change
- ✅ AWS-managed migration (CDK handles complexity)
- ✅ Easy rollback (revert one line + redeploy)
- ✅ No data loss (DynamoDB, SQS unchanged)
- ✅ No breaking changes to API contract

### Medium Risk
- ⚠️ Brief downtime during deployment (~5-10 min)
- ⚠️ DNS propagation may take up to 60 seconds
- ⚠️ If REGIONAL doesn't fix issue, need to iterate further

### Mitigations
- ✅ Deploy during low-traffic window
- ✅ Monitor CloudWatch metrics during deployment
- ✅ Have rollback plan ready
- ✅ Test thoroughly with curl after deployment

---

## Expected Outcomes

### If Successful
- ✅ Custom domain `https://hooks.vincentchan.cloud/v1/events` works
- ✅ Base path mapping correctly strips `/v1` before Lambda
- ✅ FastAPI receives `/events` and matches route
- ✅ All integration tests pass
- ✅ Authorizer caching continues to work
- ✅ No code changes needed in Lambda/FastAPI
- ✅ **Phase 6 complete** ✨

### If Unsuccessful
- ⚠️ Still getting 404 on custom domain
- Next iteration options:
  1. Explicitly create `/v1/{proxy+}` resource in API Gateway
  2. Modify FastAPI routes to include `/v1` prefix
  3. Investigate API Gateway request transformation
  4. Review CDK `LambdaRestApi` construct limitations with base path mappings

---

## Notes

### Why REGIONAL Over EDGE?

1. **Simpler architecture:** No CloudFront intermediary
2. **Better debugging:** Fewer layers to troubleshoot
3. **No caching issues:** CloudFront cache won't interfere
4. **Better documented:** AWS docs focus on REGIONAL for base path mappings
5. **Performance:** For US-based traffic, REGIONAL may be faster (no CloudFront hop)

### Trade-offs

- **No global edge caching:** REGIONAL doesn't use CloudFront
  - **Impact:** Minimal - Authorizer already provides 5-min caching
  - **Mitigation:** Add CloudFront separately if needed later
- **Higher latency for distant clients:** No edge locations
  - **Impact:** Low - Most traffic likely US-based
  - **Mitigation:** Monitor latency metrics; add CloudFront if needed

### Alternative Approaches (Not Recommended)

1. **Keep EDGE, change to `/v1/{proxy+}` resource:**
   - Requires modifying API Gateway resource structure
   - Would need FastAPI route changes OR request transformation
   - More complex than endpoint type change

2. **Keep EDGE, add `/v1` to all FastAPI routes:**
   - Requires code changes in Lambda
   - Couples application code to API versioning
   - Less clean separation of concerns

3. **Keep EDGE, investigate CloudFront behavior:**
   - May require complex CloudFront configuration
   - Harder to debug and maintain
   - Still doesn't address base path stripping issue

---

## References

- **Related Investigation:** Phase 6 Integration Testing
- **Previous Handoff:** `thoughts/shared/handoffs/general/2025-11-22_16-15-36_lambda-authorizer-phases-1-4-complete.md`
- **Implementation Plan:** `thoughts/shared/plans/2025-11-22-lambda-authorizer-separation.md`
- **AWS Documentation:**
  - [API endpoint types for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-api-endpoint-types.html)
  - [Use API mappings for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-mappings.html)
  - [Set up edge-optimized custom domain](https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-edge-optimized-custom-domain-name.html)
  - [Set up regional custom domain](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-regional-api-custom-domain-create.html)

---

## Commit Message Template

```
Migrate API Gateway custom domain from EDGE to REGIONAL

Changes base path mapping endpoint from EDGE to REGIONAL to fix
/v1 path routing issue. REGIONAL endpoints have better documented
base path stripping behavior and avoid CloudFront caching issues.

Changes:
- Update custom domain endpoint_type from EDGE to REGIONAL
- No changes to base path mapping logic (still "v1")
- No changes to Lambda/FastAPI code

Testing:
- Custom domain /v1/events now routes correctly
- Base path stripping works as expected
- All integration tests pass
- Authorizer caching still functional

Fixes: Custom domain 404 issue discovered in Phase 6 testing

Related: thoughts/shared/plans/2025-11-22-edge-to-regional-migration.md
```
