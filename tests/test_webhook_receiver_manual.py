#!/usr/bin/env python3
"""
Manual test for webhook receiver using curl-like requests.
Tests signature validation without requiring actual DynamoDB.
"""
import time
import hmac
import hashlib
import json


def generate_stripe_signature(payload: str, secret: str) -> str:
    """Generate Stripe-style webhook signature"""
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_signature_generation():
    """Test that signature generation works correctly"""
    test_secret = "whsec_test123"
    test_payload = '{"event": "test", "data": "example"}'

    # Generate signature
    signature = generate_stripe_signature(test_payload, test_secret)
    print(f"✓ Signature generated: {signature}")

    # Verify format
    assert signature.startswith("t="), "Signature should start with t="
    assert ",v1=" in signature, "Signature should contain v1="

    parts = dict(item.split("=") for item in signature.split(","))
    assert "t" in parts and "v1" in parts, "Signature should have both t and v1"

    print(f"✓ Signature format is correct")

    return signature, test_payload


def test_signature_verification():
    """Test signature verification logic (from webhook_receiver)"""
    test_secret = "whsec_test123"
    test_payload = '{"event": "test"}'

    # Generate valid signature
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{test_payload}"
    signature = hmac.new(
        test_secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    valid_header = f"t={timestamp},v1={signature}"

    # Test verification logic (same as in main.py)
    parts = dict(item.split("=") for item in valid_header.split(","))
    extracted_timestamp = parts.get("t")
    extracted_signature = parts.get("v1")

    expected_payload = f"{extracted_timestamp}.{test_payload}"
    expected_signature = hmac.new(
        test_secret.encode("utf-8"),
        expected_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert hmac.compare_digest(
        expected_signature, extracted_signature
    ), "Valid signature should verify"
    print(f"✓ Valid signature verification works")

    # Test with invalid signature
    invalid_header = f"t={timestamp},v1=invalid_signature"
    parts = dict(item.split("=") for item in invalid_header.split(","))
    extracted_signature = parts.get("v1")

    assert not hmac.compare_digest(
        expected_signature, extracted_signature
    ), "Invalid signature should fail"
    print(f"✓ Invalid signature rejection works")


def generate_curl_commands():
    """Generate curl commands for manual testing"""
    test_secret = "whsec_test123"
    test_payload = '{"eventId": "evt_test123", "test": true}'

    signature = generate_stripe_signature(test_payload, test_secret)

    print("\n" + "=" * 60)
    print("CURL TEST COMMANDS")
    print("=" * 60)

    print("\n1. Test health endpoint:")
    print("curl -v http://localhost:5001/v1/receiver/health")

    print("\n2. Test webhook with valid signature:")
    print(f"curl -v -X POST http://localhost:5001/v1/receiver/test-tenant/webhook \\")
    print(f'  -H "Content-Type: application/json" \\')
    print(f'  -H "Stripe-Signature: {signature}" \\')
    print(f"  -d '{test_payload}'")

    print("\n3. Test webhook with invalid signature:")
    print(f"curl -v -X POST http://localhost:5001/v1/receiver/test-tenant/webhook \\")
    print(f'  -H "Content-Type: application/json" \\')
    print(f'  -H "Stripe-Signature: t=12345,v1=invalid" \\')
    print(f"  -d '{test_payload}'")

    print("\n4. Test webhook without signature header:")
    print(f"curl -v -X POST http://localhost:5001/v1/receiver/test-tenant/webhook \\")
    print(f'  -H "Content-Type: application/json" \\')
    print(f"  -d '{test_payload}'")

    print("\n" + "=" * 60)

    return signature, test_payload


if __name__ == "__main__":
    print("Testing Webhook Receiver Signature Logic\n")

    # Test 1: Signature generation
    print("Test 1: Signature Generation")
    sig, payload = test_signature_generation()
    print()

    # Test 2: Signature verification logic
    print("Test 2: Signature Verification Logic")
    test_signature_verification()
    print()

    # Test 3: Generate curl commands
    print("Test 3: Generate Curl Commands")
    generate_curl_commands()

    print("\n✅ All signature logic tests passed!")
