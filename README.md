# Zapier Trigger Ingestion API

Multi-tenant event ingestion API built with FastAPI, AWS Lambda, and DynamoDB. Simulates Zapier's Triggers API architecture.

## Architecture

- **API Framework**: FastAPI + Mangum (serverless adapter)
- **Compute**: AWS Lambda
- **Storage**: DynamoDB with GSI for efficient queries
- **API Gateway**: AWS API Gateway (REST API)
- **Infrastructure**: AWS CDK (Python)
- **Authentication**: API key-based multi-tenant isolation

## Features

- ✅ Multi-tenant event ingestion with tenant isolation
- ✅ RESTful API design with proper HTTP semantics
- ✅ Durable event storage with DynamoDB
- ✅ Pull-based event delivery (inbox pattern)
- ✅ Acknowledgment semantics for event lifecycle
- ✅ Mock worker simulating Zapier's automation engine
- ✅ Unit tests with >80% coverage
- ✅ Single-command deployment

## Quick Start

### Prerequisites

- Python 3.11+
- AWS CLI configured with credentials
- Node.js 18+ (for CDK)

### 1. Deploy

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

This will:
- Install dependencies
- Bootstrap CDK
- Deploy DynamoDB tables and Lambda functions
- Create API Gateway
- Seed 3 test tenants

### 2. Get API URL and Keys

The deploy script outputs:
- API Gateway URL
- 3 tenant API keys (acme, globex, initech)

Export them:
```bash
export API_URL="https://your-api-url"
export ACME_API_KEY="tenant_acme_live_xxx"
```

### 3. Test

```bash
# Health check
curl $API_URL/health

# Create event
curl -X POST $API_URL/v1/events \
  -H "Authorization: Bearer $ACME_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"customer.created","email":"test@example.com"}'

# List undelivered events
curl $API_URL/v1/events?status=undelivered \
  -H "Authorization: Bearer $ACME_API_KEY"
```

### 4. Run Mock Worker

```bash
export API_URL="your-api-url"
export API_KEY="$ACME_API_KEY"
export TENANT_NAME="acme"
python src/worker/mock_worker.py
```

The worker will poll for events, process them, and acknowledge them.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/v1/events` | Create event |
| `GET` | `/v1/events` | List events (filterable) |
| `GET` | `/v1/events/{id}` | Get single event |
| `POST` | `/v1/events/{id}/ack` | Acknowledge event |
| `DELETE` | `/v1/events/{id}` | Delete event |

See [docs/TESTING.md](docs/TESTING.md) for detailed testing guide.

## Project Structure

```
zapier/
├── cdk/                      # AWS CDK infrastructure
│   ├── app.py
│   └── stacks/
│       └── trigger_api_stack.py
├── src/
│   ├── lambda_handlers/      # FastAPI application
│   │   └── api/
│   │       ├── main.py       # FastAPI app + Mangum handler
│   │       ├── auth.py       # Authentication middleware
│   │       ├── models.py     # Pydantic models
│   │       └── routes/
│   │           └── events.py # Event endpoints
│   └── worker/               # Mock worker
│       └── mock_worker.py
├── tests/                    # Unit tests
├── scripts/                  # Utility scripts
│   ├── deploy.sh
│   └── seed_tenants.py
└── docs/                     # Documentation
    ├── TESTING.md
    └── postman_collection.json
```

## Testing

### Unit Tests

```bash
pytest tests/ -v --cov=src --cov-report=html
```

### Manual Testing

Import `docs/postman_collection.json` into Postman and update variables:
- `api_url`: Your API Gateway URL
- `api_key`: One of the tenant API keys

### Multi-Tenant Worker Test

```bash
export API_URL="your-api-url"
export API_KEYS="$ACME_API_KEY,$GLOBEX_API_KEY,$INITECH_API_KEY"
export TENANT_NAMES="acme,globex,initech"
python src/worker/mock_worker.py
```

## Cleanup

```bash
cd cdk
cdk destroy
```

## Documentation

- [Project Overview](project.md)
- [DynamoDB Schema](dynamodb.md)
- [API Endpoints](api_endpoints.md)
- [Testing Guide](docs/TESTING.md)

## License

MIT
