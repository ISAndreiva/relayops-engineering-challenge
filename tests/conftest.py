import os
import sys
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


@pytest.fixture
def receiver():
    with httpx.Client(base_url=RECEIVER_URL, timeout=5) as client:
        client.delete("/received")
        yield client
