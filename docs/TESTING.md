# Testing Guide

## Setup

1. Deploy the infrastructure:
```bash
./scripts/deploy.sh
```

2. Export API keys from seed script output:
```bash
export ACME_API_KEY='tenant_acme_live_xxx'
export GLOBEX_API_KEY='tenant_globex_live_xxx'
export INITECH_API_KEY='tenant_initech_live_xxx'
```

3. Get your API URL:
```bash
export API_URL=$(aws cloudformation describe-stacks \
    --stack-name TriggerApiStack \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
    --output text)
```

## Manual Testing Sequence

### 1. Health Check
```bash
curl $API_URL/health
# Expected: {"status":"healthy"}
```

### 2. Create Events (Tenant: Acme)
```bash
curl -X POST $API_URL/v1/events \
  -H "Authorization: Bearer $ACME_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "customer.created",
    "customer_id": "cust_123",
    "email": "alice@acme.com"
  }'
# Expected: 201, returns event_id
```

### 3. List Undelivered Events
```bash
curl $API_URL/v1/events?status=undelivered \
  -H "Authorization: Bearer $ACME_API_KEY"
# Expected: Array with the event created above
```

### 4. Get Single Event
```bash
EVENT_ID="evt_xxx"  # From previous response
curl $API_URL/v1/events/$EVENT_ID \
  -H "Authorization: Bearer $ACME_API_KEY"
# Expected: Full event details
```

### 5. Acknowledge Event
```bash
curl -X POST $API_URL/v1/events/$EVENT_ID/ack \
  -H "Authorization: Bearer $ACME_API_KEY"
# Expected: {"status":"acknowledged"}
```

### 6. Verify Acknowledgment
```bash
curl $API_URL/v1/events?status=undelivered \
  -H "Authorization: Bearer $ACME_API_KEY"
# Expected: Empty array (event no longer undelivered)

curl $API_URL/v1/events?status=delivered \
  -H "Authorization: Bearer $ACME_API_KEY"
# Expected: Array with the acknowledged event
```

### 7. Delete Event
```bash
curl -X DELETE $API_URL/v1/events/$EVENT_ID \
  -H "Authorization: Bearer $ACME_API_KEY"
# Expected: 204 No Content
```

### 8. Multi-Tenant Isolation Test
```bash
# Create event as Acme
ACME_EVENT=$(curl -X POST $API_URL/v1/events \
  -H "Authorization: Bearer $ACME_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"test","data":"acme"}' | jq -r '.id')

# Try to access Acme's event as Globex (should fail)
curl $API_URL/v1/events/$ACME_EVENT \
  -H "Authorization: Bearer $GLOBEX_API_KEY"
# Expected: 404 (tenant isolation working)
```

## Mock Worker Testing

### Single Tenant
```bash
export API_URL=$API_URL
export API_KEY=$ACME_API_KEY
export TENANT_NAME="acme"
python src/worker/mock_worker.py
```

In another terminal, create events:
```bash
curl -X POST $API_URL/v1/events \
  -H "Authorization: Bearer $ACME_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"test.event","message":"hello"}'
```

Watch the worker process and acknowledge the event.

### Multi-Tenant Worker
```bash
export API_URL=$API_URL
export API_KEYS="$ACME_API_KEY,$GLOBEX_API_KEY,$INITECH_API_KEY"
export TENANT_NAMES="acme,globex,initech"
python src/worker/mock_worker.py
```

Create events for multiple tenants and watch them process independently.

## Unit Tests

Run all tests:
```bash
pytest tests/ -v --cov=src
```

Run specific test file:
```bash
pytest tests/test_auth.py -v
```

View coverage report:
```bash
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```
