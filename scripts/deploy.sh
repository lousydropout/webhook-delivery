#!/bin/bash
set -e

echo "=========================================="
echo "Deploying Trigger Ingestion API"
echo "=========================================="
echo ""

# Check prerequisites
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI not found. Please install it first."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 not found. Please install it first."
    exit 1
fi

# Install Python dependencies
echo "1. Installing Python dependencies..."
pip install -r requirements.txt
pip install -r cdk/requirements.txt
echo "   ✓ Dependencies installed"
echo ""

# Bootstrap CDK (if needed)
echo "2. Bootstrapping CDK (if needed)..."
cd cdk
cdk bootstrap || echo "   (Already bootstrapped)"
echo "   ✓ CDK ready"
echo ""

# Deploy CDK stack
echo "3. Deploying infrastructure..."
cdk deploy --require-approval never
echo "   ✓ Infrastructure deployed"
echo ""

cd ..

# Seed tenants
echo "4. Seeding test tenants..."
python scripts/seed_tenants.py
echo "   ✓ Tenants seeded"
echo ""

# Get API URL
API_URL=$(aws cloudformation describe-stacks \
    --stack-name TriggerApiStack \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
    --output text)

echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "API URL: $API_URL"
echo ""
echo "Next steps:"
echo "1. Export tenant API keys (see output from seed script above)"
echo "2. Test with: curl $API_URL/health"
echo "3. Import Postman collection from docs/postman_collection.json"
echo "4. Run mock worker: python src/worker/mock_worker.py"
echo ""
