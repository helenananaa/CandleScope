"""Bounded observation journals for deterministic varip reconstruction.

Each session keeps one header row and an append-only operation log, so a
commit writes only the operations observed since the previous commit. The
budget row is updated in the same transaction as the rows it counts.
"""
import json
import sqlite3
from pathlib import Path

FULL = "PINE_SESSION_JOURNAL_FULL: close unused sessions or increase the journal budget; live state was not silently discarded"


def encode(value, **options):
    return json.dumps(value, separators=(",", ":"), allow_nan=False, **options)


class SessionJournal:
    def __init__(self, path=None, *, max_sessions=512, max_bytes=256 * 1024 * 1024):
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path else ":memory:")
        with self.db:
            # Schema 1 stored a whole transcript per row; it is read and then
            # migrated by that session's next commit.
            self.db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS journal_sessions (id TEXT PRIMARY KEY, header TEXT NOT NULL, "
                            "state TEXT NOT NULL, seq INTEGER NOT NULL, bytes INTEGER NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS journal_operations (session_id TEXT NOT NULL, seq INTEGER NOT NULL, "
                            "op TEXT NOT NULL, PRIMARY KEY (session_id, seq)) WITHOUT ROWID")
            self.db.execute("CREATE TABLE IF NOT EXISTS journal_budget (id INTEGER PRIMARY KEY CHECK (id = 0), "
                            "sessions INTEGER NOT NULL, bytes INTEGER NOT NULL)")
            self.db.execute("INSERT OR REPLACE INTO journal_budget VALUES (0, "
                            "(SELECT COUNT(*) FROM journal_sessions) + (SELECT COUNT(*) FROM sessions), "
                            "(SELECT COALESCE(SUM(bytes), 0) FROM journal_sessions) + "
                            "(SELECT COALESCE(SUM(length(CAST(body AS BLOB))), 0) FROM sessions))")
        self.max_sessions, self.max_bytes = max_sessions, max_bytes

    def read(self, key):
        row = self.db.execute("SELECT header, state, seq FROM journal_sessions WHERE id=?", (key,)).fetchone()
        if row is None:
            legacy = self.db.execute("SELECT body FROM sessions WHERE id=?", (key,)).fetchone()
            return json.loads(legacy[0]) if legacy else None
        operations = [json.loads(op) for (op,) in self.db.execute(
            "SELECT op FROM journal_operations WHERE session_id=? ORDER BY seq", (key,))]
        if len(operations) != row[2]:
            raise ValueError("PINE_SESSION_JOURNAL_INVALID: incomplete observation journal")
        return {"schema": 2, "header": json.loads(row[0]), "state": json.loads(row[1]), "operations": operations}

    def append(self, key, header, state, operations, seq):
        """Append encoded operations after ``seq``; a header starts a new log."""
        added = len(state.encode()) + sum(len(op.encode()) for op in operations)
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            current = self.db.execute("SELECT seq, bytes, length(CAST(state AS BLOB)) FROM journal_sessions WHERE id=?", (key,)).fetchone()
            legacy = self.db.execute("SELECT length(CAST(body AS BLOB)) FROM sessions WHERE id=?", (key,)).fetchone()
            sessions, total = self.db.execute("SELECT sessions, bytes FROM journal_budget WHERE id=0").fetchone()
            released = (current[1] if current else 0) + (legacy[0] if legacy else 0)
            if header is not None:
                size = len(header.encode()) + added
            elif current is None or current[0] != seq:
                raise ValueError("PINE_SESSION_JOURNAL_INVALID: observation journal changed outside this session")
            else:
                size = current[1] - current[2] + added
            if current is None and legacy is None and sessions >= self.max_sessions or total - released + size > self.max_bytes:
                raise ValueError(FULL)
            if header is not None:
                self.db.execute("DELETE FROM journal_operations WHERE session_id=?", (key,))
                self.db.execute("DELETE FROM sessions WHERE id=?", (key,))
                self.db.execute("INSERT OR REPLACE INTO journal_sessions VALUES (?,?,?,?,?)",
                                (key, header, state, seq + len(operations), size))
            else:
                self.db.execute("UPDATE journal_sessions SET state=?, seq=?, bytes=? WHERE id=?",
                                (state, seq + len(operations), size, key))
            self.db.executemany("INSERT INTO journal_operations VALUES (?,?,?)",
                                ((key, seq + index, op) for index, op in enumerate(operations)))
            self.db.execute("UPDATE journal_budget SET sessions=?, bytes=? WHERE id=0",
                            (sessions + (current is None and legacy is None), total - released + size))

    def delete(self, key):
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            current = self.db.execute("SELECT bytes FROM journal_sessions WHERE id=?", (key,)).fetchone()
            legacy = self.db.execute("SELECT length(CAST(body AS BLOB)) FROM sessions WHERE id=?", (key,)).fetchone()
            if current is None and legacy is None:
                return
            self.db.execute("DELETE FROM journal_operations WHERE session_id=?", (key,))
            self.db.execute("DELETE FROM journal_sessions WHERE id=?", (key,))
            self.db.execute("DELETE FROM sessions WHERE id=?", (key,))
            self.db.execute("UPDATE journal_budget SET sessions=sessions-?, bytes=bytes-? WHERE id=0",
                            ((current is not None) + (legacy is not None),
                             (current[0] if current else 0) + (legacy[0] if legacy else 0)))

    def close(self):
        self.db.close()
