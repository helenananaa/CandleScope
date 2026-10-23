"""Historical-prefix replay. Checkpoints bind input identity and a committed cursor.

Both native batch and incremental scripts use their historical batch semantics.
Native results retain native authority. External replay checkpoints preserve
the Host matcher, allocation, execution cursor and evaluator feedback transcript.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict

from app.data_engine.interval_policy import parse_interval_spec
from .errors import BacktestError

_KEEP_STATE=object()
# Large seeks can replace the private base after rechecking the prior read's
# validated bytes. Sequential play and small steps retain structural deltas.
PRIVATE_REBASE_MIN_BARS=64


class NativeReplay:
    def __init__(self, native):
        self.native = native
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="native-replay")
        self.jobs = {}
        self.workers = {}
        self.closed = False
        self._inputs = OrderedDict()
        from .native_replay_views import ResultViews
        self.views = ResultViews()
        db = native.db
        db.execute("CREATE TABLE IF NOT EXISTS native_replays (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS native_replay_snapshots (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        from .native_replay_storage import ResultJournal
        self.results = ResultJournal(db)
        for (key,) in db.execute("SELECT id FROM native_replays").fetchall():
            raw = db.execute("SELECT record FROM native_replays WHERE id=?", (key,)).fetchone()[0]
            record = json.loads(raw)
            if "_resultStorage" not in record:
                self._save(record)
            if record["state"] == "RUNNING":
                record.update(state="INTERRUPTED", revision=record["revision"] + 1)
                self._save(self.get(key) | {"state": "INTERRUPTED", "revision": record["revision"]})
        db.commit()

    def _save(self, record, *, external_state=_KEEP_STATE, restoring=False, external_validation=None,
              consume_external_state=False):
        from .native import encoded
        from .native_replay_storage import SCHEMA
        header = {**record, "result": None, "_resultStorage": SCHEMA}
        result = record.get("result")
        body = {k: v for k, v in result.items() if k not in {"bars", "report_hash"}} if result is not None else None
        try:
            with self.native.db:
                if external_state is not _KEEP_STATE:
                    header["_externalStateRevision"]=self.results.save("host:"+record["replay_id"],external_state,
                        **({"compare_base_bytes":True} if restoring else {}),
                        **({"validated_base":external_validation} if external_validation is not None else {}))
                    if consume_external_state and external_state is not None:
                        # A seek owns this detached checkpoint and has no next
                        # step to resume. Once encoded in the transaction, its
                        # graph need not overlap public-result cache creation.
                        # A later failure rolls back the DB and drops the job;
                        # recovery still reads the prior committed checkpoint.
                        external_state.clear()
                else:
                    old=self.native.db.execute("SELECT record FROM native_replays WHERE id=?",(record["replay_id"],)).fetchone()
                    if old and "_externalStateRevision" in (previous:=json.loads(old[0])):
                        header["_externalStateRevision"]=previous["_externalStateRevision"]
                header["_resultRevision"] = self.results.save(record["replay_id"], body)
                self.native.db.execute("INSERT OR REPLACE INTO native_replays VALUES (?,?)", (record["replay_id"], encoded(header)))
            self.views.discard(record["replay_id"])
        except BaseException:
            self.results.cache.clear()
            self.views.discard()
            raise

    def get(self, key, *, if_revision=None, _metadata_only=False):
        with self.native.lock:
            row = self.native.db.execute("SELECT record FROM native_replays WHERE id=?", (key,)).fetchone()
            if not row:
                raise BacktestError("RUN_NOT_FOUND", "native replay not found")
            record = json.loads(row[0])
            record.pop("_externalStateRevision",None)
            storage = record.pop("_resultStorage", None)
            result_revision = record.pop("_resultRevision", None)
            if storage is not None:
                from .native_replay_storage import SCHEMA
                if storage != SCHEMA:
                    raise ValueError("unsupported native replay result storage")
                if type(result_revision) is not int:
                    raise ValueError("native replay result revision is missing")
                if if_revision is not None and if_revision == record["revision"]:
                    self.results.check_revision(key, expected_revision=result_revision)
                    record.pop("result", None)
                    return {**record, "result_unchanged": True}
                # Validate the stored revision even when an encoded view is
                # cached; a cold journal still verifies its checksums first.
                result = self.results.load(key, expected_revision=result_revision)
                if _metadata_only:
                    record["result"] = None
                    return record
                if result is not None:
                    view_key = (key, record["run_id"], record["input_hash"], result_revision, record["cursor"])
                    result = self.views.read(view_key, result,
                        self._input(record["run_id"])["bars"][:record["cursor"]])
                record["result"] = result
            return record

    def list(self):
        with self.native.lock:
            return [{k: v for k, v in json.loads(row[0]).items() if k not in {"result", "_resultStorage", "_resultRevision", "_externalStateRevision"}}
                    for row in self.native.db.execute("SELECT record FROM native_replays ORDER BY rowid DESC LIMIT 100")]

    def _host_state(self,key,*,detached=True,validation=False):
        raw=self.native.db.execute("SELECT record FROM native_replays WHERE id=?",(key,)).fetchone()
        header=json.loads(raw[0])
        revision=header.get("_externalStateRevision")
        receipt=None
        if revision is None:
            state=None
        elif validation:
            state,receipt=self.results.load("host:"+key,expected_revision=revision,validation=True)
        else:
            state=self.results.load("host:"+key,expected_revision=revision)
        if header.get("execution_mode")=="CANDLESCOPE" and ((header["cursor"]==0 and state is not None)
                or (header["cursor"] and (not state or state.get("cursor")!=header["cursor"]))):
            raise BacktestError("NATIVE_IDENTITY_MISMATCH","external account state does not match replay cursor")
        state=copy.deepcopy(state) if detached else state
        return (state,receipt) if validation else state

    def _input(self, run_id):
        if run_id in self._inputs:
            self._inputs.move_to_end(run_id)
            return self._inputs[run_id]
        row = self.native.db.execute("SELECT wire FROM native_inputs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise BacktestError("NATIVE_REPLAY_INPUT_MISSING", "rerun this strategy to capture replay inputs")
        wire = json.loads(row[0])
        self._inputs[run_id] = wire
        while len(self._inputs) > 2:
            self._inputs.popitem(last=False)
        return wire

    def _take_host_state(self,key,*,validation=False):
        # Active jobs exclude same-key snapshot/restore/write operations. The
        # cache's validated JSON value becomes this job's private owned input;
        # default inspection and public snapshots still return detached values.
        state=self._host_state(key,detached=False,validation=validation)
        self.results.cache.pop("host:"+key,None)
        return state

    def create(self, run_id):
        with self.native.lock:
            if self.closed:
                raise BacktestError("NATIVE_REPLAY_CLOSED", "replay service stopped")
            origin = self.native.get(run_id)
            external=origin["execution_mode"]=="CANDLESCOPE"
            if external and origin["config"]["language"]!="pine":
                raise BacktestError("EXTERNAL_UNSUPPORTED","external replay currently requires the Pine feedback contract")
            if origin["state"] != "COMPLETED":
                raise BacktestError("NATIVE_REPLAY_NOT_READY", "complete native backtest before replay")
            wire = self._input(run_id)
            record = {"replay_id": "nr_" + uuid.uuid4().hex, "run_id": run_id,
                      "state": "PAUSED", "revision": 0, "cursor": 0, "total": len(wire["bars"]),
                      "method": "HISTORICAL_PREFIX_REBUILD", "input_hash": origin["input_hash"],
                      "runtime_identity": wire["identity"], "result": None, "error": None,
                      "created_at_ms": int(time.time() * 1000), "snapshots": []}
            if external:
                record.update(execution_mode="CANDLESCOPE",method="HOST_ACCOUNT_CHECKPOINT")
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
        # Detach only the revealed prefix; never copy unrevealed history.
        clipped = {key: copy.deepcopy(value) for key, value in wire.items()
                   if key not in {"bars", "contexts", "magnifier", "execution_times"}}
        clipped["bars"] = copy.deepcopy(wire["bars"][:count])
        if "execution_times" in wire:
            clipped["execution_times"] = list(wire["execution_times"][:count])
        boundary = parse_interval_spec(config["interval"]).next_ms(clipped["bars"][-1]["time"] * 1000)
        clipped["contexts"] = []
        for context, ref in zip(wire["contexts"], config.get("contexts", []), strict=True):
            interval = parse_interval_spec(ref["interval"])
            clipped["contexts"].append({**copy.deepcopy({key: value for key, value in context.items() if key != "bars"}),
                "bars": copy.deepcopy([bar for bar in context["bars"] if interval.next_ms(bar["time"] * 1000) <= boundary])})
        clipped["magnifier"] = ({**copy.deepcopy({key: value for key, value in wire["magnifier"].items() if key != "chartBars"}),
                                "chartBars": copy.deepcopy(wire["magnifier"]["chartBars"][:count])}
                               if wire.get("magnifier") else None)
        return clipped

    def _worker(self, key, plugin, wire, cancelled, *, external=False):
        from .native import invoke
        from .native_session import SessionWorker
        if self.native.runner is not invoke or (not external and wire["identity"].get("historical_session") != "fixed-history/1"):
            return None
        from .external_support import pine_replay_available
        if external and not pine_replay_available(wire["identity"]):
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
        if external and (wire.get("pine_history_tick_contract") or wire.get("pine_print_tick_contract")):
            if wire.get("pine_print_tick_contract"):
                from .pine_print_tick_execution import ReplayWorker
            else:
                from .pine_history_tick_execution import ReplayWorker
            worker=ReplayWorker(plugin,wire)
        else:
            worker = SessionWorker(plugin, wire, cancelled,evaluator=external)
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
                current = self.get(key,_metadata_only=True)
                origin = self.native.get(current["run_id"])
                # Replay needs the original seal/authority and input settings,
                # not a second resident copy of the complete batch report or
                # uploaded physical-event configuration.
                origin["result"] = {name: origin["result"].get(name) for name in ("account_authority", "report_hash")}
                origin["config"] = {name: origin["config"][name] for name in ("language", "interval", "contexts")
                                    if name in origin["config"]}
                wire = self._input(current["run_id"])
                external=origin["execution_mode"]=="CANDLESCOPE"
                external_validation=None
                if external and action=="seek" and abs(target-current["cursor"])>=PRIVATE_REBASE_MIN_BARS:
                    external_state,external_validation=self._take_host_state(key,validation=True)
                else:
                    external_state=self._take_host_state(key) if external else None
            if digest(wire) != current["input_hash"]:
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "replay input changed")
            plugin = origin.get("runtime_launch") or self.native.resolver(origin["config"]["language"])
            if self.native.runner(plugin, {"operation": "describe"}, cancelled=cancelled, timeout=15)["identity"] != wire["identity"]:
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "reinstall the frozen runtime before continuing")
            worker = self._worker(key, plugin, wire, cancelled,external=external)
            method = "HOST_ACCOUNT_CHECKPOINT" if external else "FIXED_HORIZON_INCREMENTAL" if worker else "HISTORICAL_PREFIX_REBUILD"
            if external and target<current["cursor"]:
                external_state=None
            counts = range(current["cursor"] + 1, target + 1) if action == "play" else [target]
            for count in counts:
                if cancelled.is_set():
                    return
                current["result"]=None
                result=None
                if count == 0:
                    result = None
                    external_state=None
                else:
                    if external:
                        from .external import _run_external_host
                        if wire.get("pine_history_tick_contract") or wire.get("pine_print_tick_contract"):
                            if worker:
                                result,external_state=worker.execute(self.native.runner,cancelled,resume=external_state,target=count,
                                    resume_owned=True)
                            else:
                                from .external import run_external_host
                                result,external_state=run_external_host(plugin,wire,self.native.runner,cancelled,
                                    resume=external_state,target=count)
                        else:
                            evaluate=(lambda _plugin,payload,**kwargs:worker.request(payload,**kwargs)) if worker else self.native.runner
                            result,external_state=_run_external_host(plugin,wire,evaluate,cancelled,resume=external_state,target=count,
                                _scenario_runner=self.native.runner)
                    else:
                        result = worker.advance(count, cancelled) if worker else self.native.runner(plugin, self._prefix(wire, origin["config"], count), cancelled=cancelled)
                    if result.get("identity") != wire["identity"] or result.get("account_authority") != origin["result"]["account_authority"] or result.get("execution_mode") != origin["execution_mode"]:
                        raise BacktestError("NATIVE_IDENTITY_MISMATCH", "unexpected replay account authority")
                    if count == current["total"]:
                        result["bars"] = wire["bars"]
                        result["report_hash"] = digest(result)
                        if result["report_hash"] != origin["result"]["report_hash"]:
                            raise BacktestError("NATIVE_REPLAY_PARITY_FAILED", "replay endpoint differs from frozen batch result")
                with self.native.lock:
                    if cancelled.is_set():
                        return
                    record = current
                    record.update(cursor=count, result=result, method=method, revision=record["revision"] + 1,
                                  state="COMPLETED" if count == record["total"] else "RUNNING" if action == "play" else "PAUSED")
                    self._save(record,**({"external_state":external_state,"external_validation":external_validation,
                        "consume_external_state":action=="seek"} if external else {}))
                if action == "play" and cancelled.wait(0.1):
                    return
            with self.native.lock:
                if not cancelled.is_set():
                    record = current
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
        from .native import MAX_BYTES
        from .native_checkpoint import pack, checkpoint_digest
        with self.native.lock:
            record = self._current(key, revision)
            if key in self.jobs or record["state"] == "RUNNING":
                raise BacktestError("NATIVE_REPLAY_BUSY", "pause before saving a checkpoint")
            checkpoint_id = "nrs_" + uuid.uuid4().hex
            checkpoint = {"replay_id": key, "input_hash": record["input_hash"], "cursor": record["cursor"], "result": record["result"]}
            if record.get("execution_mode")=="CANDLESCOPE":
                # Only serialize the borrowed journal value while holding the
                # native lock. It never escapes this call or reaches a mutable
                # execution path; normal callers still receive a detached copy.
                checkpoint["external_state"]=self._host_state(key,detached=False)
            checkpoint["checksum"] = checkpoint_digest(checkpoint)
            stored = pack(checkpoint)
            if len(stored.encode("utf-8")) > MAX_BYTES:
                raise BacktestError("BUDGET_EXCEEDED", "replay checkpoint exceeds 64 MiB")
            self.native.db.execute("INSERT INTO native_replay_snapshots VALUES (?,?)", (checkpoint_id, stored))
            record["snapshots"].append({"snapshot_id": checkpoint_id, "cursor": record["cursor"]})
            record["revision"] += 1
            self._save(record)
            return record

    def restore(self, key, revision, checkpoint_id):
        from .native_checkpoint import unpack, checkpoint_digest
        with self.native.lock:
            record = self._current(key, revision)
            if key in self.jobs:
                raise BacktestError("NATIVE_REPLAY_BUSY", "pause before restoring a checkpoint")
            row = self.native.db.execute("SELECT record FROM native_replay_snapshots WHERE id=?", (checkpoint_id,)).fetchone()
            if not row:
                raise BacktestError("RUN_NOT_FOUND", "checkpoint not found")
            checkpoint = unpack(row[0])
            checksum = checkpoint.pop("checksum")
            if checkpoint_digest(checkpoint) != checksum or checkpoint["replay_id"] != key or checkpoint["input_hash"] != record["input_hash"]:
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "checkpoint does not belong to this replay")
            if record.get("execution_mode")=="CANDLESCOPE" and checkpoint["cursor"]:
                from .external_replay import validate_state
                state=checkpoint.get("external_state")
                if not state or state.get("cursor")!=checkpoint["cursor"]:
                    raise BacktestError("NATIVE_IDENTITY_MISMATCH","checkpoint account cursor differs")
                validate_state(self._input(record["run_id"]),state)
            elif record.get("execution_mode")=="CANDLESCOPE" and checkpoint.get("external_state") is not None:
                raise BacktestError("NATIVE_IDENTITY_MISMATCH","zero cursor must have no external account state")
            record.update(cursor=checkpoint["cursor"], result=checkpoint["result"], state="PAUSED", error=None, revision=revision + 1)
            self._save(record,restoring=True,
                **({"external_state":checkpoint.get("external_state")} if record.get("execution_mode")=="CANDLESCOPE" else {}))
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
        self.results.cache.clear()
        self.views.discard()
        self._inputs.clear()
