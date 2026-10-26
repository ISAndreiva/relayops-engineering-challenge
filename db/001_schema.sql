-- RelayOps schema (applied by the postgres image on first start)

CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    event_id    TEXT        NOT NULL,
    type        TEXT        NOT NULL,
    payload     JSONB       NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',
    attempts    INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS events_status_idx ON events (status);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    id           BIGSERIAL PRIMARY KEY,
    event_pk     BIGINT      NOT NULL REFERENCES events (id),
    attempt      INTEGER     NOT NULL,
    status_code  INTEGER,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
