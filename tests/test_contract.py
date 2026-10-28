"""Contract tests. Require the stack: docker compose up --build."""
import time
import uuid


def eid():
    return f"evt-{uuid.uuid4()}"


def wait_final_state(api, event_id, seconds=30):
    deadline = time.time() + seconds
    result = None
    while time.time() < deadline:
        result = api.get(f"/events/{event_id}").json()
        if result.get("status") in ("delivered", "failed"):
            return result
        time.sleep(0.5)
    return result


def test_idempotent_replay_returns_200(api):
    body = {"event_id": eid(), "type": "t", "payload": {"x": 1}}
    assert api.post("/events", json=body).status_code == 202
    resp = api.post("/events", json=body)
    assert resp.status_code == 200
    assert resp.json()["event_id"] == body["event_id"]


def test_conflict_returns_409(api):
    event_id = eid()
    api.post("/events", json={"event_id": event_id, "type": "t", "payload": {"x": 1}})
    resp = api.post("/events", json={"event_id": event_id, "type": "t", "payload": {"x": 2}})
    assert resp.status_code == 409


def test_invalid_body_returns_422(api):
    assert api.post("/events", json={"type": "t", "payload": {}}).status_code == 422


def test_retry_then_success(api, receiver):
    event_id = eid()
    receiver.post("/control", json={"fail_next": 2, "status_code": 503})
    api.post("/events", json={"event_id": event_id, "type": "t", "payload": {}})
    result = wait_final_state(api, event_id)
    assert result["status"] == "delivered"
    assert result["attempts"] == 3
    assert [a["status_code"] for a in result["delivery_attempts"]] == [503, 503, 200]


def test_exhaustion_marks_failed(api, receiver):
    event_id = eid()
    receiver.post("/control", json={"fail_next": 5, "status_code": 503})
    api.post("/events", json={"event_id": event_id, "type": "t", "payload": {}})
    result = wait_final_state(api, event_id, seconds=45)
    assert result["status"] == "failed"
    assert result["attempts"] == 3
    assert [a["status_code"] for a in result["delivery_attempts"]] == [503, 503, 503]


def test_permanent_failure_no_retry(api, receiver):
    event_id = eid()
    receiver.post("/control", json={"fail_next": 1, "status_code": 400})
    api.post("/events", json={"event_id": event_id, "type": "t", "payload": {}})
    result = wait_final_state(api, event_id, seconds=15)
    assert result["status"] == "failed"
    assert result["attempts"] == 1
    assert result["delivery_attempts"][0]["status_code"] == 400


def test_timeout_per_attempt_then_success(api, receiver):
    event_id = eid()
    receiver.post("/control", json={"delay_next": 1, "delay_ms": 6000})
    api.post("/events", json={"event_id": event_id, "type": "t", "payload": {}})
    result = wait_final_state(api, event_id, seconds=45)
    assert result["status"] == "delivered"
    assert result["attempts"] == 2
    assert result["delivery_attempts"][0]["status_code"] is None
    assert result["delivery_attempts"][0]["error"]
    assert result["delivery_attempts"][1]["status_code"] == 200


def test_no_double_delivery_burst(api, receiver):
    ids = [eid() for _ in range(5)]
    for i in ids:
        api.post("/events", json={"event_id": i, "type": "t", "payload": {}})
    deadline = time.time() + 30
    seen = []
    while time.time() < deadline:
        seen = [r["event_id"] for r in receiver.get("/received").json()]
        if all(i in seen for i in ids):
            break
        time.sleep(0.5)
    assert all(i in seen for i in ids)
    for i in ids:
        assert seen.count(i) == 1


def test_request_id_generated_and_propagated(api):
    assert api.get("/health").headers.get("X-Request-ID")
    resp = api.get("/health", headers={"X-Request-ID": "test-rid-123"})
    assert resp.headers["X-Request-ID"] == "test-rid-123"


def test_one_mb_payload_accepted(api):
    resp = api.post("/events", json={"event_id": eid(), "type": "t", "payload": {"data": "x" * 1_000_000}})
    assert resp.status_code == 202


def test_metrics_endpoint(api):
    text = api.get("/metrics").text
    assert 'relayops_events{status="delivered"}' in text
    assert "relayops_delivery_attempts_total" in text
