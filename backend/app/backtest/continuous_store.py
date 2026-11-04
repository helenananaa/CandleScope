"""Private durable boundary for one continuing strategy/account execution.

The execution host owns input coverage and checkpoint cadence. This store has no
market fetch, strategy evaluator or public API; a checkpoint, its cursor and its
published generation commit together. A view subscription never owns execution.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
from pathlib import Path
import sqlite3
import threading
import time
from collections.abc import Mapping

from app.core.committed_updates import committed_updates_for
from .errors import BacktestError

SCHEMA = 3
PHASES = {"CATCHING_UP", "LIVE", "PAUSED", "REPAIR_REQUIRED", "FAILED", "CANCELLED"}
MAX_DEFINITION_BYTES = 1024 * 1024
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
MAX_RETAINED_CHECKPOINTS = 8
MAX_RUN_CHECKPOINT_BYTES = 128 * 1024 * 1024
SUMMARY_COLUMNS = "id,mode,generation,revision,phase,sequence,event_time_ms,data_revision,checkpoint_revision,error_json,updated_at_ms"


def fail(code, message):
    return BacktestError(code, message)


def _text(value, maximum):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise fail("CONTINUOUS_INPUT_INVALID", "Expected a bounded identity")
    return value


def _counter(value):
    if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
        raise fail("CONTINUOUS_INPUT_INVALID", "Expected a nonnegative safe cursor")
    return value


def _json(value):
    if not isinstance(value, Mapping):
        raise fail("CONTINUOUS_INPUT_INVALID", "Expected an owned checkpoint or definition object")
    try:
        return json.dumps(dict(value),sort_keys=True,separators=(",",":"),default=str,allow_nan=False)
    except (TypeError,ValueError,RecursionError) as error:
        raise fail("CONTINUOUS_INPUT_INVALID","Checkpoint is not finite JSON") from error


def _wire(value, maximum):
    raw=_json(value)
    if len(raw.encode("utf-8")) > maximum:
        raise fail("BUDGET_EXCEEDED", "Continuous strategy storage budget exceeded")
    return raw


@dataclass(frozen=True)
class PreparedCheckpoint:
    """Owned encoded state, prepared before the source's commit fence."""
    raw: bytes
    event_time_ms: int
    data_revision: str
    result_patch: object = None
    result_owner: tuple[str,bool] | None = None


def _checkpoint(value, event_time_ms, data_revision):
    if isinstance(value,PreparedCheckpoint):
        if not isinstance(value.raw,bytes) or len(value.raw)>MAX_CHECKPOINT_BYTES:
            raise fail("BUDGET_EXCEEDED","Continuous strategy storage budget exceeded")
        if value.event_time_ms != event_time_ms or value.data_revision != data_revision:
            raise fail("CONTINUOUS_INPUT_INVALID","Prepared checkpoint identity changed")
        return value
    required = {"engine", "provider", "planner"}
    if not isinstance(value, Mapping) or not required <= set(value) <= required | {"source"} or any(
            not isinstance(value[key], Mapping) for key in value):
        raise fail("CONTINUOUS_INPUT_INVALID", "Checkpoint must contain the account engine, provider and planner")
    if "source" in value:
        from app.data_engine.storage.prefix_watches import PrefixReceipt
        point = PrefixReceipt.from_dict(dict(value["source"]))
        if point.through_ms != event_time_ms or point.incarnation != data_revision:
            raise fail("CONTINUOUS_INPUT_INVALID","Source receipt, financial cursor and data identity must commit together")
    raw=_json(value).encode("utf-8")
    if len(raw)>MAX_CHECKPOINT_BYTES:
        raise fail("BUDGET_EXCEEDED","Continuous strategy storage budget exceeded")
    return PreparedCheckpoint(raw,event_time_ms,data_revision)


def _summary(row):
    if row is None:
        raise fail("CONTINUOUS_RUN_NOT_FOUND", "Unknown continuous strategy run")
    value = {key: row[key] for key in SUMMARY_COLUMNS.split(",")}
    raw_error = value.pop("error_json")
    value["error"] = json.loads(raw_error) if raw_error else None
    return value


class ContinuousStrategyStore:
    def __init__(self, path: Path, *, max_runs=64, max_total_checkpoint_bytes=512 * 1024 * 1024):
        if type(max_runs) is not int or max_runs < 1:
            raise ValueError("max_runs must be positive")
        if type(max_total_checkpoint_bytes) is not int or max_total_checkpoint_bytes < 1:
            raise ValueError("checkpoint storage budget must be positive")
        self.max_total_checkpoint_bytes = max_total_checkpoint_bytes
        self.path, self.max_runs = Path(path), max_runs
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.closed = False
        self.updates = committed_updates_for(self.path, "continuous-strategy")
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            with self._transaction():
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2, SCHEMA):
                    raise fail("CONTINUOUS_SCHEMA_UNSUPPORTED", "Continuous strategy schema is unsupported")
                if version == 0:
                    if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                        raise fail("CONTINUOUS_SCHEMA_UNSUPPORTED", "Unrecognized database must not be overwritten")
                    self.db.execute("""CREATE TABLE runs (
                        id TEXT PRIMARY KEY, definition_json TEXT NOT NULL, mode TEXT NOT NULL,
                        generation INTEGER NOT NULL, revision INTEGER NOT NULL, phase TEXT NOT NULL,
                        sequence INTEGER NOT NULL, event_time_ms INTEGER NOT NULL, data_revision TEXT NOT NULL,
                        checkpoint_revision INTEGER NOT NULL, error_json TEXT, updated_at_ms INTEGER NOT NULL)""")
                    self.db.execute("""CREATE TABLE checkpoints (
                        run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                        revision INTEGER NOT NULL, generation INTEGER NOT NULL, sequence INTEGER NOT NULL,
                        event_time_ms INTEGER NOT NULL, data_revision TEXT NOT NULL, wire TEXT NOT NULL,
                        stored_bytes INTEGER NOT NULL, PRIMARY KEY(run_id,revision))""")
                from .continuous_creation_journal import create_schema, ContinuousCreationJournal
                if version < 2:create_schema(self.db)
                from .continuous_results import create_schema as create_results_schema, ContinuousResults
                if version < 3:create_results_schema(self.db)
                self.db.execute(f"PRAGMA user_version={SCHEMA}")
            self.creations = ContinuousCreationJournal(self)
            self.results = ContinuousResults(self)
        except BaseException:
            self.db.close()
            self.closed = True
            raise

    @contextmanager
    def _transaction(self):
        with self.lock:
            if self.closed:
                raise fail("CONTINUOUS_STORE_CLOSED", "Continuous strategy store is closed")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def _row(self, run_id):
        return self.db.execute(f"SELECT {SUMMARY_COLUMNS} FROM runs WHERE id=?", (run_id,)).fetchone()

    def _expected(self, run_id, generation, revision):
        _counter(generation), _counter(revision)
        row = self._row(run_id)
        _summary(row)
        if row["generation"] != generation or row["revision"] != revision:
            raise fail("CONTINUOUS_COMMIT_CONFLICT", "The continuing execution generation or commit changed")
        return row

    def summary(self, run_id):
        with self.lock:
            if self.closed:
                raise fail("CONTINUOUS_STORE_CLOSED", "Continuous strategy store is closed")
            return _summary(self._row(run_id))

    def load(self, run_id):
        with self.lock:
            if self.closed:
                raise fail("CONTINUOUS_STORE_CLOSED", "Continuous strategy store is closed")
            # One statement obtains state and cursor from one SQLite read
            # snapshot even when another process commits concurrently.
            row = self.db.execute("SELECT r.*,c.wire,c.sequence AS cp_sequence,c.event_time_ms AS cp_time,"
                "c.data_revision AS cp_data_revision FROM runs r LEFT JOIN checkpoints c "
                "ON c.run_id=r.id AND c.revision=r.checkpoint_revision WHERE r.id=?", (run_id,)).fetchone()
            summary = _summary(row)
            if row["wire"] is None or (row["cp_sequence"],row["cp_time"],row["cp_data_revision"]) != (
                    summary["sequence"],summary["event_time_ms"],summary["data_revision"]):
                raise fail("CONTINUOUS_CHECKPOINT_CORRUPT", "Committed state and cursor do not agree")
            try:
                return {"run": summary, "definition": json.loads(row["definition_json"]), "checkpoint": json.loads(row["wire"])}
            except (TypeError, ValueError) as error:
                raise fail("CONTINUOUS_CHECKPOINT_CORRUPT", "Committed state is unavailable") from error

    def describe(self, run_id):
        """Bounded immutable execution definition, without decoding its account."""
        with self.lock:
            if self.closed:
                raise fail("CONTINUOUS_STORE_CLOSED", "Continuous strategy store is closed")
            row = self.db.execute("SELECT "+SUMMARY_COLUMNS+",definition_json FROM runs WHERE id=?",(run_id,)).fetchone()
            return {"run":_summary(row),"definition":json.loads(row["definition_json"])}

    def list_summaries(self):
        with self.lock:
            if self.closed:
                raise fail("CONTINUOUS_STORE_CLOSED", "Continuous strategy store is closed")
            return [_summary(row) for row in self.db.execute("SELECT "+SUMMARY_COLUMNS+" FROM runs ORDER BY id")]

    def restore_candidates(self):
        """One SQLite read for active runs and the committed-before-start window."""
        with self.lock:
            if self.closed:raise fail("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
            columns=",".join("r."+name for name in SUMMARY_COLUMNS.split(","))
            return [_summary(row) for row in self.db.execute("SELECT "+columns+" FROM runs r WHERE "
                "r.phase IN ('CATCHING_UP','LIVE') OR (r.phase='PAUSED' AND r.generation=1 AND r.revision=1 AND "
                "EXISTS(SELECT 1 FROM creation_requests c WHERE c.run_id=r.id AND c.phase='COMMITTED')) ORDER BY r.id")]

    def find_created(self, run_id, *, definition, mode, data_revision, event_time_ms, creation_request=None):
        """Resolve an uncertain create before preparing/executing a provider."""
        _text(run_id,128), _text(data_revision,256), _counter(event_time_ms)
        if mode not in {"HISTORY_LIVE","LIVE_ONLY"}:
            raise fail("CONTINUOUS_INPUT_INVALID","Unsupported continuing strategy mode")
        definition_json = _wire(definition, MAX_DEFINITION_BYTES)
        with self.lock:
            if self.closed:
                raise fail("CONTINUOUS_STORE_CLOSED", "Continuous strategy store is closed")
            if creation_request is not None:
                self.creations.guard_creation(creation_request,run_id=run_id,definition=definition,mode=mode,
                    data_revision=data_revision,event_time_ms=event_time_ms)
            row = self.db.execute("SELECT r.*,c.data_revision AS initial_revision,c.event_time_ms AS initial_time "
                "FROM runs r LEFT JOIN checkpoints c ON c.run_id=r.id AND c.revision=1 WHERE r.id=?", (run_id,)).fetchone()
            if row is None:
                return None
            if row["initial_revision"] is None:
                raise fail("CONTINUOUS_CHECKPOINT_CORRUPT", "Initial execution receipt is unavailable")
            if (row["definition_json"],row["mode"],row["initial_revision"],row["initial_time"]) != (
                    definition_json,mode,data_revision,event_time_ms):
                raise fail("CONTINUOUS_COMMIT_CONFLICT", "Run identity already owns a different creation request")
            return _summary(row)

    def create(self, run_id, *, definition, mode, data_revision, event_time_ms, checkpoint, creation_request=None):
        _text(run_id, 128), _text(data_revision, 256), _counter(event_time_ms)
        if mode not in {"HISTORY_LIVE", "LIVE_ONLY"}:
            raise fail("CONTINUOUS_INPUT_INVALID", "Unsupported continuing strategy mode")
        definition_json = _wire(definition, MAX_DEFINITION_BYTES)
        state = self.prepare_checkpoint(checkpoint,event_time_ms=event_time_ms,data_revision=data_revision,run_id=run_id,initial=True)
        with self._transaction():
            creation_key = None if creation_request is None else self.creations.guard_creation(creation_request,
                run_id=run_id,definition=definition,mode=mode,data_revision=data_revision,event_time_ms=event_time_ms)
            previous = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if previous is not None:
                initial = self.db.execute("SELECT wire,event_time_ms,data_revision FROM checkpoints WHERE run_id=? AND revision=1", (run_id,)).fetchone()
                if initial is None:
                    raise fail("CONTINUOUS_CHECKPOINT_CORRUPT", "Initial execution receipt is unavailable")
                if (previous["definition_json"] != definition_json or previous["mode"] != mode
                        or ((initial["wire"].encode("utf-8") if isinstance(initial["wire"],str) else initial["wire"]), initial["event_time_ms"], initial["data_revision"]) != (state.raw,event_time_ms,data_revision)):
                    raise fail("CONTINUOUS_COMMIT_CONFLICT", "Run identity already owns different code or execution conditions")
                # An uncertain create retry observes its original run, never
                # resets the account/cursor to the newly supplied initial state.
                return _summary(self._row(run_id))
            if self.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]+self.creations._pending_count(exclude=creation_key) >= self.max_runs:
                raise fail("BUDGET_EXCEEDED", "Continuous strategy run capacity reached")
            self.db.execute("INSERT INTO runs VALUES(?,?,?,1,1,'PAUSED',0,?,?,1,NULL,?)",
                            (run_id, definition_json, mode, event_time_ms, data_revision, int(time.time()*1000)))
            self._insert_checkpoint(run_id, 1, 1, 0, event_time_ms, data_revision, state)
            self._enforce_total_budget()
            if creation_key is not None:self.creations._commit_creation(creation_key)
        self.updates.notify(run_id)
        if creation_key is not None:self.updates.notify("creation:"+creation_key)
        return self.summary(run_id)

    def resume(self, run_id, *, generation, revision, retry_failed=False):
        with self._transaction():
            row = self._expected(run_id, generation, revision)
            if row["phase"] not in {"PAUSED", "CATCHING_UP", "LIVE"} and not (retry_failed is True and row["phase"] == "FAILED"):
                raise fail("CONTINUOUS_NOT_READY", "Repair, failure or cancellation requires explicit resolution")
            # Always restore/catch up from the committed cursor; never reuse an
            # old LIVE badge or the frontend close timestamp as evidence.
            self.db.execute("UPDATE runs SET generation=generation+1,revision=revision+1,phase='CATCHING_UP',error_json=NULL,updated_at_ms=? WHERE id=?",
                            (int(time.time()*1000), run_id))
        self.updates.notify(run_id)
        return self.summary(run_id)

    def prepare_checkpoint(self,checkpoint,*,event_time_ms,data_revision,run_id=None,initial=False):
        with self.lock:
            if self.closed:raise fail("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
        state=_checkpoint(checkpoint,event_time_ms,data_revision)
        if run_id is None:return state
        _text(run_id,128)
        if state.result_owner is not None:
            from .continuous_results import ResultPatch
            patch=state.result_patch
            if state.result_owner!=(run_id,initial) or (patch is not None and (
                    not isinstance(patch,ResultPatch) or patch.run_id!=run_id or patch.initial!=initial)):
                raise fail("CONTINUOUS_COMMIT_CONFLICT","Prepared result belongs to another execution or publication")
            return state
        # Recovery state is encoded once; the normal Host supplies the original
        # mapping here before taking its source fence. Compatibility callers
        # supplying only encoded state pay one decode during preparation.
        value=checkpoint if isinstance(checkpoint,Mapping) else json.loads(state.raw)
        patch=self.results.prepare(run_id,value["engine"],initial=initial)
        return replace(state,result_patch=patch,result_owner=(run_id,initial))

    def commit(self, run_id, *, generation, revision, sequence, event_time_ms, data_revision, checkpoint,
               phase="CATCHING_UP", confirm_caught_up=False):
        _counter(sequence), _counter(event_time_ms), _text(data_revision, 256)
        if phase not in {"CATCHING_UP", "LIVE"}:
            raise fail("CONTINUOUS_INPUT_INVALID", "Invalid execution commit phase")
        state = self.prepare_checkpoint(checkpoint,event_time_ms=event_time_ms,data_revision=data_revision,run_id=run_id)
        with self._transaction():
            row = self._expected(run_id, generation, revision)
            if row["phase"] not in {"CATCHING_UP", "LIVE"}:
                raise fail("CONTINUOUS_NOT_READY", "Execution is paused or awaiting repair")
            if data_revision != row["data_revision"]:
                raise fail("CONTINUOUS_REPAIR_REQUIRED", "Processed input revision changed; preserve the committed result")
            reaffirm = (confirm_caught_up is True and phase == "LIVE" and row["phase"] == "CATCHING_UP"
                        and sequence == row["sequence"] and event_time_ms == row["event_time_ms"])
            if (sequence <= row["sequence"] or event_time_ms < row["event_time_ms"]) and not reaffirm:
                raise fail("CONTINUOUS_CURSOR_INVALID", "Commit must advance the same source without going back in time")
            next_revision = revision + 1
            self._insert_checkpoint(run_id, next_revision, generation, sequence, event_time_ms, data_revision, state)
            self.db.execute("UPDATE runs SET revision=?,phase=?,sequence=?,event_time_ms=?,checkpoint_revision=?,updated_at_ms=? WHERE id=?",
                            (next_revision, phase, sequence, event_time_ms, next_revision, int(time.time()*1000), run_id))
            self._retain(run_id, next_revision)
            self._enforce_total_budget()
        self.updates.notify(run_id)
        return self.summary(run_id)

    def defer(self, run_id, *, generation, revision, reason):
        error_json = _wire(reason,4096)
        with self._transaction():
            row = self._expected(run_id,generation,revision)
            if row["phase"] not in {"CATCHING_UP","LIVE"}:
                raise fail("CONTINUOUS_NOT_READY", "Execution cannot defer a stopped or repair-required run")
            self.db.execute("UPDATE runs SET revision=revision+1,phase='CATCHING_UP',error_json=?,updated_at_ms=? WHERE id=?",
                            (error_json,int(time.time()*1000),run_id))
        self.updates.notify(run_id)
        return self.summary(run_id)

    def stop(self, run_id, *, generation, revision, phase="PAUSED", error=None):
        if phase not in {"PAUSED", "REPAIR_REQUIRED", "FAILED", "CANCELLED"}:
            raise fail("CONTINUOUS_INPUT_INVALID", "Invalid stopped phase")
        error_json = None if error is None else _wire(error, 4096)
        if phase in {"REPAIR_REQUIRED", "FAILED"} and error_json is None:
            raise fail("CONTINUOUS_INPUT_INVALID", "A stopped execution requires its visible reason")
        with self._transaction():
            row = self._expected(run_id, generation, revision)
            if (row["phase"] in {"REPAIR_REQUIRED", "FAILED", "CANCELLED"} and phase != row["phase"]
                    and not (phase=="CANCELLED" and row["phase"]!="CANCELLED")):
                raise fail("CONTINUOUS_NOT_READY", "Stopped or repair-required state needs explicit resolution")
            self.db.execute("UPDATE runs SET revision=revision+1,phase=?,error_json=?,updated_at_ms=? WHERE id=?",
                            (phase, error_json, int(time.time()*1000), run_id))
        self.updates.notify(run_id)
        return self.summary(run_id)

    def _insert_checkpoint(self, run_id, revision, generation, sequence, event_time_ms, data_revision, state):
        self.db.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?,?)",
                        (run_id, revision, generation, sequence, event_time_ms, data_revision, state.raw, len(state.raw)))
        self.results.publish(run_id,revision,state.result_patch)

    def _retain(self, run_id, current):
        rows = self.db.execute("SELECT revision,stored_bytes FROM checkpoints WHERE run_id=? ORDER BY revision DESC", (run_id,)).fetchall()
        # Preserve the original create receipt for exact uncertain retries and
        # the latest committed recovery point, then retain bounded recent ones.
        mandatory = {1,current}
        used = sum(row["stored_bytes"] for row in rows if row["revision"] in mandatory)
        kept = len(mandatory)
        for row in rows:
            if row["revision"] in mandatory:
                continue
            if kept < MAX_RETAINED_CHECKPOINTS and used + row["stored_bytes"] <= MAX_RUN_CHECKPOINT_BYTES:
                used += row["stored_bytes"]
                kept += 1
            else:
                self.db.execute("DELETE FROM checkpoints WHERE run_id=? AND revision=?", (run_id, row["revision"]))

    def _enforce_total_budget(self):
        total = self.db.execute("SELECT COALESCE(SUM(stored_bytes),0) FROM checkpoints").fetchone()[0]
        total += self.db.execute("SELECT COALESCE(SUM(stored_bytes),0) FROM result_heads").fetchone()[0]
        if total > self.max_total_checkpoint_bytes:
            raise fail("BUDGET_EXCEEDED", "Continuous checkpoints reached the total disk budget; committed recovery points are retained")

    def close(self):
        with self.lock:
            if not self.closed:
                self.db.close()
                self.closed = True
