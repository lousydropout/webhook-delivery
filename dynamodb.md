# **DynamoDB Schema**

We use **two tables**:

1. **TenantApiKeys** – maps API keys → tenant identity
2. **Events** – stores all ingested events partitioned by tenant

This gives clean multi-tenancy, isolated queries, and scalable ingestion.

---

# **1. Table: TenantApiKeys**

Used by the Lambda Authorizer (or inline auth code) to determine which tenant is making a request.

### **Primary Key**

```
pk  = api_key        (STRING)  # the API key itself
sk  = "meta"         (STRING)
```

### **Attributes**

```
tenant_id   (STRING)
status      (STRING)   # "active", "revoked"
created_at  (NUMBER)   # epoch_ms
```

### **Notes**

* Lookup is a simple GetItem on `api_key`.
* Very small table, rarely written to, heavily read during auth.

---

# **2. Table: Events**

This table stores **all events for all tenants**, cleanly partitioned.

### **Primary Key (Partition + Sort)**

```
pk = tenant_id           (STRING)
sk = event_id            (STRING, UUIDv4)
```

This ensures:

* Tenant-level isolation
* Even distribution (UUID SK)
* Scalable writes

### **Attributes**

```
tenant_id   (STRING)
event_id    (STRING)
status      (STRING)       # "undelivered" | "delivered"
timestamp   (NUMBER)       # epoch_ms
payload     (MAP)          # arbitrary JSON from POST /events
```

---

# **3. Global Secondary Indexes**

### **GSI1: status-index**

Used by `/inbox` to fetch **undelivered events per tenant**.

**GSI Key Schema:**

```
GSI1PK = tenant_id
GSI1SK = status#timestamp
```

This requires writing a composite attribute:

```
gsi1sk = status + "#" + timestamp
```

Example:

```
"undelivered#1732140249123"
```

### **Query Example**

```
Query GSI1 
Where GSI1PK = :tenant_id 
  AND begins_with(GSI1SK, "undelivered#")
```

Returns events in chronological order, earliest first.

---

# **4. Future-Proof Optional Index**

*You don’t need this for the demo, but it’s a realistic extension.*

### **GSI2: event-type-index**

```
GSI2PK = tenant_id
GSI2SK = event_type#timestamp
```

Useful if you later support:

* event_type filtering
* Zap subscribing to subsets of events

Again, optional.

---
