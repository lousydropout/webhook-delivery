#!/usr/bin/env python3
"""
Test webhook receiver that validates HMAC signatures.
FastAPI-based receiver for testing webhook delivery.
"""
import hmac
import hashlib
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional
import uvicorn

app = FastAPI(
    title="Webhook Test Receiver",
    description="Test receiver for validating webhook delivery and HMAC signatures",
    version="1.0.0",
)

# Test webhook secret (from seeding script)
WEBHOOK_SECRET = "whsec_test123"  # Replace with actual secret


def verify_signature(payload: str, signature_header: str) -> bool:
    """Verify Stripe-style signature"""
    try:
        parts = dict(item.split("=") for item in signature_header.split(","))
        timestamp = parts.get("t")
        signature = parts.get("v1")

        if not timestamp or not signature:
            return False

        signed_payload = f"{timestamp}.{payload}"
        expected = hmac.new(
            WEBHOOK_SECRET.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
    except Exception as e:
        print(f"Error verifying signature: {e}")
        return False


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """Receive webhook and validate signature"""
    if not stripe_signature:
        raise HTTPException(status_code=401, detail="Missing Stripe-Signature header")

    # Read raw body
    body = await request.body()
    payload = body.decode("utf-8")

    # Verify signature
    if not verify_signature(payload, stripe_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    print(f"✓ Valid webhook received: {payload}")
    return {"status": "received"}


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


if __name__ == "__main__":
    print("Starting webhook test receiver on http://localhost:5000")
    print(f"Webhook secret: {WEBHOOK_SECRET}")
    print("POST webhooks to: http://localhost:5000/webhook")
    uvicorn.run(app, host="0.0.0.0", port=5000)
