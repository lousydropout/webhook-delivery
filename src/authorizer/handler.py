import os
import boto3
from typing import Dict, Any, Optional

dynamodb = boto3.resource("dynamodb")
tenant_identity_table = dynamodb.Table(os.environ["TENANT_IDENTITY_TABLE"])


def get_tenant_from_api_key(api_key: str) -> Optional[Dict]:
    """
    Look up tenant identity from API key in DynamoDB.

    Uses projection expression to only retrieve tenantId, status, plan, createdAt.
    Never accesses webhook secrets (stored in separate TenantWebhookConfig table).

    Returns tenant identity if valid and active, None otherwise.
    """
    try:
        # Use ProjectionExpression to limit fields retrieved (least privilege)
        response = tenant_identity_table.get_item(
            Key={"apiKey": api_key},
            ProjectionExpression="tenantId, #status, plan, createdAt",
            ExpressionAttributeNames={"#status": "status"},
        )
        item = response.get("Item")

        if not item or item.get("status") != "active":
            return None

        return item
    except Exception as e:
        print(f"Error looking up API key: {e}")
        return None


def generate_policy(
    principal_id: str, effect: str, resource: str, context: Dict[str, Any] = None
) -> Dict:
    """
    Generate IAM policy document for API Gateway.

    Args:
        principal_id: Identifier for the authenticated principal (tenantId)
        effect: "Allow" or "Deny"
        resource: ARN of the API Gateway method
        context: Additional context to pass to the Lambda (must be string values)
    """
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}
            ],
        },
    }

    if context:
        # API Gateway requires all context values to be strings
        policy["context"] = {k: str(v) for k, v in context.items()}

    return policy


def handler(event: Dict, context: Any) -> Dict:
    """
    Lambda authorizer for API Gateway TOKEN type.

    Event structure:
    {
        "type": "TOKEN",
        "authorizationToken": "Bearer <api-key>",
        "methodArn": "arn:aws:execute-api:..."
    }

    Returns IAM policy with tenant context or Deny policy.
    """
    token = event.get("authorizationToken", "")
    method_arn = event["methodArn"]

    # Extract Bearer token
    if not token.startswith("Bearer "):
        print("Missing or invalid Authorization header format")
        return generate_policy("anonymous", "Deny", method_arn)

    api_key = token[7:]  # Remove "Bearer " prefix

    # Validate API key
    tenant = get_tenant_from_api_key(api_key)

    if not tenant:
        print(f"Invalid or inactive API key")
        return generate_policy("anonymous", "Deny", method_arn)

    # Generate Allow policy with tenant context
    # Use wildcard to allow all methods for this API
    # Convert arn:aws:execute-api:region:account:api-id/stage/method/path
    # to arn:aws:execute-api:region:account:api-id/*
    arn_parts = method_arn.split("/")
    resource_arn = f"{arn_parts[0]}/*"

    tenant_id = tenant["tenantId"]
    # Authorizer context only includes identity info (no webhook secrets)
    context_data = {
        "tenantId": tenant["tenantId"],
        "status": tenant.get("status", "active"),
        "plan": tenant.get("plan", "free"),
    }

    print(f"Authorized tenant: {tenant_id}")
    return generate_policy(tenant_id, "Allow", resource_arn, context_data)
