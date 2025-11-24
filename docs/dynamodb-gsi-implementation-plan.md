# DynamoDB GSI Implementation Plan

**Status**: Ready for Implementation  
**Priority**: High (Performance Improvement)  
**Estimated Effort**: 2-3 hours

## Overview

Add Global Secondary Index (GSI) on `tenantId` to improve performance of tenant lookups. Currently using inefficient `scan()` operations.

## Current Implementation

### Problem Areas

1. **`get_tenant_by_id()`** (`src/api/dynamo.py:275-315`):

   ```python
   # Uses scan with filter - inefficient
   response = tenant_api_keys_table.scan(
       FilterExpression="tenantId = :tid",
       ExpressionAttributeValues={":tid": tenant_id}
   )
   ```

2. **`update_tenant_config_by_id()`** (`src/api/dynamo.py:318-386`):
   ```python
   # Uses scan to find API key - inefficient
   response = tenant_api_keys_table.scan(
       FilterExpression="tenantId = :tid",
       ExpressionAttributeValues={":tid": tenant_id}
   )
   ```

### Performance Impact

- **Current**: O(n) scan operation - scans entire table
- **With GSI**: O(1) query operation - direct lookup
- **Cost**: Scan consumes more RCU (Read Capacity Units)
- **Latency**: Scan slower, especially with many tenants

## Implementation Steps

### Step 1: Add GSI to CDK Stack

**File**: `cdk/stacks/webhook_delivery_stack.py`

**Location**: Around line 74 where `TenantApiKeys` table is defined

**Change**:

```python
# Current (no GSI)
self.tenant_api_keys_table = dynamodb.Table(
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

# Updated (with GSI)
self.tenant_api_keys_table = dynamodb.Table(
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
self.tenant_api_keys_table.add_global_secondary_index(
    index_name="tenantId-index",
    partition_key=dynamodb.Attribute(
        name="tenantId",
        type=dynamodb.AttributeType.STRING
    ),
)
```

### Step 2: Update `get_tenant_by_id()` Function

**File**: `src/api/dynamo.py`

**Location**: Lines 275-315

**Change**:

```python
def get_tenant_by_id(tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Get tenant details by tenant ID.

    Uses GSI on tenantId for efficient lookups.

    Args:
        tenant_id: Tenant identifier

    Returns:
        Tenant data (excluding webhook secret for security)
    """
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

        # Remove webhook secret from response for security
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

### Step 3: Update `update_tenant_config_by_id()` Function

**File**: `src/api/dynamo.py`

**Location**: Lines 318-386

**Change**:

```python
def update_tenant_config_by_id(
    tenant_id: str,
    target_url: Optional[str] = None,
    webhook_secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update tenant configuration by tenant ID.

    Uses GSI on tenantId to find API key efficiently.

    Args:
        tenant_id: Tenant identifier
        target_url: New webhook URL (optional)
        webhook_secret: New webhook secret (optional)

    Returns:
        Updated tenant configuration
    """
    tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])

    # Use GSI query to find API key for this tenant
    response = tenant_api_keys_table.query(
        IndexName="tenantId-index",
        KeyConditionExpression="tenantId = :tid",
        ExpressionAttributeValues={":tid": tenant_id}
    )

    items = response.get("Items", [])
    if not items:
        raise ValueError(f"Tenant {tenant_id} not found")

    api_key = items[0]["apiKey"]

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

### Step 4: Deploy Infrastructure

```bash
cd cdk
cdk deploy --require-approval never
```

**Note**: GSI creation is non-breaking:

- Existing data is automatically indexed
- No downtime required
- GSI becomes available once creation completes (~1-2 minutes)

### Step 5: Test Changes

```bash
# Test get_tenant_by_id
curl -X GET "https://hooks.vincentchan.cloud/v1/tenants/acme" \
  -H "Authorization: Bearer tenant_acme_key"

# Test update_tenant_config_by_id
curl -X PATCH "https://hooks.vincentchan.cloud/v1/tenants/acme" \
  -H "Authorization: Bearer tenant_acme_key" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com/webhook"}'
```

### Step 6: Verify Performance

Monitor CloudWatch metrics:

- Check DynamoDB read capacity units (should decrease)
- Check Lambda execution time (should improve)
- Verify no errors in CloudWatch Logs

## Rollback Plan

If issues occur:

1. **Revert code changes** (keep GSI in infrastructure)
2. **Update functions** to use scan again temporarily
3. **Investigate GSI** configuration
4. **Fix and redeploy**

GSI can remain in infrastructure without being used (no cost impact if not queried).

## Testing Checklist

- [ ] GSI created successfully in DynamoDB
- [ ] `get_tenant_by_id()` works with GSI
- [ ] `update_tenant_config_by_id()` works with GSI
- [ ] Existing tenants still accessible
- [ ] New tenants work correctly
- [ ] Error handling works (non-existent tenant)
- [ ] Performance improved (check CloudWatch metrics)
- [ ] No regressions in other functionality

## Success Criteria

- ✅ GSI created and active
- ✅ Functions use GSI queries instead of scans
- ✅ All tests pass
- ✅ Performance improved (lower latency, lower RCU)
- ✅ No breaking changes

## Notes

- **GSI Naming**: `tenantId-index` follows DynamoDB naming conventions
- **Cost**: GSI has minimal cost impact (only when queried)
- **Backward Compatibility**: Fully backward compatible
- **Data Consistency**: GSI is eventually consistent (acceptable for this use case)

---

**Ready to implement**: Yes  
**Breaking Changes**: None  
**Risk Level**: Low
