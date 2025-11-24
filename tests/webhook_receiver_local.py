#!/usr/bin/env python3
"""
Local test version of webhook receiver with mocked DynamoDB.
Run with: python tests/webhook_receiver_local.py
"""
import hmac
import hashlib
import json
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional
import uvicorn

app = FastAPI(
    title="Webhook Receiver (Local Test)",
    description="Multi-tenant webhook receiver with HMAC validation - Local Test Mode",
    version="2.0.0",
    docs_url="/v1/receiver/docs",
    redoc_url="/v1/receiver/redoc",
    openapi_url="/v1/receiver/openapi.json",
)

# Mock tenant secrets for testing
MOCK_TENANT_SECRETS = {
    "test-tenant": "whsec_test123",
    "tenant1": "whsec_tenant1_secret",
    "tenant2": "whsec_tenant2_secret",
}


def get_webhook_secret_for_tenant(tenant_id: str) -> Optional[str]:
    """
    Mock version - retrieve from in-memory dict instead of DynamoDB.
    """
    secret = MOCK_TENANT_SECRETS.get(tenant_id)
    if secret:
        print(f"✓ Found secret for tenant: {tenant_id}")
    else:
        print(f"✗ No secret found for tenant: {tenant_id}")
    return secret


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
            print(f"✗ Missing timestamp or signature in header")
            return False

        signed_payload = f"{timestamp}.{payload}"
        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(expected, signature)
        if is_valid:
            print(f"✓ Signature verified successfully")
        else:
            print(f"✗ Signature mismatch - expected: {expected}, got: {signature}")

        return is_valid
    except Exception as e:
        print(f"✗ Error verifying signature: {e}")
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
    print(f"\n{'='*60}")
    print(f"Incoming webhook for tenant: {tenant_id}")
    print(f"{'='*60}")

    # Validate signature header presence
    if not stripe_signature:
        print(f"✗ Missing Stripe-Signature header for tenant: {tenant_id}")
        raise HTTPException(status_code=401, detail="Missing Stripe-Signature header")

    print(f"Stripe-Signature: {stripe_signature}")

    # Read raw body for signature verification
    body = await request.body()
    payload = body.decode("utf-8")
    print(f"Payload: {payload}")

    # Retrieve webhook secret
    webhook_secret = get_webhook_secret_for_tenant(tenant_id)
    if not webhook_secret:
        print(f"✗ No active webhook secret found for tenant: {tenant_id}")
        raise HTTPException(status_code=404, detail="Tenant not found or inactive")

    # Verify HMAC signature
    if not verify_signature(payload, stripe_signature, webhook_secret):
        print(f"✗ Invalid signature for tenant: {tenant_id}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload for logging
    try:
        payload_json = json.loads(payload)
        event_id = payload_json.get("eventId") or payload_json.get("event_id")
        print(f"✓ Valid webhook received for tenant {tenant_id}, event: {event_id}")
    except json.JSONDecodeError:
        print(f"✓ Valid webhook received for tenant {tenant_id} (non-JSON payload)")

    print(f"{'='*60}\n")
    return {"status": "received", "tenant_id": tenant_id}


@app.get("/v1/receiver/health")
async def health_check():
    """Health check endpoint for monitoring"""
    print("Health check requested")
    return {"status": "healthy", "service": "webhook-receiver"}


if __name__ == "__main__":
    print("=" * 80)
    print("Starting Webhook Receiver (Local Test Mode)")
    print("=" * 80)
    print("\nMock tenant secrets configured:")
    for tenant_id, secret in MOCK_TENANT_SECRETS.items():
        print(f"  - {tenant_id}: {secret}")
    print("\nServer starting on http://localhost:5001")
    print("Docs available at http://localhost:5001/v1/receiver/docs")
    print("=" * 80)
    print()

    uvicorn.run(app, host="0.0.0.0", port=5001, log_level="info")
