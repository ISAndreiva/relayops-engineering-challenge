from fastapi import FastAPI, HTTPException
from psycopg.types.json import Jsonb

from .db import get_conn
from .models import EventIn

app = FastAPI(title="RelayOps API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/events", status_code=202)
def create_event(event: EventIn):
    # TODO: idempotency
    conn = get_conn()
    row = conn.execute(
        """
        INSERT INTO events (event_id, type, payload)
        VALUES (%s, %s, %s)
        RETURNING event_id, status
        """,
        (event.event_id, event.type, Jsonb(event.payload)),
    ).fetchone()
    conn.commit()
    return row


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

    # TODO: include delivery attempt history
    row["delivery_attempts"] = []
    return row
