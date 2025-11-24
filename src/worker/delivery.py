import json
import requests
from decimal import Decimal
from typing import Dict, Any, Tuple
from signatures import generate_stripe_signature


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            # Convert Decimal to int if it's a whole number, otherwise float
            return int(obj) if obj % 1 == 0 else float(obj)
        return super(DecimalEncoder, self).default(obj)


def deliver_webhook(
    target_url: str, payload: Dict[str, Any], webhook_secret: str, timeout: int = 30
) -> Tuple[bool, int, str]:
    """
    Deliver webhook with HMAC signature.

    Returns: (success: bool, status_code: int, error_message: str)
    """
    payload_json = json.dumps(payload, cls=DecimalEncoder)
    signature = generate_stripe_signature(payload_json, webhook_secret)

    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": signature,
    }

    try:
        response = requests.post(
            target_url,
            data=payload_json,
            headers=headers,
            timeout=timeout,
        )

        success = 200 <= response.status_code < 300
        return success, response.status_code, ""

    except requests.exceptions.Timeout:
        return False, 0, "Request timeout"
    except requests.exceptions.ConnectionError as e:
        return False, 0, f"Connection error: {str(e)}"
    except Exception as e:
        return False, 0, f"Unexpected error: {str(e)}"
