"""Private connection journal; no account, fill or report tables."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS external_provider_usage (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    logical_bytes INTEGER NOT NULL CHECK (logical_bytes >= 0)
);
INSERT OR IGNORE INTO external_provider_usage VALUES (1, 0);
CREATE TABLE IF NOT EXISTS external_provider_sessions (
    run_id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES external_provider_connections(connection_id),
    host_generation INTEGER NOT NULL,
    context_json TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    last_completed INTEGER NOT NULL DEFAULT 0,
    state_hash TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
);
CREATE TABLE IF NOT EXISTS external_provider_calls (
    run_id TEXT NOT NULL REFERENCES external_provider_sessions(run_id),
    cursor INTEGER NOT NULL,
    call_id TEXT NOT NULL UNIQUE,
    operation TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    state_before_hash TEXT,
    reply_json TEXT,
    reply_hash TEXT,
    state_after_hash TEXT,
    created_ms INTEGER NOT NULL,
    PRIMARY KEY (run_id, cursor)
);
CREATE INDEX IF NOT EXISTS external_provider_pending
    ON external_provider_calls(created_ms) WHERE reply_json IS NULL;
CREATE TABLE IF NOT EXISTS external_provider_states (
    run_id TEXT NOT NULL REFERENCES external_provider_sessions(run_id),
    state_hash TEXT NOT NULL,
    state_json TEXT NOT NULL,
    logical_bytes INTEGER NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, state_hash)
);
"""
