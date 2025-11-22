---
date: 2025-11-22T00:14:37-06:00
researcher: Claude (Sonnet 4.5)
git_commit: fc83c2ef4e81d3d14e7265a1f40fda03946f0565
branch: main
repository: zapier
topic: "Webhook Delivery System - Full Rewrite Implementation Plan"
tags: [implementation, planning, webhook-delivery, sqs, lambda, rewrite]
status: complete
last_updated: 2025-11-22
last_updated_by: Claude (Sonnet 4.5)
type: implementation_strategy
---

# Handoff: Webhook Delivery System Rewrite - Implementation Plan Created

## Task(s)

**Status: Planning Phase Complete - Implementation Plan Ready**

Created comprehensive implementation plan for transforming the current pull-based event inbox API into a push-based webhook delivery system with SQS-driven async processing.

### Completed:
- **Architecture Analysis**: Compared current implementation (`cdk/stacks/trigger_api_stack.py`) with target architecture (`new_stack.py`)
- **Requirements Gathering**: Confirmed approach with user (full rewrite, no layers, Stripe-style HMAC, etc.)
- **Implementation Plan**: Created detailed 6-phase plan in `thoughts/shared/plans/2025-11-21-webhook-delivery-system-rewrite.md`

### Key Decisions Confirmed:
- Complete replacement (no backward compatibility)
- No data migration (starting fresh)
- No Lambda layers (dependencies bundled directly)
- Full webhook delivery with Stripe-style HMAC signatures
- Manual DLQ requeue via Lambda function
- Custom domain: hooks.vincentchan.cloud
- 30-second webhook timeout
- 5 retry attempts with exponential backoff

### Not Started:
- Implementation of the 6 phases (awaiting user approval of plan)

## Critical References

1. **Implementation Plan**: `thoughts/shared/plans/2025-11-21-webhook-delivery-system-rewrite.md` - Complete 6-phase implementation plan with detailed code examples and success criteria
2. **Target Architecture**: `new_stack.py` - CDK stack showing desired end state
3. **Current Implementation**: `cdk/stacks/trigger_api_stack.py` - Existing stack to be replaced

## Recent Changes

**Created Files:**
- `thoughts/shared/plans/2025-11-21-webhook-delivery-system-rewrite.md:1-1000+` - Complete implementation plan

**No Code Changes**: This session was planning only, no implementation performed.

## Learnings

### Architecture Evolution Requirements:
1. **Pull → Push Model Shift**: Current implementation uses inbox pattern (GET /v1/events). New system uses push-based webhooks with automatic delivery.
2. **DynamoDB Schema Changes**:
   - TenantApiKeys: `pk/sk` → single `apiKey` partition key, add `targetUrl`, `webhookSecret`
   - Events: Rename `pk`→`tenantId`, add `status` (PENDING/DELIVERED/FAILED), `attempts`, `targetUrl`, TTL support
   - GSI: `gsi1pk/gsi1sk` → `status/createdAt` for status-index
3. **SQS Integration Pattern**: API Lambda → SQS Queue → Worker Lambda for async processing with built-in retry via SQS
4. **No Lambda Layers**: User explicitly wants dependencies bundled directly into each Lambda (simpler, easier to manage)
5. **Custom Domain from Start**: hooks.vincentchan.cloud configured via Route53/ACM from Phase 1

### Webhook Delivery Specifics:
- **Signature Format**: `Stripe-Signature: t={timestamp},v1={hmac_sha256}`
- **HMAC Payload**: `{timestamp}.{request_body}`
- **Retry Strategy**: 1min, 2min, 4min, 8min, 16min (5 attempts via SQS max_receive_count)
- **DLQ Handling**: Manual Lambda trigger to requeue failed messages

## Artifacts

### Created:
- `thoughts/shared/plans/2025-11-21-webhook-delivery-system-rewrite.md` - Implementation plan with 6 phases:
  - Phase 1: New CDK Infrastructure Stack
  - Phase 2: API Lambda - Event Ingestion
  - Phase 3: Worker Lambda - Webhook Delivery
  - Phase 4: DLQ Processor Lambda
  - Phase 5: Seeding & Testing
  - Phase 6: Deployment & Documentation

### Referenced:
- `new_stack.py:1-333` - Target architecture specification
- `cdk/stacks/trigger_api_stack.py:1-152` - Current implementation to be replaced

## Action Items & Next Steps

### Immediate:
1. **User Approval**: Get user approval/feedback on implementation plan
2. **Plan Refinement**: Address any concerns or adjustments requested

### After Approval:
1. **Phase 1**: Implement new CDK stack with custom domain, SQS, updated DynamoDB schemas
2. **Phase 2**: Create new API Lambda in `src/api/` for event ingestion
3. **Phase 3**: Create Worker Lambda in `src/worker/` for webhook delivery
4. **Phase 4**: Create DLQ Processor Lambda in `src/dlq_processor/`
5. **Phase 5**: Update seeding script and create integration tests
6. **Phase 6**: Update deployment automation and documentation

### Success Criteria for Starting Implementation:
- User confirms plan structure is acceptable
- No major architectural changes needed
- Ready to begin Phase 1 (infrastructure)

## Other Notes

### Project Context:
- This is the **Zapier Trigger Ingestion API** project
- Previously completed 8 phases of pull-based inbox implementation (Phases 1-8 all committed)
- Now pivoting to push-based webhook delivery system (complete rewrite)
- Old implementation will be removed/replaced

### Current Git State:
- Branch: main
- Last commit: `fc83c2e` (relates to previous implementation)
- Working directory: Clean (no uncommitted changes)

### Key Files/Directories:
- **Current CDK**: `cdk/stacks/trigger_api_stack.py` (to be replaced)
- **Current API**: `src/lambda_handlers/api/` (to be replaced with `src/api/`)
- **Worker (old)**: `src/worker/mock_worker.py` (pull-based, will be replaced)
- **Tests**: `tests/` (will need updates for new architecture)
- **Docs**: `docs/` (will need complete rewrite)

### Important Considerations:
1. **No Migration**: Starting fresh, no data to preserve
2. **Downtime Acceptable**: Can destroy old stack before deploying new one
3. **Custom Domain Ready**: hooks.vincentchan.cloud already registered
4. **All Features Important**: SQS, webhooks, custom domain, retry logic all required

### Plan Review Points:
User should verify:
- Phase ordering makes sense
- DynamoDB schema matches requirements
- HMAC implementation looks correct
- Retry strategy (5 attempts) acceptable
- Nothing missing from plan
