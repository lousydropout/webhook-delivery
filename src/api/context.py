from typing import Dict, Any


def get_tenant_from_context(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract tenant identity from API Gateway authorizer.

    When using Lambda authorizer, API Gateway adds the authorizer's
    context to event['requestContext']['authorizer'].

    The authorizer only returns tenant identity (tenantId, status, plan).
    Webhook configuration (targetUrl, webhookSecret) is stored separately
    in TenantWebhookConfig table and must be fetched when needed.

    Args:
        event: Lambda event from API Gateway

    Returns:
        Tenant identity dict with tenantId, status, plan

    Raises:
        ValueError: If authorizer context is missing (should not happen with proper config)
    """
    authorizer = event.get("requestContext", {}).get("authorizer", {})

    if not authorizer:
        raise ValueError("Missing authorizer context - authentication required")

    return {
        "tenantId": authorizer["tenantId"],
        "status": authorizer.get("status", "active"),
        "plan": authorizer.get("plan", "free"),
    }
