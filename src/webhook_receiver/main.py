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
from typing import Optional, Dict, Any
from mangum import Mangum

# Initialize FastAPI app
app = FastAPI(
    title="Webhook Receiver",
    description="Multi-tenant webhook receiver with HMAC validation",
    version="2.0.0",
    docs_url="/v1/receiver/docs",
    redoc_url="/v1/receiver/redoc",
    openapi_url="/v1/receiver/openapi.json",
)

# Module-level DynamoDB initialization (Lambda best practice)
dynamodb = boto3.resource("dynamodb")
tenant_api_keys_table = dynamodb.Table(os.environ["TENANT_API_KEYS_TABLE"])


def get_webhook_secret_for_tenant(tenant_id: str) -> Optional[str]:
    """
    Retrieve webhook secret for a tenant from DynamoDB.
    Uses scan with filter (table is small enough for this pattern).
    """
    try:
        response = tenant_api_keys_table.scan(
            FilterExpression="tenantId = :tid",
            ExpressionAttributeValues={":tid": tenant_id}
        )

        items = response.get("Items", [])
        if items and items[0].get("isActive"):
            return items[0].get("webhookSecret")

        return None
    except Exception as e:
        print(f"Error retrieving webhook secret for tenant {tenant_id}: {e}")
        return None


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


@app.post("/v1/receiver/{tenant_id}/webhook")
async def receive_webhook(
    tenant_id: str,
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """
    Receive and validate webhook for a specific tenant.
    Path parameter identifies the tenant for secret lookup.
    """
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


@app.get("/v1/receiver/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "service": "webhook-receiver"}


# Lambda handler using Mangum adapter
handler = Mangum(app)
