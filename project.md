# **Trigger Ingestion API**

## **1. Overview**

This project implements a **multi-tenant event ingestion and delivery API**, modeled after the upcoming “Triggers API” concept described by Zapier. It demonstrates how external systems can submit real-time events into a unified trigger pipeline, store them durably, and expose them to a consuming worker that processes the events and acknowledges delivery.

While Zapier's internal system is not publicly available, this prototype **simulates the core platform behavior** with:

* A public REST API for event ingestion
* Per-tenant authentication
* Durable event storage (DynamoDB)
* A pull-based inbox for undelivered events
* Acknowledge semantics to complete the event lifecycle
* A mock worker representing the “Zap runner”

The goal is to show architectural correctness, real-time event flow, and multi-tenant safety.

---

## **2. What We Are Building and Why**

### **2.1 Purpose**

Modern automation platforms require an efficient way for external systems to emit events that downstream workflows can react to. Today, many integrations rely on ad-hoc webhook URLs, polling, or custom triggers inside individual apps. This creates fragmentation and scaling limitations.

This prototype implements a **unified event ingestion interface** that:

* Accepts events from any number of external systems
* Stores them in a durable, scalable system
* Allows downstream workers to pull and process events
* Enforces clean separation between tenants
* Demonstrates an idiomatic AWS design using API Gateway, Lambda, and DynamoDB

### **2.2 What This Represents**

This prototype simulates the backend portion of:

* Zapier’s future unified Trigger API
* Segment’s event ingestion architecture
* Stripe/Twilio-style multi-tenant API key authentication
* A minimal event bus (inbox + ack)
* Any automation platform that requires real-time, multi-tenant event handling

### **2.3 Why This Architecture**

This design is intentionally:

* **Simple** enough to demo
* **Scalable** enough to be credible
* **Multi-tenant aware**
* **Durable**
* **Serverless** (low maintenance, low cost)
* **Extensible** (can evolve into a full real-time automation engine)

The purpose is to **demonstrate architecture**, not recreate Zapier’s entire platform.

---

## **3. Example Use Cases**

### **Use Case A – CRM App Emits User Signup Event**

AcmeCRM posts:

```json
{
  "event_type": "customer.created",
  "customer_id": "123",
  "email": "alice@example.com"
}
```

The platform:

* Stores the event for tenant `acme`
* Worker pulls event
* Worker “acts” on it (e.g., logs or sends Slack message)
* Event is acknowledged

### **Use Case B – SaaS Billing App Emits Invoice Paid Event**

Tenant `globex` posts:

```json
{
  "event_type": "invoice.paid",
  "invoice_id": "inv_8912",
  "amount": 3200
}
```

Worker picks it up and processes it separately from Acme’s events.

### **Use Case C – Multi-Tenant Security**

Acme and Globex may push event streams concurrently.
Neither can view or acknowledge the other's events because each API key maps to exactly one tenant.

---

## **4. High-Level Architecture**

```
External App → POST /events → API Gateway → Lambda (FastAPI+Mangum) → DynamoDB
                                                                          ↓
                                                               GET /inbox (per tenant)
                                                                          ↓
                                                            Mock Worker pulls + processes
                                                                          ↓
                                                              POST /ack → mark delivered
```

### **Components**

* **API Gateway** – public API surface
* **Lambda functions** – event ingestion, inbox retrieval, acknowledgments
* **DynamoDB** – durable event store
* **API Keys table** – maps API keys to tenant IDs
* **Mock Worker** – simple Python/Node loop simulating Zapier’s trigger engine

---

## **5. Authentication (Per-Tenant API Keys)**

### Why this model?

* Simple
* Secure enough for MVP
* Matches Stripe/Twilio API key design
* Ensures clear tenant boundaries
* Ideal for Postman demos

### How it works

1. Each tenant receives an API key such as:

```
tenant_acme_live_8fc12bfe-29a8
```

2. They include it in every request:

```
Authorization: Bearer tenant_acme_live_8fc12bfe-29a8
```

3. Lambda looks up the key in DynamoDB to resolve the tenant.

4. All event storage, inbox queries, and acks are scoped to that tenant.

This is straightforward, safe, and very demo-friendly.

---

## **6. Data Model (DynamoDB)**

### **6.1 Table: TenantApiKeys**

Stores the mapping between API keys and tenant IDs.

```
pk = api_key
sk = “meta”
tenant_id (string)
status (“active”, “revoked”)
created_at (timestamp)
```

### **6.2 Table: Events**

Stores all events per tenant.

```
pk = tenant_id
sk = event_id
status = “undelivered” | “delivered”
timestamp = epoch_ms
payload = JSON
```

### **GSI: status-index**

For querying undelivered events:

```
GSI1PK = tenant_id
GSI1SK = status#timestamp
```

---

## **7. REST API Endpoints**

### **POST /events**

Ingests an external event.

**Headers:**

```
Authorization: Bearer <tenant_api_key>
```

**Body (free form JSON):**

```json
{
  "event_type": "customer.created",
  "foo": "bar"
}
```

**Response:**

```json
{
  "event_id": "evt_b1cb3",
  "received_at": 1732140249123,
  "status": "accepted"
}
```

---

### **GET /inbox**

Returns undelivered events for that tenant.

**Response:**

```json
{
  "events": [
    {
      "event_id": "evt_b1cb3",
      "payload": {...},
      "timestamp": 1732140249123
    }
  ]
}
```

---

### **POST /ack**

Marks an event as delivered.

**Body:**

```json
{ "event_id": "evt_b1cb3" }
```

**Response:**

```json
{ "status": "acknowledged" }
```

---

## **8. Mock Worker (Zap Simulation)**

A minimal script that simulates Zapier’s internal automation engine:

```python
import time, requests

API_KEY = "tenant_acme_live_xxx"
BASE = "https://your-api.com"

headers = {"Authorization": f"Bearer {API_KEY}"}

while True:
    inbox = requests.get(f"{BASE}/inbox", headers=headers).json()
    for evt in inbox["events"]:
        print("Processing:", evt["event_id"], evt["payload"])

        # pretend we run some action
        requests.post(f"{BASE}/ack", json={"event_id": evt["event_id"]}, headers=headers)

    time.sleep(2)
```

This demonstrates:

* Pull-based delivery
* Isolation per tenant
* End-to-end lifecycle

Perfect for a senior engineer review.

---

## **9. Expected Demo Sequence (Postman-friendly)**

1. **Insert API key into Postman environment**
2. `POST /events` with tenant A → event stored
3. `POST /events` with tenant B → event stored separately
4. `GET /inbox` (tenant A) → only A’s events
5. `GET /inbox` (tenant B) → only B’s events
6. Run worker → events are processed + acknowledged
7. `GET /inbox` again → shows no undelivered events

This clearly shows correctness, isolation, and lifecycle.

---

## **10. Non-Goals (Explicitly Out of Scope)**

* Event transformations
* Deduplication strategies beyond UUID event IDs
* Zapier UI integration
* Zap editor or workflow builder
* High-scale concurrency benchmarking
* Retry backoff or poison queue management
* Role-based auth
* OAuth or Cognito auth flows

The prototype is meant to be **minimal but architecturally sound**.

---

## **11. Technical Justification**

* **API Gateway + Lambda + FastAPI + Mangum** gives scalable ingestion (thousands of RPS by default).
* **DynamoDB** provides ultra-low-latency writes (< 10ms) and unbounded scaling.
* **API keys** simplify multi-tenant auth and clean scoping.
* **Serverless compute** makes ops cost negligible and reduces cognitive load for the demo.
* **Pull-based inbox** aligns with Zapier’s trigger engine and predictable delivery semantics.

---

## **12. Summary**

This prototype demonstrates a realistic, scalable, multi-tenant Trigger API architecture that:

* Accepts events from arbitrary external systems
* Stores them durably
* Exposes them via a per-tenant inbox
* Supports acknowledgment semantics
* Simulates Zapier’s internal trigger engine via a mock worker
* Uses AWS services idiomatically (Lambda, DynamoDB, API Gateway)

