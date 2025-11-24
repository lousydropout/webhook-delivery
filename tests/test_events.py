import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "api"))

# Set environment variables before importing the app
os.environ["EVENTS_QUEUE_URL"] = (
    "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue"
)
os.environ["EVENTS_TABLE"] = "test-events-table"
os.environ["TENANT_API_KEYS_TABLE"] = "test-api-keys-table"


@pytest.fixture
def mock_sqs():
    """Mock SQS client"""
    with patch("routes.sqs") as mock:
        mock.send_message.return_value = {}
        yield mock


@pytest.fixture
def mock_create_event():
    """Mock create_event function"""
    with patch("routes.create_event") as mock:
        mock.return_value = "evt_test123"
        yield mock


@pytest.fixture
def mock_get_tenant_from_context():
    """Mock get_tenant_from_context to return test tenant"""
    with patch("routes.get_tenant_from_context") as mock:
        mock.return_value = {
            "tenantId": "test_tenant",
            "targetUrl": "https://example.com/webhook",
            "webhookSecret": "test_secret",
            "isActive": True,
        }
        yield mock


@pytest.fixture
def client():
    """FastAPI test client"""
    from main import app

    return TestClient(app)


def test_create_event(
    client, mock_sqs, mock_create_event, mock_get_tenant_from_context
):
    """Test event creation with authorizer context"""
    response = client.post(
        "/v1/events",
        json={"event_type": "test.event", "data": "foo"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["event_id"] == "evt_test123"
    assert data["status"] == "PENDING"

    # Verify create_event was called with correct tenant_id
    mock_create_event.assert_called_once_with(
        "test_tenant",
        {"event_type": "test.event", "data": "foo"},
        "https://example.com/webhook",
    )

    # Verify SQS message was sent
    mock_sqs.send_message.assert_called_once()
    call_args = mock_sqs.send_message.call_args
    assert call_args[1]["QueueUrl"] == os.environ["EVENTS_QUEUE_URL"]


def test_create_event_missing_auth_context(client, mock_sqs, mock_create_event):
    """Test event creation without authorizer context (should fail)"""
    with patch("routes.get_tenant_from_context") as mock_context:
        mock_context.side_effect = ValueError("Missing authorizer context")

        response = client.post(
            "/v1/events",
            json={"event_type": "test.event", "data": "foo"},
        )

    assert response.status_code == 401
    assert "Authentication error" in response.json()["detail"]


def test_create_event_sqs_failure(
    client, mock_sqs, mock_create_event, mock_get_tenant_from_context
):
    """Test event creation when SQS fails"""
    mock_sqs.send_message.side_effect = Exception("SQS error")

    response = client.post(
        "/v1/events",
        json={"event_type": "test.event", "data": "foo"},
    )

    assert response.status_code == 500
    assert "Failed to enqueue event" in response.json()["detail"]
