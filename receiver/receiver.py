"""Mock webhook receiver.

Simulates a downstream service. It is part of the test harness: do not change
its contract.

Every request must carry  X-RelayOps-Signature: sha256=<hex>  where <hex> is
HMAC-SHA256(WEBHOOK_SECRET, raw request body). Requests with a missing or
invalid signature are answered with 401.

Behaviour can be changed at runtime through POST /control:

  {
    "fail_next": 2,        # the next N signed requests fail ...
    "status_code": 503,    # ... with this status code
    "retry_after": 0,      # if > 0, failures carry a Retry-After header (seconds)
    "delay_ms": 0,         # delay before answering ...
    "delay_next": 0        # ... for the next N requests only (0 = all requests)
  }

  POST   /webhook   receive an event
  GET    /received  every request received, in arrival order
  DELETE /received  clear the list and reset the control state
  POST   /control   change behaviour (see above)
  GET    /health
"""
import asyncio
import hashlib
import hmac
import os
import threading
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"].encode()

app = FastAPI(title="RelayOps mock receiver")

_lock = threading.Lock()
_received: list[dict[str, Any]] = []


class Control(BaseModel):
    fail_next: int = 0
    status_code: int = 503
    retry_after: int = 0
    delay_ms: int = 0
    delay_next: int = 0


_state = Control()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/control")
def control(c: Control):
    global _state
    with _lock:
        _state = c
    return _state


@app.get("/received")
def received():
    with _lock:
        return list(_received)


@app.delete("/received")
def reset():
    global _state
    with _lock:
        _received.clear()
        _state = Control()
    return {"status": "reset"}


def _valid_signature(raw: bytes, header: str | None) -> bool:
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET, raw, hashlib.sha256).hexdigest()
    return header is not None and hmac.compare_digest(expected, header)


@app.post("/webhook")
async def webhook(request: Request):
    raw = await request.body()
    signature_valid = _valid_signature(raw, request.headers.get("x-relayops-signature"))
    arrived_at = time.time()

    with _lock:
        delay_ms = _state.delay_ms
        if delay_ms and _state.delay_next > 0:
            _state.delay_next -= 1
            if _state.delay_next == 0:
                _state.delay_ms = 0
        status_code, headers = 200, {}
        if not signature_valid:
            status_code = 401
        elif _state.fail_next > 0:
            _state.fail_next -= 1
            status_code = _state.status_code
            if _state.retry_after:
                headers["Retry-After"] = str(_state.retry_after)

    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)

    try:
        body = await request.json()
    except ValueError:
        body = None

    with _lock:
        _received.append(
            {
                "event_id": body.get("event_id") if isinstance(body, dict) else None,
                "body": body,
                "signature_valid": signature_valid,
                "status_code": status_code,
                "arrived_at": arrived_at,
                "answered_at": time.time(),
            }
        )
    return JSONResponse(status_code=status_code, content={"accepted": status_code < 300}, headers=headers)
