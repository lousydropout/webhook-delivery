from typing import Dict, Any


def get_tenant_from_context(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract tenant context from API Gateway authorizer.

    When using Lambda authorizer, API Gateway adds the authorizer's
    context to event['requestContext']['authorizer'].

    Args:
        event: Lambda event from API Gateway

    Returns:
        Tenant context dict with tenantId, targetUrl, webhookSecret, isActive

    Raises:
        KeyError: If authorizer context is missing (should not happen with proper config)
    """
    authorizer = event.get("requestContext", {}).get("authorizer", {})

    if not authorizer:
        raise ValueError("Missing authorizer context - authentication required")

    return {
        "tenantId": authorizer["tenantId"],
        "targetUrl": authorizer["targetUrl"],
        "webhookSecret": authorizer["webhookSecret"],
        "isActive": authorizer["isActive"] == "True",  # API GW context is all strings
    }
