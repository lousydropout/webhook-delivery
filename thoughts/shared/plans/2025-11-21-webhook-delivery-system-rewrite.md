# Webhook Delivery System - Full Rewrite Implementation Plan

## Overview

Complete rewrite of the trigger ingestion API to transform it from a pull-based event inbox into a push-based webhook delivery system with SQS-driven async processing, automatic delivery with retry logic, and Stripe-style HMAC signatures.

## Current State Analysis

**Existing Implementation (to be replaced):**
- Pull-based event inbox model (GET /v1/events)
- Single Lambda handling all operations
- Status: undelivered/delivered
- Manual event acknowledgment required
- No outbound delivery mechanism
- Generic API Gateway URL

**Target Architecture:**
- Push-based webhook delivery
- Dual Lambda setup (API + Worker)
- SQS queue with DLQ for reliability
- Automatic webhook delivery with retries
- Stripe-style HMAC signatures
- Custom domain: hooks.vincentchan.cloud
- Status: PENDING/DELIVERED/FAILED with attempt tracking

## Desired End State

A production-ready webhook delivery system where:

1. **Event Ingestion**: External systems POST events to hooks.vincentchan.cloud/events
2. **Async Processing**: Events are queued to SQS for async delivery
3. **Webhook Delivery**: Worker Lambda delivers to tenant-configured URLs with HMAC signatures
4. **Retry Logic**: Failed deliveries retry with exponential backoff (1min, 2min, 4min, 8min, 16min)
5. **DLQ Management**: Failed messages move to DLQ after 5 attempts, can be manually requeued
6. **Status Tracking**: Events track delivery status and attempt count

### Verification Criteria:
- Custom domain resolves and has valid SSL certificate
- Event ingestion returns 201 with event_id
- Worker Lambda successfully delivers webhooks
- HMAC signatures validate correctly at receiver
- Retry logic functions with exponential backoff
- DLQ processor can manually requeue messages
- All endpoints accessible via hooks.vincentchan.cloud

## What We're NOT Doing

- Backward compatibility with old schema/endpoints
- Data migration from existing implementation
- Event transformation or filtering
- Webhook payload templates
- Rate limiting per tenant
- Webhook response validation beyond 2xx status
- Multi-region deployment
- UI or dashboard
- Real-time webhook status notifications
- Webhook retry configuration per tenant (uses fixed strategy)

## Implementation Approach

Full rewrite with clean slate architecture:
- No Lambda layers (dependencies bundled directly)
- New codebase structure (src/api, src/worker, src/dlq_processor)
- New DynamoDB schema optimized for webhook delivery
- SQS as the backbone for reliability and retry logic
- Custom domain with SSL from the start

Build in 6 phases with clear automated and manual verification at each step.

---

## Phase 1: New CDK Infrastructure Stack

### Overview
Create completely new CDK stack with custom domain, SQS queues, updated DynamoDB schemas, and three Lambda functions (no layers).

### Changes Required:

#### 1. New CDK Stack File

**File**: `cdk/stacks/webhook_delivery_stack.py`
```python
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    BundlingOptions,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_apigateway as apigateway,
    aws_sqs as sqs,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_lambda_event_sources as lambda_events,
)
from constructs import Construct

prefix = "Vincent-TriggerApi"


class WebhookDeliveryStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ============================================================
        # Route53 Hosted Zone (existing)
        # ============================================================
        zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "VincentHostedZone",
            hosted_zone_id="Z00669322LNYAWLYNIHGN",
            zone_name="vincentchan.cloud",
        )

        # ============================================================
        # ACM Certificate for Custom Domain
        # ============================================================
        certificate = acm.Certificate(
            self,
            "TriggerApiCert",
            domain_name="hooks.vincentchan.cloud",
            validation=acm.CertificateValidation.from_dns(zone),
        )

        # ============================================================
        # DynamoDB: TenantApiKeys
        # Schema: apiKey (PK) → { tenantId, targetUrl, webhookSecret, isActive }
        # ============================================================
        self.tenant_api_keys_table = dynamodb.Table(
            self,
            "TenantApiKeys",
            table_name=f"{prefix}-TenantApiKeys",
            partition_key=dynamodb.Attribute(
                name="apiKey",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery=False,
        )

        # ============================================================
        # DynamoDB: Events
        # Schema: tenantId (PK), eventId (SK)
        # GSI: status-index (status PK, createdAt SK)
        # Attributes: status, payload, targetUrl, attempts, lastAttemptAt, ttl
        # ============================================================
        self.events_table = dynamodb.Table(
            self,
            "Events",
            table_name=f"{prefix}-Events",
            partition_key=dynamodb.Attribute(
                name="tenantId",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="eventId",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery=False,
            time_to_live_attribute="ttl",
        )

        self.events_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="createdAt",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ============================================================
        # SQS: Event Delivery Queue + DLQ
        # ============================================================
        self.events_dlq = sqs.Queue(
            self,
            "EventsDlq",
            queue_name=f"{prefix}-EventsDlq",
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.events_queue = sqs.Queue(
            self,
            "EventsQueue",
            queue_name=f"{prefix}-EventsQueue",
            visibility_timeout=Duration.seconds(60),
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=self.events_dlq,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ============================================================
        # API Lambda (Event Ingestion)
        # Bundled dependencies, no layer
        # ============================================================
        self.api_lambda = lambda_.Function(
            self,
            "ApiLambda",
            function_name=f"{prefix}-ApiHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="main.handler",
            code=lambda_.Code.from_asset(
                "../src/api",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && "
                        + "cp -r . /asset-output",
                    ],
                ),
            ),
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment={
                "TENANT_API_KEYS_TABLE": self.tenant_api_keys_table.table_name,
                "EVENTS_TABLE": self.events_table.table_name,
                "EVENTS_QUEUE_URL": self.events_queue.queue_url,
            },
        )

        self.tenant_api_keys_table.grant_read_data(self.api_lambda)
        self.events_table.grant_read_write_data(self.api_lambda)
        self.events_queue.grant_send_messages(self.api_lambda)

        # ============================================================
        # Worker Lambda (Webhook Delivery)
        # SQS triggered, bundled dependencies
        # ============================================================
        self.worker_lambda = lambda_.Function(
            self,
            "WorkerLambda",
            function_name=f"{prefix}-WorkerHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.main",
            code=lambda_.Code.from_asset(
                "../src/worker",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && "
                        + "cp -r . /asset-output",
                    ],
                ),
            ),
            timeout=Duration.seconds(60),
            memory_size=1024,
            environment={
                "TENANT_API_KEYS_TABLE": self.tenant_api_keys_table.table_name,
                "EVENTS_TABLE": self.events_table.table_name,
            },
        )

        self.events_table.grant_read_write_data(self.worker_lambda)
        self.tenant_api_keys_table.grant_read_data(self.worker_lambda)

        self.worker_lambda.add_event_source(
            lambda_events.SqsEventSource(
                self.events_queue,
                batch_size=10,
                max_batching_window=Duration.seconds(5),
            )
        )

        # ============================================================
        # DLQ Processor Lambda (Manual Trigger)
        # Reads DLQ and requeues to main queue
        # ============================================================
        self.dlq_processor_lambda = lambda_.Function(
            self,
            "DlqProcessorLambda",
            function_name=f"{prefix}-DlqProcessor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.main",
            code=lambda_.Code.from_asset(
                "../src/dlq_processor",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && "
                        + "cp -r . /asset-output",
                    ],
                ),
            ),
            timeout=Duration.seconds(300),
            memory_size=512,
            environment={
                "EVENTS_DLQ_URL": self.events_dlq.queue_url,
                "EVENTS_QUEUE_URL": self.events_queue.queue_url,
            },
        )

        self.events_dlq.grant_consume_messages(self.dlq_processor_lambda)
        self.events_queue.grant_send_messages(self.dlq_processor_lambda)

        # ============================================================
        # API Gateway with Custom Domain
        # ============================================================
        self.api = apigateway.LambdaRestApi(
            self,
            "TriggerApi",
            handler=self.api_lambda,
            proxy=True,
            rest_api_name="Webhook Delivery API",
            description="Multi-tenant webhook delivery with SQS-backed processing",
            deploy_options=apigateway.StageOptions(
                stage_name="prod",
                throttling_rate_limit=500,
                throttling_burst_limit=1000,
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=["*"],
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Amz-Date",
                    "X-Api-Key",
                    "X-Amz-Security-Token",
                ],
            ),
        )

        # Custom domain mapping
        custom_domain = apigateway.DomainName(
            self,
            "TriggerApiCustomDomain",
            domain_name="hooks.vincentchan.cloud",
            certificate=certificate,
            endpoint_type=apigateway.EndpointType.EDGE,
        )

        custom_domain.add_base_path_mapping(
            self.api,
            base_path="",
            stage=self.api.deployment_stage,
        )

        # DNS A record
        route53.ARecord(
            self,
            "TriggerApiAliasRecord",
            zone=zone,
            record_name="hooks",
            target=route53.RecordTarget.from_alias(
                targets.ApiGatewayDomain(custom_domain)
            ),
        )

        # ============================================================
        # Outputs
        # ============================================================
        CfnOutput(
            self,
            "TenantApiKeysTableName",
            value=self.tenant_api_keys_table.table_name,
        )

        CfnOutput(
            self,
            "EventsTableName",
            value=self.events_table.table_name,
        )

        CfnOutput(
            self,
            "EventsQueueUrl",
            value=self.events_queue.queue_url,
        )

        CfnOutput(
            self,
            "EventsDlqUrl",
            value=self.events_dlq.queue_url,
        )

        CfnOutput(
            self,
            "CustomDomainUrl",
            value=f"https://{custom_domain.domain_name}",
        )
```

#### 2. Update CDK App Entry Point

**File**: `cdk/app.py`
```python
#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.webhook_delivery_stack import WebhookDeliveryStack

app = cdk.App()

WebhookDeliveryStack(
    app,
    "WebhookDeliveryStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1"
    )
)

app.synth()
```

### Success Criteria:

#### Automated Verification:
- [ ] CDK synth runs without errors: `cd cdk && cdk synth`
- [ ] CDK deploy completes successfully: `cd cdk && cdk deploy --require-approval never`
- [ ] Both DynamoDB tables exist: `aws dynamodb describe-table --table-name Vincent-TriggerApi-TenantApiKeys`
- [ ] Events table has status-index GSI
- [ ] SQS queues exist: `aws sqs get-queue-url --queue-name Vincent-TriggerApi-EventsQueue`
- [ ] All 3 Lambdas deployed: `aws lambda list-functions | grep Vincent-TriggerApi`
- [ ] Custom domain created: `aws apigateway get-domain-names | grep hooks.vincentchan.cloud`

#### Manual Verification:
- [ ] CloudFormation stack shows CREATE_COMPLETE
- [ ] Custom domain has valid SSL certificate in ACM
- [ ] DNS record for hooks.vincentchan.cloud points to API Gateway
- [ ] All stack outputs visible in CloudFormation console

**Implementation Note**: Phase 1 creates the complete infrastructure foundation. Do not proceed until all resources are deployed and verifiable.

---

## Phase 2: API Lambda - Event Ingestion

### Overview
Implement new FastAPI application for event ingestion that validates API keys, stores events in DynamoDB, and enqueues to SQS.

### Changes Required:

#### 1. Directory Structure

Create new `src/api/` directory:
```
src/api/
├── main.py           # FastAPI app + Mangum handler
├── auth.py           # API key authentication
├── models.py         # Pydantic models
├── routes.py         # Event ingestion endpoint
├── dynamo.py         # DynamoDB operations
└── requirements.txt  # Dependencies
```

#### 2. Dependencies

**File**: `src/api/requirements.txt`
```txt
fastapi==0.104.1
mangum==0.17.0
boto3==1.34.0
pydantic==2.5.0
```

#### 3. Data Models

**File**: `src/api/models.py`
```python
from pydantic import BaseModel
from typing import Any, Dict


class EventCreateRequest(BaseModel):
    """Free-form JSON payload for event creation"""
    class Config:
        extra = "allow"


class EventCreateResponse(BaseModel):
    event_id: str
    status: str  # "PENDING"
```

#### 4. Authentication

**File**: `src/api/auth.py`
```python
import os
import boto3
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional, Dict

security = HTTPBearer()

dynamodb = boto3.resource('dynamodb')
api_keys_table = dynamodb.Table(os.environ['TENANT_API_KEYS_TABLE'])


def get_tenant_from_api_key(api_key: str) -> Optional[Dict]:
    """
    Look up tenant from API key in DynamoDB.

    Returns: {
        "tenantId": "...",
        "targetUrl": "https://...",
        "webhookSecret": "...",
        "isActive": true
    }
    """
    try:
        response = api_keys_table.get_item(Key={'apiKey': api_key})
        item = response.get('Item')

        if not item or not item.get('isActive'):
            return None

        return item
    except Exception as e:
        print(f"Error looking up API key: {e}")
        return None


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> Dict:
    """FastAPI dependency that validates API key and returns tenant info"""
    api_key = credentials.credentials
    tenant = get_tenant_from_api_key(api_key)

    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return tenant
```

#### 5. DynamoDB Operations

**File**: `src/api/dynamo.py`
```python
import os
import uuid
import time
import boto3
from typing import Dict, Any

dynamodb = boto3.resource('dynamodb')
events_table = dynamodb.Table(os.environ['EVENTS_TABLE'])


def create_event(tenant_id: str, payload: Dict[str, Any], target_url: str) -> str:
    """
    Create event in DynamoDB with PENDING status.

    Returns: event_id
    """
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    created_at = time.time()

    # TTL: 30 days from now
    ttl = int(created_at + (30 * 24 * 60 * 60))

    item = {
        'tenantId': tenant_id,
        'eventId': event_id,
        'status': 'PENDING',
        'createdAt': str(int(created_at)),
        'payload': payload,
        'targetUrl': target_url,
        'attempts': 0,
        'ttl': ttl,
    }

    events_table.put_item(Item=item)
    return event_id
```

#### 6. Event Ingestion Endpoint

**File**: `src/api/routes.py`
```python
import os
import json
import boto3
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any

from auth import verify_api_key
from dynamo import create_event
from models import EventCreateResponse

router = APIRouter()

sqs = boto3.client('sqs')
EVENTS_QUEUE_URL = os.environ['EVENTS_QUEUE_URL']


@router.post("/events", status_code=201, response_model=EventCreateResponse)
async def ingest_event(
    payload: Dict[str, Any],
    tenant: Dict = Depends(verify_api_key)
):
    """
    Ingest event: store in DynamoDB and enqueue to SQS for delivery.
    """
    tenant_id = tenant['tenantId']
    target_url = tenant['targetUrl']

    # Store event in DynamoDB
    event_id = create_event(tenant_id, payload, target_url)

    # Enqueue to SQS for worker to process
    message_body = json.dumps({
        'tenantId': tenant_id,
        'eventId': event_id,
    })

    try:
        sqs.send_message(
            QueueUrl=EVENTS_QUEUE_URL,
            MessageBody=message_body,
        )
    except Exception as e:
        print(f"Error enqueuing to SQS: {e}")
        raise HTTPException(status_code=500, detail="Failed to enqueue event")

    return EventCreateResponse(
        event_id=event_id,
        status="PENDING"
    )
```

#### 7. FastAPI Application

**File**: `src/api/main.py`
```python
from fastapi import FastAPI
from mangum import Mangum
from routes import router

app = FastAPI(
    title="Webhook Delivery API",
    description="Multi-tenant webhook delivery system",
    version="2.0.0"
)

app.include_router(router)

# Mangum handler for AWS Lambda
handler = Mangum(app)
```

### Success Criteria:

#### Automated Verification:
- [ ] Python imports work: `python -c "from src.api.main import app; print('OK')"`
- [ ] CDK deploy updates Lambda: `cd cdk && cdk deploy --require-approval never`
- [ ] Lambda updated: `aws lambda get-function --function-name Vincent-TriggerApi-ApiHandler`

#### Manual Verification:
- [ ] Create test tenant manually in DynamoDB with targetUrl and webhookSecret
- [ ] POST event to API returns 201 with event_id
- [ ] Event appears in DynamoDB Events table with status=PENDING
- [ ] Message appears in SQS queue
- [ ] Invalid API key returns 401
- [ ] Custom domain accessible: `curl https://hooks.vincentchan.cloud/events`

**Implementation Note**: Complete API Lambda before starting Worker to ensure ingestion works end-to-end.

---

## Phase 3: Worker Lambda - Webhook Delivery

### Overview
Implement SQS-triggered Lambda that delivers webhooks with Stripe-style HMAC signatures and retry logic.

### Changes Required:

#### 1. Directory Structure

Create `src/worker/` directory:
```
src/worker/
├── handler.py        # SQS event handler
├── delivery.py       # Webhook delivery logic
├── signatures.py     # HMAC signature generation
├── dynamo.py         # Status updates
└── requirements.txt  # Dependencies
```

#### 2. Dependencies

**File**: `src/worker/requirements.txt`
```txt
boto3==1.34.0
requests==2.31.0
```

#### 3. HMAC Signature Generation

**File**: `src/worker/signatures.py`
```python
import hmac
import hashlib
import time


def generate_stripe_signature(payload: str, secret: str) -> str:
    """
    Generate Stripe-style webhook signature.

    Returns header value: "t={timestamp},v1={signature}"
    """
    timestamp = int(time.time())

    # Signed payload: {timestamp}.{payload}
    signed_payload = f"{timestamp}.{payload}"

    # HMAC-SHA256
    signature = hmac.new(
        secret.encode('utf-8'),
        signed_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return f"t={timestamp},v1={signature}"
```

#### 4. Webhook Delivery

**File**: `src/worker/delivery.py`
```python
import json
import requests
from typing import Dict, Any, Tuple
from signatures import generate_stripe_signature


def deliver_webhook(
    target_url: str,
    payload: Dict[str, Any],
    webhook_secret: str,
    timeout: int = 30
) -> Tuple[bool, int, str]:
    """
    Deliver webhook with HMAC signature.

    Returns: (success: bool, status_code: int, error_message: str)
    """
    payload_json = json.dumps(payload)
    signature = generate_stripe_signature(payload_json, webhook_secret)

    headers = {
        'Content-Type': 'application/json',
        'Stripe-Signature': signature,
    }

    try:
        response = requests.post(
            target_url,
            data=payload_json,
            headers=headers,
            timeout=timeout,
        )

        success = 200 <= response.status_code < 300
        return success, response.status_code, ""

    except requests.exceptions.Timeout:
        return False, 0, "Request timeout"
    except requests.exceptions.ConnectionError as e:
        return False, 0, f"Connection error: {str(e)}"
    except Exception as e:
        return False, 0, f"Unexpected error: {str(e)}"
```

#### 5. DynamoDB Status Updates

**File**: `src/worker/dynamo.py`
```python
import os
import time
import boto3

dynamodb = boto3.resource('dynamodb')
events_table = dynamodb.Table(os.environ['EVENTS_TABLE'])
tenant_keys_table = dynamodb.Table(os.environ['TENANT_API_KEYS_TABLE'])


def get_event(tenant_id: str, event_id: str):
    """Retrieve event from DynamoDB"""
    response = events_table.get_item(
        Key={'tenantId': tenant_id, 'eventId': event_id}
    )
    return response.get('Item')


def get_tenant(api_key: str):
    """Get tenant config (for webhook secret)"""
    response = tenant_keys_table.get_item(Key={'apiKey': api_key})
    return response.get('Item')


def update_event_status(
    tenant_id: str,
    event_id: str,
    status: str,
    attempts: int,
    error_message: str = None
):
    """Update event delivery status"""
    update_expr = "SET #status = :status, attempts = :attempts, lastAttemptAt = :last_attempt"
    expr_values = {
        ':status': status,
        ':attempts': attempts,
        ':last_attempt': str(int(time.time())),
    }
    expr_names = {'#status': 'status'}

    if error_message:
        update_expr += ", errorMessage = :error"
        expr_values[':error'] = error_message

    events_table.update_item(
        Key={'tenantId': tenant_id, 'eventId': event_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
```

#### 6. SQS Event Handler

**File**: `src/worker/handler.py`
```python
import json
from delivery import deliver_webhook
from dynamo import get_event, update_event_status, tenant_keys_table
import boto3

dynamodb = boto3.resource('dynamodb')


def main(event, context):
    """
    Process SQS messages for webhook delivery.

    SQS will retry failed messages with exponential backoff:
    - Visibility timeout: 60s
    - Max receive count: 5
    - Backoff: ~1min, 2min, 4min, 8min, 16min
    """
    for record in event['Records']:
        message_body = json.loads(record['body'])
        tenant_id = message_body['tenantId']
        event_id = message_body['eventId']

        # Get event details
        event_item = get_event(tenant_id, event_id)
        if not event_item:
            print(f"Event not found: {tenant_id}/{event_id}")
            continue

        target_url = event_item['targetUrl']
        payload = event_item['payload']
        current_attempts = event_item.get('attempts', 0)

        # Get webhook secret from tenant config
        # Note: We need to find the API key for this tenant
        # For now, store webhookSecret directly on event or pass in message
        # Let's add it to the message body in Phase 2

        # For this implementation, get tenant by scanning (inefficient but works)
        # Better: store webhookSecret on event during creation
        tenant_response = tenant_keys_table.scan(
            FilterExpression='tenantId = :tid',
            ExpressionAttributeValues={':tid': tenant_id}
        )

        if not tenant_response['Items']:
            print(f"Tenant not found: {tenant_id}")
            continue

        webhook_secret = tenant_response['Items'][0]['webhookSecret']

        # Attempt delivery
        success, status_code, error_msg = deliver_webhook(
            target_url, payload, webhook_secret
        )

        new_attempts = current_attempts + 1

        if success:
            # Mark as DELIVERED
            update_event_status(tenant_id, event_id, 'DELIVERED', new_attempts)
            print(f"✓ Delivered: {tenant_id}/{event_id} (status={status_code})")
        else:
            # Mark as FAILED (will retry via SQS or go to DLQ)
            update_event_status(
                tenant_id, event_id, 'FAILED', new_attempts, error_msg
            )
            print(f"✗ Failed: {tenant_id}/{event_id} - {error_msg}")

            # Re-raise to trigger SQS retry
            raise Exception(f"Webhook delivery failed: {error_msg}")

    return {'statusCode': 200}
```

### Success Criteria:

#### Automated Verification:
- [ ] Worker Lambda code deployed: `aws lambda get-function --function-name Vincent-TriggerApi-WorkerHandler`
- [ ] SQS trigger configured: Check Lambda console shows SQS as event source

#### Manual Verification:
- [ ] Create test webhook receiver that validates HMAC signatures
- [ ] Manually enqueue test message to SQS
- [ ] Worker processes message and delivers webhook
- [ ] Webhook receiver validates signature successfully
- [ ] Event status updates to DELIVERED in DynamoDB
- [ ] Failed delivery triggers retry (test with invalid URL)
- [ ] After 5 failures, message moves to DLQ

**Implementation Note**: Test with both successful and failed deliveries before proceeding.

---

## Phase 4: DLQ Processor Lambda - Manual Requeue

### Overview
Implement Lambda function that can be manually triggered to read DLQ messages, validate them, and requeue to main queue.

### Changes Required:

#### 1. Directory Structure

Create `src/dlq_processor/` directory:
```
src/dlq_processor/
├── handler.py
└── requirements.txt
```

#### 2. Dependencies

**File**: `src/dlq_processor/requirements.txt`
```txt
boto3==1.34.0
```

#### 3. DLQ Processor Handler

**File**: `src/dlq_processor/handler.py`
```python
import os
import json
import boto3

sqs = boto3.client('sqs')

DLQ_URL = os.environ['EVENTS_DLQ_URL']
MAIN_QUEUE_URL = os.environ['EVENTS_QUEUE_URL']


def main(event, context):
    """
    Manually triggered Lambda to requeue DLQ messages.

    Reads messages from DLQ and sends them back to main queue.
    Use with caution - only requeue if confident the issue is resolved.
    """
    batch_size = event.get('batchSize', 10)
    max_messages = event.get('maxMessages', 100)

    requeued_count = 0
    failed_count = 0

    while requeued_count < max_messages:
        # Receive messages from DLQ
        response = sqs.receive_message(
            QueueUrl=DLQ_URL,
            MaxNumberOfMessages=min(batch_size, max_messages - requeued_count),
            WaitTimeSeconds=1,
        )

        messages = response.get('Messages', [])
        if not messages:
            break

        for message in messages:
            try:
                # Validate message has required fields
                body = json.loads(message['Body'])
                if 'tenantId' not in body or 'eventId' not in body:
                    print(f"Invalid message format: {body}")
                    failed_count += 1
                    continue

                # Requeue to main queue
                sqs.send_message(
                    QueueUrl=MAIN_QUEUE_URL,
                    MessageBody=message['Body'],
                )

                # Delete from DLQ
                sqs.delete_message(
                    QueueUrl=DLQ_URL,
                    ReceiptHandle=message['ReceiptHandle'],
                )

                requeued_count += 1
                print(f"✓ Requeued: {body['tenantId']}/{body['eventId']}")

            except Exception as e:
                print(f"Error processing message: {e}")
                failed_count += 1

    return {
        'statusCode': 200,
        'body': json.dumps({
            'requeued': requeued_count,
            'failed': failed_count,
        })
    }
```

### Success Criteria:

#### Automated Verification:
- [ ] DLQ Processor Lambda deployed: `aws lambda get-function --function-name Vincent-TriggerApi-DlqProcessor`

#### Manual Verification:
- [ ] Manually trigger Lambda with test event: `{"batchSize": 5, "maxMessages": 10}`
- [ ] Messages move from DLQ to main queue
- [ ] Worker processes requeued messages
- [ ] Verify via CloudWatch Logs that requeue count is reported

**Implementation Note**: Document the manual trigger process for operations team.

---

## Phase 5: Seeding Script & Integration Testing

### Overview
Update seeding script for new schema and create comprehensive integration tests.

### Changes Required:

#### 1. New Seeding Script

**File**: `scripts/seed_webhooks.py`
```python
#!/usr/bin/env python3
"""
Seed test tenants with webhook configurations.
"""
import boto3
import uuid
import time
import sys

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('Vincent-TriggerApi-TenantApiKeys')


def generate_api_key(tenant_name: str) -> str:
    """Generate API key"""
    random_suffix = uuid.uuid4().hex[:12]
    return f"tenant_{tenant_name}_live_{random_suffix}"


def generate_webhook_secret() -> str:
    """Generate webhook secret"""
    return f"whsec_{uuid.uuid4().hex}"


def seed_tenants():
    """Seed 3 test tenants with webhook configs"""
    tenants = [
        {
            'name': 'acme',
            'display': 'Acme Corp',
            'targetUrl': 'https://webhook.site/unique-acme-id',  # Replace with real endpoint
        },
        {
            'name': 'globex',
            'display': 'Globex Inc',
            'targetUrl': 'https://webhook.site/unique-globex-id',
        },
        {
            'name': 'initech',
            'display': 'Initech LLC',
            'targetUrl': 'https://webhook.site/unique-initech-id',
        },
    ]

    print("Seeding tenants with webhook configurations...")
    print()

    created = []

    for tenant in tenants:
        api_key = generate_api_key(tenant['name'])
        webhook_secret = generate_webhook_secret()

        item = {
            'apiKey': api_key,
            'tenantId': tenant['name'],
            'targetUrl': tenant['targetUrl'],
            'webhookSecret': webhook_secret,
            'isActive': True,
            'createdAt': str(int(time.time())),
            'displayName': tenant['display'],
        }

        try:
            table.put_item(Item=item)
            print(f"✓ Created: {tenant['display']}")
            print(f"  API Key: {api_key}")
            print(f"  Webhook Secret: {webhook_secret}")
            print(f"  Target URL: {tenant['targetUrl']}")
            print()

            created.append({
                'tenant': tenant['name'],
                'apiKey': api_key,
                'webhookSecret': webhook_secret,
            })
        except Exception as e:
            print(f"✗ Error: {e}")
            sys.exit(1)

    print("=" * 60)
    print("All tenants created!")
    print("=" * 60)
    print()
    print("Test with:")
    for item in created:
        print(f"curl -X POST https://hooks.vincentchan.cloud/events \\")
        print(f"  -H 'Authorization: Bearer {item['apiKey']}' \\")
        print(f"  -H 'Content-Type: application/json' \\")
        print(f"  -d '{{\"test\": \"data\"}}'")
        print()


if __name__ == '__main__':
    seed_tenants()
```

#### 2. Test Webhook Receiver

Create simple Flask app to receive and validate webhooks:

**File**: `tests/webhook_receiver.py`
```python
#!/usr/bin/env python3
"""
Test webhook receiver that validates HMAC signatures.
"""
from flask import Flask, request, jsonify
import hmac
import hashlib

app = Flask(__name__)

# Test webhook secret (from seeding script)
WEBHOOK_SECRET = "whsec_test123"  # Replace with actual secret


def verify_signature(payload: str, signature_header: str) -> bool:
    """Verify Stripe-style signature"""
    parts = dict(item.split('=') for item in signature_header.split(','))
    timestamp = parts.get('t')
    signature = parts.get('v1')

    if not timestamp or not signature:
        return False

    signed_payload = f"{timestamp}.{payload}"
    expected = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        signed_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


@app.route('/webhook', methods=['POST'])
def receive_webhook():
    """Receive webhook and validate signature"""
    payload = request.data.decode('utf-8')
    signature = request.headers.get('Stripe-Signature')

    if not signature:
        return jsonify({'error': 'Missing signature'}), 401

    if not verify_signature(payload, signature):
        return jsonify({'error': 'Invalid signature'}), 401

    print(f"✓ Valid webhook received: {payload}")
    return jsonify({'status': 'received'}), 200


if __name__ == '__main__':
    app.run(port=5000)
```

### Success Criteria:

#### Automated Verification:
- [ ] Seed script runs successfully: `python scripts/seed_webhooks.py`
- [ ] 3 tenants created in DynamoDB
- [ ] Each tenant has apiKey, targetUrl, webhookSecret

#### Manual Verification:
- [ ] Start test webhook receiver: `python tests/webhook_receiver.py`
- [ ] Use ngrok to expose receiver: `ngrok http 5000`
- [ ] Update one tenant's targetUrl to ngrok URL
- [ ] POST event via API
- [ ] Webhook receiver gets event with valid signature
- [ ] Invalid signature rejected by receiver
- [ ] Check all 3 tenants can receive webhooks
- [ ] Verify events update to DELIVERED status
- [ ] Test retry flow by stopping webhook receiver
- [ ] Verify DLQ processor can requeue failed messages

**Implementation Note**: Run full end-to-end tests before declaring phase complete.

---

## Phase 6: Deployment Automation & Documentation

### Overview
Update deployment scripts and documentation for new webhook delivery architecture.

### Changes Required:

#### 1. Update Deployment Script

**File**: `scripts/deploy.sh`
```bash
#!/bin/bash
set -e

echo "=========================================="
echo "Deploying Webhook Delivery System"
echo "=========================================="
echo ""

# Check prerequisites
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI not found"
    exit 1
fi

# Install CDK dependencies
echo "1. Installing CDK dependencies..."
cd cdk
pip install -r requirements.txt
echo "   ✓ CDK ready"
echo ""

# Bootstrap if needed
echo "2. Bootstrapping CDK..."
cdk bootstrap || echo "   (Already bootstrapped)"
echo ""

# Deploy stack
echo "3. Deploying infrastructure..."
cdk deploy --require-approval never
echo "   ✓ Stack deployed"
echo ""

cd ..

# Seed tenants
echo "4. Seeding test tenants..."
python scripts/seed_webhooks.py
echo ""

# Get custom domain
CUSTOM_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name WebhookDeliveryStack \
    --query 'Stacks[0].Outputs[?OutputKey==`CustomDomainUrl`].OutputValue' \
    --output text)

echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "API URL: $CUSTOM_DOMAIN"
echo ""
echo "Next steps:"
echo "1. Configure webhook receiver endpoints for test tenants"
echo "2. Test event ingestion: curl -X POST $CUSTOM_DOMAIN/events -H 'Authorization: Bearer <api-key>' -d '{\"test\":\"data\"}'"
echo "3. Monitor CloudWatch Logs for delivery status"
echo ""
```

#### 2. Webhook Integration Guide

**File**: `docs/WEBHOOK_INTEGRATION.md`
```markdown
# Webhook Integration Guide

## Overview

The Webhook Delivery System automatically delivers events to tenant-configured endpoints with Stripe-style HMAC signatures for verification.

## Receiving Webhooks

### 1. Configure Target URL

Each tenant must provide a `targetUrl` where webhooks will be delivered:

```bash
# Update tenant configuration
aws dynamodb update-item \
  --table-name Vincent-TriggerApi-TenantApiKeys \
  --key '{"apiKey": {"S": "your-api-key"}}' \
  --update-expression "SET targetUrl = :url" \
  --expression-attribute-values '{":url": {"S": "https://your-domain.com/webhooks"}}'
```

### 2. Verify Webhook Signatures

All webhooks include a `Stripe-Signature` header:

```
Stripe-Signature: t=1234567890,v1=abc123...
```

Where:
- `t` = Unix timestamp
- `v1` = HMAC-SHA256 signature

**Verification Algorithm:**

```python
import hmac
import hashlib

def verify_signature(payload: str, signature_header: str, webhook_secret: str) -> bool:
    parts = dict(item.split('=') for item in signature_header.split(','))
    timestamp = parts['t']
    signature = parts['v1']

    signed_payload = f"{timestamp}.{payload}"
    expected = hmac.new(
        webhook_secret.encode('utf-8'),
        signed_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
```

**Best Practices:**
- Always verify signatures before processing
- Check timestamp to prevent replay attacks (reject if >5 minutes old)
- Use constant-time comparison (`hmac.compare_digest`)

### 3. Respond to Webhooks

Return a 2xx status code to acknowledge receipt:

```python
@app.route('/webhooks', methods=['POST'])
def handle_webhook():
    # Verify signature
    # Process event
    return '', 200  # Success
```

Non-2xx responses trigger retries with exponential backoff.

## Retry Logic

Failed deliveries retry automatically:
- **Attempts**: 5 total (1 initial + 4 retries)
- **Backoff**: ~1min, 2min, 4min, 8min, 16min
- **DLQ**: After 5 failures, messages move to Dead Letter Queue

## Manual Requeue from DLQ

If webhooks fail due to temporary issues, manually requeue from DLQ:

```bash
aws lambda invoke \
  --function-name Vincent-TriggerApi-DlqProcessor \
  --payload '{"batchSize": 10, "maxMessages": 100}' \
  response.json

cat response.json
```

## Monitoring

Check delivery status in DynamoDB Events table:
- `status`: PENDING → DELIVERED or FAILED
- `attempts`: Number of delivery attempts
- `lastAttemptAt`: Timestamp of last attempt

CloudWatch Logs provide detailed delivery information.
```

#### 3. Update Main README

**File**: `README.md`
```markdown
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

## License

MIT
```

### Success Criteria:

#### Automated Verification:
- [ ] Deployment script runs end-to-end successfully
- [ ] All documentation files created and valid

#### Manual Verification:
- [ ] Follow deployment script from clean state
- [ ] Verify custom domain works with SSL
- [ ] Follow webhook integration guide to set up receiver
- [ ] Test full flow using documentation examples
- [ ] Verify DLQ requeue procedure works as documented
- [ ] All CloudFormation outputs match documentation

**Implementation Note**: Have someone unfamiliar with the system follow the docs to verify clarity.

---

## Testing Strategy

### Integration Tests
1. **Event Ingestion**:
   - POST event with valid API key → 201 response
   - POST with invalid key → 401 response
   - Verify event in DynamoDB with status=PENDING

2. **Webhook Delivery**:
   - Event triggers SQS message
   - Worker delivers webhook with valid signature
   - Receiver validates signature
   - Event status updates to DELIVERED

3. **Retry Logic**:
   - Simulate webhook endpoint failure
   - Verify retry attempts increase
   - Verify exponential backoff timing
   - Verify DLQ after 5 failures

4. **DLQ Requeue**:
   - Manually trigger DLQ processor
   - Verify messages requeued
   - Verify successful redelivery

### Manual Testing Checklist
- [ ] Custom domain resolves correctly
- [ ] SSL certificate valid
- [ ] Event ingestion works via custom domain
- [ ] Webhooks delivered with valid signatures
- [ ] Retry logic functions correctly
- [ ] DLQ requeue works as expected
- [ ] Multi-tenant isolation verified
- [ ] TTL cleanup occurs (after 30 days)

## Performance Considerations

- **SQS Throughput**: Default limits handle 3000 msg/sec, sufficient for most workloads
- **Lambda Concurrency**: Set reserved concurrency if needed to prevent throttling
- **DynamoDB**: PAY_PER_REQUEST auto-scales, no manual capacity planning
- **API Gateway**: 500 RPS rate limit, 1000 burst configured
- **Webhook Timeout**: 30s per delivery attempt

## Migration Notes

**This is a complete replacement** - no migration from old implementation:
- Old stack destroyed before deploying new stack
- Fresh database with no legacy data
- New API endpoints (no backward compatibility)
- New event schema

## References

- Stripe Webhook Signatures: https://stripe.com/docs/webhooks/signatures
- AWS SQS Retry: https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html
- Custom Domains in API Gateway: https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-custom-domains.html
