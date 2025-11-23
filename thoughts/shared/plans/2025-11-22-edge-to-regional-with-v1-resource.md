# Implementation Plan: EDGE to REGIONAL with /v1 Resource

**Date:** 2025-11-22
**Purpose:** Migrate API Gateway from EDGE to REGIONAL AND move `/v1` logic to API Gateway resource level
**Related Investigation:** Phase 6 testing revealed custom domain `/v1` path not working with EDGE endpoint

---

## Problem Statement

After successful deployment of Lambda Authorizer (Phases 1-5), integration testing revealed:

- ✅ **Direct API Gateway URL works:** `https://1ptya5rgn5.execute-api.us-east-1.amazonaws.com/prod/events`
- ❌ **Custom domain URL fails:** `https://hooks.vincentchan.cloud/v1/events` returns 404
- **Root cause:** Base path mapping not stripping `/v1` prefix on EDGE endpoint before reaching Lambda
- **Contributing factor:** CloudFront (used by EDGE endpoints) adds complexity and caching issues

## Solution Overview

**Dual approach:**
1. Change EDGE → REGIONAL endpoint (remove CloudFront complexity)
2. Move `/v1` from custom domain base path mapping to API Gateway resource level

**Architecture Change:**

```
BEFORE:
Custom Domain (EDGE):     hooks.vincentchan.cloud/v1/* → base path mapping strips "/v1"
API Gateway (EDGE):       /{proxy+} → Lambda (receives /events)
FastAPI:                  /events

AFTER:
Custom Domain (REGIONAL): hooks.vincentchan.cloud/* → direct to API (no base path)
API Gateway (REGIONAL):   /v1/{proxy+} → Lambda (receives /v1/events)
FastAPI:                  /events (Lambda proxy strips /v1)
```

**Why this approach?**
- ✅ Explicit `/v1` routing at API Gateway level (more predictable)
- ✅ No reliance on base path mapping stripping behavior
- ✅ REGIONAL endpoint (no CloudFront, simpler debugging)
- ✅ Better for future versioning (easy to add `/v2/{proxy+}`)
- ✅ No Lambda/FastAPI code changes (proxy integration handles path)

## Current State

### CDK Configuration

**File:** `cdk/stacks/webhook_delivery_stack.py:295-338`

```python
# Current: LambdaRestApi with proxy=True (auto-creates /{proxy+})
self.api = apigateway.LambdaRestApi(
    self,
    "TriggerApi",
    handler=self.api_lambda,
    proxy=True,  # ← Auto-creates /{proxy+} resource
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
        allow_headers=[...],
    ),
)

# Custom domain: EDGE with base path mapping "v1"
custom_domain = apigateway.DomainName(
    self,
    "TriggerApiCustomDomain",
    domain_name=domain_name,
    certificate=certificate,
    endpoint_type=apigateway.EndpointType.EDGE,  # ← Change to REGIONAL
)

custom_domain.add_base_path_mapping(
    self.api,
    base_path="v1",  # ← Change to "" (empty/root)
    stage=self.api.deployment_stage,
)
```

### Current AWS Resources

- **API Gateway:**
  - Resources: `/` and `/{proxy+}` (auto-created by `LambdaRestApi`)
  - All requests go to `/{proxy+}` → Lambda

- **Custom domain:**
  - Type: EDGE
  - Base path: `v1` → strips and routes to API
  - CloudFront: `dl595id3fbzt6.cloudfront.net`

## Implementation Steps

### Phase 1: Code Changes

The challenge: `LambdaRestApi` with `proxy=True` automatically creates `/{proxy+}`. We cannot add `/v1/{proxy+}` on top of this without switching to manual API Gateway construction.

**Two implementation options:**

#### Option A: Keep LambdaRestApi, use base path (simpler)

Just change EDGE → REGIONAL, keep base path mapping:

```python
# Line 330: Change endpoint type
endpoint_type=apigateway.EndpointType.REGIONAL,

# Line 336: Keep base path "v1"
base_path="v1",
```

**Pros:** Minimal change (2 lines)
**Cons:** Still relies on base path stripping (but REGIONAL should work better)

#### Option B: Manual API Gateway with /v1/{proxy+} (your preference)

Replace `LambdaRestApi` with manual `RestApi` + resources:

```python
# Create RestApi manually
self.api = apigateway.RestApi(
    self,
    "TriggerApi",
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

# Create /v1 resource
v1_resource = self.api.root.add_resource("v1")

# Create /v1/{proxy+} resource
proxy_resource = v1_resource.add_resource("{proxy+}")

# Add Lambda integration to /v1/{proxy+}
lambda_integration = apigateway.LambdaIntegration(
    self.api_lambda,
    proxy=True,
)

proxy_resource.add_method(
    "ANY",
    lambda_integration,
    authorization_type=apigateway.AuthorizationType.CUSTOM,
    authorizer=self.token_authorizer,
)

# Also add to /v1 directly (for /v1 without trailing path)
v1_resource.add_method(
    "ANY",
    lambda_integration,
    authorization_type=apigateway.AuthorizationType.CUSTOM,
    authorizer=self.token_authorizer,
)

# Custom domain: REGIONAL with NO base path (or empty "")
custom_domain = apigateway.DomainName(
    self,
    "TriggerApiCustomDomain",
    domain_name=domain_name,
    certificate=certificate,
    endpoint_type=apigateway.EndpointType.REGIONAL,  # Changed from EDGE
)

custom_domain.add_base_path_mapping(
    self.api,
    base_path="",  # Empty = root path (no stripping needed)
    stage=self.api.deployment_stage,
)
```

**Pros:**
- ✅ Explicit `/v1` at API Gateway level
- ✅ No base path stripping needed
- ✅ Clear architecture
- ✅ Easy to add `/v2` later

**Cons:**
- ⚠️ More code changes (~30 lines vs 2 lines)
- ⚠️ Replaces `LambdaRestApi` convenience construct
- ⚠️ Need to manually configure integration

### Important: Lambda Proxy Integration Behavior

With proxy integration, API Gateway sends the full path to Lambda:
- Request: `https://hooks.vincentchan.cloud/v1/events`
- API Gateway matches: `/v1/{proxy+}` where `{proxy+}` = `events`
- Lambda receives: `/v1/events` in the event
- **Mangum/FastAPI:** Extracts path and matches to route `/events`

**Wait - will this work?**

Actually, we need to verify: Does FastAPI/Mangum handle the `/v1` prefix stripping automatically?

Let me check the current FastAPI routes:

**File:** `src/api/routes.py:17`
```python
@router.post("/events", status_code=201, response_model=EventCreateResponse)
```

The route is `/events` (no `/v1`). With Lambda proxy integration receiving `/v1/events`, FastAPI won't match unless:
1. Mangum strips the base path, OR
2. We add `/v1` to FastAPI routes

**Research needed:** Check if Mangum has path stripping capability.

### Alternative: Use API Gateway stage variables

Another approach is to use a stage variable to strip the prefix, but this is complex.

---

## Recommended Implementation (Conservative)

Given the uncertainty about Mangum/FastAPI path handling, I recommend **Option A** first:

### Step 1.1: Change to REGIONAL endpoint

**File:** `cdk/stacks/webhook_delivery_stack.py:330`

```python
# Before
endpoint_type=apigateway.EndpointType.EDGE,

# After
endpoint_type=apigateway.EndpointType.REGIONAL,
```

### Step 1.2: Keep base path mapping

**File:** `cdk/stacks/webhook_delivery_stack.py:336`

```python
# Keep this unchanged
base_path="v1",
```

**Rationale:** REGIONAL endpoints should have better base path stripping behavior than EDGE. This tests whether the issue is specific to EDGE/CloudFront.

### Step 1.3: If REGIONAL + base path works

Stop here! Problem solved with minimal change.

### Step 1.4: If REGIONAL + base path still fails

Then proceed with Option B (manual `/v1/{proxy+}` resource) AND either:
- Add `/v1` prefix to all FastAPI routes, OR
- Configure Mangum to strip `/v1` prefix (if supported)

---

## Phase 2: Testing Strategy

### Test 1: Deploy REGIONAL with base path mapping (Option A)

```bash
cd cdk
cdk diff  # Verify only endpoint type changes
cdk deploy
```

Test custom domain:
```bash
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "regional.test", "data": "test"}' \
  -w "\nHTTP Status: %{http_code}\n"
```

**If this works:** ✅ Done! The issue was EDGE-specific.

**If this fails:** ❌ Proceed to Option B.

### Test 2: If needed, implement Option B (manual /v1/{proxy+})

After implementing manual API Gateway structure:

```bash
cd cdk
cdk diff  # Verify resource changes
cdk deploy
```

Check what path Lambda receives:
```bash
# Make request
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer test_api_key_123" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "path.test", "data": "checking"}' \
  -s

# Check Lambda logs for received path
aws logs tail /aws/lambda/Vincent-TriggerApi-ApiHandler --since 1m --format short
```

**Expected in logs:** Look for event path - should be `/v1/events`

**If FastAPI returns 404:** Need to add `/v1` to routes OR configure Mangum stripping.

---

## FastAPI Route Update (if needed for Option B)

If Lambda receives `/v1/events` but FastAPI expects `/events`:

**File:** `src/api/routes.py`

```python
# Option 1: Add /v1 prefix to route
@router.post("/v1/events", status_code=201, response_model=EventCreateResponse)

# Option 2: Configure Mangum with strip_base_path (if supported)
# In src/api/main.py
handler = Mangum(app, strip_base_path="/v1")  # Check if Mangum supports this
```

**Note:** Adding `/v1` to routes couples the application to API versioning, which is less clean.

---

## Success Criteria

### For Option A (REGIONAL + base path)
- [ ] Custom domain `/v1/events` returns 201
- [ ] Lambda receives `/events` (base path stripped)
- [ ] FastAPI matches `/events` route
- [ ] All integration tests pass

### For Option B (REGIONAL + /v1 resource)
- [ ] Custom domain `/v1/events` returns 201
- [ ] API Gateway `/v1/{proxy+}` resource exists
- [ ] Lambda receives `/v1/events`
- [ ] FastAPI handles path correctly (either via route update or Mangum config)
- [ ] All integration tests pass

---

## Rollback Plan

### Rollback Option A
```bash
# Revert line 330
endpoint_type=apigateway.EndpointType.EDGE,

cdk deploy
```

### Rollback Option B
```bash
# Revert entire API Gateway section to LambdaRestApi
git checkout HEAD -- cdk/stacks/webhook_delivery_stack.py

cdk deploy
```

---

## Decision Tree

```
Start
  ├─> Try Option A (REGIONAL + base path "v1")
  │   ├─> Works? ✅ Done!
  │   └─> Fails? ❌ Continue to Option B
  │
  └─> Try Option B (REGIONAL + /v1/{proxy+} resource)
      ├─> Lambda receives /v1/events?
      │   ├─> Yes → FastAPI matches /events?
      │   │   ├─> Yes ✅ Done! (Mangum strips automatically)
      │   │   └─> No ❌ Add /v1 to FastAPI routes OR configure Mangum
      │   │
      │   └─> No → Issue with API Gateway integration config
      │
      └─> Still broken? → Investigate further
```

---

## Recommendation

**Start with Option A** (minimal change):
1. Change EDGE → REGIONAL
2. Keep base path mapping `"v1"`
3. Test if REGIONAL has better stripping behavior

**If that fails, proceed to Option B** (explicit /v1 resource):
1. Replace `LambdaRestApi` with manual `RestApi` + `/v1/{proxy+}`
2. Set base path to `""` (empty/root)
3. Handle path in FastAPI or Mangum

This incremental approach minimizes risk and code changes.

---

## Next Steps

**Immediate:**
1. Decide: Try Option A first, or go straight to Option B?
2. If Option A: Change line 330 only, deploy, test
3. If Option B or A fails: Implement full manual API Gateway structure

**User preference noted:** You want `/v1` at API Gateway level (Option B), but Option A is safer to try first.

Which approach would you like to implement first?
