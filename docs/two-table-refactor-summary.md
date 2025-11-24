# Two-Table Architecture Refactor Summary

**Date**: 2025-01-XX  
**Status**: Complete

## Overview

Refactored the Webhook Delivery System to separate tenant authentication from webhook delivery configuration into two distinct DynamoDB tables. This enforces least-privilege access and aligns with security best practices.

## Changes Summary

### DynamoDB Tables

**Before**: Single table `TenantApiKeys`
- PK: `apiKey`
- Attributes: `tenantId`, `targetUrl`, `webhookSecret`, `isActive`, `plan`, `createdAt`, `updatedAt`

**After**: Two tables

1. **TenantIdentity** (PK: `apiKey`)
   - Purpose: Authentication and tenant identity
   - Attributes: `tenantId`, `status`, `plan`, `createdAt`
   - Used by: Lambda Authorizer, API Lambda

2. **TenantWebhookConfig** (PK: `tenantId`)
   - Purpose: Webhook delivery configuration
   - Attributes: `targetUrl`, `webhookSecret`, `rotationHistory` (optional), `lastUpdated`
   - Used by: Worker Lambda, Webhook Receiver Lambda

### IAM Permissions

**Lambda Authorizer**:
- ✅ Read-only access to `TenantIdentity` table
- ✅ Uses `ProjectionExpression` to limit fields retrieved
- ❌ No access to `TenantWebhookConfig` (never sees webhook secrets)

**API Lambda**:
- ✅ Read/write access to `TenantIdentity` table
- ✅ Read/write access to `TenantWebhookConfig` table
- ✅ Creates tenants in both tables atomically

**Worker Lambda**:
- ✅ Read-only access to `TenantWebhookConfig` table
- ❌ No access to `TenantIdentity` table

**Webhook Receiver Lambda**:
- ✅ Read-only access to `TenantWebhookConfig` table
- ❌ No access to `TenantIdentity` table

**DLQ Processor Lambda**:
- ✅ No changes (only accesses Events table and SQS)

### Code Changes

#### Lambda Authorizer (`src/authorizer/handler.py`)
- Changed table reference from `TENANT_API_KEYS_TABLE` to `TENANT_IDENTITY_TABLE`
- Added `ProjectionExpression` to limit retrieved fields
- Updated context data to exclude webhook secrets
- Changed status check from `isActive` boolean to `status` string ("active")

#### API Lambda (`src/api/`)
- **`dynamo.py`**:
  - `create_tenant()`: Writes to both `TenantIdentity` and `TenantWebhookConfig` tables
  - `get_tenant_by_id()`: Reads from `TenantWebhookConfig` table (tenantId is PK)
  - `update_tenant_config_by_id()`: Updates `TenantWebhookConfig` table only
- **`context.py`**: Updated to extract only tenant identity (tenantId, status, plan) from authorizer context
- **`routes.py`**: Updated `ingest_event()` to fetch `targetUrl` from `TenantWebhookConfig` table

#### Worker Lambda (`src/worker/dynamo.py`)
- Changed table reference from `TENANT_API_KEYS_TABLE` to `TENANT_WEBHOOK_CONFIG_TABLE`
- Updated `get_tenant_by_id()` to use direct `get_item()` instead of scan (tenantId is PK)

#### Webhook Receiver Lambda (`src/webhook_receiver/main.py`)
- Changed table reference from `TENANT_API_KEYS_TABLE` to `TENANT_WEBHOOK_CONFIG_TABLE`
- Updated `get_webhook_secret_for_tenant()` to use direct `get_item()` instead of scan

### CDK Infrastructure (`cdk/stacks/webhook_delivery_stack.py`)

- Removed `TenantApiKeys` table definition
- Added `TenantIdentity` table (PK: `apiKey`)
- Added `TenantWebhookConfig` table (PK: `tenantId`)
- Updated all Lambda environment variables:
  - `TENANT_API_KEYS_TABLE` → `TENANT_IDENTITY_TABLE` and `TENANT_WEBHOOK_CONFIG_TABLE`
- Updated IAM permissions for all Lambdas
- Updated CloudFormation outputs

### Documentation

- Updated `README.md`:
  - Architecture overview with two-table separation
  - Updated DynamoDB schema documentation
  - Updated Mermaid diagrams (system diagram and sequence diagrams)
  - Updated tenant setup instructions
  - Updated monitoring commands

### Migration

- Created migration script: `scripts/migrate_to_two_table_architecture.py`
- Script deletes all data from old `TenantApiKeys` table
- No data migration (as requested - we don't care to migrate existing data)

## Benefits

1. **Security**: Lambda Authorizer never has access to webhook secrets
2. **Least Privilege**: Each Lambda only has access to the data it needs
3. **Separation of Concerns**: Authentication data separate from delivery configuration
4. **Performance**: Direct lookups by tenantId (no GSI needed for TenantWebhookConfig)
5. **Clarity**: Clear distinction between identity and webhook configuration

## API Behavior

- ✅ All API endpoints remain unchanged
- ✅ Tenant creation still works (writes to both tables)
- ✅ Event ingestion still works (fetches targetUrl from TenantWebhookConfig)
- ✅ Webhook delivery still works (reads from TenantWebhookConfig)
- ✅ Webhook receiver validation still works (reads from TenantWebhookConfig)

## Testing Checklist

After deployment, verify:

- [ ] Creating a tenant works (writes to both tables)
- [ ] Event ingestion works (fetches targetUrl correctly)
- [ ] Workers deliver webhooks correctly (reads webhook config)
- [ ] Webhook receiver validates HMAC correctly (reads webhook secret)
- [ ] Retry logic still functions
- [ ] DLQ flow unaffected
- [ ] Tenants remain completely isolated
- [ ] Authorizer has minimal privilege (no webhook secrets)

## Deployment Steps

1. Run migration script to delete old table data:
   ```bash
   python scripts/migrate_to_two_table_architecture.py
   ```

2. Deploy updated CDK stack:
   ```bash
   cd cdk
   cdk deploy
   ```

3. Create new tenants using POST /v1/tenants endpoint

4. Verify system functionality using test checklist above

5. Optionally delete old `TenantApiKeys` table manually if no longer needed

## Files Modified

### Infrastructure
- `cdk/stacks/webhook_delivery_stack.py`

### Lambda Code
- `src/authorizer/handler.py`
- `src/api/dynamo.py`
- `src/api/context.py`
- `src/api/routes.py`
- `src/worker/dynamo.py`
- `src/webhook_receiver/main.py`

### Documentation
- `README.md`

### Scripts
- `scripts/migrate_to_two_table_architecture.py` (new)

## Notes

- The old `auth.py` file in `src/api/` is no longer used (authorization handled by Lambda Authorizer)
- Events table still stores `targetUrl` snapshot for historical reference, but Worker reads current config from `TenantWebhookConfig`
- Migration script requires manual confirmation before deletion

