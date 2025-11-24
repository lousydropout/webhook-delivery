# Webhook Retry Mechanism Demonstration

This guide demonstrates the complete webhook retry functionality using the receiver control endpoints.

## Overview

The webhook delivery system includes control endpoints that allow you to temporarily disable webhook reception. This enables demonstration and testing of the retry mechanism by:

1. Disabling the webhook receiver to force delivery failures
2. Creating events that will fail when delivered
3. Re-enabling the receiver
4. Manually retrying the failed events to show successful delivery

## Receiver Control Endpoints

These endpoints control webhook reception **globally** for all tenants.

### GET `/status`

Check whether webhook reception is enabled or disabled globally.

**Response:**

```json
{
  "webhook_reception": "enabled",
  "accepts_webhooks": true
}
```

### POST `/disable`

Temporarily disable webhook reception globally. All incoming webhooks will return `503 Service Unavailable`.

**Response:**

```json
{
  "webhook_reception": "disabled",
  "message": "Webhook reception has been disabled for all tenants. Webhooks will return 503 until re-enabled."
}
```

### POST `/enable`

Re-enable webhook reception globally after being disabled.

**Response:**

```json
{
  "webhook_reception": "enabled",
  "message": "Webhook reception has been enabled for all tenants"
}
```

## Complete Retry Flow Example

### Step 1: Check Initial Status

```bash
curl -X GET https://receiver.vincentchan.cloud/status
```

Expected: `{"webhook_reception": "enabled", "accepts_webhooks": true}`

### Step 2: Disable Webhook Reception

```bash
curl -X POST https://receiver.vincentchan.cloud/disable
```

Expected: `{"webhook_reception": "disabled", "message": "Webhook reception has been disabled for all tenants..."}`

### Step 3: Create Event (Will Fail)

```bash
curl -X POST https://hooks.vincentchan.cloud/v1/events \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "test.retry.demo",
    "data": "This event will fail delivery"
  }'
```

Expected: `{"event_id": "evt_...", "status": "PENDING"}`

Save the `event_id` from the response.

### Step 4: Wait for Delivery Attempt

Wait 1-2 seconds for the worker Lambda to pick up the event from SQS and attempt delivery.

### Step 5: Verify Event Failed

```bash
curl -X GET https://hooks.vincentchan.cloud/v1/events/evt_YOUR_EVENT_ID \
  -H "Authorization: Bearer YOUR_API_KEY"
```

Expected response showing failure:

```json
{
  "event": {
    "event_id": "evt_YOUR_EVENT_ID",
    "status": "FAILED",
    "attempts": 1,
    "last_attempt_at": "1763959108",
    "error_message": null
  }
}
```

### Step 6: Re-enable Webhook Reception

```bash
curl -X POST https://receiver.vincentchan.cloud/enable
```

Expected: `{"webhook_reception": "enabled", "message": "Webhook reception has been enabled for all tenants"}`

### Step 7: Retry Failed Event

```bash
curl -X PATCH https://hooks.vincentchan.cloud/v1/events/evt_YOUR_EVENT_ID \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "PENDING"}'
```

Expected: `{"event_id": "evt_...", "status": "PENDING", "attempts": 0, ...}`

### Step 8: Wait and Verify Success

Wait 1-2 seconds, then check the event status again:

```bash
curl -X GET https://hooks.vincentchan.cloud/v1/events/evt_YOUR_EVENT_ID \
  -H "Authorization: Bearer YOUR_API_KEY"
```

Expected response showing successful delivery:

```json
{
  "event": {
    "event_id": "evt_YOUR_EVENT_ID",
    "status": "DELIVERED",
    "attempts": 2,
    "last_attempt_at": "1763959202",
    "error_message": null
  }
}
```

## Real Example from Testing

Here's an actual test run demonstrating the flow:

**Event Created:** `evt_9662694bb566`

**Initial State (Disabled):**

- Receiver disabled
- Event created and queued
- Worker attempted delivery → received 503
- Event status: `FAILED`, attempts: `1`

**After Re-enabling:**

- Receiver enabled via POST /enable (global for all tenants)
- Event retried via POST /v1/events/evt_9662694bb566/retry
- Event requeued to SQS (attempts preserved)
- Worker attempted delivery again → received 200
- Final event status: `DELIVERED`, attempts: `2`

## Implementation Details

### State Management

- Uses in-memory global state in Lambda container (`global_webhook_reception_enabled: bool`)
- Default state: enabled (accepts webhooks for all tenants)
- State persists for Lambda container lifetime
- Applies globally to all tenants (not per-tenant)
- No DynamoDB persistence (intentionally temporary for testing)

### Webhook Endpoint Protection

Located in `src/webhook_receiver/main.py`:

```python
# Check if webhook reception is enabled globally
if not is_webhook_reception_enabled():
    print(f"Webhook reception disabled globally")
    raise HTTPException(status_code=503, detail="Webhook reception temporarily disabled")
```

### Retry Logic

Located in `src/api/routes.py`:

1. Validates event exists and belongs to tenant
2. Accepts retry via POST `/v1/events/{event_id}/retry`
3. Resets event to `PENDING` in DynamoDB (preserves attempt count)
4. Requeues message to SQS
5. Returns updated event details

## Use Cases

1. **Testing Retry Logic**: Verify that failed events can be manually retried
2. **Demonstrating Resilience**: Show how the system handles temporary outages
3. **Load Testing**: Create controlled failure scenarios for testing
4. **Debugging**: Temporarily disable webhooks to prevent side effects during investigation
5. **Training**: Demonstrate webhook delivery mechanics to stakeholders

## Postman Collection

The control endpoints are available in the Postman collection under:

- **3. Webhook Receiver** folder:
  - "Get Webhook Status"
  - "Disable Webhook Reception"
  - "Enable Webhook Reception"

## Architecture Notes

### Why In-Memory State?

- **Simplicity**: No additional DynamoDB table or attribute needed
- **Temporary by Design**: State resets when Lambda container recycles
- **Testing Focus**: Designed for demonstration, not production feature flags
- **Performance**: Zero DynamoDB overhead for state checks

### Production Considerations

If you need persistent enable/disable state:

1. Add `webhookReceptionEnabled` boolean to TenantApiKeys table
2. Check this field in `get_webhook_secret_for_tenant()`
3. Update control endpoints to modify DynamoDB instead of cache
4. Consider adding audit logging for state changes

## Related Endpoints

- **POST /v1/events** - Create events
- **GET /v1/events** - List events
- **GET /v1/events/{event_id}** - Event details
- **POST /v1/events/{event_id}/retry** - Retry failed event
- **POST /enable** - Enable webhook reception globally
- **POST /disable** - Disable webhook reception globally
- **GET /status** - Get global webhook reception status

## Troubleshooting

### Event stays PENDING after retry

- Check SQS queue: `aws sqs get-queue-attributes --queue-url <URL> --attribute-names ApproximateNumberOfMessages`
- Worker Lambda may be throttled or erroring
- Check CloudWatch logs for worker Lambda

### Enable/Disable not working

- State is global and per-Lambda container
- If multiple containers exist, you may need to disable multiple times
- State resets when container recycles (typically after 15-30 minutes of inactivity)
- Applies to all tenants (not per-tenant)

### 404 on control endpoints

- Endpoints are at root level: `/enable`, `/disable`, `/status` (no tenant_id needed)
- Verify API Gateway deployment completed successfully

## Code References

- **Webhook Receiver**: [src/webhook_receiver/main.py](src/webhook_receiver/main.py)
- **State Management**: Global state variable and helper functions
- **Control Endpoints**: `/enable`, `/disable`, `/status` (global, not tenant-specific)
- **CDK Infrastructure**: [cdk/stacks/webhook_delivery_stack.py](cdk/stacks/webhook_delivery_stack.py)
- **Postman Collection**: `4. Webhook Receiver` folder
