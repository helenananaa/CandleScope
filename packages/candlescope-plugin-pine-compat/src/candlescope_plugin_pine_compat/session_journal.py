"""Bounded observation journals for deterministic varip reconstruction."""
import json
import sqlite3
from pathlib import Path


class SessionJournal:
    def __init__(self, path=None, *, max_sessions=512, max_bytes=256 * 1024 * 1024):
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path else ":memory:")
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.max_sessions, self.max_bytes = max_sessions, max_bytes

    def read(self, key):
        row = self.db.execute("SELECT body FROM sessions WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def write(self, key, value):
        body = json.dumps(value, separators=(",", ":"), allow_nan=False)
        count, size = self.db.execute("SELECT COUNT(*), COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM sessions WHERE id<>?", (key,)).fetchone()
        if count >= self.max_sessions or size + len(body.encode()) > self.max_bytes:
            raise ValueError("PINE_SESSION_JOURNAL_FULL: close unused sessions or increase the journal budget; live state was not silently discarded")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (key, body))

    def delete(self, key):
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE id=?", (key,))

    def close(self):
        self.db.close()
