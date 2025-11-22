#!/bin/bash
set -e

echo "=========================================="
echo "Deploying Webhook Delivery System"
echo "=========================================="
echo ""

# Check prerequisites
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI not found"
    exit 1
fi

# Install CDK dependencies
echo "1. Installing CDK dependencies..."
cd cdk
pip install -r requirements.txt
echo "   ✓ CDK ready"
echo ""

# Bootstrap if needed
echo "2. Bootstrapping CDK..."
cdk bootstrap || echo "   (Already bootstrapped)"
echo ""

# Deploy stack
echo "3. Deploying infrastructure..."
cdk deploy --require-approval never
echo "   ✓ Stack deployed"
echo ""

cd ..

# Seed tenants
echo "4. Seeding test tenants..."
python scripts/seed_webhooks.py
echo ""

# Get custom domain
CUSTOM_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name WebhookDeliveryStack \
    --query 'Stacks[0].Outputs[?OutputKey==`CustomDomainUrl`].OutputValue' \
    --output text)

echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "API URL: $CUSTOM_DOMAIN"
echo ""
echo "Next steps:"
echo "1. Configure webhook receiver endpoints for test tenants"
echo "2. Test event ingestion: curl -X POST $CUSTOM_DOMAIN/events -H 'Authorization: Bearer <api-key>' -d '{\"test\":\"data\"}'"
echo "3. Monitor CloudWatch Logs for delivery status"
echo ""
