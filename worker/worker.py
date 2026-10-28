"""RelayOps delivery worker.

Polls the events table and delivers pending events to the configured
webhook receiver. Every request is signed with HMAC-SHA256.
"""
import hashlib
import hmac
import json
import os
import time
import signal
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

_stop = False
def _handle_sigterm(signum, frame):
    global _stop
    _stop = True
    print(f"received signal {signum}, finishing current delivery and stopping", flush=True)

signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


def sign(raw: bytes) -> str:
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


def deliver(client, event):
    """Returns (attempts_used, delivered).
    2xx -> delivered.
    429 / 5xx -> retried
    other -> permanent failure, no retry.
    """
    body = {
        "event_id": event["event_id"],
        "type": event["type"],
        "payload": event["payload"],
    }
    raw = json.dumps(body).encode()
    headers = {"X-RelayOps-Signature": sign(raw),
               "Content-Type": "application/json"}
    attempts_used = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts_used = attempt
        temp = False
        try:
            resp = client.post(RECEIVER_URL, content=raw, headers=headers)
            code = resp.status_code
            print(f"delivered {event['event_id']} attempt={attempt} -> {code}")
            if code < 300:
                return attempts_used, True
            temp = code == 429 or 500 <= code < 600
        except httpx.HTTPError as exc:
            temp = True
            print(f"{event['event_id']} attempt={attempt}: {exc}")
        if not temp:
            break
        if attempt < MAX_ATTEMPTS:
            delay = float(2**attempt)
            if resp is not None:
                try:
                    ra = float(resp.headers.get("Retry-After", ""))
                    delay = max(delay, ra)
                except ValueError:
                    pass
            time.sleep(delay)
    return attempts_used, False

def connect_with_retry():
    delay = 1.0
    while True:
        try:
            return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
        except psycopg.OperationalError as exc:
            print(f"db not ready ({exc}); retrying in {delay:.1f}s")
            time.sleep(delay)
            delay = min(delay * 2, 30.0)

def recover_stale(conn):
    n = conn.execute(
        "UPDATE events SET status = 'pending', updated_at = now() "
        "WHERE status = 'processing' RETURNING id"
    ).fetchall()
    if n:
        print(f"recovered {len(n)} stale 'processing' event(s)", flush=True)


def main():
    global _stop
    print(f"worker started, receiver={RECEIVER_URL}")
    conn = connect_with_retry()
    recover_stale(conn)
    with httpx.Client(timeout=5) as client:
        while not _stop:
            events = fetch_pending(conn)
            for event in events:
                if _stop:
                    break
                claimed = conn.execute("UPDATE events SET status = 'processing', updated_at = now() WHERE id = %s AND status = 'pending' RETURNING id",(event["id"],),).fetchone()
                if claimed is None:
                    continue
                attempts, delivered = deliver(client, event)
                conn.execute(
                    "UPDATE events SET status = %s, attempts = %s, updated_at = now() WHERE id = %s",
                    ("delivered" if delivered else "failed", attempts, event["id"]),
                )
            if not events:
                time.sleep(POLL_INTERVAL)
    conn.close()
    print("worker stopped")


if __name__ == "__main__":
    main()
