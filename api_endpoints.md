# **Trigger Ingestion API — RESTful Endpoint Design**

## **Base URL**

```
/v1
```

---

# **1. POST /v1/events**

**Create (ingest) a new event.**
This is the canonical RESTful place to send events *into* the system.

### Request

```
POST /v1/events
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Body:** arbitrary JSON (the event payload).

**Example:**

```json
{
  "event_type": "customer.created",
  "customer_id": "123",
  "email": "alice@example.com"
}
```

### Response (201 Created)

```json
{
  "id": "evt_83e5f475",
  "created_at": 1732140249123,
  "status": "undelivered"
}
```

**REST notes:**

* `POST /events` = create a new event resource.
* Response contains the canonical `id` of the newly created event.
* Status code should be **201** for resource creation.

---

# **2. GET /v1/events**

**List all events for the authenticated tenant.**
Supports filtering via query parameters.

### Request

```
GET /v1/events?status=undelivered&limit=50
Authorization: Bearer <api_key>
```

### Response

```json
{
  "events": [
    {
      "id": "evt_83e5f475",
      "created_at": 1732140249123,
      "status": "undelivered",
      "payload": {...}
    }
  ]
}
```

### REST semantics:

* `/events` is the **collection** resource.
* Query parameters modify the view (status filtering, pagination).

This endpoint replaces the old non-RESTful `/inbox`.
“Inbox” is just **events filtered by status=undelivered**.

---

# **3. GET /v1/events/{event_id}**

Retrieve a single event resource.

### Request

```
GET /v1/events/{event_id}
Authorization: Bearer <api_key>
```

### Response

```json
{
  "id": "evt_83e5f475",
  "created_at": 1732140249123,
  "status": "undelivered",
  "payload": {...}
}
```

**REST notes:**
Reading a single resource always uses `GET /resource/{id}`.

---

# **4. POST /v1/events/{event_id}/ack**

**Mark an event as delivered** (state transition).

### Request

```
POST /v1/events/{event_id}/ack
Authorization: Bearer <api_key>
Content-Type: application/json
```

### Response

```json
{ "status": "acknowledged" }
```

### REST semantics:

* Acknowledgment is a **state change**, not a CRUD operation.
* Using a **sub-resource action** (`/ack`) is standard practice (see Stripe `/capture`, `/close`, etc.).
* Action endpoints are acceptable in REST *only* when no CRUD verb cleanly expresses the transition (true here).

---

# **5. DELETE /v1/events/{event_id}** (Optional)

Delete an event entirely (usually for debugging or admin purposes only).

### Request

```
DELETE /v1/events/{event_id}
Authorization: Bearer <api_key>
```

### Response

```
204 No Content
```

### REST semantics:

* Delete uses the canonical `{id}` location.
* Response should be empty `204`.

---

# **Event Lifecycle in REST Terms**

```
POST   /v1/events                    # create event
GET    /v1/events                    # list events
GET    /v1/events/{id}               # fetch one event
POST   /v1/events/{id}/ack           # transition -> delivered
DELETE /v1/events/{id}               # remove event (optional)
```

This is perfectly RESTful:

* Proper nouns are pluralized (`events`)
* Resource IDs live at `/events/{id}`
* List endpoints filter via `?status=undelivered`
* State transitions handled by sub-resources (`/ack`)

---

# **How `/inbox` Is Represented in REST**

You wanted inbox semantics — in REST, that simply becomes:

```
GET /v1/events?status=undelivered
```

This is idiomatic, predictable, and matches how Stripe/Twilio/Segment shape their endpoints.

---

# **Optional Enhancements (future-friendly)**

### Filtering by event type:

```
GET /v1/events?event_type=customer.created
```

### Pagination:

```
GET /v1/events?status=undelivered&limit=100&cursor=abc123
```

### Bulk acknowledgment:

```
POST /v1/events/ack
{
  "event_ids": [...]
}
```

(Not needed for MVP, but clean extension.)

---
