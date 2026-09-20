"""Historical-prefix replay. Checkpoints bind input identity and a committed cursor.

Both native batch and incremental scripts use their historical batch semantics.
Never substitute realtime bar flags, persist a foreign account, or rematch fills.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.data_engine.interval_policy import parse_interval_spec
from .errors import BacktestError


class NativeReplay:
    def __init__(self, native):
        self.native = native
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="native-replay")
        self.jobs = {}
        self.workers = {}
        self.closed = False
        db = native.db
        db.execute("CREATE TABLE IF NOT EXISTS native_replays (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS native_replay_snapshots (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        for key, raw in db.execute("SELECT id,record FROM native_replays").fetchall():
            record = json.loads(raw)
            if record["state"] == "RUNNING":
                record.update(state="INTERRUPTED", revision=record["revision"] + 1)
                self._save(record)
        db.commit()

    def _save(self, record):
        from .native import encoded
        self.native.db.execute("INSERT OR REPLACE INTO native_replays VALUES (?,?)", (record["replay_id"], encoded(record)))
        self.native.db.commit()

    def get(self, key):
        with self.native.lock:
            row = self.native.db.execute("SELECT record FROM native_replays WHERE id=?", (key,)).fetchone()
            if not row:
                raise BacktestError("RUN_NOT_FOUND", "native replay not found")
            return json.loads(row[0])

    def list(self):
        with self.native.lock:
            return [{k: v for k, v in json.loads(row[0]).items() if k != "result"}
                    for row in self.native.db.execute("SELECT record FROM native_replays ORDER BY rowid DESC LIMIT 100")]

    def _input(self, run_id):
        row = self.native.db.execute("SELECT wire FROM native_inputs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise BacktestError("NATIVE_REPLAY_INPUT_MISSING", "rerun this strategy to capture replay inputs")
        return json.loads(row[0])

    def create(self, run_id):
        with self.native.lock:
            if self.closed:
                raise BacktestError("NATIVE_REPLAY_CLOSED", "replay service stopped")
            origin = self.native.get(run_id)
            if origin["execution_mode"] != "NATIVE":
                raise BacktestError("EXTERNAL_UNSUPPORTED", "native replay cannot restore a CandleScope matching account")
            if origin["state"] != "COMPLETED":
                raise BacktestError("NATIVE_REPLAY_NOT_READY", "complete native backtest before replay")
            wire = self._input(run_id)
            record = {"replay_id": "nr_" + uuid.uuid4().hex, "run_id": run_id,
                      "state": "PAUSED", "revision": 0, "cursor": 0, "total": len(wire["bars"]),
                      "method": "HISTORICAL_PREFIX_REBUILD", "input_hash": origin["input_hash"],
                      "runtime_identity": wire["identity"], "result": None, "error": None,
                      "created_at_ms": int(time.time() * 1000), "snapshots": []}
            self._save(record)
            return record

    def _current(self, key, revision):
        record = self.get(key)
        if record["revision"] != revision:
            raise BacktestError("NATIVE_REPLAY_CONFLICT", "replay changed; refresh before retry")
        return record

    def command(self, key, revision, action, target=None):
        with self.native.lock:
            if self.closed:
                raise BacktestError("NATIVE_REPLAY_CLOSED", "replay service stopped")
            record = self.get(key) if action == "pause" else self._current(key, revision)
            if action == "pause":
                if key in self.jobs:
                    self.jobs[key].set()
                record.update(state="PAUSED", revision=record["revision"] + 1)
                self._save(record)
                return record
            if key in self.jobs or len(self.jobs) + len(self.native.cancel_events) >= 2:
                raise BacktestError("RUN_CAPACITY_EXCEEDED", "wait for the active replay operation")
            end = record["total"] if action == "play" else record["cursor"] + 1 if action == "step" else target
            if end is None or not 0 <= end <= record["total"]:
                raise BacktestError("NATIVE_REPLAY_RANGE", "cursor outside frozen history")
            record.update(state="RUNNING", revision=revision + 1, error=None)
            self._save(record)
            cancelled = threading.Event()
            self.jobs[key] = cancelled
            self.pool.submit(self._execute, key, action, end, cancelled)
            return record

    def _prefix(self, wire, config, count):
        clipped = copy.deepcopy(wire)
        clipped["bars"] = clipped["bars"][:count]
        boundary = parse_interval_spec(config["interval"]).next_ms(clipped["bars"][-1]["time"] * 1000)
        for context, ref in zip(clipped["contexts"], config.get("contexts", []), strict=True):
            interval = parse_interval_spec(ref["interval"])
            context["bars"] = [bar for bar in context["bars"] if interval.next_ms(bar["time"] * 1000) <= boundary]
        if clipped.get("magnifier"):
            clipped["magnifier"]["chartBars"] = clipped["magnifier"]["chartBars"][:count]
        return clipped

    def _worker(self, key, plugin, wire, cancelled):
        from .native import invoke
        from .native_session import SessionWorker
        if self.native.runner is not invoke or wire["identity"].get("historical_session") != "fixed-history/1":
            return None
        with self.native.lock:
            if key in self.workers:
                return self.workers[key]
            while len(self.workers) >= 2:
                idle = next((other for other in self.workers if other not in self.jobs), None)
                if idle is None:
                    raise BacktestError("RUN_CAPACITY_EXCEEDED", "all historical workers are active")
                evicted = self.workers.pop(idle)
                if evicted is not None:
                    evicted.close()
            self.workers[key] = None  # Reserve a slot before launching outside the lock.
        worker = SessionWorker(plugin, wire, cancelled)
        if not worker.supported:
            worker.close()
            worker = None
        with self.native.lock:
            self.workers[key] = worker
        return worker

    def _execute(self, key, action, target, cancelled):
        from .native import digest
        try:
            with self.native.lock:
                current = self.get(key)
                origin = self.native.get(current["run_id"])
                wire = self._input(current["run_id"])
            if digest(wire) != current["input_hash"]:
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "replay input changed")
            plugin = origin.get("runtime_launch") or self.native.resolver(origin["config"]["language"])
            if self.native.runner(plugin, {"operation": "describe"}, cancelled=cancelled, timeout=15)["identity"] != wire["identity"]:
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "reinstall the frozen runtime before continuing")
            worker = self._worker(key, plugin, wire, cancelled)
            method = "FIXED_HORIZON_INCREMENTAL" if worker else "HISTORICAL_PREFIX_REBUILD"
            counts = range(current["cursor"] + 1, target + 1) if action == "play" else [target]
            for count in counts:
                if cancelled.is_set():
                    return
                if count == 0:
                    result = None
                else:
                    prefix = self._prefix(wire, origin["config"], count)
                    result = worker.advance(count, cancelled) if worker else self.native.runner(plugin, prefix, cancelled=cancelled)
                    if result.get("identity") != wire["identity"] or result.get("account_authority") != origin["result"]["account_authority"] or result.get("execution_mode") != "NATIVE":
                        raise BacktestError("NATIVE_IDENTITY_MISMATCH", "unexpected replay account authority")
                    result["bars"] = prefix["bars"]
                    result["report_hash"] = digest(result)
                    if count == current["total"] and result["report_hash"] != origin["result"]["report_hash"]:
                        raise BacktestError("NATIVE_REPLAY_PARITY_FAILED", "replay endpoint differs from frozen batch result")
                with self.native.lock:
                    if cancelled.is_set():
                        return
                    record = self.get(key)
                    record.update(cursor=count, result=result, method=method, revision=record["revision"] + 1,
                                  state="COMPLETED" if count == record["total"] else "RUNNING" if action == "play" else "PAUSED")
                    self._save(record)
                if action == "play" and cancelled.wait(0.1):
                    return
            with self.native.lock:
                if not cancelled.is_set():
                    record = self.get(key)
                    record.update(state="COMPLETED" if record["cursor"] == record["total"] else "PAUSED")
                    self._save(record)
        except Exception as exc:
            with self.native.lock:
                failed_worker = self.workers.pop(key, None)
                if failed_worker:
                    failed_worker.close()
                if not cancelled.is_set():
                    record = self.get(key)
                    record.update(state="FAILED", revision=record["revision"] + 1,
                                  error={"message": str(exc), "details": getattr(exc, "details", {})})
                    self._save(record)
        finally:
            with self.native.lock:
                if cancelled.is_set():
                    stopped_worker = self.workers.pop(key, None)
                    if stopped_worker:
                        stopped_worker.close()
                self.jobs.pop(key, None)

    def snapshot(self, key, revision):
        from .native import digest, encoded
        with self.native.lock:
            record = self._current(key, revision)
            if key in self.jobs or record["state"] == "RUNNING":
                raise BacktestError("NATIVE_REPLAY_BUSY", "pause before saving a checkpoint")
            checkpoint_id = "nrs_" + uuid.uuid4().hex
            checkpoint = {"replay_id": key, "input_hash": record["input_hash"], "cursor": record["cursor"], "result": record["result"]}
            checkpoint["checksum"] = digest(checkpoint)
            self.native.db.execute("INSERT INTO native_replay_snapshots VALUES (?,?)", (checkpoint_id, encoded(checkpoint)))
            record["snapshots"].append({"snapshot_id": checkpoint_id, "cursor": record["cursor"]})
            record["revision"] += 1
            self._save(record)
            return record

    def restore(self, key, revision, checkpoint_id):
        from .native import digest
        with self.native.lock:
            record = self._current(key, revision)
            if key in self.jobs:
                raise BacktestError("NATIVE_REPLAY_BUSY", "pause before restoring a checkpoint")
            row = self.native.db.execute("SELECT record FROM native_replay_snapshots WHERE id=?", (checkpoint_id,)).fetchone()
            if not row:
                raise BacktestError("RUN_NOT_FOUND", "checkpoint not found")
            checkpoint = json.loads(row[0])
            checksum = checkpoint.pop("checksum")
            if digest(checkpoint) != checksum or checkpoint["replay_id"] != key or checkpoint["input_hash"] != record["input_hash"]:
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "checkpoint does not belong to this replay")
            record.update(cursor=checkpoint["cursor"], result=checkpoint["result"], state="PAUSED", error=None, revision=revision + 1)
            self._save(record)
            return record

    def shutdown(self):
        with self.native.lock:
            self.closed = True
            for key, event in self.jobs.items():
                event.set()
                record = self.get(key)
                record.update(state="INTERRUPTED", revision=record["revision"] + 1)
                self._save(record)
        self.pool.shutdown(wait=True)
        for worker in self.workers.values():
            if worker:
                worker.close()
        self.workers.clear()
