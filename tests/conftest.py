import os
import sys
import time
from pathlib import Path
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

BASE_URL = os.environ.get("RELAYOPS_BASE_URL", "http://localhost:8080")
RECEIVER_URL = os.environ.get("RELAYOPS_RECEIVER_URL", "http://localhost:9000")


@pytest.fixture
def api():
    try:
        httpx.get(f"{BASE_URL}/health", timeout=2).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"stack not reachable at {BASE_URL}: {exc}")
    with httpx.Client(base_url=BASE_URL, timeout=5) as client:
        yield client

def _queue_drained(client) -> bool:
    text = client.get("/metrics").text
    pending = processing = 0
    for line in text.splitlines():
        if line.startswith('relayops_events{status="pending"}'):
            pending = int(line.rsplit(" ", 1)[1])
        elif line.startswith('relayops_events{status="processing"}'):
            processing = int(line.rsplit(" ", 1)[1])
    processing = int(line.rsplit(" ", 1)[1])

@pytest.fixture
def receiver(api):
    with httpx.Client(base_url=RECEIVER_URL, timeout=5) as client:
        client.delete("/received")
        deadline = time.time() + 30
        while not _queue_drained(api) and time.time() < deadline:
            time.sleep(0.5)
        yield client
