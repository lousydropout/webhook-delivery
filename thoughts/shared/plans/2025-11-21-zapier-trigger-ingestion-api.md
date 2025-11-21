# Zapier Trigger Ingestion API Implementation Plan

## Overview

Build a production-ready multi-tenant event ingestion API that simulates Zapier's Triggers API architecture. The system accepts events from external systems, stores them durably in DynamoDB, and exposes them via a RESTful API for downstream workers to process. The implementation uses Python + FastAPI + Mangum on AWS Lambda, with infrastructure managed by AWS CDK.

## Current State Analysis

This is a **greenfield project** with no existing implementation. We have:
- Complete technical specifications in `project.md`, `dynamodb.md`, and `api_endpoints.md`
- Clear requirements for multi-tenant architecture
- Defined REST API contract
- DynamoDB schema design

**What's Missing:**
- All infrastructure code
- All application code
- Testing harness
- Deployment automation

## Desired End State

A fully functional serverless API that:

1. **Accepts events** via `POST /v1/events` with tenant-scoped API key authentication
2. **Stores events** durably in DynamoDB with proper partitioning by tenant
3. **Lists events** via `GET /v1/events?status=undelivered` using GSI for efficient queries
4. **Retrieves individual events** via `GET /v1/events/{id}`
5. **Acknowledges events** via `POST /v1/events/{id}/ack` to mark them delivered
6. **Deletes events** via `DELETE /v1/events/{id}` for cleanup
7. **Includes a mock worker** that polls, processes, and acknowledges events
8. **Seeds 3 test tenants** with valid API keys for demonstration
9. **Deploys to AWS** via CDK with a single command

### Verification Criteria:
- All endpoints return correct HTTP status codes and JSON responses
- Multi-tenant isolation is enforced (tenant A cannot see tenant B's events)
- Events flow through the complete lifecycle: ingest → store → retrieve → ack
- Mock worker successfully processes events for all 3 test tenants
- Unit tests pass with >80% coverage on core business logic

## What We're NOT Doing

- OAuth or Cognito authentication flows
- Event transformations or filtering by event_type
- Deduplication beyond UUID generation
- Retry policies or dead letter queues
- Rate limiting or throttling
- Multi-region deployment
- CI/CD pipeline setup
- Local development with LocalStack/DynamoDB Local
- UI or dashboard
- Webhooks or push-based delivery
- High-scale load testing

## Implementation Approach

We'll build incrementally in 8 phases:

1. **Foundation**: Set up monorepo structure and CDK infrastructure with DynamoDB tables
2. **API Gateway**: Connect Lambda to API Gateway via CDK (exposes endpoints early)
3. **Auth + Ingestion**: Implement authentication and basic event creation
4. **Retrieval**: Add event listing and single-event retrieval
5. **State Management**: Implement acknowledgment and deletion
6. **Worker**: Build mock worker for event processing
7. **Testing**: Add unit tests and seed test data
8. **Deployment**: Document deployment and create Postman collection

Each phase builds on the previous, with clear success criteria before proceeding.

---

## Phase 1: Project Setup & CDK Infrastructure Foundation

### Overview
Establish the monorepo structure, initialize AWS CDK, and define DynamoDB tables with GSI. This creates the foundation for all subsequent development.

### Changes Required:

#### 1. Project Structure Setup

**Directory Layout:**
```
zapier/
├── cdk/
│   ├── app.py
│   ├── cdk.json
│   ├── requirements.txt
│   └── stacks/
│       └── trigger_api_stack.py
├── src/
│   ├── lambda_handlers/
│   │   ├── __init__.py
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── main.py
│   │       ├── auth.py
│   │       ├── models.py
│   │       └── routes/
│   │           ├── __init__.py
│   │           ├── events.py
│   │           └── health.py
│   └── worker/
│       └── mock_worker.py
├── tests/
│   ├── __init__.py
│   ├── test_auth.py
│   └── test_events.py
├── scripts/
│   └── seed_tenants.py
├── requirements.txt
├── pyproject.toml
└── README.md
```

#### 2. Root Dependencies

**File**: `requirements.txt`
```txt
fastapi==0.104.1
mangum==0.17.0
boto3==1.29.0
pydantic==2.5.0
python-dotenv==1.0.0
pytest==7.4.3
pytest-cov==4.1.0
moto==4.2.0
```

**File**: `pyproject.toml`
```toml
[tool.poetry]
name = "zapier-trigger-api"
version = "0.1.0"
description = "Multi-tenant event ingestion API"
authors = ["Your Name <you@example.com>"]

[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.104.1"
mangum = "^0.17.0"
boto3 = "^1.29.0"
pydantic = "^2.5.0"

[tool.poetry.dev-dependencies]
pytest = "^7.4.3"
pytest-cov = "^4.1.0"
moto = "^4.2.0"
black = "^23.11.0"
ruff = "^0.1.6"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

#### 3. CDK Infrastructure

**File**: `cdk/requirements.txt`
```txt
aws-cdk-lib==2.110.0
constructs>=10.0.0
```

**File**: `cdk/app.py`
```python
#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.trigger_api_stack import TriggerApiStack

app = cdk.App()

TriggerApiStack(
    app,
    "TriggerApiStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1"
    )
)

app.synth()
```

**File**: `cdk/cdk.json`
```json
{
  "app": "python3 app.py",
  "watch": {
    "include": ["**"],
    "exclude": [
      "README.md",
      "cdk*.json",
      "requirements*.txt",
      "source.bat",
      "**/__init__.py",
      "**/__pycache__",
      "**/*.pyc"
    ]
  },
  "context": {
    "@aws-cdk/aws-lambda:recognizeLayerVersion": true,
    "@aws-cdk/core:checkSecretUsage": true,
    "@aws-cdk/core:target-partitions": ["aws", "aws-cn"]
  }
}
```

**File**: `cdk/stacks/trigger_api_stack.py`
```python
from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    RemovalPolicy,
    CfnOutput
)
from constructs import Construct


class TriggerApiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DynamoDB Table: TenantApiKeys
        self.api_keys_table = dynamodb.Table(
            self,
            "TenantApiKeys",
            table_name="TriggerApi-TenantApiKeys",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # For dev/demo only
            point_in_time_recovery=False
        )

        # DynamoDB Table: Events
        self.events_table = dynamodb.Table(
            self,
            "Events",
            table_name="TriggerApi-Events",
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # For dev/demo only
            point_in_time_recovery=False
        )

        # GSI: status-index for querying undelivered events
        self.events_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="gsi1pk",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="gsi1sk",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL
        )

        # Outputs
        CfnOutput(
            self,
            "ApiKeysTableName",
            value=self.api_keys_table.table_name,
            description="TenantApiKeys table name"
        )

        CfnOutput(
            self,
            "EventsTableName",
            value=self.events_table.table_name,
            description="Events table name"
        )
```

#### 4. Basic README

**File**: `README.md`
```markdown
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
```

### Success Criteria:

#### Automated Verification:
- [x] Directory structure created successfully
- [x] `requirements.txt` files are valid and install without errors: `pip install -r requirements.txt && pip install -r cdk/requirements.txt`
- [x] CDK synth runs without errors: `cd cdk && cdk synth`
- [x] **CDK deploy completes successfully**: `cd cdk && cdk deploy --require-approval never` returns exit code 0
- [x] **Both DynamoDB tables exist in AWS**: `aws dynamodb describe-table --table-name TriggerApi-TenantApiKeys` succeeds
- [x] **Events table has GSI**: `aws dynamodb describe-table --table-name TriggerApi-Events --query 'Table.GlobalSecondaryIndexes[?IndexName==\`status-index\`]'` returns the GSI

#### Manual Verification:
- [x] **Verify CloudFormation stack deployed**: Check AWS Console shows "CREATE_COMPLETE" status for TriggerApiStack
- [x] **Verify both tables visible**: DynamoDB Console shows TriggerApi-TenantApiKeys and TriggerApi-Events
- [x] **Verify GSI configuration**: status-index has gsi1pk (HASH) and gsi1sk (RANGE) keys with ALL projection
- [x] **Confirm billing mode**: Both tables show "On-demand" capacity mode
- [x] **Verify table outputs**: CloudFormation Outputs tab shows ApiKeysTableName and EventsTableName

**Implementation Note**: Phase 1 is complete only when `cdk deploy` fully succeeds and both tables are queryable in AWS. Do not proceed to Phase 2 until deployment is verified.

---

## Phase 2: API Gateway Integration via CDK

### Overview
Create API Gateway REST API with CDK and connect it to the Lambda function (which will be implemented in Phase 3). This exposes a public HTTPS endpoint early, allowing us to test the API as we build it.

### Changes Required:

#### 1. Update CDK Stack for Lambda and API Gateway

**File**: `cdk/stacks/trigger_api_stack.py` (add after table definitions)
```python
from aws_cdk import (
    aws_lambda as lambda_,
    aws_apigateway as apigateway,
    Duration
)

# ... (existing table definitions) ...

# Lambda Function for API (placeholder that returns 404 for now)
self.api_lambda = lambda_.Function(
    self,
    "ApiLambda",
    runtime=lambda_.Runtime.PYTHON_3_11,
    handler="index.handler",
    code=lambda_.Code.from_inline("""
def handler(event, context):
    return {
        'statusCode': 404,
        'body': '{"message": "API not yet implemented"}'
    }
"""),
    timeout=Duration.seconds(30),
    memory_size=512,
    environment={
        "API_KEYS_TABLE": self.api_keys_table.table_name,
        "EVENTS_TABLE": self.events_table.table_name
    }
)

# Grant DynamoDB permissions
self.api_keys_table.grant_read_data(self.api_lambda)
self.events_table.grant_read_write_data(self.api_lambda)

# API Gateway REST API
self.api = apigateway.LambdaRestApi(
    self,
    "TriggerApi",
    handler=self.api_lambda,
    proxy=True,  # Forward all requests to Lambda
    rest_api_name="Trigger Ingestion API",
    description="Multi-tenant event ingestion API",
    deploy_options=apigateway.StageOptions(
        stage_name="prod",
        throttling_rate_limit=1000,
        throttling_burst_limit=2000
    ),
    default_cors_preflight_options=apigateway.CorsOptions(
        allow_origins=apigateway.Cors.ALL_ORIGINS,
        allow_methods=apigateway.Cors.ALL_METHODS,
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Amz-Date",
            "X-Api-Key",
            "X-Amz-Security-Token"
        ]
    )
)

CfnOutput(
    self,
    "ApiLambdaArn",
    value=self.api_lambda.function_arn,
    description="API Lambda function ARN"
)

CfnOutput(
    self,
    "ApiUrl",
    value=self.api.url,
    description="API Gateway endpoint URL"
)
```

### Success Criteria:

#### Automated Verification:
- [x] CDK synth includes API Gateway: `cd cdk && cdk synth | grep "AWS::ApiGateway::RestApi"`
- [x] CDK synth includes Lambda: `cd cdk && cdk synth | grep "AWS::Lambda::Function"`
- [x] **CDK deploy completes successfully**: `cd cdk && cdk deploy --require-approval never` returns exit code 0
- [x] **API Gateway URL is output**: `aws cloudformation describe-stacks --stack-name TriggerApiStack --query 'Stacks[0].Outputs[?OutputKey==\`ApiUrl\`].OutputValue' --output text` returns a valid URL
- [x] **API Gateway is accessible**: `curl -f $(aws cloudformation describe-stacks --stack-name TriggerApiStack --query 'Stacks[0].Outputs[?OutputKey==\`ApiUrl\`].OutputValue' --output text)` returns HTTP 404 (expected, as API not yet implemented)

#### Manual Verification:
- [x] **Verify CloudFormation stack updated**: Stack shows "UPDATE_COMPLETE" status
- [x] **Copy API Gateway URL** from CDK output or CloudFormation console: https://upgmwjvy3i.execute-api.us-east-1.amazonaws.com/prod/
- [x] **Test endpoint responds**: `curl <api-url>` returns 404 JSON response (placeholder Lambda)
- [x] **Verify Lambda exists**: AWS Lambda Console shows ApiLambda function
- [x] **Verify API Gateway configuration**: API Gateway Console shows "Trigger Ingestion API" with proxy integration
- [x] **Check throttling limits**: API Gateway shows 1000 RPS rate limit and 2000 burst limit in stage settings
- [x] **Test CORS**: `curl -H "Origin: http://example.com" -H "Access-Control-Request-Method: POST" -X OPTIONS <api-url>` returns CORS headers

**Implementation Note**: Phase 2 is complete when API Gateway is deployed and returns 404 responses. The placeholder Lambda will be replaced in Phase 3. Do not proceed until the API URL is accessible.

---

## Phase 3: Authentication & Basic Event Ingestion

### Overview
Implement the authentication middleware that validates API keys against DynamoDB, and create the core event ingestion endpoint (`POST /v1/events`). This replaces the placeholder Lambda with a real FastAPI application.

### Changes Required:

#### 1. Pydantic Models

**File**: `src/lambda_handlers/api/models.py`
```python
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime


class EventCreateRequest(BaseModel):
    """Free-form JSON payload for event creation"""
    class Config:
        extra = "allow"  # Allow arbitrary fields


class EventResponse(BaseModel):
    id: str
    created_at: int  # epoch_ms
    status: str


class EventDetail(BaseModel):
    id: str
    created_at: int
    status: str
    payload: Dict[str, Any]


class AckRequest(BaseModel):
    pass  # No body needed, event_id in path


class AckResponse(BaseModel):
    status: str = "acknowledged"


class EventListResponse(BaseModel):
    events: list[EventDetail]
```

#### 2. Authentication Middleware

**File**: `src/lambda_handlers/api/auth.py`
```python
import os
import boto3
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional

security = HTTPBearer()

dynamodb = boto3.resource('dynamodb')
api_keys_table = dynamodb.Table(os.environ.get('API_KEYS_TABLE', 'TriggerApi-TenantApiKeys'))


def get_tenant_from_api_key(api_key: str) -> Optional[str]:
    """
    Look up tenant_id from API key in DynamoDB.

    Table structure:
    pk = api_key
    sk = "meta"
    tenant_id = <tenant_id>
    status = "active" | "revoked"
    """
    try:
        response = api_keys_table.get_item(
            Key={'pk': api_key, 'sk': 'meta'}
        )

        item = response.get('Item')
        if not item:
            return None

        if item.get('status') != 'active':
            return None

        return item.get('tenant_id')
    except Exception as e:
        print(f"Error looking up API key: {e}")
        return None


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> str:
    """
    FastAPI dependency that validates the API key and returns tenant_id.

    Usage:
        @app.get("/endpoint")
        async def endpoint(tenant_id: str = Depends(verify_api_key)):
            ...
    """
    api_key = credentials.credentials

    tenant_id = get_tenant_from_api_key(api_key)

    if not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked API key"
        )

    return tenant_id
```

#### 3. Event Ingestion Route

**File**: `src/lambda_handlers/api/routes/events.py`
```python
import os
import uuid
import time
import boto3
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any

from ..auth import verify_api_key
from ..models import EventCreateRequest, EventResponse

router = APIRouter(prefix="/v1/events", tags=["events"])

dynamodb = boto3.resource('dynamodb')
events_table = dynamodb.Table(os.environ.get('EVENTS_TABLE', 'TriggerApi-Events'))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EventResponse)
async def create_event(
    payload: Dict[str, Any],
    tenant_id: str = Depends(verify_api_key)
):
    """
    Ingest a new event for the authenticated tenant.

    The payload is free-form JSON and stored as-is.
    """
    event_id = f"evt_{uuid.uuid4().hex[:8]}"
    timestamp = int(time.time() * 1000)  # epoch_ms

    item = {
        'pk': tenant_id,
        'sk': event_id,
        'tenant_id': tenant_id,
        'event_id': event_id,
        'status': 'undelivered',
        'timestamp': timestamp,
        'payload': payload,
        # GSI attributes for status-index
        'gsi1pk': tenant_id,
        'gsi1sk': f"undelivered#{timestamp}"
    }

    try:
        events_table.put_item(Item=item)
    except Exception as e:
        print(f"Error storing event: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to store event"
        )

    return EventResponse(
        id=event_id,
        created_at=timestamp,
        status="undelivered"
    )
```

#### 4. Health Check Route

**File**: `src/lambda_handlers/api/routes/health.py`
```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}
```

#### 5. Main FastAPI Application

**File**: `src/lambda_handlers/api/main.py`
```python
from fastapi import FastAPI
from mangum import Mangum

from .routes import events, health

app = FastAPI(
    title="Trigger Ingestion API",
    description="Multi-tenant event ingestion API",
    version="1.0.0"
)

# Include routers
app.include_router(health.router)
app.include_router(events.router)

# Mangum handler for AWS Lambda
handler = Mangum(app)
```

#### 6. Update CDK Stack to Replace Placeholder Lambda

**File**: `cdk/stacks/trigger_api_stack.py` (replace the placeholder Lambda code)

Replace the inline Lambda definition from Phase 2 with:

```python
# Remove the inline Lambda code and replace with:

# Lambda Layer for dependencies
from aws_cdk import (
    aws_lambda_python_alpha as lambda_python,
)

self.dependencies_layer = lambda_python.PythonLayerVersion(
    self,
    "DependenciesLayer",
    entry="../",  # Root of project
    compatible_runtimes=[lambda_.Runtime.PYTHON_3_11],
    description="FastAPI, Mangum, Boto3"
)

# Update Lambda Function for API (replace placeholder)
self.api_lambda = lambda_.Function(
    self,
    "ApiLambda",
    runtime=lambda_.Runtime.PYTHON_3_11,
    handler="main.handler",
    code=lambda_.Code.from_asset("../src/lambda_handlers/api"),
    layers=[self.dependencies_layer],
    timeout=Duration.seconds(30),
    memory_size=512,
    environment={
        "API_KEYS_TABLE": self.api_keys_table.table_name,
        "EVENTS_TABLE": self.events_table.table_name
    }
)

# Permissions already granted in Phase 2, but ensure they're present
self.api_keys_table.grant_read_data(self.api_lambda)
self.events_table.grant_read_write_data(self.api_lambda)

# API Gateway already defined in Phase 2
```

### Success Criteria:

#### Automated Verification:
- [ ] Python imports work: `python -c "from src.lambda_handlers.api.main import app; print('OK')"`
- [ ] FastAPI app initializes: `python -c "from src.lambda_handlers.api.main import app; assert app is not None"`
- [ ] **CDK deploy succeeds**: `cd cdk && cdk deploy --require-approval never` returns exit code 0
- [ ] **Lambda function updated**: `aws lambda get-function --function-name $(aws cloudformation describe-stacks --stack-name TriggerApiStack --query 'Stacks[0].Outputs[?OutputKey==\`ApiLambdaArn\`].OutputValue' --output text | cut -d':' -f7)` shows updated code
- [ ] **Health endpoint works**: `curl $(aws cloudformation describe-stacks --stack-name TriggerApiStack --query 'Stacks[0].Outputs[?OutputKey==\`ApiUrl\`].OutputValue' --output text)/health` returns `{"status":"healthy"}`

#### Manual Verification:
- [ ] **Seed a test API key manually** in DynamoDB TenantApiKeys table (pk=test_key_123, sk=meta, tenant_id=test, status=active)
- [ ] **Test auth with invalid key**: `curl -X POST <api-url>/v1/events -H "Authorization: Bearer invalid_key" -H "Content-Type: application/json" -d '{"test":"data"}'` returns 401
- [ ] **Test auth with valid key**: `curl -X POST <api-url>/v1/events -H "Authorization: Bearer test_key_123" -H "Content-Type: application/json" -d '{"event_type":"test"}'` returns 201 with event_id
- [ ] **Verify event stored in DynamoDB**: Check Events table for the created event with tenant_id=test
- [ ] **Check CloudWatch Logs**: Verify FastAPI startup messages and successful request logs
- [ ] **Confirm auth isolation**: Try to access the event with different tenant key (should fail)

**Implementation Note**: Phase 3 is complete when basic authentication works and you can successfully create events via the API using a valid API key. The key verification must be confirmed before proceeding to Phase 4.

---

## Phase 4: Event Retrieval Endpoints

### Overview
Implement event listing with status filtering (`GET /v1/events`) and single event retrieval (`GET /v1/events/{id}`). These endpoints use the GSI for efficient queries and enable the worker to discover undelivered events.

### Changes Required:

#### 1. Add Retrieval Routes to events.py

**File**: `src/lambda_handlers/api/routes/events.py` (append to existing)
```python
from typing import Optional
from ..models import EventDetail, EventListResponse


@router.get("", response_model=EventListResponse)
async def list_events(
    status: Optional[str] = None,
    limit: int = 50,
    tenant_id: str = Depends(verify_api_key)
):
    """
    List events for the authenticated tenant.

    Query parameters:
    - status: Filter by status ("undelivered" or "delivered")
    - limit: Maximum number of events to return (default 50, max 100)
    """
    if limit > 100:
        limit = 100

    try:
        if status:
            # Query using GSI for status filtering
            response = events_table.query(
                IndexName='status-index',
                KeyConditionExpression='gsi1pk = :tenant_id AND begins_with(gsi1sk, :status)',
                ExpressionAttributeValues={
                    ':tenant_id': tenant_id,
                    ':status': f"{status}#"
                },
                Limit=limit,
                ScanIndexForward=True  # Oldest first
            )
        else:
            # Query main table for all events
            response = events_table.query(
                KeyConditionExpression='pk = :tenant_id',
                ExpressionAttributeValues={
                    ':tenant_id': tenant_id
                },
                Limit=limit,
                ScanIndexForward=False  # Newest first
            )

        items = response.get('Items', [])

        events = [
            EventDetail(
                id=item['event_id'],
                created_at=item['timestamp'],
                status=item['status'],
                payload=item['payload']
            )
            for item in items
        ]

        return EventListResponse(events=events)

    except Exception as e:
        print(f"Error listing events: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to list events"
        )


@router.get("/{event_id}", response_model=EventDetail)
async def get_event(
    event_id: str,
    tenant_id: str = Depends(verify_api_key)
):
    """
    Retrieve a single event by ID.

    Returns 404 if event doesn't exist or doesn't belong to tenant.
    """
    try:
        response = events_table.get_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            }
        )

        item = response.get('Item')
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Event {event_id} not found"
            )

        return EventDetail(
            id=item['event_id'],
            created_at=item['timestamp'],
            status=item['status'],
            payload=item['payload']
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error retrieving event: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve event"
        )
```

### Success Criteria:

#### Automated Verification:
- [ ] Python imports work: `python -c "from src.lambda_handlers.api.routes.events import list_events, get_event; print('OK')"`
- [ ] **CDK deploy succeeds**: `cd cdk && cdk deploy --require-approval never` returns exit code 0
- [ ] Lambda function updated: `aws lambda get-function --function-name <function-name> --query 'Configuration.LastModified'` shows recent timestamp

#### Manual Verification:
- [ ] **Create mock data**: Use POST /v1/events with test API key to create 3-5 test events
- [ ] **Retrieve all events**: `curl <api-url>/v1/events -H "Authorization: Bearer test_key_123"` returns array with all created events
- [ ] **Filter by undelivered**: `curl <api-url>/v1/events?status=undelivered -H "Authorization: Bearer test_key_123"` returns only undelivered events
- [ ] **Retrieve single event**: `curl <api-url>/v1/events/<event_id> -H "Authorization: Bearer test_key_123"` returns full event details with payload
- [ ] **Test 404 for invalid ID**: `curl <api-url>/v1/events/evt_nonexistent -H "Authorization: Bearer test_key_123"` returns 404
- [ ] **Verify tenant isolation**: Create event with tenant A's key, try to retrieve with tenant B's key (should return 404)
- [ ] **Check mock data integrity**: Verify retrieved payloads match what was submitted in POST
- [ ] **Verify GSI usage**: Check CloudWatch Logs show Query operation with IndexName=status-index when filtering by status

**Implementation Note**: Phase 4 is complete when you can reliably retrieve mock data you've created, including filtering by status. The ability to retrieve and verify mock events confirms the data flow is working correctly. Do not proceed until retrieval works for multiple test events.

---

## Phase 5: Event Acknowledgment & Deletion

### Overview
Implement state transition endpoints: `POST /v1/events/{id}/ack` to mark events as delivered, and `DELETE /v1/events/{id}` to remove events. These complete the event lifecycle.

### Changes Required:

#### 1. Add Acknowledgment and Deletion Routes

**File**: `src/lambda_handlers/api/routes/events.py` (append to existing)
```python
from ..models import AckRequest, AckResponse


@router.post("/{event_id}/ack", response_model=AckResponse)
async def acknowledge_event(
    event_id: str,
    tenant_id: str = Depends(verify_api_key)
):
    """
    Mark an event as delivered (acknowledged).

    Updates the status from "undelivered" to "delivered" and updates GSI attributes.
    """
    try:
        # First verify the event exists and belongs to this tenant
        response = events_table.get_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            }
        )

        item = response.get('Item')
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Event {event_id} not found"
            )

        if item.get('status') == 'delivered':
            # Already acknowledged, return success (idempotent)
            return AckResponse()

        # Update status to delivered
        timestamp = item['timestamp']
        events_table.update_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            },
            UpdateExpression='SET #status = :delivered, gsi1sk = :gsi1sk',
            ExpressionAttributeNames={
                '#status': 'status'
            },
            ExpressionAttributeValues={
                ':delivered': 'delivered',
                ':gsi1sk': f"delivered#{timestamp}"
            }
        )

        return AckResponse()

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error acknowledging event: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to acknowledge event"
        )


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    tenant_id: str = Depends(verify_api_key)
):
    """
    Delete an event.

    Returns 204 No Content on success, 404 if event doesn't exist.
    """
    try:
        # Check if event exists first
        response = events_table.get_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            }
        )

        if not response.get('Item'):
            raise HTTPException(
                status_code=404,
                detail=f"Event {event_id} not found"
            )

        # Delete the event
        events_table.delete_item(
            Key={
                'pk': tenant_id,
                'sk': event_id
            }
        )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting event: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to delete event"
        )
```

### Success Criteria:

#### Automated Verification:
- [ ] Python imports work: `python -c "from src.lambda_handlers.api.routes.events import acknowledge_event, delete_event; print('OK')"`
- [ ] **CDK deploy succeeds**: `cd cdk && cdk deploy --require-approval never` returns exit code 0

#### Manual Verification:
- [ ] **Create mock event**: `curl -X POST <api-url>/v1/events -H "Authorization: Bearer test_key_123" -d '{"event_type":"test.ack","data":"mock"}' -H "Content-Type: application/json"` returns event_id
- [ ] **Verify undelivered**: `curl <api-url>/v1/events?status=undelivered -H "Authorization: Bearer test_key_123"` includes the mock event
- [ ] **Acknowledge mock event**: `curl -X POST <api-url>/v1/events/<event_id>/ack -H "Authorization: Bearer test_key_123"` returns `{"status":"acknowledged"}`
- [ ] **Verify status changed in DB**: `curl <api-url>/v1/events/<event_id> -H "Authorization: Bearer test_key_123"` shows status="delivered"
- [ ] **Verify GSI updated**: `curl <api-url>/v1/events?status=undelivered -H "Authorization: Bearer test_key_123"` no longer includes the event
- [ ] **Verify in delivered list**: `curl <api-url>/v1/events?status=delivered -H "Authorization: Bearer test_key_123"` includes the acknowledged event
- [ ] **Test idempotency**: Acknowledge same event again, returns 200 without error
- [ ] **Delete mock event**: `curl -X DELETE <api-url>/v1/events/<event_id> -H "Authorization: Bearer test_key_123"` returns 204
- [ ] **Verify deletion**: `curl <api-url>/v1/events/<event_id> -H "Authorization: Bearer test_key_123"` returns 404
- [ ] **Test tenant isolation**: Try to ack/delete other tenant's events (should return 404)

**Implementation Note**: Phase 5 is complete when you can successfully modify mock data through ack and delete operations, and verify the changes persist in DynamoDB. The full event lifecycle (create → retrieve → ack → delete) must work with mock data before proceeding to Phase 6.

---

## Phase 6: Mock Worker Implementation

### Overview
Build a Python script that simulates Zapier's event processing engine. The worker polls for undelivered events, processes them (logs payload), and acknowledges them. Supports multi-tenant operation with configurable API keys.

### Changes Required:

#### 1. Mock Worker Script

**File**: `src/worker/mock_worker.py`
```python
#!/usr/bin/env python3
"""
Mock Worker - Simulates Zapier's trigger engine

Polls the API for undelivered events, processes them, and acknowledges them.
Supports multiple tenants via environment variables.
"""
import os
import sys
import time
import requests
from typing import Optional


class MockWorker:
    def __init__(self, api_url: str, api_key: str, tenant_name: str):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.tenant_name = tenant_name
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

    def get_undelivered_events(self):
        """Fetch undelivered events from the inbox"""
        try:
            url = f"{self.api_url}/v1/events?status=undelivered&limit=10"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json().get('events', [])
        except requests.exceptions.RequestException as e:
            print(f"[{self.tenant_name}] Error fetching events: {e}")
            return []

    def process_event(self, event: dict):
        """
        Simulate event processing.
        In a real system, this would trigger a Zap, send webhooks, etc.
        """
        event_id = event['id']
        payload = event['payload']

        print(f"[{self.tenant_name}] Processing event {event_id}")
        print(f"[{self.tenant_name}]   Payload: {payload}")

        # Simulate some work
        time.sleep(0.5)

        print(f"[{self.tenant_name}]   ✓ Processed successfully")

    def acknowledge_event(self, event_id: str) -> bool:
        """Acknowledge an event as delivered"""
        try:
            url = f"{self.api_url}/v1/events/{event_id}/ack"
            response = requests.post(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            print(f"[{self.tenant_name}]   ✓ Acknowledged {event_id}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"[{self.tenant_name}]   ✗ Error acknowledging {event_id}: {e}")
            return False

    def run(self, poll_interval: int = 5):
        """Main worker loop"""
        print(f"[{self.tenant_name}] Worker started")
        print(f"[{self.tenant_name}] API URL: {self.api_url}")
        print(f"[{self.tenant_name}] Poll interval: {poll_interval}s")
        print()

        while True:
            try:
                events = self.get_undelivered_events()

                if events:
                    print(f"[{self.tenant_name}] Found {len(events)} undelivered event(s)")

                    for event in events:
                        self.process_event(event)
                        self.acknowledge_event(event['id'])

                    print()

                time.sleep(poll_interval)

            except KeyboardInterrupt:
                print(f"\n[{self.tenant_name}] Worker stopped by user")
                sys.exit(0)
            except Exception as e:
                print(f"[{self.tenant_name}] Unexpected error: {e}")
                time.sleep(poll_interval)


def main():
    """
    Run worker for a single tenant or multiple tenants.

    Environment variables:
    - API_URL: API Gateway endpoint URL (required)
    - API_KEY: Single tenant API key (for single-tenant mode)
    - API_KEYS: Comma-separated list of API keys (for multi-tenant mode)
    - TENANT_NAMES: Comma-separated list of tenant names (optional, for logging)
    - POLL_INTERVAL: Seconds between polls (default: 5)
    """
    api_url = os.environ.get('API_URL')
    if not api_url:
        print("Error: API_URL environment variable required")
        sys.exit(1)

    # Single-tenant mode
    api_key = os.environ.get('API_KEY')
    if api_key:
        tenant_name = os.environ.get('TENANT_NAME', 'default')
        poll_interval = int(os.environ.get('POLL_INTERVAL', '5'))

        worker = MockWorker(api_url, api_key, tenant_name)
        worker.run(poll_interval)

    # Multi-tenant mode
    api_keys_str = os.environ.get('API_KEYS')
    if api_keys_str:
        api_keys = [k.strip() for k in api_keys_str.split(',')]
        tenant_names_str = os.environ.get('TENANT_NAMES', '')
        tenant_names = [n.strip() for n in tenant_names_str.split(',')] if tenant_names_str else []

        # Pad tenant names if not enough provided
        while len(tenant_names) < len(api_keys):
            tenant_names.append(f'tenant-{len(tenant_names) + 1}')

        poll_interval = int(os.environ.get('POLL_INTERVAL', '5'))

        print("Starting workers for multiple tenants...")
        print()

        import threading

        workers = []
        for api_key, tenant_name in zip(api_keys, tenant_names):
            worker = MockWorker(api_url, api_key, tenant_name)
            thread = threading.Thread(target=worker.run, args=(poll_interval,))
            thread.daemon = True
            thread.start()
            workers.append(thread)

        # Wait for all threads
        try:
            for thread in workers:
                thread.join()
        except KeyboardInterrupt:
            print("\nStopping all workers...")
            sys.exit(0)

    print("Error: Either API_KEY or API_KEYS must be set")
    sys.exit(1)


if __name__ == '__main__':
    main()
```

#### 2. Worker Requirements

**File**: `src/worker/requirements.txt`
```txt
requests==2.31.0
```

#### 3. Worker README

**File**: `src/worker/README.md`
```markdown
# Mock Worker

Simulates Zapier's trigger engine by polling for events and processing them.

## Usage

### Single Tenant
```bash
export API_URL="https://your-api-gateway-url"
export API_KEY="tenant_acme_live_xxx"
export TENANT_NAME="acme"
python src/worker/mock_worker.py
```

### Multiple Tenants
```bash
export API_URL="https://your-api-gateway-url"
export API_KEYS="key1,key2,key3"
export TENANT_NAMES="acme,globex,initech"
python src/worker/mock_worker.py
```

## Environment Variables

- `API_URL` (required): API Gateway endpoint URL
- `API_KEY`: Single tenant API key
- `API_KEYS`: Comma-separated list of API keys for multi-tenant mode
- `TENANT_NAMES`: Comma-separated list of tenant names (for logging)
- `POLL_INTERVAL`: Seconds between polls (default: 5)
```

### Success Criteria:

#### Automated Verification:
- [ ] Worker script has correct permissions: `chmod +x src/worker/mock_worker.py`
- [ ] Python syntax is valid: `python -m py_compile src/worker/mock_worker.py`
- [ ] Worker dependencies install: `pip install -r src/worker/requirements.txt`

#### Manual Verification:
- [ ] Run worker with test API key: `API_URL=<url> API_KEY=<key> TENANT_NAME=test python src/worker/mock_worker.py`
- [ ] Worker starts without errors and displays startup messages
- [ ] Create test events via POST /v1/events from another terminal
- [ ] Verify worker discovers and processes events (logs appear)
- [ ] Verify worker acknowledges events (check with GET /v1/events?status=delivered)
- [ ] Test multi-tenant mode with 2-3 API keys simultaneously
- [ ] Verify each tenant's events are processed independently
- [ ] Test graceful shutdown with Ctrl+C

**Implementation Note**: After automated verification, manually test the worker end-to-end with multiple tenants creating events concurrently before proceeding.

---

## Phase 7: Data Seeding & Testing

### Overview
Create a script to seed 3 test tenants with API keys, and implement unit tests for core functionality. This enables demo-ready testing and validates business logic correctness.

### Changes Required:

#### 1. Tenant Seeding Script

**File**: `scripts/seed_tenants.py`
```python
#!/usr/bin/env python3
"""
Seed test tenants into DynamoDB

Creates 3 test tenants with API keys for demonstration purposes.
"""
import boto3
import uuid
import time
import sys


def generate_api_key(tenant_name: str) -> str:
    """Generate a Stripe-style API key"""
    random_suffix = uuid.uuid4().hex[:12]
    return f"tenant_{tenant_name}_live_{random_suffix}"


def seed_tenants():
    """Seed 3 test tenants"""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('TriggerApi-TenantApiKeys')

    tenants = [
        {'name': 'acme', 'display': 'Acme Corp'},
        {'name': 'globex', 'display': 'Globex Inc'},
        {'name': 'initech', 'display': 'Initech LLC'}
    ]

    print("Seeding test tenants...")
    print()

    created_keys = []

    for tenant in tenants:
        tenant_name = tenant['name']
        api_key = generate_api_key(tenant_name)

        item = {
            'pk': api_key,
            'sk': 'meta',
            'tenant_id': tenant_name,
            'status': 'active',
            'created_at': int(time.time() * 1000),
            'display_name': tenant['display']
        }

        try:
            table.put_item(Item=item)
            print(f"✓ Created tenant: {tenant['display']}")
            print(f"  Tenant ID: {tenant_name}")
            print(f"  API Key: {api_key}")
            print()

            created_keys.append({
                'tenant': tenant_name,
                'key': api_key
            })
        except Exception as e:
            print(f"✗ Error creating tenant {tenant_name}: {e}")
            sys.exit(1)

    print("=" * 60)
    print("All tenants created successfully!")
    print("=" * 60)
    print()
    print("Export these for testing:")
    print()
    for item in created_keys:
        print(f"export {item['tenant'].upper()}_API_KEY='{item['key']}'")
    print()
    print("Multi-tenant worker:")
    print(f"export API_KEYS='{','.join([i['key'] for i in created_keys])}'")
    print(f"export TENANT_NAMES='{','.join([i['tenant'] for i in created_keys])}'")


if __name__ == '__main__':
    seed_tenants()
```

#### 2. Unit Tests - Authentication

**File**: `tests/test_auth.py`
```python
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from src.lambda_handlers.api.auth import get_tenant_from_api_key


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table"""
    with patch('src.lambda_handlers.api.auth.api_keys_table') as mock_table:
        yield mock_table


def test_get_tenant_from_api_key_success(mock_dynamodb_table):
    """Test successful API key lookup"""
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'pk': 'test_key',
            'sk': 'meta',
            'tenant_id': 'acme',
            'status': 'active'
        }
    }

    tenant_id = get_tenant_from_api_key('test_key')

    assert tenant_id == 'acme'
    mock_dynamodb_table.get_item.assert_called_once_with(
        Key={'pk': 'test_key', 'sk': 'meta'}
    )


def test_get_tenant_from_api_key_not_found(mock_dynamodb_table):
    """Test API key not found"""
    mock_dynamodb_table.get_item.return_value = {}

    tenant_id = get_tenant_from_api_key('invalid_key')

    assert tenant_id is None


def test_get_tenant_from_api_key_revoked(mock_dynamodb_table):
    """Test revoked API key"""
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'pk': 'test_key',
            'sk': 'meta',
            'tenant_id': 'acme',
            'status': 'revoked'
        }
    }

    tenant_id = get_tenant_from_api_key('test_key')

    assert tenant_id is None


def test_get_tenant_from_api_key_exception(mock_dynamodb_table):
    """Test DynamoDB exception handling"""
    mock_dynamodb_table.get_item.side_effect = Exception("DynamoDB error")

    tenant_id = get_tenant_from_api_key('test_key')

    assert tenant_id is None
```

#### 3. Unit Tests - Events

**File**: `tests/test_events.py`
```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.lambda_handlers.api.main import app


@pytest.fixture
def client():
    """FastAPI test client"""
    return TestClient(app)


@pytest.fixture
def mock_auth():
    """Mock authentication to return test tenant"""
    with patch('src.lambda_handlers.api.routes.events.verify_api_key') as mock:
        mock.return_value = 'test_tenant'
        yield mock


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB table"""
    with patch('src.lambda_handlers.api.routes.events.events_table') as mock_table:
        yield mock_table


def test_create_event(client, mock_auth, mock_dynamodb):
    """Test event creation"""
    mock_dynamodb.put_item.return_value = {}

    response = client.post(
        "/v1/events",
        json={"event_type": "test.event", "data": "foo"},
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 201
    data = response.json()
    assert 'id' in data
    assert data['id'].startswith('evt_')
    assert data['status'] == 'undelivered'
    assert 'created_at' in data


def test_list_events_undelivered(client, mock_auth, mock_dynamodb):
    """Test listing undelivered events"""
    mock_dynamodb.query.return_value = {
        'Items': [
            {
                'event_id': 'evt_123',
                'timestamp': 1700000000000,
                'status': 'undelivered',
                'payload': {'test': 'data'}
            }
        ]
    }

    response = client.get(
        "/v1/events?status=undelivered",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data['events']) == 1
    assert data['events'][0]['id'] == 'evt_123'
    assert data['events'][0]['status'] == 'undelivered'


def test_get_event_not_found(client, mock_auth, mock_dynamodb):
    """Test getting non-existent event"""
    mock_dynamodb.get_item.return_value = {}

    response = client.get(
        "/v1/events/evt_nonexistent",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 404


def test_acknowledge_event(client, mock_auth, mock_dynamodb):
    """Test event acknowledgment"""
    mock_dynamodb.get_item.return_value = {
        'Item': {
            'event_id': 'evt_123',
            'status': 'undelivered',
            'timestamp': 1700000000000
        }
    }
    mock_dynamodb.update_item.return_value = {}

    response = client.post(
        "/v1/events/evt_123/ack",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'acknowledged'


def test_delete_event(client, mock_auth, mock_dynamodb):
    """Test event deletion"""
    mock_dynamodb.get_item.return_value = {
        'Item': {'event_id': 'evt_123'}
    }
    mock_dynamodb.delete_item.return_value = {}

    response = client.delete(
        "/v1/events/evt_123",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 204
```

#### 4. Pytest Configuration

**File**: `pytest.ini`
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --strict-markers
    --cov=src
    --cov-report=term-missing
    --cov-report=html
```

### Success Criteria:

#### Automated Verification:
- [ ] Seeding script is executable: `chmod +x scripts/seed_tenants.py`
- [ ] Python syntax valid: `python -m py_compile scripts/seed_tenants.py`
- [ ] Run seeding script: `python scripts/seed_tenants.py` completes without errors
- [ ] Verify 3 tenants created: `aws dynamodb scan --table-name TriggerApi-TenantApiKeys --query 'Count'` returns 3
- [ ] Unit tests run successfully: `pytest tests/ -v`
- [ ] Code coverage >80%: `pytest tests/ --cov=src --cov-report=term`

#### Manual Verification:
- [ ] Check DynamoDB Console: 3 API keys exist with status="active"
- [ ] Copy API keys from script output
- [ ] Test each API key with POST /v1/events (should succeed)
- [ ] Test invalid API key (should return 401)
- [ ] Verify test coverage report in htmlcov/index.html
- [ ] Review coverage report to identify untested edge cases

**Implementation Note**: After automated tests pass, manually verify all 3 tenant API keys work correctly with the API before proceeding.

---

## Phase 8: Deployment & Documentation

### Overview
Finalize deployment process, create comprehensive documentation, and provide a Postman collection for easy testing. This makes the project demo-ready and easily shareable.

### Changes Required:

#### 1. Deployment Script

**File**: `scripts/deploy.sh`
```bash
#!/bin/bash
set -e

echo "=========================================="
echo "Deploying Trigger Ingestion API"
echo "=========================================="
echo ""

# Check prerequisites
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI not found. Please install it first."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 not found. Please install it first."
    exit 1
fi

# Install Python dependencies
echo "1. Installing Python dependencies..."
pip install -r requirements.txt
pip install -r cdk/requirements.txt
echo "   ✓ Dependencies installed"
echo ""

# Bootstrap CDK (if needed)
echo "2. Bootstrapping CDK (if needed)..."
cd cdk
cdk bootstrap || echo "   (Already bootstrapped)"
echo "   ✓ CDK ready"
echo ""

# Deploy CDK stack
echo "3. Deploying infrastructure..."
cdk deploy --require-approval never
echo "   ✓ Infrastructure deployed"
echo ""

cd ..

# Seed tenants
echo "4. Seeding test tenants..."
python scripts/seed_tenants.py
echo "   ✓ Tenants seeded"
echo ""

# Get API URL
API_URL=$(aws cloudformation describe-stacks \
    --stack-name TriggerApiStack \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
    --output text)

echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "API URL: $API_URL"
echo ""
echo "Next steps:"
echo "1. Export tenant API keys (see output from seed script above)"
echo "2. Test with: curl $API_URL/health"
echo "3. Import Postman collection from docs/postman_collection.json"
echo "4. Run mock worker: python src/worker/mock_worker.py"
echo ""
```

#### 2. Testing Guide

**File**: `docs/TESTING.md`
```markdown
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
```

#### 3. Postman Collection

**File**: `docs/postman_collection.json`
```json
{
  "info": {
    "name": "Trigger Ingestion API",
    "description": "Multi-tenant event ingestion API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "variable": [
    {
      "key": "api_url",
      "value": "https://your-api-gateway-url",
      "type": "string"
    },
    {
      "key": "api_key",
      "value": "tenant_acme_live_xxx",
      "type": "string"
    }
  ],
  "item": [
    {
      "name": "Health Check",
      "request": {
        "method": "GET",
        "header": [],
        "url": {
          "raw": "{{api_url}}/health",
          "host": ["{{api_url}}"],
          "path": ["health"]
        }
      }
    },
    {
      "name": "Create Event",
      "request": {
        "method": "POST",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{api_key}}"
          },
          {
            "key": "Content-Type",
            "value": "application/json"
          }
        ],
        "body": {
          "mode": "raw",
          "raw": "{\n  \"event_type\": \"customer.created\",\n  \"customer_id\": \"cust_123\",\n  \"email\": \"alice@example.com\"\n}"
        },
        "url": {
          "raw": "{{api_url}}/v1/events",
          "host": ["{{api_url}}"],
          "path": ["v1", "events"]
        }
      }
    },
    {
      "name": "List Events (Undelivered)",
      "request": {
        "method": "GET",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{api_key}}"
          }
        ],
        "url": {
          "raw": "{{api_url}}/v1/events?status=undelivered&limit=50",
          "host": ["{{api_url}}"],
          "path": ["v1", "events"],
          "query": [
            {
              "key": "status",
              "value": "undelivered"
            },
            {
              "key": "limit",
              "value": "50"
            }
          ]
        }
      }
    },
    {
      "name": "Get Event by ID",
      "request": {
        "method": "GET",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{api_key}}"
          }
        ],
        "url": {
          "raw": "{{api_url}}/v1/events/evt_12345678",
          "host": ["{{api_url}}"],
          "path": ["v1", "events", "evt_12345678"]
        }
      }
    },
    {
      "name": "Acknowledge Event",
      "request": {
        "method": "POST",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{api_key}}"
          }
        ],
        "url": {
          "raw": "{{api_url}}/v1/events/evt_12345678/ack",
          "host": ["{{api_url}}"],
          "path": ["v1", "events", "evt_12345678", "ack"]
        }
      }
    },
    {
      "name": "Delete Event",
      "request": {
        "method": "DELETE",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{api_key}}"
          }
        ],
        "url": {
          "raw": "{{api_url}}/v1/events/evt_12345678",
          "host": ["{{api_url}}"],
          "path": ["v1", "events", "evt_12345678"]
        }
      }
    },
    {
      "name": "List All Events",
      "request": {
        "method": "GET",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{api_key}}"
          }
        ],
        "url": {
          "raw": "{{api_url}}/v1/events?limit=100",
          "host": ["{{api_url}}"],
          "path": ["v1", "events"],
          "query": [
            {
              "key": "limit",
              "value": "100"
            }
          ]
        }
      }
    }
  ]
}
```

#### 4. Update Main README

**File**: `README.md` (replace existing content)
```markdown
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
```

### Success Criteria:

#### Automated Verification:
- [ ] Deploy script is executable: `chmod +x scripts/deploy.sh`
- [ ] Deploy script runs without errors: `./scripts/deploy.sh`
- [ ] API URL is accessible: `curl -f $(aws cloudformation describe-stacks --stack-name TriggerApiStack --query 'Stacks[0].Outputs[?OutputKey==\`ApiUrl\`].OutputValue' --output text)/health`
- [ ] All documentation files are valid markdown (no syntax errors)

#### Manual Verification:
- [ ] Follow README.md Quick Start guide from scratch
- [ ] Import Postman collection and test all endpoints
- [ ] Verify all Postman requests work with test tenant
- [ ] Follow TESTING.md guide and complete all test scenarios
- [ ] Run multi-tenant worker with all 3 test tenants
- [ ] Create demo video or screenshots showing:
  - Event creation
  - Worker processing
  - Multi-tenant isolation
  - Full event lifecycle
- [ ] Share with colleague for external validation

**Implementation Note**: After automated verification, perform a complete end-to-end test following the documentation as if you were a new user to ensure everything works smoothly.

---

## Testing Strategy

### Unit Tests

**Coverage Target**: >80% on core business logic

**What to Test**:
1. **Authentication** (`test_auth.py`):
   - Valid API key returns tenant_id
   - Invalid API key returns None
   - Revoked API key returns None
   - DynamoDB exceptions handled gracefully

2. **Event Endpoints** (`test_events.py`):
   - Event creation with valid payload
   - Event listing with/without status filter
   - Single event retrieval (found/not found)
   - Event acknowledgment (idempotency)
   - Event deletion (exists/not exists)
   - Multi-tenant isolation

**Test Tools**:
- `pytest` for test runner
- `pytest-cov` for coverage reporting
- `moto` for mocking AWS services
- `FastAPI TestClient` for API testing

### Integration Tests (Manual)

**Test Scenarios**:

1. **Happy Path**:
   - Create event → List undelivered → Acknowledge → Verify delivered → Delete

2. **Multi-Tenant Isolation**:
   - Tenant A creates event
   - Tenant B cannot access it (404)
   - Tenant B cannot acknowledge it (404)

3. **Worker Integration**:
   - Create multiple events
   - Start worker
   - Verify all events processed
   - Verify all events acknowledged
   - Verify inbox empty

4. **Edge Cases**:
   - Acknowledge already-acknowledged event (idempotent)
   - Delete non-existent event (404)
   - Invalid API key (401)
   - Malformed JSON payload (422)

### Performance Considerations

**Expected Performance** (DynamoDB PAY_PER_REQUEST):
- Event ingestion: <100ms p99
- Event listing (via GSI): <50ms p99
- Single event retrieval: <20ms p99
- Acknowledgment: <50ms p99

**No Load Testing Required** for this demo, but architecture supports:
- 1000+ RPS ingestion
- Linear scaling with DynamoDB
- Lambda concurrency handles burst traffic

## Migration Notes

N/A - This is a greenfield project with no existing data to migrate.

**Future Considerations**:
- If adding event_type filtering, consider adding GSI2
- If implementing deduplication, add dedupe_key attribute
- If adding event expiration, enable DynamoDB TTL

## References

- Project documentation: `project.md`
- DynamoDB schema: `dynamodb.md`
- API endpoints spec: `api_endpoints.md`
- FastAPI docs: https://fastapi.tiangolo.com/
- AWS CDK Python: https://docs.aws.amazon.com/cdk/v2/guide/work-with-cdk-python.html
- Mangum (Lambda adapter): https://mangum.io/
