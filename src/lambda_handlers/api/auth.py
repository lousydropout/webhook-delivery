import os
import boto3
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional

security = HTTPBearer()

dynamodb = boto3.resource('dynamodb')
api_keys_table = dynamodb.Table(os.environ.get('API_KEYS_TABLE', 'TriggerApi-TenantApiKeys'))


def get_tenant_from_api_key(api_key: str) -> Optional[str]:
    """
    Look up tenant_id from API key in DynamoDB.

    Table structure:
    pk = api_key
    sk = "meta"
    tenant_id = <tenant_id>
    status = "active" | "revoked"
    """
    try:
        response = api_keys_table.get_item(
            Key={'pk': api_key, 'sk': 'meta'}
        )

        item = response.get('Item')
        if not item:
            return None

        if item.get('status') != 'active':
            return None

        return item.get('tenant_id')
    except Exception as e:
        print(f"Error looking up API key: {e}")
        return None


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> str:
    """
    FastAPI dependency that validates the API key and returns tenant_id.

    Usage:
        @app.get("/endpoint")
        async def endpoint(tenant_id: str = Depends(verify_api_key)):
            ...
    """
    api_key = credentials.credentials

    tenant_id = get_tenant_from_api_key(api_key)

    if not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked API key"
        )

    return tenant_id
