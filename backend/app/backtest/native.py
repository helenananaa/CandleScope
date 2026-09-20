"""Durable native runs with exactly one account authority: the plugin engine.

Separate records and endpoints prevent native fills entering SimulationKernel,
host cost sensitivity, training replay or a shared account ledger accidentally.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core.config import runtime_environment
from app.data_engine.interval_policy import parse_interval_spec
from app.plugin_runtime.registry import default_runtime_registry_path, load_runtime_registry
from .errors import BacktestError

PROTOCOL = "candlescope.native-strategy/1"
MODULES = {"pine": ("candlescope.pine-compat", "candlescope_plugin_pine_compat.native_strategy"),
           "pyne": ("candlescope.pyne", "candlescope_plugin_pyne.native_strategy")}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}
MAX_BYTES = 64 * 1024 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return "sha256:" + hashlib.sha256(encoded(value).encode()).hexdigest()


def timeframe(interval):
    import re
    match = re.fullmatch(r"(\d+)([smhdwM])", interval)
    if match is None:
        raise BacktestError("NATIVE_INPUT_UNSUPPORTED", "unsupported chart interval")
    n, unit = int(match[1]), match[2]
    return str(n * 60) if unit == "h" else str(n) if unit == "m" else f"{n}{unit.upper()}"


def resolve_plugin(language):
    env = runtime_environment()
    if env.get("CANDLESCOPE_PLUGIN_HOST_ENABLED", "1").lower() in {"0", "false", "off"}:
        raise BacktestError("FLAG_DISABLED", "plugin host is disabled")
    default = default_runtime_registry_path(env)
    native_registry = default.with_name("native-strategy-registry.json")
    path = env.get("CANDLESCOPE_NATIVE_RUNTIME_REGISTRY") or env.get("CANDLESCOPE_RUNTIME_REGISTRY")
    registry = load_runtime_registry(path or (native_registry if native_registry.exists() else default), allow_missing=True)
    runtime_id, module = MODULES[language]
    spec = registry.by_id().get(runtime_id)
    if spec is None or not spec.enabled:
        raise BacktestError("NATIVE_RUNTIME_UNAVAILABLE", f"install and enable {runtime_id} with native strategy support")
    return {"command": [str(spec.executable), "-I", "-m", module],
            "plugin_id": runtime_id, "plugin_version": spec.expected_version,
            "installation": spec.managed.to_wire() if spec.managed else None}


def invoke(plugin, payload, cancelled=None, timeout=120):
    """File-backed IPC bounds memory; timeout/cancellation kill and reap the child."""
    raw = encoded(payload).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise BacktestError("BUDGET_EXCEEDED", "native input exceeds 64 MiB")
    with tempfile.TemporaryFile() as inp, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        inp.write(raw)
        inp.seek(0)
        process = subprocess.Popen(plugin["command"], stdin=inp, stdout=out, stderr=err,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancelled is not None and cancelled.is_set():
                    raise BacktestError("NATIVE_CANCELLED", "native execution cancelled")
                if time.monotonic() > deadline:
                    raise BacktestError("NATIVE_TIMEOUT", "native execution exceeded its host deadline")
                if os.fstat(out.fileno()).st_size > MAX_BYTES or os.fstat(err.fileno()).st_size > MAX_BYTES:
                    raise BacktestError("BUDGET_EXCEEDED", "native output exceeds 64 MiB")
                time.sleep(0.05)
            if os.fstat(out.fileno()).st_size > MAX_BYTES:
                raise BacktestError("BUDGET_EXCEEDED", "native output exceeds 64 MiB")
            out.seek(0)
            if process.returncode:
                err.seek(0)
                raise BacktestError("NATIVE_RUNTIME_UNAVAILABLE", err.read(4096).decode("utf-8", errors="replace"))
            try:
                response = json.load(out)
            except (ValueError, UnicodeError) as exc:
                raise BacktestError("NATIVE_PROTOCOL_ERROR", "plugin returned invalid JSON") from exc
            if not isinstance(response, dict) or response.get("ok") is not True:
                raise BacktestError("NATIVE_EXECUTION_FAILED", "native engine rejected the run",
                                    details={"diagnostics": response.get("diagnostics", []) if isinstance(response, dict) else []})
            return response
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


class NativeBacktests:
    def __init__(self, runtime, *, resolver=resolve_plugin, runner=invoke):
        self.runtime, self.resolver, self.runner = runtime, resolver, runner
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="native-backtest")
        self.cancel_events = {}
        self.closed = False
        self.db = sqlite3.connect(runtime.settings.db_path.with_name("native-backtests.db"), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, key TEXT UNIQUE, hash TEXT NOT NULL, record TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS native_inputs (id TEXT PRIMARY KEY, wire TEXT NOT NULL)")
        for run_id, raw in self.db.execute("SELECT id,record FROM runs").fetchall():
            record = json.loads(raw)
            if record["state"] not in TERMINAL:
                record.update(state="INTERRUPTED", error={"code": "HOST_RESTARTED", "message": "host stopped before native completion; rerun explicitly"})
                self.db.execute("UPDATE runs SET record=? WHERE id=?", (encoded(record), run_id))
        self.db.commit()
        from .native_replay import NativeReplay
        self.replay = NativeReplay(self)

    def capabilities(self):
        result = []
        for language in MODULES:
            try:
                plugin = self.resolver(language)
                description = self.runner(plugin, {"operation": "describe"}, timeout=15)
                try:
                    external_plugin = {**plugin, "command": [*plugin["command"][:-1], plugin["command"][-1].replace(".native_strategy", ".external_strategy")]}
                    external = self.runner(external_plugin, {"operation": "describe"}, timeout=15)
                    supported = {"pine": {"pine-external/1", "pine-external/2", "pine-external/3", "pine-external/4", "pine-external/5"},
                                 "pyne": {"pyne-external/1", "pyne-external/2", "pyne-external/3", "pyne-external/4"}}
                    external_available = (external["identity"].get("protocol") == PROTOCOL
                                          and external["identity"].get("adapter") in supported[language])
                except Exception:
                    external_available = False
                result.append({"language": language, "available": True, "identity": description["identity"], "external_available": external_available})
            except Exception as exc:
                result.append({"language": language, "available": False, "reason": str(exc)})
        return {"execution_mode": "NATIVE", "engines": result, "interactive_replay": True,
                "replay_method": "HISTORICAL_PREFIX_REBUILD", "external_matching_feedback": "BAR_CLOSE_ORDERS_V2",
                "input_profile": "frozen-standard-ohlcv", "account_settings": "script-owned"}

    def _freeze(self, value):
        ref = self.runtime._dataset_ref(
            dataset_id=value["dataset_id"], data_epoch=value["data_epoch"],
            snapshot_hash=value["snapshot_hash"], start_time_ms=value["start_time_ms"],
            end_time_ms=value["end_time_ms"], interval=value["interval"],
            exchange=value.get("exchange", "binance"), market_type=value.get("market_type", "usdm"))
        snapshot = self.runtime.snapshots.open(ref)
        try:
            bars = []
            interval = parse_interval_spec(value["interval"])
            for event in snapshot.events:
                if event.role != "BARS":
                    continue
                bar = event.payload
                if int(bar["open_time_ms"]) < value["start_time_ms"] or int(bar["close_time_ms"]) > value["end_time_ms"]:
                    raise BacktestError("DATA_QUALITY_FAILED", "native ranges must contain whole confirmed bars")
                if bars and (interval is None or not interval.is_successor(bars[-1]["time"] * 1000, int(bar["open_time_ms"]))):
                    raise BacktestError("DATA_QUALITY_FAILED", "native snapshot has missing bars")
                bars.append({"time": int(bar["open_time_ms"]) // 1000,
                             **{key: float(bar[key]) for key in ("open", "high", "low", "close", "volume")}})
            if not bars:
                raise BacktestError("DATA_QUALITY_FAILED", "native snapshot contains no bars")
            return bars
        finally:
            snapshot.close()

    def create(self, payload, key):
        if not self.runtime.settings.bar_effective:
            raise BacktestError("FLAG_DISABLED", "BAR backtests are disabled")
        fingerprint = digest(payload)
        with self.lock:
            existing = self.db.execute("SELECT hash,record FROM runs WHERE key=?", (key,)).fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise BacktestError("IDEMPOTENCY_CONFLICT", "key belongs to different native inputs")
                return json.loads(existing[1])
            if self.closed or len(self.cancel_events) + len(self.replay.jobs) >= 2:
                raise BacktestError("RUN_CAPACITY_EXCEEDED", "two native runs are already active")
            external = payload.get("execution_mode") == "CANDLESCOPE"
            plugin = self.resolver(payload["language"])
            if external:
                if payload.get("libraries") or payload.get("magnifier"):
                    raise BacktestError("EXTERNAL_UNSUPPORTED", "host matching does not accept native libraries or Magnifier")
                plugin = {**plugin, "command": [*plugin["command"][:-1], plugin["command"][-1].replace(".native_strategy", ".external_strategy")]}
            identity = self.runner(plugin, {"operation": "describe"}, timeout=15)["identity"]
            if identity.get("protocol") != PROTOCOL:
                raise BacktestError("NATIVE_PROTOCOL_ERROR", "unsupported native plugin protocol")
            bars = self._freeze(payload)
            manifest = self.runtime.local_data.get_manifest(payload["dataset_id"])
            if payload["context"]["symbol"].split(":")[-1] != manifest["symbol"] or payload["context"]["timeframe"] != timeframe(payload["interval"]):
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "chart metadata differs from frozen dataset")
            contexts, keys = [], set()
            for context in payload.get("contexts", []):
                pair = (context["symbol"], context["timeframe"])
                if pair in keys:
                    raise BacktestError("SCHEMA_UNKNOWN_FIELD", "duplicate requested context")
                keys.add(pair)
                requested = self.runtime.local_data.get_manifest(context["dataset_id"])
                if pair[0].split(":")[-1] != requested["symbol"] or pair[1] != timeframe(context["interval"]):
                    raise BacktestError("DATA_SNAPSHOT_MISMATCH", "requested metadata differs from frozen dataset")
                contexts.append({"symbol": pair[0], "timeframe": pair[1], "bars": self._freeze(context)})
            magnifier = None
            if payload.get("magnifier"):
                if payload["language"] != "pine":
                    raise BacktestError("NATIVE_INPUT_UNSUPPORTED", "Bar Magnifier is a Pine input profile")
                lower_ref = payload["magnifier"]
                lower_manifest = self.runtime.local_data.get_manifest(lower_ref["dataset_id"])
                if lower_manifest["symbol"] != manifest["symbol"]:
                    raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Magnifier symbol differs from chart")
                lower = self._freeze(lower_ref)
                chart_interval = parse_interval_spec(payload["interval"])
                lower_interval = parse_interval_spec(lower_ref["interval"])
                chart_bars, cursor = [], 0
                for index, bar in enumerate(bars):
                    start = bar["time"] * 1000
                    end = chart_interval.next_ms(start)
                    if lower_interval.next_ms(start) >= end:
                        raise BacktestError("NATIVE_INPUT_UNSUPPORTED", "Magnifier interval must be lower than chart")
                    while cursor < len(lower) and lower[cursor]["time"] * 1000 < start:
                        cursor += 1
                    selected = []
                    while cursor < len(lower) and lower[cursor]["time"] * 1000 < end:
                        selected.append(lower[cursor]); cursor += 1
                    if not selected or selected[0]["time"] * 1000 != start or lower_interval.next_ms(selected[-1]["time"] * 1000) != end:
                        raise BacktestError("DATA_QUALITY_FAILED", "Magnifier requires full intrabar coverage")
                    chart_bars.append({"chartBarIndex": index, "bars": selected})
                magnifier = {"schemaVersion": 1, "chartBars": chart_bars}
            wire = {"protocol": PROTOCOL, "identity": identity, "source": payload["source"],
                    "parameters": payload.get("parameters", {}), "bars": bars, "contexts": contexts,
                    "libraries": payload.get("libraries", {}), "context": payload["context"], "magnifier": magnifier}
            if external:
                from .external import host_identity
                from .external_market import freeze_execution
                wire.update(fill_recalculation=payload.get("fill_recalculation", False), execution_events=freeze_execution(self, payload, bars), execution_fidelity=payload.get("execution_fidelity", "BAR_APPROX"))
                wire["execution_provenance"] = (payload.get("execution_data") or {}).get("provenance", {})
                wire.update(host_settings=payload["host_settings"], interval=payload["interval"], host_runtime_identity=host_identity(),
                            context_intervals=[item["interval"] for item in payload.get("contexts", [])])
            if len(encoded(wire).encode()) > MAX_BYTES:
                raise BacktestError("BUDGET_EXCEEDED", "native input exceeds 64 MiB")
            run_id = "native_" + uuid.uuid4().hex
            record = {"run_id": run_id, "execution_mode": "CANDLESCOPE" if external else "NATIVE", "state": "QUEUED",
                      "created_at_ms": int(time.time() * 1000), "config": payload,
                      "input_hash": digest(wire), "source_hash": digest(payload["source"]),
                      "runtime_identity": identity, "plugin_installation": plugin.get("installation"),
                      "runtime_launch": plugin,
                      "row_count": len(bars), "result": None, "error": None}
            self.db.execute("INSERT INTO runs VALUES (?,?,?,?)", (run_id, key, fingerprint, encoded(record)))
            self.db.execute("INSERT INTO native_inputs VALUES (?,?)", (run_id, encoded(wire)))
            self.db.commit()
            cancel = threading.Event()
            self.cancel_events[run_id] = cancel
            self.pool.submit(self._execute, run_id, plugin, wire, cancel)
            return record

    def get(self, run_id):
        with self.lock:
            row = self.db.execute("SELECT record FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise BacktestError("RUN_NOT_FOUND", "native run not found")
            return json.loads(row[0])

    def list(self):
        with self.lock:
            records = [json.loads(row[0]) for row in self.db.execute("SELECT record FROM runs ORDER BY rowid DESC LIMIT 100")]
            return [{key: value for key, value in record.items() if key not in {"result", "config"}} for record in records]

    def _update(self, run_id, **values):
        record = self.get(run_id)
        record.update(values)
        self.db.execute("UPDATE runs SET record=? WHERE id=?", (encoded(record), run_id))
        self.db.commit()

    def _execute(self, run_id, plugin, wire, cancel):
        try:
            with self.lock:
                if cancel.is_set():
                    return
                self._update(run_id, state="RUNNING")
            external = "host_settings" in wire
            if external:
                from .external import run_external_host
                result = run_external_host(plugin, wire, self.runner, cancel)
            else:
                result = self.runner(plugin, wire, cancelled=cancel)
            if result.get("identity") != wire["identity"] or result.get("execution_mode") != ("CANDLESCOPE" if external else "NATIVE"):
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "result identity differs from frozen engine")
            authority = "candlescope" if external else "pine-compat-runtime" if plugin["plugin_id"] == "candlescope.pine-compat" else "pyne-runtime"
            if result.get("account_authority") != authority:
                raise BacktestError("NATIVE_PROTOCOL_ERROR", "unexpected account authority")
            result["bars"] = wire["bars"]
            result["report_hash"] = digest(result)
            with self.lock:
                if not cancel.is_set():
                    self._update(run_id, state="COMPLETED", result=result)
        except Exception as exc:
            with self.lock:
                if not cancel.is_set():
                    self._update(run_id, state="FAILED", error={"code": getattr(exc, "code", "NATIVE_EXECUTION_FAILED"),
                                 "message": str(exc), "details": getattr(exc, "details", {})})
        finally:
            with self.lock:
                self.cancel_events.pop(run_id, None)

    def cancel(self, run_id):
        with self.lock:
            record = self.get(run_id)
            if record["state"] not in TERMINAL:
                event = self.cancel_events.get(run_id)
                if event:
                    event.set()
                self._update(run_id, state="CANCELLED")
            return self.get(run_id)

    def shutdown(self):
        self.replay.shutdown()
        with self.lock:
            self.closed = True
            for run_id, event in self.cancel_events.items():
                event.set()
                self._update(run_id, state="INTERRUPTED")
        self.pool.shutdown(wait=True)
        self.db.close()
