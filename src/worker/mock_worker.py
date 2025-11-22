#!/usr/bin/env python3
"""
Mock Worker - Simulates Zapier's trigger engine

Polls the API for undelivered events, processes them, and acknowledges them.
Supports multiple tenants via environment variables.
"""
import os
import sys
import time
import requests
from typing import Optional


class MockWorker:
    def __init__(self, api_url: str, api_key: str, tenant_name: str):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.tenant_name = tenant_name
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def get_undelivered_events(self):
        """Fetch undelivered events from the inbox"""
        try:
            url = f"{self.api_url}/v1/events?status=undelivered&limit=10"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json().get("events", [])
        except requests.exceptions.RequestException as e:
            print(f"[{self.tenant_name}] Error fetching events: {e}")
            return []

    def process_event(self, event: dict):
        """
        Simulate event processing.
        In a real system, this would trigger a Zap, send webhooks, etc.
        """
        event_id = event["id"]
        payload = event["payload"]

        print(f"[{self.tenant_name}] Processing event {event_id}")
        print(f"[{self.tenant_name}]   Payload: {payload}")

        # Simulate some work
        time.sleep(0.5)

        print(f"[{self.tenant_name}]   ✓ Processed successfully")

    def acknowledge_event(self, event_id: str) -> bool:
        """Acknowledge an event as delivered"""
        try:
            url = f"{self.api_url}/v1/events/{event_id}/ack"
            response = requests.post(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            print(f"[{self.tenant_name}]   ✓ Acknowledged {event_id}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"[{self.tenant_name}]   ✗ Error acknowledging {event_id}: {e}")
            return False

    def run(self, poll_interval: int = 5):
        """Main worker loop"""
        print(f"[{self.tenant_name}] Worker started")
        print(f"[{self.tenant_name}] API URL: {self.api_url}")
        print(f"[{self.tenant_name}] Poll interval: {poll_interval}s")
        print()

        while True:
            try:
                events = self.get_undelivered_events()

                if events:
                    print(
                        f"[{self.tenant_name}] Found {len(events)} undelivered event(s)"
                    )

                    for event in events:
                        self.process_event(event)
                        self.acknowledge_event(event["id"])

                    print()

                time.sleep(poll_interval)

            except KeyboardInterrupt:
                print(f"\n[{self.tenant_name}] Worker stopped by user")
                sys.exit(0)
            except Exception as e:
                print(f"[{self.tenant_name}] Unexpected error: {e}")
                time.sleep(poll_interval)


def main():
    """
    Run worker for a single tenant or multiple tenants.

    Environment variables:
    - API_URL: API Gateway endpoint URL (required)
    - API_KEY: Single tenant API key (for single-tenant mode)
    - API_KEYS: Comma-separated list of API keys (for multi-tenant mode)
    - TENANT_NAMES: Comma-separated list of tenant names (optional, for logging)
    - POLL_INTERVAL: Seconds between polls (default: 5)
    """
    api_url = os.environ.get("API_URL")
    if not api_url:
        print("Error: API_URL environment variable required")
        sys.exit(1)

    # Single-tenant mode
    api_key = os.environ.get("API_KEY")
    if api_key:
        tenant_name = os.environ.get("TENANT_NAME", "default")
        poll_interval = int(os.environ.get("POLL_INTERVAL", "5"))

        worker = MockWorker(api_url, api_key, tenant_name)
        worker.run(poll_interval)

    # Multi-tenant mode
    api_keys_str = os.environ.get("API_KEYS")
    if api_keys_str:
        api_keys = [k.strip() for k in api_keys_str.split(",")]
        tenant_names_str = os.environ.get("TENANT_NAMES", "")
        tenant_names = (
            [n.strip() for n in tenant_names_str.split(",")] if tenant_names_str else []
        )

        # Pad tenant names if not enough provided
        while len(tenant_names) < len(api_keys):
            tenant_names.append(f"tenant-{len(tenant_names) + 1}")

        poll_interval = int(os.environ.get("POLL_INTERVAL", "5"))

        print("Starting workers for multiple tenants...")
        print()

        import threading

        workers = []
        for api_key, tenant_name in zip(api_keys, tenant_names):
            worker = MockWorker(api_url, api_key, tenant_name)
            thread = threading.Thread(target=worker.run, args=(poll_interval,))
            thread.daemon = True
            thread.start()
            workers.append(thread)

        # Wait for all threads
        try:
            for thread in workers:
                thread.join()
        except KeyboardInterrupt:
            print("\nStopping all workers...")
            sys.exit(0)

    print("Error: Either API_KEY or API_KEYS must be set")
    sys.exit(1)


if __name__ == "__main__":
    main()
