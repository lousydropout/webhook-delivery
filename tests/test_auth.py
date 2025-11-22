import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from src.lambda_handlers.api.auth import get_tenant_from_api_key


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table"""
    with patch('src.lambda_handlers.api.auth.api_keys_table') as mock_table:
        yield mock_table


def test_get_tenant_from_api_key_success(mock_dynamodb_table):
    """Test successful API key lookup"""
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'pk': 'test_key',
            'sk': 'meta',
            'tenant_id': 'acme',
            'status': 'active'
        }
    }

    tenant_id = get_tenant_from_api_key('test_key')

    assert tenant_id == 'acme'
    mock_dynamodb_table.get_item.assert_called_once_with(
        Key={'pk': 'test_key', 'sk': 'meta'}
    )


def test_get_tenant_from_api_key_not_found(mock_dynamodb_table):
    """Test API key not found"""
    mock_dynamodb_table.get_item.return_value = {}

    tenant_id = get_tenant_from_api_key('invalid_key')

    assert tenant_id is None


def test_get_tenant_from_api_key_revoked(mock_dynamodb_table):
    """Test revoked API key"""
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'pk': 'test_key',
            'sk': 'meta',
            'tenant_id': 'acme',
            'status': 'revoked'
        }
    }

    tenant_id = get_tenant_from_api_key('test_key')

    assert tenant_id is None


def test_get_tenant_from_api_key_exception(mock_dynamodb_table):
    """Test DynamoDB exception handling"""
    mock_dynamodb_table.get_item.side_effect = Exception("DynamoDB error")

    tenant_id = get_tenant_from_api_key('test_key')

    assert tenant_id is None
