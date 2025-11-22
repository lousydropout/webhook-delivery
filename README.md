# Webhook Delivery System

Serverless multi-tenant webhook delivery platform with SQS-driven async processing, automatic retries, and Stripe-style HMAC signatures.

## Architecture

- **API**: FastAPI on Lambda (event ingestion)
- **Queue**: SQS with DLQ for reliability
- **Worker**: Lambda for webhook delivery
- **Storage**: DynamoDB with TTL
- **Domain**: hooks.vincentchan.cloud (SSL via ACM)

## Features

- ✅ Webhook delivery with HMAC signatures
- ✅ Automatic retries with exponential backoff
- ✅ Dead Letter Queue with manual requeue
- ✅ Multi-tenant isolation
- ✅ Custom domain with SSL
- ✅ TTL-based event cleanup (30 days)

## Quick Start

```bash
# Deploy
./scripts/deploy.sh

# Send event
curl -X POST https://hooks.vincentchan.cloud/events \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"event": "user.signup", "data": {...}}'
```

See [Webhook Integration Guide](docs/WEBHOOK_INTEGRATION.md) for receiver setup.

## Monitoring

```bash
# Check event status
aws dynamodb get-item \
  --table-name Vincent-TriggerApi-Events \
  --key '{"tenantId": {"S": "acme"}, "eventId": {"S": "evt_123"}}'

# View DLQ messages
aws sqs receive-message \
  --queue-url <dlq-url> \
  --max-number-of-messages 10
```

## Development

This is a complete rewrite. Old implementation removed.

Project structure:
```
src/
├── api/              # Event ingestion Lambda
├── worker/           # Webhook delivery Lambda
└── dlq_processor/    # DLQ requeue Lambda
```

## Testing

### Test Webhook Receiver

```bash
# Install dependencies
pip install -r tests/requirements.txt

# Run test receiver
python tests/webhook_receiver.py

# In another terminal, expose via ngrok
ngrok http 5000

# Update tenant targetUrl to ngrok URL, then test
```

## Cleanup

```bash
cd cdk
cdk destroy
```

## License

MIT
