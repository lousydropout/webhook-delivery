import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add src/authorizer to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "authorizer"))


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table for authorizer"""
    with patch("handler.api_keys_table") as mock_table:
        yield mock_table


@pytest.fixture
def authorizer_event():
    """Mock API Gateway authorizer event"""
    return {
        "type": "TOKEN",
        "authorizationToken": "Bearer test_key_123",
        "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/POST/events",
    }


@pytest.fixture
def lambda_context():
    """Mock Lambda context"""
    context = MagicMock()
    context.function_name = "test-authorizer"
    context.request_id = "test-request-id"
    return context


def test_authorizer_valid_token(mock_dynamodb_table, authorizer_event, lambda_context):
    """Test authorizer with valid API key"""
    from handler import handler

    mock_dynamodb_table.get_item.return_value = {
        "Item": {
            "apiKey": "test_key_123",
            "tenantId": "acme",
            "targetUrl": "https://example.com/webhook",
            "webhookSecret": "secret123",
            "isActive": True,
        }
    }

    result = handler(authorizer_event, lambda_context)

    assert result["principalId"] == "acme"
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert result["context"]["tenantId"] == "acme"
    assert result["context"]["targetUrl"] == "https://example.com/webhook"


def test_authorizer_invalid_token(
    mock_dynamodb_table, authorizer_event, lambda_context
):
    """Test authorizer with invalid API key"""
    from handler import handler

    mock_dynamodb_table.get_item.return_value = {}

    result = handler(authorizer_event, lambda_context)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_authorizer_inactive_key(mock_dynamodb_table, authorizer_event, lambda_context):
    """Test authorizer with inactive API key"""
    from handler import handler

    mock_dynamodb_table.get_item.return_value = {
        "Item": {
            "apiKey": "test_key_123",
            "tenantId": "acme",
            "isActive": False,
        }
    }

    result = handler(authorizer_event, lambda_context)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_authorizer_missing_bearer_prefix(authorizer_event, lambda_context):
    """Test authorizer with missing Bearer prefix"""
    from handler import handler

    authorizer_event["authorizationToken"] = "test_key_123"  # No "Bearer "

    result = handler(authorizer_event, lambda_context)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_authorizer_missing_token(lambda_context):
    """Test authorizer with missing token"""
    from handler import handler

    event = {
        "type": "TOKEN",
        "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/POST/events",
    }

    result = handler(event, lambda_context)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"
