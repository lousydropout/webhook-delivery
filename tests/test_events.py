import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.lambda_handlers.api.main import app
from src.lambda_handlers.api.auth import verify_api_key


async def mock_verify_api_key():
    """Mock authentication that returns test tenant"""
    return 'test_tenant'


@pytest.fixture
def client():
    """FastAPI test client with dependency overrides"""
    app.dependency_overrides[verify_api_key] = mock_verify_api_key
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def mock_auth():
    """Mock authentication fixture (for compatibility)"""
    pass


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB table"""
    with patch('src.lambda_handlers.api.routes.events.events_table') as mock_table:
        yield mock_table


def test_create_event(client, mock_auth, mock_dynamodb):
    """Test event creation"""
    mock_dynamodb.put_item.return_value = {}

    response = client.post(
        "/v1/events",
        json={"event_type": "test.event", "data": "foo"},
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 201
    data = response.json()
    assert 'id' in data
    assert data['id'].startswith('evt_')
    assert data['status'] == 'undelivered'
    assert 'created_at' in data


def test_list_events_undelivered(client, mock_auth, mock_dynamodb):
    """Test listing undelivered events"""
    mock_dynamodb.query.return_value = {
        'Items': [
            {
                'event_id': 'evt_123',
                'timestamp': 1700000000000,
                'status': 'undelivered',
                'payload': {'test': 'data'}
            }
        ]
    }

    response = client.get(
        "/v1/events?status=undelivered",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data['events']) == 1
    assert data['events'][0]['id'] == 'evt_123'
    assert data['events'][0]['status'] == 'undelivered'


def test_get_event_not_found(client, mock_auth, mock_dynamodb):
    """Test getting non-existent event"""
    mock_dynamodb.get_item.return_value = {}

    response = client.get(
        "/v1/events/evt_nonexistent",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 404


def test_acknowledge_event(client, mock_auth, mock_dynamodb):
    """Test event acknowledgment"""
    mock_dynamodb.get_item.return_value = {
        'Item': {
            'event_id': 'evt_123',
            'status': 'undelivered',
            'timestamp': 1700000000000
        }
    }
    mock_dynamodb.update_item.return_value = {}

    response = client.post(
        "/v1/events/evt_123/ack",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'acknowledged'


def test_delete_event(client, mock_auth, mock_dynamodb):
    """Test event deletion"""
    mock_dynamodb.get_item.return_value = {
        'Item': {'event_id': 'evt_123'}
    }
    mock_dynamodb.delete_item.return_value = {}

    response = client.delete(
        "/v1/events/evt_123",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 204


def test_get_event_success(client, mock_auth, mock_dynamodb):
    """Test getting an existing event"""
    mock_dynamodb.get_item.return_value = {
        'Item': {
            'event_id': 'evt_123',
            'timestamp': 1700000000000,
            'status': 'undelivered',
            'payload': {'test': 'data'}
        }
    }

    response = client.get(
        "/v1/events/evt_123",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['id'] == 'evt_123'
    assert data['status'] == 'undelivered'
    assert data['payload'] == {'test': 'data'}


def test_list_all_events(client, mock_auth, mock_dynamodb):
    """Test listing all events without status filter"""
    mock_dynamodb.query.return_value = {
        'Items': [
            {
                'event_id': 'evt_123',
                'timestamp': 1700000000000,
                'status': 'undelivered',
                'payload': {'test': 'data'}
            },
            {
                'event_id': 'evt_456',
                'timestamp': 1700000001000,
                'status': 'delivered',
                'payload': {'test': 'data2'}
            }
        ]
    }

    response = client.get(
        "/v1/events",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data['events']) == 2


def test_acknowledge_already_delivered_event(client, mock_auth, mock_dynamodb):
    """Test acknowledging an already-delivered event (idempotent)"""
    mock_dynamodb.get_item.return_value = {
        'Item': {
            'event_id': 'evt_123',
            'status': 'delivered',
            'timestamp': 1700000000000
        }
    }

    response = client.post(
        "/v1/events/evt_123/ack",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'acknowledged'


def test_acknowledge_nonexistent_event(client, mock_auth, mock_dynamodb):
    """Test acknowledging non-existent event"""
    mock_dynamodb.get_item.return_value = {}

    response = client.post(
        "/v1/events/evt_nonexistent/ack",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 404


def test_delete_nonexistent_event(client, mock_auth, mock_dynamodb):
    """Test deleting non-existent event"""
    mock_dynamodb.get_item.return_value = {}

    response = client.delete(
        "/v1/events/evt_nonexistent",
        headers={"Authorization": "Bearer test_key"}
    )

    assert response.status_code == 404
