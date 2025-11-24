# Webhook Delivery System

## OpenAPI Docs

- https://hooks.vincentchan.cloud/v1/docs#/
- https://receiver.vincentchan.cloud/docs#/

## Overview

This system provides a complete webhook delivery infrastructure that:

- Ingests events via REST API
- Queues events for reliable async processing
- Delivers webhooks to tenant-configured endpoints
- Validates deliveries with Stripe-style HMAC signatures
- Automatically retries failed deliveries with exponential backoff
- Routes permanently failed messages to a Dead Letter Queue

## Architecture

**Components:**

- **Lambda Authorizer**: API Gateway authorizer for Bearer token validation (5-min cache)
- **API Lambda** (FastAPI): Event ingestion with tenant context from authorizer
- **SQS Queue**: Reliable message queue with 5 retry attempts (180s visibility timeout > 60s Lambda timeout)
- **Worker Lambda**: Webhook delivery with HMAC signature generation
- **Webhook Receiver Lambda** (FastAPI): Multi-tenant webhook validation with HMAC verification
- **DLQ Processor Lambda**: Manual requeue for failed deliveries
- **DynamoDB**: Three tables with strict separation of concerns:
  - **TenantIdentity**: API keys → tenant identity (authentication only)
  - **TenantWebhookConfig**: tenantId → webhook delivery config (targetUrl, webhookSecret)
  - **Events**: Event storage with TTL support
- **Custom Domains**:
  - hooks.vincentchan.cloud (Main API - REGIONAL endpoint with ACM SSL)
  - receiver.vincentchan.cloud (Webhook Receiver - REGIONAL endpoint with ACM SSL)

**System Diagram:**

```mermaid
graph LR
    A[External System] -->|POST /v1/events<br/>Bearer Token| B[API Gateway<br/>hooks.vincentchan.cloud]
    B -->|Validate Token| C[(DynamoDB<br/>TenantIdentity)]
    B -->|Authorized| D[API Lambda<br/>FastAPI]
    D -->|Store Event| E[(DynamoDB<br/>Events)]
    D -->|Enqueue| F[SQS Queue]
    F -->|Trigger| G[Worker Lambda]
    G -->|Read Event| E
    G -->|Read Webhook Config| H[(DynamoDB<br/>TenantWebhookConfig)]
    G -->|Deliver with<br/>HMAC| I[Tenant Webhook<br/>Endpoint]
    G -.->|Deliver to<br/>Built-in Receiver| J[Receiver API Gateway<br/>receiver.vincentchan.cloud]
    J -->|Validate HMAC| K[Webhook Receiver<br/>Lambda]
    K -->|Lookup Secret| H
    F -->|After 5 Retries| L[Dead Letter<br/>Queue]
    L -.->|Manual Requeue| M[DLQ Processor<br/>Lambda]
    M -.->|Requeue| F

    style B fill:#f9f,stroke:#333,color:#000
    style D fill:#f9f,stroke:#333,color:#000
    style G fill:#f9f,stroke:#333,color:#000
    style M fill:#f9f,stroke:#333,color:#000
    style J fill:#f9f,stroke:#333,color:#000
    style K fill:#f9f,stroke:#333,color:#000
    style C fill:#bbf,stroke:#333,color:#000
    style H fill:#bbf,stroke:#333,color:#000
    style E fill:#bbf,stroke:#333,color:#000
    style F fill:#bfb,stroke:#333,color:#000
    style L fill:#fbb,stroke:#333,color:#000
```

**Event Lifecycle:**

```mermaid
stateDiagram-v2
    [*] --> PENDING: Event Created
    PENDING --> DELIVERED: Webhook 2xx Response
    PENDING --> FAILED: Webhook Error
    FAILED --> PENDING: SQS Retry (1-4)
    FAILED --> DLQ: 5th Failure
    DLQ --> PENDING: Manual Requeue
    DELIVERED --> [*]: TTL Cleanup (30d)
    DLQ --> [*]: TTL Cleanup (14d)
```

**Delivery Sequence:**

```mermaid
sequenceDiagram
    participant Ext as External System
    participant AGW as API Gateway
    participant Auth as Authorizer Lambda
    participant API as API Lambda
    participant TenantIdentity as TenantIdentity Table
    participant TenantWebhookConfig as TenantWebhookConfig Table
    participant Events as Events Table
    participant SQS as SQS Queue
    participant Worker as Worker Lambda
    participant Tenant as Tenant Server

    Ext->>AGW: POST /v1/events + Bearer Token
    AGW->>Auth: Validate Token
    Auth->>TenantIdentity: Lookup API Key (projection: tenantId, status, plan)
    TenantIdentity-->>Auth: Tenant Identity (no secrets)
    Auth-->>AGW: Allow + Tenant Context (cached 5min)
    AGW->>API: Invoke with Tenant Context
    API->>TenantWebhookConfig: Get targetUrl
    TenantWebhookConfig-->>API: targetUrl
    API->>Events: Create Event (PENDING)
    API->>SQS: Enqueue {tenantId, eventId}
    API-->>Ext: 201 {event_id, status}

    SQS->>Worker: Trigger with Message
    Worker->>Events: Get Event Details
    Events-->>Worker: Event (payload, targetUrl)
    Worker->>TenantWebhookConfig: Get Webhook Config
    TenantWebhookConfig-->>Worker: Config (targetUrl, webhookSecret)
    Worker->>Worker: Generate HMAC Signature
    Worker->>Tenant: POST Webhook + Stripe-Signature

    alt Success
        Tenant-->>Worker: 200 OK
        Worker->>Events: Update Status: DELIVERED
    else Failure
        Tenant-->>Worker: 5xx Error
        Worker->>Events: Update Status: FAILED
        Worker->>SQS: Return Error (Retry)
    end
```

## Features

- ✅ **Reliable Delivery**: SQS-backed processing with automatic retries
- ✅ **Security**: Stripe-style HMAC-SHA256 webhook signatures
- ✅ **API Gateway Authorizer**: Lambda authorizer with 5-minute caching for performance
- ✅ **Interactive API Docs**: Public Swagger UI and ReDoc documentation
- ✅ **Retry Logic**: Exponential backoff (1min, 2min, 4min, 8min, 16min)
- ✅ **Multi-tenant**: Isolated API keys and webhook endpoints per tenant
- ✅ **Auto-cleanup**: 30-day TTL on delivered events
- ✅ **DLQ Management**: Manual requeue of failed messages

## API Documentation

Interactive API documentation is available at:

- **Swagger UI**: https://hooks.vincentchan.cloud/v1/docs
- **ReDoc**: https://hooks.vincentchan.cloud/v1/redoc
- **OpenAPI Schema**: https://hooks.vincentchan.cloud/v1/openapi.json

These endpoints are publicly accessible (no authentication required) for easy integration.

## Quick Start

### Prerequisites

- AWS CLI configured with credentials
- Python 3.12+
- Node.js 20+ (for CDK)
- Environment variables in `.env`:
  ```bash
  PREFIX=Vincent-Events
  HOSTED_ZONE_ID=Z00669322LNYAWLYNIHGN
  HOSTED_ZONE_URL=vincentchan.cloud
  ```

### Deploy

Go into `cdk/` and run

```bash
cdk deploy
```

## Project Structure

```
/
├── cdk/
│   ├── app.py                          # CDK application entry
│   ├── stacks/
│   │   └── webhook_delivery_stack.py  # Infrastructure definition
│   └── requirements.txt
├── src/
│   ├── authorizer/                     # API Gateway Authorizer Lambda
│   │   ├── handler.py                  # Bearer token validation
│   │   └── requirements.txt            # boto3
│   ├── api/                            # Event Ingestion Lambda
│   │   ├── main.py                     # FastAPI app + Mangum handler
│   │   ├── context.py                  # Extract tenant from authorizer context
│   │   ├── routes.py                   # POST /v1/events endpoint
│   │   ├── dynamo.py                   # DynamoDB operations
│   │   ├── models.py                   # Pydantic request/response models
│   │   └── requirements.txt            # FastAPI, Mangum, boto3, pydantic
│   ├── worker/                         # Webhook Delivery Lambda
│   │   ├── handler.py                  # SQS event processor
│   │   ├── delivery.py                 # HTTP webhook delivery (with DecimalEncoder)
│   │   ├── signatures.py               # HMAC signature generation
│   │   ├── dynamo.py                   # Event status updates
│   │   └── requirements.txt            # boto3, requests
│   ├── webhook_receiver/               # Webhook Receiver Lambda
│   │   ├── main.py                     # FastAPI app + Mangum handler
│   │   └── requirements.txt            # fastapi, mangum, boto3
│   └── dlq_processor/                  # DLQ Requeue Lambda
│       ├── handler.py                  # Manual DLQ requeue
│       └── requirements.txt
└── README.md
```
