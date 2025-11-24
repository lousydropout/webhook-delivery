# Future Improvements & Technical Debt

**Last Updated**: 2025-11-24  
**Status**: Planning Phase

## Overview

This document tracks identified improvements, technical debt, and future enhancements for the RESTful API refactoring project.

---

## High Priority Improvements

### 1. DynamoDB GSI for Tenant Lookups ⚠️ Performance Issue

**Current State**:

- `get_tenant_by_id()` uses `table.scan()` with FilterExpression
- `update_tenant_config_by_id()` uses `table.scan()` to find API key
- Inefficient for production scale (O(n) scan vs O(1) query)

**Impact**:

- Slow performance as tenant count grows
- Higher DynamoDB costs (scan operations consume more RCU)
- Potential timeout issues with many tenants

**Proposed Solution**:
Add Global Secondary Index (GSI) on `tenantId` field

**Implementation Plan**:

1. **CDK Infrastructure Update** (`cdk/stacks/webhook_delivery_stack.py`):

   ```python
   # Add GSI to TenantApiKeys table
   tenant_api_keys_table = dynamodb.Table(
       self,
       "TenantApiKeys",
       table_name=f"{prefix}-TenantApiKeys",
       partition_key=dynamodb.Attribute(
           name="apiKey",
           type=dynamodb.AttributeType.STRING
       ),
       billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
       removal_policy=RemovalPolicy.DESTROY,
   )

   # Add GSI for tenantId lookups
   tenant_api_keys_table.add_global_secondary_index(
       index_name="tenantId-index",
       partition_key=dynamodb.Attribute(
           name="tenantId",
           type=dynamodb.AttributeType.STRING
       ),
   )
   ```

2. **Update DynamoDB Functions** (`src/api/dynamo.py`):

   ```python
   def get_tenant_by_id(tenant_id: str) -> Optional[Dict[str, Any]]:
       """Get tenant details by tenant ID using GSI."""
       tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])

       try:
           # Use GSI query instead of scan
           response = tenant_api_keys_table.query(
               IndexName="tenantId-index",
               KeyConditionExpression="tenantId = :tid",
               ExpressionAttributeValues={":tid": tenant_id}
           )

           items = response.get("Items", [])
           if not items:
               return None

           tenant = items[0]
           # ... rest of function
   ```

3. **Migration Considerations**:
   - GSI creation is non-breaking (existing data automatically indexed)
   - No code changes needed during GSI creation
   - Update functions after GSI is active
   - Test with existing tenants

**Estimated Effort**: 2-3 hours  
**Priority**: High (performance impact)  
**Risk**: Low (non-breaking change)

---

### 2. Admin Authorization for Tenant Creation 🔒 Security Enhancement

**Current State**:

- `POST /v1/tenants` allows any authenticated user to create tenants
- TODO comment at `src/api/routes.py:408`
- No role-based access control

**Impact**:

- Security risk: Any API key can create tenants
- Potential abuse: Unauthorized tenant creation
- Billing concerns: Unlimited tenant creation

**Proposed Solutions**:

#### Option A: Admin Role Check (Recommended)

Add admin role to authorizer context and check in endpoint:

```python
@router.post("/v1/tenants", response_model=TenantCreateResponse, status_code=201)
async def create_new_tenant(
    request: Request,
    tenant: TenantCreate,
):
    """Create a new tenant with auto-generated API key."""

    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})
    tenant_context = get_tenant_from_context(event)

    # Check if user has admin role
    if tenant_context.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required to create tenants"
        )

    # ... rest of function
```

**Requirements**:

- Update Lambda Authorizer to include role in context
- Add `role` field to TenantApiKeys table (or separate AdminUsers table)
- Update authorizer to check admin status

#### Option B: Self-Service Signup Flow

Allow public signup with email verification:

```python
@router.post("/v1/tenants/signup", response_model=TenantCreateResponse, status_code=201)
async def signup_tenant(
    tenant: TenantSignup,  # Includes email, verification token
):
    """Self-service tenant signup with email verification."""
    # Verify email token
    # Create tenant
    # Send welcome email with API key
```

**Requirements**:

- Email verification service
- Public endpoint (no auth required)
- Rate limiting to prevent abuse

#### Option C: Separate Admin Endpoint

Create admin-only endpoint with different authentication:

```python
@router.post("/v1/admin/tenants", response_model=TenantCreateResponse, status_code=201)
async def admin_create_tenant(
    request: Request,
    tenant: TenantCreate,
):
    """Admin-only tenant creation."""
    # Check admin credentials
    # Create tenant
```

**Requirements**:

- Separate admin authentication mechanism
- Admin API keys or IAM roles

**Recommendation**: Option A (Admin Role Check)  
**Estimated Effort**: 4-6 hours  
**Priority**: Medium (security best practice)  
**Risk**: Medium (requires authorizer changes)

---

## Medium Priority Improvements

### 3. Enhanced Error Messages

**Current State**:

- Generic error messages in some cases
- Limited context for debugging

**Proposed Improvements**:

- Add request ID to error responses
- Include more context in validation errors
- Add error codes for programmatic handling

**Estimated Effort**: 2-3 hours  
**Priority**: Medium  
**Risk**: Low

---

### 4. Rate Limiting Per Tenant

**Current State**:

- API Gateway has global rate limits (500 req/sec)
- No per-tenant rate limiting

**Proposed Solution**:

- Implement per-tenant rate limiting using DynamoDB
- Track request counts per tenant
- Return 429 Too Many Requests when exceeded

**Estimated Effort**: 4-6 hours  
**Priority**: Medium  
**Risk**: Medium (requires careful implementation)

---

### 5. Event Webhooks (Meta-Webhooks)

**Current State**:

- No notification when events are delivered/failed
- Manual polling required to check status

**Proposed Solution**:

- Add webhook URL for event status changes
- Send webhook when event status changes
- Include event details in webhook payload

**Estimated Effort**: 6-8 hours  
**Priority**: Low  
**Risk**: Medium (adds complexity)

---

## Low Priority / Future Enhancements

### 6. Bulk Event Creation

**Proposed Endpoint**:

```
POST /v1/events/bulk
{
  "events": [
    {"event": "user.signup", "user_id": "123"},
    {"event": "order.created", "order_id": "456"}
  ]
}
```

**Estimated Effort**: 3-4 hours  
**Priority**: Low

---

### 7. Event Export

**Proposed Endpoints**:

```
GET /v1/events/export?format=csv
GET /v1/events/export?format=json
```

**Estimated Effort**: 4-6 hours  
**Priority**: Low

---

### 8. Dashboard Statistics Endpoint

**Proposed Endpoint**:

```
GET /v1/stats
{
  "total_events": 1234,
  "events_by_status": {
    "PENDING": 10,
    "DELIVERED": 1200,
    "FAILED": 24
  },
  "events_last_24h": 56
}
```

**Estimated Effort**: 3-4 hours  
**Priority**: Low

---

## Implementation Priority

### Phase 1 (Immediate - Next Sprint)

1. ✅ DynamoDB GSI for tenant lookups (Performance)
2. ⏳ Admin authorization for tenant creation (Security)

### Phase 2 (Next Month)

3. Enhanced error messages
4. Rate limiting per tenant

### Phase 3 (Future)

5. Event webhooks
6. Bulk operations
7. Export functionality
8. Statistics endpoint

---

## Notes

- **Breaking Changes**: None of these improvements require breaking changes
- **Backward Compatibility**: All improvements maintain API compatibility
- **Testing**: Each improvement should include comprehensive tests
- **Documentation**: Update API docs and guides as improvements are made

---

## References

- Current implementation: `src/api/routes.py`, `src/api/dynamo.py`
- Infrastructure: `cdk/stacks/webhook_delivery_stack.py`
- TODO comments: `src/api/routes.py:408`, `src/api/dynamo.py:285,337`
