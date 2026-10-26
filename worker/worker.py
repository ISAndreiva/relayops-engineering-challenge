"""RelayOps delivery worker.

Polls the events table and delivers pending events to the configured
webhook receiver. Every request is signed with HMAC-SHA256.
"""
import hashlib
import hmac
import json
import os
import time

import httpx
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://relayops:relayops@db:5432/relayops"
)
RECEIVER_URL = os.environ.get("RECEIVER_URL", "http://receiver:9000/webhook")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "10"))
MAX_ATTEMPTS = 3


def sign(body: dict) -> str:
    raw = json.dumps(body).encode()
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()


def fetch_pending(conn):
    return conn.execute(
        """
        SELECT id, event_id, type, payload
        FROM events
        WHERE status = 'pending'
        ORDER BY id
        LIMIT %s
        """,
        (BATCH_SIZE,),
    ).fetchall()


def deliver(client, event) -> int:
    """Returns the number of attempts used, or 0 if delivery failed."""
    body = {
        "event_id": event["event_id"],
        "type": event["type"],
        "payload": event["payload"],
    }
    headers = {"X-RelayOps-Signature": sign(body)}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.post(RECEIVER_URL, json=body, headers=headers)
            print(f"delivered {event['event_id']} attempt={attempt} -> {resp.status_code}")
            return attempt
        except httpx.HTTPError as exc:
            print(f"error delivering {event['event_id']} attempt={attempt}: {exc}")
            time.sleep(2 ** attempt)
    return 0


def main():
    print(f"worker started, receiver={RECEIVER_URL}")
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
    with httpx.Client(timeout=5) as client:
        while True:
            events = fetch_pending(conn)
            for event in events:
                attempts = deliver(client, event)
                conn.execute(
                    "UPDATE events SET status = %s, attempts = %s, updated_at = now() WHERE id = %s",
                    ("delivered" if attempts else "failed", attempts or MAX_ATTEMPTS, event["id"]),
                )
            if not events:
                time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
