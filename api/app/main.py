from fastapi import FastAPI, HTTPException, Response
from psycopg.types.json import Jsonb

from .db import get_conn
from .models import EventIn

app = FastAPI(title="RelayOps API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/events", status_code=202)
def create_event(event: EventIn, response: Response):
    conn = get_conn()
    existing = conn.execute(
        "SELECT type, payload, status FROM events WHERE event_id = %s",
        (event.event_id,),
    ).fetchone()
    if existing is not None:
        if existing["type"] == event.type and existing["payload"] == event.payload:
            response.status_code = 200
            return {"event_id": event.event_id, "status": existing["status"]}
        raise HTTPException(status_code=409, detail="event_id already exists with different content")
    try:
        row = conn.execute(
            """
            INSERT INTO events (event_id, type, payload)
            VALUES (%s, %s, %s)
            RETURNING event_id, status
            """,
            (event.event_id, event.type, Jsonb(event.payload)),).fetchone()
        conn.commit()
        return row
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        winner = conn.execute(
            "SELECT type, payload, status FROM events WHERE event_id = %s",
            (event.event_id,),).fetchone()
        if winner["type"] == event.type and winner["payload"] == event.payload:
            response.status_code = 200
            return {"event_id": event.event_id, "status": winner["status"]}
        raise HTTPException(status_code=409, detail="event_id already exists with different content")


@app.get("/events/{event_id}")
def get_event(event_id: str):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT event_id, type, payload, status, attempts, created_at, updated_at
        FROM events WHERE event_id = %s
        ORDER BY id LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")

    rows = conn.execute(
        """
        SELECT da.attempt, da.status_code, da.error, da.created_at
        FROM delivery_attempts da
        JOIN events e ON e.id = da.event_pk
        WHERE e.event_id = %s
        ORDER BY da.attempt
        """,
        (event_id,),).fetchall()
    row["delivery_attempts"] = [
        {
            "attempt": r["attempt"],
            "status_code": r["status_code"],
            "error": r["error"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return row
