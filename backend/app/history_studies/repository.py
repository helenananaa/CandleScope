"""Durable, bounded study inputs and annotations, independent of market caches.

A saved input is an explicit user capture, not a claim that mutable public
history can be read at an old storage revision. Cursor writes never edit it.
SQLite transactions also fence independent windows/processes with revisions.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from app.data_engine.interval_policy import parse_interval_spec
from app.trading_accounts.models import TradingAccountError, normalize_fields


class StudyConflict(ValueError):
    pass


class HistoryStudyRepository:
    def __init__(self, path: Path, *, clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: int(time.time() * 1000))

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS studies (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    created_ms INTEGER NOT NULL, input_json TEXT NOT NULL, cursor_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS views (
                    owner TEXT PRIMARY KEY, study_id TEXT REFERENCES studies(id),
                    revision INTEGER NOT NULL, cursor_ms INTEGER, active INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES studies(id),
                    market_ms INTEGER NOT NULL, created_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS note_revisions (
                    note_id TEXT NOT NULL REFERENCES notes(id), revision INTEGER NOT NULL,
                    saved_ms INTEGER NOT NULL, fields_json TEXT NOT NULL,
                    PRIMARY KEY(note_id, revision)
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @staticmethod
    def _view(db, owner):
        view = db.execute("SELECT * FROM views WHERE owner=?", (owner,)).fetchone()
        if view is None:
            return {"revision": 0, "active": False, "cursorMs": None, "study": None}
        if view["study_id"] is None:
            return {"revision": view["revision"], "active": False, "cursorMs": None, "study": None}
        study = db.execute("SELECT * FROM studies WHERE id=?", (view["study_id"],)).fetchone()
        return {"revision": view["revision"], "active": bool(view["active"]),
                "cursorMs": view["cursor_ms"], "study": {"id": study["id"],
                "capturedAtMs": study["created_ms"], **json.loads(study["input_json"])}}

    def view(self, owner):
        with self.transaction() as db:
            return self._view(db, owner)

    @staticmethod
    def _expect(db, owner, revision, study_id=None):
        current = HistoryStudyRepository._view(db, owner)
        if current["revision"] != revision or (study_id is not None
                and (not current["study"] or current["study"]["id"] != study_id)):
            raise StudyConflict("Study changed in another window; reload before saving")
        return current

    @staticmethod
    def _cursor(study, cursor):
        rows = study["rows"]
        if type(cursor) is not int or not rows[0]["time"] * 1000 <= cursor <= rows[-1]["closeTimeMs"]:
            raise ValueError("Cursor is outside the saved study input")

    def capture(self, owner, study_id, series, rows, *, cursor_ms, expected_revision):
        spec = parse_interval_spec(series["interval"])
        if spec is None or not 1 <= len(rows) <= 5000:
            raise ValueError("Unsupported study interval or input size")
        now, previous, captured = self.clock(), -1, []
        for bar in rows:
            opened = bar["time"] * 1000
            closed = spec.next_ms(opened)
            if (opened <= previous or spec.floor_ms(opened) != opened or closed > now
                    or not bar["low"] <= min(bar["open"], bar["close"])
                    or not bar["high"] >= max(bar["open"], bar["close"])
                    or bar["low"] > bar["high"] or bar["volume"] < 0):
                raise ValueError("Study input must be ordered, valid closed candles")
            previous = opened
            captured.append({**bar, "closeTimeMs": closed, "is_closed": True})
        data = {"series": series, "rows": captured, "inputKind": "captured-market-history"}
        self._cursor(data, cursor_ms)
        encoded = json.dumps(data, allow_nan=False, separators=(",", ":"), sort_keys=True)
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM studies WHERE id=?", (study_id,)).fetchone()
            if existing is not None:
                current = self._view(db, owner)
                if existing["owner"] != owner or existing["input_json"] != encoded or not current["study"] or current["study"]["id"] != study_id:
                    raise StudyConflict("Study capture identifier is already in use")
                return current  # uncertain-response retry never resets a newer cursor
            self._expect(db, owner, expected_revision)
            if db.execute("SELECT COUNT(*) FROM studies").fetchone()[0] >= 128:
                raise ValueError("Study library is full; remove a saved study before capturing another")
            db.execute("INSERT INTO studies VALUES(?,?,?,?,?)", (study_id, owner, now, encoded, cursor_ms))
            db.execute("INSERT INTO views VALUES(?,?,?,?,1) ON CONFLICT(owner) DO UPDATE SET "
                       "study_id=excluded.study_id,revision=excluded.revision,cursor_ms=excluded.cursor_ms,active=1",
                       (owner, study_id, expected_revision + 1, cursor_ms))
            return self._view(db, owner)

    def move(self, owner, study_id, *, expected_revision, cursor_ms, active):
        with self.transaction() as db:
            current = self._expect(db, owner, expected_revision, study_id)
            self._cursor(current["study"], cursor_ms)
            db.execute("UPDATE views SET revision=revision+1,cursor_ms=?,active=? WHERE owner=?",
                       (cursor_ms, int(active), owner))
            db.execute("UPDATE studies SET cursor_ms=? WHERE id=?", (cursor_ms, study_id))
            return self._view(db, owner)

    def saved(self, owner):
        with self.transaction() as db:
            out = []
            for row in db.execute("SELECT * FROM studies WHERE owner=? ORDER BY created_ms DESC,id", (owner,)):
                data = json.loads(row["input_json"])
                out.append({"id": row["id"], "series": data["series"], "capturedAtMs": row["created_ms"],
                            "cursorMs": row["cursor_ms"], "firstMs": data["rows"][0]["time"] * 1000,
                            "lastMs": data["rows"][-1]["closeTimeMs"]})
            return out

    def activate(self, owner, study_id, *, expected_revision):
        with self.transaction() as db:
            self._expect(db, owner, expected_revision)
            study = db.execute("SELECT * FROM studies WHERE owner=? AND id=?", (owner, study_id)).fetchone()
            if study is None:
                raise ValueError("Saved study does not belong to this chart")
            db.execute("UPDATE views SET study_id=?,cursor_ms=?,active=1,revision=revision+1 WHERE owner=?",
                       (study_id, study["cursor_ms"], owner))
            return self._view(db, owner)

    def remove(self, owner, study_id, *, expected_revision):
        with self.transaction() as db:
            current = self._expect(db, owner, expected_revision)
            if db.execute("SELECT id FROM studies WHERE id=? AND owner=?", (study_id, owner)).fetchone() is None:
                raise ValueError("Saved study does not belong to this chart")
            db.execute("DELETE FROM note_revisions WHERE note_id IN (SELECT id FROM notes WHERE study_id=?)", (study_id,))
            db.execute("DELETE FROM notes WHERE study_id=?", (study_id,))
            if current["study"] and current["study"]["id"] == study_id:
                db.execute("UPDATE views SET study_id=NULL,cursor_ms=NULL,active=0,revision=revision+1 WHERE owner=?", (owner,))
            else:
                db.execute("UPDATE views SET revision=revision+1 WHERE owner=?", (owner,))
            db.execute("DELETE FROM studies WHERE id=?", (study_id,))
            return self._view(db, owner)

    @staticmethod
    def _note(db, note_id):
        note = db.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        revisions = db.execute("SELECT * FROM note_revisions WHERE note_id=? ORDER BY revision", (note_id,)).fetchall()
        last = revisions[-1]
        return {"id": note_id, "fields": json.loads(last["fields_json"]),
                "revisionCount": last["revision"], "marketTimeMs": note["market_ms"],
                "createdAtMs": note["created_ms"], "updatedAtMs": last["saved_ms"], "reviewNote": True,
                "revisions": [{"revision": row["revision"], "savedAtMs": row["saved_ms"],
                               "fields": json.loads(row["fields_json"])} for row in revisions]}

    def notes(self, study_id, cursor_ms):
        with self.transaction() as db:
            study = db.execute("SELECT input_json FROM studies WHERE id=?", (study_id,)).fetchone()
            if study is None:
                raise ValueError("Study does not exist")
            self._cursor(json.loads(study[0]), cursor_ms)
            return [self._note(db, row[0]) for row in db.execute(
                "SELECT id FROM notes WHERE study_id=? AND market_ms<=? ORDER BY market_ms,created_ms,id",
                (study_id, cursor_ms)).fetchall()]

    def save_note(self, study_id, note_id, fields, *, market_ms, expected_revision):
        try:
            fields = normalize_fields(fields)
        except TradingAccountError as exc:
            raise ValueError(str(exc)) from None
        with self.transaction() as db:
            study = db.execute("SELECT input_json FROM studies WHERE id=?", (study_id,)).fetchone()
            if study is None:
                raise ValueError("Study does not exist")
            self._cursor(json.loads(study[0]), market_ms)
            note = db.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
            if note is not None:
                if note["study_id"] != study_id or note["market_ms"] != market_ms:
                    raise StudyConflict("Annotation belongs to another study or market time")
                current = self._note(db, note_id)
                # An exact uncertain-response retry is safe, even after a later save.
                saved = db.execute("SELECT fields_json FROM note_revisions WHERE note_id=? AND revision=?",
                                   (note_id, expected_revision + 1)).fetchone()
                if saved is not None and json.loads(saved[0]) == fields:
                    return current
                if current["revisionCount"] != expected_revision:
                    raise StudyConflict("Annotation changed in another editor")
            elif expected_revision != 0:
                raise StudyConflict("Annotation no longer exists")
            elif db.execute("SELECT COUNT(*) FROM notes WHERE study_id=?", (study_id,)).fetchone()[0] >= 500:
                raise ValueError("This study has reached the annotation limit")
            else:
                db.execute("INSERT INTO notes VALUES(?,?,?,?)", (note_id, study_id, market_ms, self.clock()))
            if expected_revision >= 100:
                raise ValueError("This annotation has reached the version limit")
            db.execute("INSERT INTO note_revisions VALUES(?,?,?,?)", (note_id, expected_revision + 1,
                       self.clock(), json.dumps(fields, allow_nan=False, sort_keys=True)))
            return self._note(db, note_id)
