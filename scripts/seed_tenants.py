#!/usr/bin/env python3
"""
Seed test tenants into DynamoDB

Creates 3 test tenants with API keys for demonstration purposes.
"""
import boto3
import uuid
import time
import sys


def generate_api_key(tenant_name: str) -> str:
    """Generate a Stripe-style API key"""
    random_suffix = uuid.uuid4().hex[:12]
    return f"tenant_{tenant_name}_live_{random_suffix}"


def seed_tenants():
    """Seed 3 test tenants"""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table("TriggerApi-TenantApiKeys")

    tenants = [
        {"name": "acme", "display": "Acme Corp"},
        {"name": "globex", "display": "Globex Inc"},
        {"name": "initech", "display": "Initech LLC"},
    ]

    print("Seeding test tenants...")
    print()

    created_keys = []

    for tenant in tenants:
        tenant_name = tenant["name"]
        api_key = generate_api_key(tenant_name)

        item = {
            "pk": api_key,
            "sk": "meta",
            "tenant_id": tenant_name,
            "status": "active",
            "created_at": int(time.time() * 1000),
            "display_name": tenant["display"],
        }

        try:
            table.put_item(Item=item)
            print(f"✓ Created tenant: {tenant['display']}")
            print(f"  Tenant ID: {tenant_name}")
            print(f"  API Key: {api_key}")
            print()

            created_keys.append({"tenant": tenant_name, "key": api_key})
        except Exception as e:
            print(f"✗ Error creating tenant {tenant_name}: {e}")
            sys.exit(1)

    print("=" * 60)
    print("All tenants created successfully!")
    print("=" * 60)
    print()
    print("Export these for testing:")
    print()
    for item in created_keys:
        print(f"export {item['tenant'].upper()}_API_KEY='{item['key']}'")
    print()
    print("Multi-tenant worker:")
    print(f"export API_KEYS='{','.join([i['key'] for i in created_keys])}'")
    print(f"export TENANT_NAMES='{','.join([i['tenant'] for i in created_keys])}'")


if __name__ == "__main__":
    seed_tenants()
