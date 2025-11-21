# Zapier Trigger Ingestion API

Multi-tenant event ingestion API built with FastAPI, AWS Lambda, and DynamoDB.

## Architecture

- **API**: FastAPI + Mangum on AWS Lambda
- **Storage**: DynamoDB with GSI for efficient queries
- **Infrastructure**: AWS CDK (Python)
- **Auth**: API key-based multi-tenant authentication

## Project Structure

- `cdk/` - AWS CDK infrastructure code
- `src/lambda_handlers/` - FastAPI application code
- `src/worker/` - Mock worker for event processing
- `scripts/` - Utility scripts (seeding, etc.)
- `tests/` - Unit tests

## Setup

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r cdk/requirements.txt

# Deploy infrastructure
cd cdk
cdk bootstrap  # First time only
cdk deploy
```

## API Endpoints

- `POST /v1/events` - Ingest event
- `GET /v1/events` - List events (filterable by status)
- `GET /v1/events/{id}` - Get single event
- `POST /v1/events/{id}/ack` - Acknowledge event
- `DELETE /v1/events/{id}` - Delete event

## Testing

```bash
pytest tests/ -v --cov=src
```
