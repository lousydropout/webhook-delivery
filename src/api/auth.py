import os
import boto3
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional, Dict

security = HTTPBearer()

dynamodb = boto3.resource('dynamodb')
api_keys_table = dynamodb.Table(os.environ['TENANT_API_KEYS_TABLE'])


def get_tenant_from_api_key(api_key: str) -> Optional[Dict]:
    """
    Look up tenant from API key in DynamoDB.

    Returns: {
        "tenantId": "...",
        "targetUrl": "https://...",
        "webhookSecret": "...",
        "isActive": true
    }
    """
    try:
        response = api_keys_table.get_item(Key={'apiKey': api_key})
        item = response.get('Item')

        if not item or not item.get('isActive'):
            return None

        return item
    except Exception as e:
        print(f"Error looking up API key: {e}")
        return None


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> Dict:
    """FastAPI dependency that validates API key and returns tenant info"""
    api_key = credentials.credentials
    tenant = get_tenant_from_api_key(api_key)

    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return tenant
