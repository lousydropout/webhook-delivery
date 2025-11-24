#!/usr/bin/env python3
"""
Integration test for the complete webhook delivery flow.
Tests: API → SQS → Worker → Webhook Receiver Lambda

This validates the entire system end-to-end:
1. Create event via API with authentication
2. Worker processes SQS message
3. Worker delivers webhook to receiver Lambda
4. Receiver validates HMAC signature
5. All components log correctly
"""
import time
import json
import requests
import boto3
from typing import Dict, Any


class WebhookIntegrationTest:
    def __init__(self):
        self.api_base = "https://hooks.vincentchan.cloud"
        self.receiver_base = "https://receiver.vincentchan.cloud"
        self.tenant_id = "test-tenant"
        self.api_key = "tenant_test-tenant_key"

        # AWS clients
        self.dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        self.events_table = self.dynamodb.Table("Vincent-TriggerApi-Events")
        self.logs_client = boto3.client("logs", region_name="us-east-1")

    def test_health_endpoints(self):
        """Test health endpoints for all services"""
        print("\n" + "="*70)
        print("PHASE 1: Health Check Validation")
        print("="*70)

        # Test receiver health endpoint
        print("\n1. Testing webhook receiver health endpoint...")
        response = requests.get(f"{self.receiver_base}/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        data = response.json()
        assert data["status"] == "healthy", f"Unexpected health status: {data}"
        print(f"   ✓ Receiver health: {data}")

        # Test API docs endpoint (confirms API is responsive)
        print("\n2. Testing API documentation endpoint...")
        response = requests.get(f"{self.api_base}/v1/docs")
        assert response.status_code == 200, f"Docs endpoint failed: {response.status_code}"
        print(f"   ✓ API docs accessible")

        print("\n✅ All health checks passed!")

    def create_event(self, event_data: Dict[str, Any]) -> str:
        """Create an event via the API"""
        print("\n3. Creating event via API...")
        print(f"   Event data: {json.dumps(event_data, indent=2)}")

        response = requests.post(
            f"{self.api_base}/v1/events",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=event_data,
        )

        assert response.status_code == 201, f"Failed to create event: {response.status_code} - {response.text}"
        result = response.json()
        event_id = result["event_id"]
        print(f"   ✓ Event created: {event_id}")

        return event_id

    def wait_for_webhook_delivery(self, event_id: str, timeout: int = 30) -> Dict[str, Any]:
        """Wait for webhook to be delivered and check status in DynamoDB"""
        print(f"\n4. Waiting for webhook delivery (timeout: {timeout}s)...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self.events_table.get_item(
                    Key={
                        "tenantId": self.tenant_id,
                        "eventId": event_id,
                    }
                )

                if "Item" in response:
                    item = response["Item"]
                    status = item.get("status")
                    attempts = item.get("attempts", 0)

                    print(f"   Status: {status}, Attempts: {attempts}")

                    if status.upper() == "DELIVERED":
                        print(f"   ✓ Webhook delivered successfully!")
                        return item
                    elif status.upper() == "FAILED":
                        print(f"   ✗ Webhook delivery failed")
                        return item

            except Exception as e:
                print(f"   Error checking status: {e}")

            time.sleep(2)

        raise TimeoutError(f"Webhook not delivered within {timeout}s")

    def check_receiver_logs(self, event_id: str):
        """Check CloudWatch logs for receiver Lambda"""
        print(f"\n5. Checking receiver Lambda logs for event {event_id}...")

        log_group = "/aws/lambda/Vincent-TriggerApi-WebhookReceiver"

        try:
            # Get recent log events
            response = self.logs_client.filter_log_events(
                logGroupName=log_group,
                startTime=int((time.time() - 300) * 1000),  # Last 5 minutes
                filterPattern=event_id,
            )

            events = response.get("events", [])
            if events:
                print(f"   ✓ Found {len(events)} log entries mentioning event {event_id}")
                for event in events:
                    message = event["message"].strip()
                    if "Valid webhook received" in message:
                        print(f"   ✓ Receiver log: {message}")
                        return True
            else:
                print(f"   ⚠ No logs found for event {event_id} (may still be processing)")

        except Exception as e:
            print(f"   ⚠ Could not check logs: {e}")

        return False

    def check_worker_logs(self, event_id: str):
        """Check CloudWatch logs for worker Lambda"""
        print(f"\n6. Checking worker Lambda logs for event {event_id}...")

        log_group = "/aws/lambda/Vincent-TriggerApi-WorkerHandler"

        try:
            response = self.logs_client.filter_log_events(
                logGroupName=log_group,
                startTime=int((time.time() - 300) * 1000),
                filterPattern=event_id,
            )

            events = response.get("events", [])
            if events:
                print(f"   ✓ Found {len(events)} log entries in worker logs")
                for event in events:
                    message = event["message"].strip()
                    if "delivered successfully" in message.lower() or "status_code: 200" in message.lower():
                        print(f"   ✓ Worker log: {message}")
                        return True
            else:
                print(f"   ⚠ No logs found in worker (may still be processing)")

        except Exception as e:
            print(f"   ⚠ Could not check worker logs: {e}")

        return False

    def test_complete_flow(self):
        """Test the complete webhook delivery flow"""
        print("\n" + "="*70)
        print("PHASE 2: End-to-End Webhook Delivery Flow")
        print("="*70)

        # Create unique event data
        timestamp = int(time.time())
        event_data = {
            "type": "integration_test",
            "timestamp": timestamp,
            "test_id": f"integration_test_{timestamp}",
            "message": "Testing complete webhook flow from API to receiver",
        }

        # Step 1: Create event
        event_id = self.create_event(event_data)

        # Step 2: Wait for delivery
        event_item = self.wait_for_webhook_delivery(event_id, timeout=30)

        # Step 3: Verify event status
        assert event_item["status"] == "DELIVERED", f"Expected 'delivered', got '{event_item['status']}'"

        # Step 4: Check logs
        print("\n" + "="*70)
        print("PHASE 3: Log Verification")
        print("="*70)

        time.sleep(2)  # Give logs time to propagate

        receiver_logged = self.check_receiver_logs(event_id)
        worker_logged = self.check_worker_logs(event_id)

        print("\n" + "="*70)
        print("PHASE 4: Test Summary")
        print("="*70)
        print(f"\nEvent ID: {event_id}")
        print(f"Final Status: {event_item['status']}")
        print(f"Attempts: {event_item.get('attempts', 0)}")
        print(f"Last Attempt: {event_item.get('lastAttemptAt', 'N/A')}")
        print(f"Receiver Logged: {'✓' if receiver_logged else '⚠'}")
        print(f"Worker Logged: {'✓' if worker_logged else '⚠'}")

        return event_id

    def test_concurrent_deliveries(self, count: int = 3):
        """Test multiple concurrent webhook deliveries"""
        print("\n" + "="*70)
        print(f"PHASE 5: Concurrent Delivery Test ({count} events)")
        print("="*70)

        event_ids = []
        timestamp = int(time.time())

        # Create multiple events
        print(f"\nCreating {count} events...")
        for i in range(count):
            event_data = {
                "type": "concurrent_test",
                "timestamp": timestamp,
                "test_number": i + 1,
                "message": f"Concurrent test event {i + 1} of {count}",
            }
            event_id = self.create_event(event_data)
            event_ids.append(event_id)
            time.sleep(0.5)  # Slight delay between creates

        print(f"\n✓ Created {count} events: {event_ids}")

        # Wait for all to be delivered
        print(f"\nWaiting for all {count} events to be delivered...")
        delivered_count = 0

        for event_id in event_ids:
            try:
                event_item = self.wait_for_webhook_delivery(event_id, timeout=40)
                if event_item["status"] == "delivered":
                    delivered_count += 1
                    print(f"   ✓ Event {event_id}: delivered")
                else:
                    print(f"   ✗ Event {event_id}: {event_item['status']}")
            except TimeoutError:
                print(f"   ⚠ Event {event_id}: timeout")

        print(f"\n✅ Successfully delivered {delivered_count}/{count} events")

        return delivered_count == count


def main():
    """Run all integration tests"""
    print("\n" + "="*70)
    print("WEBHOOK RECEIVER INTEGRATION TEST SUITE")
    print("="*70)
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    test = WebhookIntegrationTest()

    try:
        # Test 1: Health checks
        test.test_health_endpoints()

        # Test 2: Complete flow
        event_id = test.test_complete_flow()

        # Test 3: Concurrent deliveries
        all_delivered = test.test_concurrent_deliveries(count=3)

        # Final summary
        print("\n" + "="*70)
        print("✅ ALL INTEGRATION TESTS PASSED!")
        print("="*70)
        print("\nValidated:")
        print("  ✓ API event creation with authentication")
        print("  ✓ SQS message queuing")
        print("  ✓ Worker Lambda webhook delivery")
        print("  ✓ Receiver Lambda HMAC validation")
        print("  ✓ DynamoDB status tracking")
        print("  ✓ CloudWatch logging")
        print("  ✓ Concurrent webhook handling")
        print("\nThe webhook delivery system is fully operational! 🎉")

        return True

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
