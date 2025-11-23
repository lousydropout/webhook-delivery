---
date: 2025-11-22T18:30:00-06:00
researcher: Claude Code
git_commit: [pending - uncommitted changes exist]
branch: main
repository: zapier
topic: "Swagger/OpenAPI Documentation Accessibility Issue"
tags: [documentation, api-gateway, fastapi, swagger, openapi, user-disagreement]
status: blocked
last_updated: 2025-11-22
last_updated_by: Claude Code
type: issue_and_disagreement
---

# Handoff: Swagger/OpenAPI Documentation Accessibility

## Task(s)

**Main Task:** Make FastAPI's automatic Swagger/OpenAPI documentation publicly accessible without requiring Bearer token authentication.

**Status:**
- ✅ **Option B Implementation:** COMPLETED - Custom domain `/v1/events` routing working
- ✅ **Integration Testing:** COMPLETED - All auth tests passing
- 🚫 **Swagger Docs Access:** BLOCKED - User disagrees with current approach

**User Disagreement:**
User explicitly stated: "note current issue and note that I disagree with your current approach"

This disagreement was expressed after I attempted to solve the docs accessibility issue by:
1. Adding specific GET routes in API Gateway for `/v1/docs`, `/v1/redoc`, `/v1/openapi.json` without authorizer
2. Modifying `src/api/main.py` to configure FastAPI's docs URLs with `/v1` prefix

## Problem Statement

### The Issue

FastAPI automatically generates interactive API documentation at:
- `/docs` - Swagger UI
- `/redoc` - ReDoc UI
- `/openapi.json` - OpenAPI schema

However, these endpoints are currently inaccessible because:
1. API Gateway has a Lambda Authorizer that requires Bearer token on all requests
2. The current API Gateway resource structure (after Option B) only has explicit routes for `/v1/events`
3. FastAPI's default docs paths don't match our `/v1/*` prefix structure

### Current Behavior

```bash
# Expected: Interactive Swagger UI
curl https://hooks.vincentchan.cloud/v1/docs

# Actual: 404 Not Found
# Reason: No API Gateway route defined for /v1/docs
```

## My Attempted Solution (User Disagrees)

### Approach Taken

I attempted a two-part fix:

**Part 1: Add specific API Gateway routes without authorizer**
- Modified `cdk/stacks/webhook_delivery_stack.py`
- Added GET methods for `/v1/docs`, `/v1/redoc`, `/v1/openapi.json`
- Did NOT attach Lambda Authorizer to these routes (public access)
- **Result:** Deployed, but got 404 errors

**Part 2: Configure FastAPI docs URLs**
- Modified `src/api/main.py`
- Added `docs_url="/v1/docs"`, `redoc_url="/v1/redoc"`, `openapi_url="/v1/openapi.json"`
- **Result:** Not deployed - user interrupted and disagreed with approach

### Why This Approach

My reasoning was:
- Keep `/v1` prefix consistent across all endpoints
- Use API Gateway routing to control which paths require auth
- Let FastAPI serve docs at custom paths matching our URL structure

### User's Disagreement

User disagrees with modifying FastAPI's built-in docs URLs to include `/v1` prefix.

**User's perspective (inferred):**
- Documentation paths are "not customer-facing"
- Similar to how user said `/v1` prefix handling "is not important so long it's handled as it's not customer-facing"
- Likely prefers a simpler solution that doesn't require changing FastAPI configuration

## Uncommitted Changes (Not Deployed)

### File 1: `cdk/stacks/webhook_delivery_stack.py`

**Lines 328-345** - Added specific docs routes:
```python
# Add public docs endpoints (no auth required)
docs_resource = v1_resource.add_resource("docs")
docs_resource.add_method("GET", lambda_integration)

redoc_resource = v1_resource.add_resource("redoc")
redoc_resource.add_method("GET", lambda_integration)

openapi_resource = v1_resource.add_resource("openapi.json")
openapi_resource.add_method("GET", lambda_integration)

# Create /v1/events resource with authorizer
events_resource = v1_resource.add_resource("events")
events_resource.add_method(
    "POST",
    lambda_integration,
    authorization_type=apigateway.AuthorizationType.CUSTOM,
    authorizer=self.token_authorizer,
)
```

**Changes:**
- Removed catch-all `/{proxy+}` route
- Added explicit GET routes for docs/redoc/openapi.json
- These routes have NO authorizer (public access intended)

**Issue:**
- Deployed this change, but got 404 because FastAPI serves docs at `/docs` not `/v1/docs`

### File 2: `src/api/main.py`

**Lines 5-12** - Configured FastAPI docs URLs:
```python
app = FastAPI(
    title="Webhook Delivery API",
    description="Multi-tenant webhook delivery system",
    version="2.0.0",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    openapi_url="/v1/openapi.json",
)
```

**Changes:**
- Added `docs_url="/v1/docs"` (default: `/docs`)
- Added `redoc_url="/v1/redoc"` (default: `/redoc`)
- Added `openapi_url="/v1/openapi.json"` (default: `/openapi.json`)

**User Disagreement:**
- User stopped deployment before this change went live
- Explicitly disagreed with this approach

## Alternative Approaches (Not Yet Discussed)

### Option 1: Add catch-all `/{proxy+}` route without auth

```python
# In webhook_delivery_stack.py
v1_proxy_resource = v1_resource.add_resource("{proxy+}")
v1_proxy_resource.add_method("ANY", lambda_integration)  # No authorizer
```

**Pros:**
- FastAPI handles all routing naturally at default paths
- No need to modify FastAPI configuration
- Docs accessible at `/v1/docs`, `/v1/redoc`, `/v1/openapi.json`

**Cons:**
- Makes ALL `/v1/*` paths publicly accessible
- Would need to move auth into FastAPI middleware (undoing Option B work)

### Option 2: Use API Gateway request transformation

```python
# Map /docs to /v1/docs at API Gateway level
# Keep FastAPI serving at default /docs path
```

**Pros:**
- No FastAPI changes
- Keeps auth at API Gateway level

**Cons:**
- Complex API Gateway configuration
- May not work well with Lambda proxy integration

### Option 3: Separate docs-only Lambda/endpoint

Create dedicated endpoint just for docs:
- `https://hooks.vincentchan.cloud/docs` (no /v1 prefix)
- Separate API Gateway route or even separate API
- Points to same FastAPI Lambda but bypasses auth

**Pros:**
- Clean separation of concerns
- Docs at simple `/docs` path

**Cons:**
- Additional infrastructure
- More complex setup

### Option 4: Keep docs at root, not under `/v1`

```python
# In webhook_delivery_stack.py
# Add docs routes at root level, not under /v1
docs_resource = self.api.root.add_resource("docs")
docs_resource.add_method("GET", lambda_integration)
```

**Pros:**
- Docs at `/docs` (standard path)
- No FastAPI changes needed
- Simple and clean

**Cons:**
- Inconsistent with `/v1/events` pattern
- Lambda receives `/docs` instead of `/v1/docs`

## Current Git State

**Uncommitted Changes:**
```bash
M  cdk/stacks/webhook_delivery_stack.py  # Added docs routes, removed /{proxy+}
M  src/api/main.py                        # Configured docs URLs (user disagrees)
```

**Last Commit:**
```
commit: [hash from 'Update README with Option B implementation']
- README.md updates
- All functional changes from Option B
```

**Working State:**
- Custom domain `/v1/events` fully working
- Bearer token auth working via Lambda Authorizer
- All integration tests passing
- Docs endpoints NOT accessible

## Recommended Next Steps

### Immediate Action Needed

**Wait for user guidance on preferred approach.**

User has indicated disagreement with modifying FastAPI's built-in docs URLs. Before proceeding:

1. **Understand user's preferred solution**
   - Does user want docs at `/docs` or `/v1/docs`?
   - Is auth required for docs, or should they be public?
   - Which of the alternative approaches aligns with user's vision?

2. **Decide on uncommitted changes**
   - Keep the API Gateway routes for docs/redoc/openapi.json?
   - Revert `src/api/main.py` changes?
   - Try a different approach?

### If Reverting Current Approach

```bash
# Revert uncommitted changes
git checkout src/api/main.py

# Optionally revert CDK changes too
git checkout cdk/stacks/webhook_delivery_stack.py
```

### If Proceeding with Option 4 (Root-level docs)

```python
# In webhook_delivery_stack.py, at root level:
docs_resource = self.api.root.add_resource("docs")
docs_resource.add_method("GET", lambda_integration)

redoc_resource = self.api.root.add_resource("redoc")
redoc_resource.add_method("GET", lambda_integration)

openapi_resource = self.api.root.add_resource("openapi.json")
openapi_resource.add_method("GET", lambda_integration)
```

Then FastAPI serves docs at default `/docs` path, API Gateway routes it directly.

## Context

### What's Working

✅ Core webhook delivery system functional
✅ Custom domain: `https://hooks.vincentchan.cloud/v1/events`
✅ Lambda Authorizer with Bearer token validation
✅ 5-minute authorizer result caching
✅ DynamoDB event storage
✅ SQS queue processing
✅ All integration tests passing

### What's Not Working

❌ Swagger UI not accessible
❌ ReDoc not accessible
❌ OpenAPI schema not accessible

### Key Constraints

**From user feedback:**
- Documentation paths are "not customer-facing"
- Simplicity preferred over configuration complexity
- User disagrees with changing FastAPI's default docs URLs

**Technical constraints:**
- FastAPI default docs paths: `/docs`, `/redoc`, `/openapi.json`
- API Gateway has explicit `/v1/events` route with authorizer
- Lambda proxy integration passes full path to FastAPI
- Current pattern: All customer-facing endpoints under `/v1/*`

## Files and References

**Modified but not deployed:**
- [src/api/main.py:5-12](src/api/main.py#L5-L12) - FastAPI docs URL config (user disagrees)
- [cdk/stacks/webhook_delivery_stack.py:328-345](cdk/stacks/webhook_delivery_stack.py#L328-L345) - Docs routes

**Related documentation:**
- FastAPI docs: https://fastapi.tiangolo.com/tutorial/metadata/
- API Gateway custom authorizers: https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-use-lambda-authorizer.html

**Previous work:**
- Option B implementation: [2025-11-22_18-04-11_try-option-a-regional-endpoint.md](thoughts/shared/handoffs/general/2025-11-22_18-04-11_try-option-a-regional-endpoint.md)
- Lambda Authorizer: [2025-11-22_16-15-36_lambda-authorizer-phases-1-4-complete.md](thoughts/shared/handoffs/general/2025-11-22_16-15-36_lambda-authorizer-phases-1-4-complete.md)

## Questions for User

1. **Where should docs be accessible?**
   - `/docs` (root level, standard path)
   - `/v1/docs` (consistent with API versioning)
   - Different domain/subdomain entirely

2. **Should docs require authentication?**
   - Public (no auth required)
   - Require Bearer token (current behavior)

3. **Preferred approach?**
   - Option 4: Root-level docs routes (`/docs`, `/redoc`, `/openapi.json`)
   - Different option from alternatives listed above
   - Something else entirely

## Success Criteria

Documentation will be considered accessible when:
- [ ] User can visit docs URL and see Swagger UI
- [ ] OpenAPI schema is downloadable
- [ ] Solution aligns with user's preferences
- [ ] No unnecessary complexity in configuration
- [ ] Maintains current auth setup for `/v1/events`

---

**Next Session:** Wait for user direction before making changes.
