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
