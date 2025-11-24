#!/usr/bin/env python3
"""
Seed test tenants with webhook configurations.
"""
import boto3
import uuid
import time
import sys

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("Vincent-Trigger-TenantApiKeys")


def generate_api_key(tenant_name: str) -> str:
    """Generate API key"""
    random_suffix = uuid.uuid4().hex[:12]
    return f"tenant_{tenant_name}_live_{random_suffix}"


def generate_webhook_secret() -> str:
    """Generate webhook secret"""
    return f"whsec_{uuid.uuid4().hex}"


def seed_tenants():
    """Seed 3 test tenants with webhook configs"""
    tenants = [
        {
            "name": "test-tenant",
            "display": "Test Tenant",
            "targetUrl": "https://receiver.vincentchan.cloud/test-tenant/webhook",
        },
        {
            "name": "acme",
            "display": "Acme Corp",
            "targetUrl": "https://receiver.vincentchan.cloud/acme/webhook",
        },
        {
            "name": "globex",
            "display": "Globex Inc",
            "targetUrl": "https://receiver.vincentchan.cloud/globex/webhook",
        },
    ]

    print("Seeding tenants with webhook configurations...")
    print()

    created = []

    for tenant in tenants:
        api_key = generate_api_key(tenant["name"])
        webhook_secret = generate_webhook_secret()

        item = {
            "apiKey": api_key,
            "tenantId": tenant["name"],
            "targetUrl": tenant["targetUrl"],
            "webhookSecret": webhook_secret,
            "isActive": True,
            "createdAt": str(int(time.time())),
            "displayName": tenant["display"],
        }

        try:
            table.put_item(Item=item)
            print(f"✓ Created: {tenant['display']}")
            print(f"  API Key: {api_key}")
            print(f"  Webhook Secret: {webhook_secret}")
            print(f"  Target URL: {tenant['targetUrl']}")
            print()

            created.append(
                {
                    "tenant": tenant["name"],
                    "apiKey": api_key,
                    "webhookSecret": webhook_secret,
                }
            )
        except Exception as e:
            print(f"✗ Error: {e}")
            sys.exit(1)

    print("=" * 60)
    print("All tenants created!")
    print("=" * 60)
    print()
    print("Test with:")
    for item in created:
        print(f"curl -X POST https://hooks.vincentchan.cloud/v1/events \\")
        print(f"  -H 'Authorization: Bearer {item['apiKey']}' \\")
        print(f"  -H 'Content-Type: application/json' \\")
        print(f'  -d \'{{"event": "test.event", "data": "test"}}\'')
        print()


if __name__ == "__main__":
    seed_tenants()
