#!/usr/bin/env python3
"""
Lambda webhook receiver that validates HMAC signatures.
FastAPI-based receiver for webhook delivery validation.
"""
import os
import hmac
import hashlib
import json
import boto3
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional
from mangum import Mangum

# Initialize FastAPI app
app = FastAPI(
    title="Webhook Receiver",
    description="Multi-tenant webhook receiver with HMAC validation",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Module-level DynamoDB initialization (Lambda best practice)
dynamodb = boto3.resource("dynamodb")
tenant_webhook_config_table = dynamodb.Table(os.environ["TENANT_WEBHOOK_CONFIG_TABLE"])

# Special tenantId used to store global webhook reception state
GLOBAL_CONFIG_TENANT_ID = "__GLOBAL_CONFIG__"


def get_webhook_secret_for_tenant(tenant_id: str) -> Optional[str]:
    """
    Retrieve webhook secret for a tenant from TenantWebhookConfig table.

    Reads only webhook delivery configuration (targetUrl, webhookSecret).
    Does not access TenantIdentity table (authentication data).
    """
    try:
        response = tenant_webhook_config_table.get_item(Key={"tenantId": tenant_id})
        item = response.get("Item")

        if item:
            return item.get("webhookSecret")

        return None
    except Exception as e:
        print(f"Error retrieving webhook secret for tenant {tenant_id}: {e}")
        return None


def is_webhook_reception_enabled() -> bool:
    """
    Check if webhook reception is enabled globally.
    Reads from DynamoDB for persistent state across container recycles.
    Default: enabled (True) if not set in DynamoDB.
    """
    try:
        response = tenant_webhook_config_table.get_item(
            Key={"tenantId": GLOBAL_CONFIG_TENANT_ID}
        )
        item = response.get("Item")
        if item:
            # State is stored as boolean in webhookReceptionEnabled field
            return item.get("webhookReceptionEnabled", True)
        # Default to enabled if not set
        return True
    except Exception as e:
        print(f"Error reading webhook reception state: {e}")
        # Default to enabled on error
        return True


def set_webhook_reception_state(enabled: bool) -> None:
    """
    Set global webhook reception state (applies to all tenants).
    Stores in DynamoDB for persistence across container recycles.
    """
    import time

    try:
        timestamp = str(int(time.time()))
        tenant_webhook_config_table.put_item(
            Item={
                "tenantId": GLOBAL_CONFIG_TENANT_ID,
                "webhookReceptionEnabled": enabled,
                "lastUpdated": timestamp,
            }
        )
        print(
            f"Global webhook reception {'enabled' if enabled else 'disabled'} (persisted to DynamoDB)"
        )
    except Exception as e:
        print(f"Error storing webhook reception state: {e}")
        raise


def verify_signature(payload: str, signature_header: str, webhook_secret: str) -> bool:
    """
    Verify Stripe-style HMAC signature.
    Format: t={timestamp},v1={signature}
    """
    try:
        parts = dict(item.split("=") for item in signature_header.split(","))
        timestamp = parts.get("t")
        signature = parts.get("v1")

        if not timestamp or not signature:
            return False

        signed_payload = f"{timestamp}.{payload}"
        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
    except Exception as e:
        print(f"Error verifying signature: {e}")
        return False


@app.post("/{tenant_id}/webhook", tags=["Webhooks"])
async def receive_webhook(
    tenant_id: str,
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """
    Receive and validate webhook for a specific tenant.
    Path parameter identifies the tenant for secret lookup.
    """
    # Check if webhook reception is enabled globally
    if not is_webhook_reception_enabled():
        print(f"Webhook reception disabled globally")
        raise HTTPException(
            status_code=503, detail="Webhook reception temporarily disabled"
        )

    # Validate signature header presence
    if not stripe_signature:
        print(f"Missing Stripe-Signature header for tenant: {tenant_id}")
        raise HTTPException(status_code=401, detail="Missing Stripe-Signature header")

    # Read raw body for signature verification
    body = await request.body()
    payload = body.decode("utf-8")

    # Retrieve webhook secret from DynamoDB
    webhook_secret = get_webhook_secret_for_tenant(tenant_id)
    if not webhook_secret:
        print(f"No active webhook secret found for tenant: {tenant_id}")
        raise HTTPException(status_code=404, detail="Tenant not found or inactive")

    # Verify HMAC signature
    if not verify_signature(payload, stripe_signature, webhook_secret):
        print(f"Invalid signature for tenant: {tenant_id}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload for logging
    try:
        payload_json = json.loads(payload)
        event_id = payload_json.get("eventId") or payload_json.get("event_id")
        print(f"✓ Valid webhook received for tenant {tenant_id}, event: {event_id}")
    except json.JSONDecodeError:
        print(f"✓ Valid webhook received for tenant {tenant_id} (non-JSON payload)")

    return {"status": "received", "tenant_id": tenant_id}


@app.post("/enable", tags=["Receiver Management"])
async def enable_webhook_reception():
    """
    Enable webhook reception globally (applies to all tenants).
    Useful for testing and demonstrating retry functionality.

    State is persisted in DynamoDB and survives Lambda container recycles.
    """
    set_webhook_reception_state(True)
    return {
        "webhook_reception": "enabled",
        "message": "Webhook reception has been enabled for all tenants",
    }


@app.post("/disable", tags=["Receiver Management"])
async def disable_webhook_reception():
    """
    Disable webhook reception globally (applies to all tenants).
    Webhooks will return 503 until re-enabled.
    Useful for testing retry functionality.

    State is persisted in DynamoDB and survives Lambda container recycles.
    """
    set_webhook_reception_state(False)
    return {
        "webhook_reception": "disabled",
        "message": "Webhook reception has been disabled for all tenants. Webhooks will return 503 until re-enabled.",
    }


@app.get("/status", tags=["Receiver Management"])
async def get_webhook_status():
    """
    Get global webhook reception status.
    Shows whether webhooks will be accepted or rejected with 503 for all tenants.

    State is read from DynamoDB and persists across Lambda container recycles.
    """
    enabled = is_webhook_reception_enabled()
    return {
        "webhook_reception": "enabled" if enabled else "disabled",
        "accepts_webhooks": enabled,
    }


@app.get("/health", tags=["Health Checks"])
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "service": "webhook-receiver"}


# Lambda handler using Mangum adapter
handler = Mangum(app)
