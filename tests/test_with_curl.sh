#!/bin/bash
# Test webhook receiver with curl

set -e

echo "======================================================================"
echo "Testing Webhook Receiver with curl"
echo "======================================================================"
echo ""

# Generate valid signature using Python
read -r TIMESTAMP SIGNATURE <<< $(python3 -c "
import time
import hmac
import hashlib

secret = 'whsec_test123'
payload = '{\"eventId\": \"evt_test123\", \"test\": true}'
timestamp = str(int(time.time()))
signed_payload = f'{timestamp}.{payload}'
signature = hmac.new(secret.encode('utf-8'), signed_payload.encode('utf-8'), hashlib.sha256).hexdigest()
print(timestamp, signature)
")

VALID_SIG="t=${TIMESTAMP},v1=${SIGNATURE}"
PAYLOAD='{"eventId": "evt_test123", "test": true}'

echo "Test 1: Health Check"
echo "----------------------------------------------------------------------"
curl -s http://localhost:5001/v1/receiver/health | python -m json.tool
echo ""
echo "✓ Health check passed"
echo ""

echo "Test 2: Webhook with VALID signature"
echo "----------------------------------------------------------------------"
echo "Signature: $VALID_SIG"
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST http://localhost:5001/v1/receiver/test-tenant/webhook \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: $VALID_SIG" \
  -d "$PAYLOAD")

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_STATUS")

echo "Status: $HTTP_STATUS"
if [ -n "$BODY" ]; then
    echo "Response: $BODY" | python -m json.tool
fi
if [ "$HTTP_STATUS" = "200" ]; then
    echo "✓ Valid signature accepted (200)"
else
    echo "✗ Expected 200, got $HTTP_STATUS"
    exit 1
fi
echo ""

echo "Test 3: Webhook with INVALID signature"
echo "----------------------------------------------------------------------"
INVALID_SIG="t=12345,v1=invalid_signature_here"
echo "Signature: $INVALID_SIG"
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST http://localhost:5001/v1/receiver/test-tenant/webhook \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: $INVALID_SIG" \
  -d "$PAYLOAD")

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_STATUS")

echo "Status: $HTTP_STATUS"
if [ -n "$BODY" ]; then
    echo "Response: $BODY" | python -m json.tool
fi
if [ "$HTTP_STATUS" = "401" ]; then
    echo "✓ Invalid signature rejected (401)"
else
    echo "✗ Expected 401, got $HTTP_STATUS"
    exit 1
fi
echo ""

echo "Test 4: Webhook WITHOUT signature header"
echo "----------------------------------------------------------------------"
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST http://localhost:5001/v1/receiver/test-tenant/webhook \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_STATUS")

echo "Status: $HTTP_STATUS"
if [ -n "$BODY" ]; then
    echo "Response: $BODY" | python -m json.tool
fi
if [ "$HTTP_STATUS" = "401" ]; then
    echo "✓ Missing signature rejected (401)"
else
    echo "✗ Expected 401, got $HTTP_STATUS"
    exit 1
fi
echo ""

echo "Test 5: Webhook for NON-EXISTENT tenant"
echo "----------------------------------------------------------------------"
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST http://localhost:5001/v1/receiver/nonexistent/webhook \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: $VALID_SIG" \
  -d "$PAYLOAD")

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_STATUS")

echo "Status: $HTTP_STATUS"
if [ -n "$BODY" ]; then
    echo "Response: $BODY" | python -m json.tool
fi
if [ "$HTTP_STATUS" = "404" ]; then
    echo "✓ Non-existent tenant returns 404"
else
    echo "✗ Expected 404, got $HTTP_STATUS"
    exit 1
fi
echo ""

echo "======================================================================"
echo "✅ All curl tests passed!"
echo "======================================================================"
