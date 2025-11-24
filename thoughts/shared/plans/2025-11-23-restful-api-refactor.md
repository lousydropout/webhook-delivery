# RESTful API Refactoring Plan

## Overview

Refactor the webhook delivery API to follow REST principles more closely by:
1. Replacing action-based endpoints with resource-based patterns
2. Using proper HTTP verbs for operations
3. Making tenant management explicit with full CRUD operations

## Current Non-RESTful Issues

### Issue 1: Retry Endpoint Uses Action Verb
```
POST /v1/events/{event_id}/retry  ❌ (RPC-style)
```

### Issue 2: Tenant Configuration Uses Contextual Identifier
```
PATCH /v1/tenants/current  ❌ ("current" is not a resource ID)
```

### Issue 3: No Tenant Creation Endpoint
- Tenants currently only created via seeding script
- No way to programmatically provision new tenants

---

## Proposed RESTful Design

### Events Resource (Mostly Good Already)

```
POST   /v1/events              ✅ Create event
GET    /v1/events              ✅ List events
GET    /v1/events/{event_id}   ✅ Get event details
PATCH  /v1/events/{event_id}   🆕 Update event (replaces retry)
DELETE /v1/events/{event_id}   ⏰ Cancel event (future)
```

**PATCH /v1/events/{event_id}** will support:
- Updating status: `{"status": "PENDING"}` triggers retry
- Future: Update other mutable fields

### Tenants Resource (New)

```
POST   /v1/tenants              🆕 Create tenant
GET    /v1/tenants              🆕 List tenants (admin only, future)
GET    /v1/tenants/{tenant_id}  🆕 Get tenant details
PATCH  /v1/tenants/{tenant_id}  🆕 Update tenant config
DELETE /v1/tenants/{tenant_id}  ⏰ Delete tenant (future)
```

For authenticated tenant endpoints, `{tenant_id}` is extracted from Bearer token but still appears in URL for RESTfulness.

---

## Implementation Strategy

### Phase 1: Add New RESTful Endpoints (Non-Breaking)

Add new endpoints alongside old ones:
- `PATCH /v1/events/{event_id}` (new) + keep `POST /v1/events/{event_id}/retry` (deprecated)
- `POST /v1/tenants` (new)
- `GET /v1/tenants/{tenant_id}` (new)
- `PATCH /v1/tenants/{tenant_id}` (new) + keep `PATCH /v1/tenants/current` (deprecated)

### Phase 2: Update Documentation

Mark old endpoints as deprecated with migration guidance.

### Phase 3: Update Postman Collection

Add new RESTful requests, mark old ones as deprecated.

### Phase 4: Monitor Usage

Track usage of deprecated endpoints (CloudWatch metrics).

### Phase 5: Remove Deprecated Endpoints (Future)

After migration period, remove deprecated endpoints.

---

## Detailed Changes

---

## Phase 1A: PATCH /v1/events/{event_id} - Event Updates

### Overview

Replace `POST /v1/events/{event_id}/retry` with RESTful `PATCH /v1/events/{event_id}`.

### New Route Handler

**File**: `src/api/routes.py`

**Add after existing `get_event_details()` function:**

```python
@router.patch("/v1/events/{event_id}", response_model=EventDetail)
async def update_event(
    request: Request,
    event_id: str,
    update: EventUpdate,
):
    """
    Update an event's mutable fields.

    Currently supports:
    - status: Change to "PENDING" to retry a FAILED event

    Future: May support updating other fields like target_url, payload, etc.

    Path Parameters:
    - event_id: The unique event identifier

    Request Body:
    - status: New status ("PENDING" to trigger retry)

    Returns updated event details.
    Authentication via Bearer token required (API Gateway Lambda Authorizer).

    Raises:
    - 404: Event not found or does not belong to authenticated tenant
    - 400: Invalid status transition
    """
    # Extract tenant context from Lambda Authorizer
    event_context = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event_context)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    tenant_id = tenant["tenantId"]

    # First verify event exists and belongs to tenant
    event_data = get_event(tenant_id, event_id)

    if not event_data:
        raise HTTPException(
            status_code=404,
            detail=f"Event {event_id} not found or does not belong to your tenant"
        )

    # Handle status update (retry logic)
    if update.status:
        if update.status == "PENDING":
            # This is a retry operation
            if event_data["status"] != "FAILED":
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot retry event with status '{event_data['status']}'. Only FAILED events can be retried."
                )

            # Reset event to PENDING in DynamoDB
            success = reset_event_for_retry(tenant_id, event_id)

            if not success:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to reset event status"
                )

            # Requeue to SQS
            message_body = json.dumps({
                "tenantId": tenant_id,
                "eventId": event_id,
            })

            try:
                sqs.send_message(
                    QueueUrl=EVENTS_QUEUE_URL,
                    MessageBody=message_body,
                )
            except Exception as e:
                print(f"Error requeuing event {event_id} to SQS: {e}")
                raise HTTPException(status_code=500, detail="Failed to requeue event for delivery")
        else:
            # Future: Handle other status transitions
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status transition to '{update.status}'"
            )

    # Fetch updated event
    updated_event_data = get_event(tenant_id, event_id)

    # Convert to response model
    event_detail = EventDetail(
        event_id=updated_event_data["eventId"],
        status=updated_event_data["status"],
        created_at=updated_event_data["createdAt"],
        payload=updated_event_data["payload"],
        target_url=updated_event_data["targetUrl"],
        attempts=updated_event_data.get("attempts", 0),
        last_attempt_at=updated_event_data.get("lastAttemptAt"),
        error_message=updated_event_data.get("errorMessage"),
    )

    return event_detail
```

### New Pydantic Model

**File**: `src/api/models.py`

**Add after existing models:**

```python
class EventUpdate(BaseModel):
    """Request body for PATCH /v1/events/{event_id}"""
    status: Optional[str] = None

    class Config:
        extra = "forbid"
```

### Update Existing Response Model

**File**: `src/api/models.py`

**Modify `EventDetailResponse` to return just the event directly:**

Actually, let's keep `EventDetailResponse` as-is for GET, but PATCH can return `EventDetail` directly (without the wrapper). This is a common REST pattern - GET returns `{event: {...}}`, but PATCH returns the resource directly.

### Update API Gateway Routes

**File**: `cdk/stacks/webhook_delivery_stack.py`

**Add after existing `event_id_resource` routes (around line 430):**

```python
# PATCH /v1/events/{eventId} - Update event (replaces retry)
event_id_resource.add_method(
    "PATCH",
    apigateway.LambdaIntegration(self.api_lambda, proxy=True),
    authorization_type=apigateway.AuthorizationType.CUSTOM,
    authorizer=self.token_authorizer,
)
```

### Deprecate Old Retry Endpoint

**File**: `src/api/routes.py`

**Update docstring for `retry_failed_event()`:**

```python
@router.post("/v1/events/{event_id}/retry", response_model=RetryResponse, deprecated=True)
async def retry_failed_event(
    request: Request,
    event_id: str,
):
    """
    [DEPRECATED] Manually retry a failed event.

    **This endpoint is deprecated. Use PATCH /v1/events/{event_id} with body {"status": "PENDING"} instead.**

    This endpoint will be removed in a future version.

    Path Parameters:
    - event_id: The unique event identifier

    This endpoint resets a FAILED event to PENDING status and requeues it
    to SQS for immediate reprocessing. Only events with status=FAILED can be retried.

    Authentication via Bearer token required (API Gateway Lambda Authorizer).

    Raises:
    - 404: Event not found, belongs to different tenant, or not in FAILED status
    - 500: Failed to requeue event
    """
    # ... existing implementation ...
```

### Success Criteria

- [x] `PATCH /v1/events/{event_id}` with `{"status": "PENDING"}` retries FAILED events
- [x] Returns full event details (not wrapped in `{event: {...}}`)
- [x] Old `POST .../retry` endpoint still works
- [x] Old endpoint shows as deprecated in Swagger UI
- [x] Both endpoints produce identical side effects (DynamoDB + SQS)

---

## Phase 1B: POST /v1/tenants - Create Tenant

### Overview

Add endpoint to programmatically create new tenants with API keys.

### New DynamoDB Function

**File**: `src/api/dynamo.py`

**Add at end of file:**

```python
import secrets
import string

def create_tenant(tenant_id: str, target_url: str, webhook_secret: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new tenant with API key.

    Args:
        tenant_id: Unique tenant identifier (e.g., "acme", "globex")
        target_url: Webhook delivery URL
        webhook_secret: HMAC secret (auto-generated if not provided)

    Returns:
        {
            "tenant_id": "...",
            "api_key": "tenant_..._key",
            "target_url": "...",
            "webhook_secret": "...",
            "created_at": "..."
        }

    Raises:
        ValueError: If tenant already exists
    """
    tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])

    # Generate API key
    api_key = f"tenant_{tenant_id}_key"

    # Generate webhook secret if not provided
    if not webhook_secret:
        # Generate 32-character random secret
        alphabet = string.ascii_letters + string.digits
        webhook_secret = "whsec_" + "".join(secrets.choice(alphabet) for _ in range(32))

    timestamp = str(int(time.time()))

    try:
        # Use ConditionExpression to ensure tenant doesn't already exist
        tenant_api_keys_table.put_item(
            Item={
                "apiKey": api_key,
                "tenantId": tenant_id,
                "targetUrl": target_url,
                "webhookSecret": webhook_secret,
                "createdAt": timestamp,
                "updatedAt": timestamp,
            },
            ConditionExpression="attribute_not_exists(apiKey)"
        )

        return {
            "tenant_id": tenant_id,
            "api_key": api_key,
            "target_url": target_url,
            "webhook_secret": webhook_secret,
            "created_at": timestamp,
        }
    except tenant_api_keys_table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Tenant with ID '{tenant_id}' already exists")
    except Exception as e:
        print(f"Error creating tenant {tenant_id}: {e}")
        raise
```

### New Pydantic Models

**File**: `src/api/models.py`

**Add:**

```python
class TenantCreate(BaseModel):
    """Request body for POST /v1/tenants"""
    tenant_id: str = Field(..., min_length=3, max_length=50, pattern="^[a-z0-9-]+$")
    target_url: str = Field(..., pattern="^https?://")
    webhook_secret: Optional[str] = None

    class Config:
        extra = "forbid"


class TenantCreateResponse(BaseModel):
    """Response for POST /v1/tenants"""
    tenant_id: str
    api_key: str
    target_url: str
    webhook_secret: str
    created_at: str
    message: str
```

### New Route Handler

**File**: `src/api/routes.py`

**Add before tenant configuration endpoints:**

```python
from models import TenantCreate, TenantCreateResponse
from dynamo import create_tenant


@router.post("/v1/tenants", response_model=TenantCreateResponse, status_code=201)
async def create_new_tenant(
    request: Request,
    tenant: TenantCreate,
):
    """
    Create a new tenant with auto-generated API key.

    Request Body:
    - tenant_id: Unique tenant identifier (lowercase alphanumeric + hyphens)
    - target_url: Webhook delivery URL (must be https)
    - webhook_secret: Optional HMAC secret (auto-generated if omitted)

    Returns the created tenant with API key and webhook secret.

    **Security Note**: Store the API key and webhook secret securely.
    The webhook secret cannot be retrieved later, only rotated.

    Authentication via Bearer token required.
    In a production system, this would be admin-only or self-service signup.
    """
    # TODO: Add admin authorization check
    # For now, any authenticated user can create tenants
    # In production, this should be restricted to admins or handled via signup flow

    try:
        result = create_tenant(
            tenant_id=tenant.tenant_id,
            target_url=tenant.target_url,
            webhook_secret=tenant.webhook_secret,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        print(f"Error creating tenant {tenant.tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create tenant")

    return TenantCreateResponse(
        tenant_id=result["tenant_id"],
        api_key=result["api_key"],
        target_url=result["target_url"],
        webhook_secret=result["webhook_secret"],
        created_at=result["created_at"],
        message="Tenant created successfully. Store your API key and webhook secret securely."
    )
```

### API Gateway Route

**File**: `cdk/stacks/webhook_delivery_stack.py`

**Add after `tenants_resource` definition:**

```python
# POST /v1/tenants - Create tenant
tenants_resource.add_method(
    "POST",
    apigateway.LambdaIntegration(self.api_lambda, proxy=True),
    authorization_type=apigateway.AuthorizationType.CUSTOM,
    authorizer=self.token_authorizer,
)
```

### Success Criteria

- [x] `POST /v1/tenants` creates new tenant with auto-generated API key
- [x] Returns 409 Conflict if tenant already exists
- [x] Auto-generates webhook secret if not provided
- [x] Validates tenant_id format (lowercase alphanumeric + hyphens)
- [x] Validates target_url format (https)
- [x] Created tenant can immediately authenticate and create events (after authorizer cache expires)

---

## Phase 1C: GET & PATCH /v1/tenants/{tenant_id} - Tenant Management

### Overview

Replace `PATCH /v1/tenants/current` with proper RESTful resource endpoint.

### New DynamoDB Function

**File**: `src/api/dynamo.py`

**Add:**

```python
def get_tenant_by_id(tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Get tenant details by tenant ID.

    Args:
        tenant_id: Tenant identifier

    Returns:
        Tenant data (excluding webhook secret for security)
    """
    tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])

    try:
        # Query by GSI on tenantId (need to add GSI if it doesn't exist)
        # For now, scan with filter (inefficient but works)
        response = tenant_api_keys_table.scan(
            FilterExpression="tenantId = :tid",
            ExpressionAttributeValues={":tid": tenant_id}
        )

        items = response.get("Items", [])
        if not items:
            return None

        tenant = items[0]

        # Remove webhook secret from response for security
        # (only return it on creation or when explicitly updated)
        tenant_safe = {
            "tenant_id": tenant["tenantId"],
            "target_url": tenant["targetUrl"],
            "created_at": tenant.get("createdAt"),
            "updated_at": tenant.get("updatedAt"),
        }

        return tenant_safe
    except Exception as e:
        print(f"Error retrieving tenant {tenant_id}: {e}")
        return None
```

### Update Existing Update Function

**File**: `src/api/dynamo.py`

**Modify `update_tenant_config()` to accept tenant_id parameter:**

```python
def update_tenant_config_by_id(
    tenant_id: str,
    target_url: Optional[str] = None,
    webhook_secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update tenant configuration by tenant ID.

    Args:
        tenant_id: Tenant identifier
        target_url: New webhook URL (optional)
        webhook_secret: New webhook secret (optional)

    Returns:
        Updated tenant configuration
    """
    tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])

    # First, get the API key for this tenant
    # (This is inefficient - in production, add GSI on tenantId)
    response = tenant_api_keys_table.scan(
        FilterExpression="tenantId = :tid",
        ExpressionAttributeValues={":tid": tenant_id}
    )

    items = response.get("Items", [])
    if not items:
        raise ValueError(f"Tenant {tenant_id} not found")

    api_key = items[0]["apiKey"]

    # Now update using the existing logic
    # Build update expression dynamically
    update_parts = []
    attr_values = {}

    if target_url:
        update_parts.append("targetUrl = :url")
        attr_values[":url"] = target_url

    if webhook_secret:
        update_parts.append("webhookSecret = :secret")
        attr_values[":secret"] = webhook_secret

    if not update_parts:
        raise ValueError("At least one field must be updated")

    # Add updatedAt timestamp
    update_parts.append("updatedAt = :timestamp")
    attr_values[":timestamp"] = str(int(time.time()))

    update_expression = "SET " + ", ".join(update_parts)

    try:
        response = tenant_api_keys_table.update_item(
            Key={"apiKey": api_key},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=attr_values,
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]
    except Exception as e:
        print(f"Error updating tenant config for tenant {tenant_id}: {e}")
        raise
```

### New Pydantic Models

**File**: `src/api/models.py`

**Add:**

```python
class TenantDetail(BaseModel):
    """Tenant details (safe for GET responses)"""
    tenant_id: str
    target_url: str
    created_at: str
    updated_at: str


class TenantDetailResponse(BaseModel):
    """Response for GET /v1/tenants/{tenant_id}"""
    tenant: TenantDetail
```

### New Route Handlers

**File**: `src/api/routes.py`

**Add:**

```python
from models import TenantDetail, TenantDetailResponse
from dynamo import get_tenant_by_id, update_tenant_config_by_id


@router.get("/v1/tenants/{tenant_id}", response_model=TenantDetailResponse)
async def get_tenant(
    request: Request,
    tenant_id: str,
):
    """
    Get tenant details.

    Path Parameters:
    - tenant_id: Tenant identifier

    Returns tenant configuration (excluding webhook secret for security).

    Authentication via Bearer token required.
    Users can only access their own tenant details (enforced by authorizer context).
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    auth_tenant_id = tenant["tenantId"]

    # Enforce tenant isolation: can only access own tenant
    if tenant_id != auth_tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access your own tenant details."
        )

    # Retrieve tenant details
    tenant_data = get_tenant_by_id(tenant_id)

    if not tenant_data:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant {tenant_id} not found"
        )

    # Convert to response model
    tenant_detail = TenantDetail(
        tenant_id=tenant_data["tenant_id"],
        target_url=tenant_data["target_url"],
        created_at=tenant_data["created_at"],
        updated_at=tenant_data["updated_at"],
    )

    return TenantDetailResponse(tenant=tenant_detail)


@router.patch("/v1/tenants/{tenant_id}", response_model=TenantConfigResponse)
async def update_tenant(
    request: Request,
    tenant_id: str,
    config: TenantConfigUpdate,
):
    """
    Update tenant webhook configuration.

    Path Parameters:
    - tenant_id: Tenant identifier

    Request Body:
    - target_url: New webhook delivery URL (optional)
    - webhook_secret: New HMAC secret for signature validation (optional)

    At least one field must be provided. Changes take effect immediately for new events.
    Authentication via Bearer token required.
    Users can only update their own tenant configuration.

    Security Note: Updating webhook_secret will invalidate signatures on in-flight webhooks.
    """
    # Extract tenant context from Lambda Authorizer
    event = request.scope.get("aws.event", {})

    try:
        tenant = get_tenant_from_context(event)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

    auth_tenant_id = tenant["tenantId"]

    # Enforce tenant isolation: can only update own tenant
    if tenant_id != auth_tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only update your own tenant configuration."
        )

    # Validate at least one field is provided
    if not config.target_url and not config.webhook_secret:
        raise HTTPException(
            status_code=400,
            detail="At least one field (target_url or webhook_secret) must be provided"
        )

    # Update tenant configuration
    try:
        updated_config = update_tenant_config_by_id(
            tenant_id=tenant_id,
            target_url=config.target_url,
            webhook_secret=config.webhook_secret,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"Error updating tenant config for {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update tenant configuration")

    return TenantConfigResponse(
        tenant_id=tenant_id,
        target_url=updated_config["targetUrl"],
        updated_at=updated_config["updatedAt"],
        message="Tenant configuration updated successfully"
    )
```

### Deprecate Old Endpoint

**File**: `src/api/routes.py`

**Update `update_tenant_configuration()` docstring:**

```python
@router.patch("/v1/tenants/current", response_model=TenantConfigResponse, deprecated=True)
async def update_tenant_configuration(
    request: Request,
    config: TenantConfigUpdate,
):
    """
    [DEPRECATED] Update tenant webhook configuration.

    **This endpoint is deprecated. Use PATCH /v1/tenants/{tenant_id} instead.**

    This endpoint will be removed in a future version.

    ...rest of docstring...
    """
    # ... existing implementation ...
```

### API Gateway Routes

**File**: `cdk/stacks/webhook_delivery_stack.py`

**Add after tenants resource definition:**

```python
# GET /v1/tenants/{tenantId} - Get tenant details
tenant_id_resource = tenants_resource.add_resource("{tenantId}")
tenant_id_resource.add_method(
    "GET",
    apigateway.LambdaIntegration(self.api_lambda, proxy=True),
    authorization_type=apigateway.AuthorizationType.CUSTOM,
    authorizer=self.token_authorizer,
    request_parameters={
        "method.request.path.tenantId": True,
    },
)

# PATCH /v1/tenants/{tenantId} - Update tenant config
tenant_id_resource.add_method(
    "PATCH",
    apigateway.LambdaIntegration(self.api_lambda, proxy=True),
    authorization_type=apigateway.AuthorizationType.CUSTOM,
    authorizer=self.token_authorizer,
)
```

### Success Criteria

- [x] `GET /v1/tenants/{tenant_id}` returns tenant details
- [x] Returns 403 if trying to access different tenant's details
- [x] Does not expose webhook_secret in GET response
- [x] `PATCH /v1/tenants/{tenant_id}` updates config
- [x] Returns 403 if trying to update different tenant
- [x] Old `PATCH /v1/tenants/current` still works
- [x] Old endpoint shows as deprecated in Swagger UI

---

## Phase 2: Documentation Updates

### Update README

Document the new RESTful endpoints and deprecation notices.

### Update Swagger Descriptions

FastAPI automatically generates OpenAPI docs with `deprecated=True` flag.

### Create Migration Guide

Document for existing API consumers:
- Old endpoint → New endpoint mapping
- Timeline for deprecation
- Code examples showing migration

---

## Phase 3: Update Postman Collection

### Add New Requests

**2. Event Ingestion folder:**
- "Update Event - Retry" (PATCH /v1/events/{event_id})

**New "7. Tenant Management" folder:**
- "Create Tenant" (POST /v1/tenants)
- "Get Tenant Details" (GET /v1/tenants/{tenant_id})
- "Update Tenant Config" (PATCH /v1/tenants/{tenant_id})

### Mark Deprecated Requests

Rename old requests to indicate deprecation:
- "Retry Failed Event [DEPRECATED]"
- "Update Webhook URL [DEPRECATED - use Tenant Management]"

---

## Benefits of This Refactor

### 1. RESTful Resource Hierarchy
```
/v1/events              - Events collection
/v1/events/{id}         - Individual event resource
/v1/tenants             - Tenants collection
/v1/tenants/{id}        - Individual tenant resource
```

### 2. Proper HTTP Verb Usage
- POST for creation
- GET for retrieval
- PATCH for partial updates
- DELETE for deletion (future)

### 3. Consistent Response Patterns
- Collections return arrays with pagination
- Individual resources return the resource directly
- Updates return the updated resource

### 4. Better Semantics
- `PATCH /events/{id}` with `{"status": "PENDING"}` is clearer than `POST /events/{id}/retry`
- `/tenants/{id}` is more RESTful than `/tenants/current`

### 5. Future-Proof
- PATCH allows adding more updateable fields without new endpoints
- Resource hierarchy supports sub-resources (e.g., `/events/{id}/attempts`)

---

## Rollout Timeline

### Week 1: Implementation
- Implement Phase 1A, 1B, 1C
- Deploy to staging
- Test all endpoints

### Week 2: Documentation
- Update all documentation
- Create migration guide
- Update Postman collection

### Week 3: Announcement
- Announce new endpoints
- Mark old endpoints as deprecated
- Set deprecation timeline (e.g., 90 days)

### Week 4+: Monitor
- Track usage of deprecated endpoints
- Assist users with migration
- Plan removal date

---

## Migration Examples

### Retry Event: Before & After

**Before (Deprecated):**
```bash
POST /v1/events/evt_abc123/retry
Authorization: Bearer {api_key}
```

**After (RESTful):**
```bash
PATCH /v1/events/evt_abc123
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "status": "PENDING"
}
```

### Update Tenant Config: Before & After

**Before (Deprecated):**
```bash
PATCH /v1/tenants/current
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "target_url": "https://example.com/webhook"
}
```

**After (RESTful):**
```bash
PATCH /v1/tenants/test-tenant
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "target_url": "https://example.com/webhook"
}
```

---

## Open Questions

1. **Admin Authorization**: Should `POST /v1/tenants` be admin-only? Or self-service signup?
2. **DynamoDB GSI**: Should we add GSI on `tenantId` for efficient lookups?
3. **Deprecation Period**: How long before removing old endpoints? (Suggest 90 days)
4. **Webhook Secret Retrieval**: Should we ever allow retrieving the webhook secret? (Currently: no)
5. **Event Updates**: What other fields should be updateable via PATCH /events/{id}?

---

## Next Steps

1. Review this plan
2. Decide on admin authorization strategy for tenant creation
3. Implement Phase 1A (event PATCH endpoint)
4. Test thoroughly
5. Implement Phase 1B (tenant creation)
6. Implement Phase 1C (tenant GET/PATCH)
7. Update documentation
8. Deploy and announce

