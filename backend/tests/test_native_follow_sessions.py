"""Pine FOLLOW rebuilds extend a warm session (ADR-BACKTEST-015 O1, B-157a).

The fake workers cover which rebuilds extend, reopen or fall back. The test at the end
runs the real installed runtime (``NATIVE_TEST_PYTHON``) and checks every extended
rebuild against the ordinary full run of the same input.
"""
from __future__ import annotations

import copy
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.native import PROTOCOL, NativeBacktests, invoke
from app.backtest.native_follow_sessions import FOLLOW_CONTRACT, FollowSessions, continues

IDENTITY = {"protocol": PROTOCOL, "historical_session": "fixed-history/1", "follow_session": FOLLOW_CONTRACT}


def bars(count):
    return [{"time": 1_700_000_000 + index * 60, "open": 1., "high": 2., "low": .5, "close": 1. + index % 7,
             "volume": 1.} for index in range(count)]


def wire(count, *, start=0, source="strategy", identity=IDENTITY, **extra):
    rows = bars(start + count)[start:]
    clocks = [row["time"] * 1000 + 59_999 for row in rows]
    return {"protocol": PROTOCOL, "identity": identity, "source": source, "parameters": {}, "bars": rows,
            "contexts": [], "interval": "1m", "libraries": {}, "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"},
            "magnifier": None, "execution_times": clocks, "host_inputs": {"executionTimes": clocks, "chartMetadata": {}},
            "clock_policy": "historical-bar-close", **extra}


def result_of(payload):
    return {"ok": True, "identity": payload["identity"], "execution_mode": "NATIVE",
            "account_authority": "pine-compat-runtime", "count": len(payload["bars"])}


class FakeWorker:
    def __init__(self, log, payload, supported=True, fail_on=None):
        self.log, self.payload, self.supported, self.fail_on = log, payload, supported, fail_on
        self.closed = False
        log.append(("open", len(payload["bars"]), payload.get("follow_contract")))

    def advance(self, target, cancelled):
        self.log.append(("advance", target))
        return result_of(self.payload)

    def request(self, payload, cancelled, timeout=120):
        assert payload["operation"] == "extend"
        self.log.append(("extend", len(payload["bars"])))
        if self.fail_on == len(payload["bars"]):
            raise BacktestError("NATIVE_EXECUTION_FAILED", "worker stopped")
        if cancelled.is_set():
            raise BacktestError("NATIVE_CANCELLED", "cancelled")
        self.payload = payload
        return result_of(payload)

    def close(self):
        self.closed = True
        self.log.append(("close",))


def sessions(**options):
    log, workers = [], []

    def open_worker(plugin, payload, cancelled):
        worker = FakeWorker(log, payload, **options)
        workers.append(worker)
        return worker
    return FollowSessions(open_worker), log, workers


def test_a_rebuild_that_continues_the_previous_one_extends_its_session():
    follows, log, workers = sessions()
    cancel = threading.Event()
    assert follows.run("base", {}, wire(100), cancel)["count"] == 100
    assert follows.run("base", {}, wire(101), cancel)["count"] == 101
    assert follows.run("base", {}, wire(130), cancel)["count"] == 130
    assert log == [("open", 100, FOLLOW_CONTRACT), ("advance", 100), ("extend", 101), ("extend", 130)]
    assert len(workers) == 1 and not workers[0].closed


@pytest.mark.parametrize("changed", [
    pytest.param(lambda: wire(100, start=1), id="the window's start moved"),
    pytest.param(lambda: wire(101, source="other"), id="the code changed"),
    pytest.param(lambda: {**wire(101), "parameters": {"length": 3}}, id="a parameter changed"),
    pytest.param(lambda: wire(100), id="no new bar"),
    pytest.param(lambda: {**wire(101), "bars": [*bars(100)[:50], {**bars(100)[50], "close": 9.}, *bars(101)[51:]]},
                 id="an earlier bar was revised"),
])
def test_any_other_rebuild_opens_a_new_session(changed):
    follows, log, workers = sessions()
    cancel = threading.Event()
    follows.run("base", {}, wire(100), cancel)
    follows.run("base", {}, changed(), cancel)
    assert [entry[0] for entry in log] == ["open", "advance", "close", "open", "advance"]
    assert workers[0].closed and not workers[1].closed


def test_continuation_compares_every_input_but_the_growing_bars():
    assert continues(wire(10), wire(11))
    assert not continues(wire(10), {**wire(11), "host_inputs": {**wire(11)["host_inputs"], "chartMetadata": {"x": 1}}})
    assert not continues(wire(10), {**wire(11), "execution_times": None})
    assert not continues(wire(10), {**wire(11), "currency_rates": {"USD": 1}})


def test_scripts_the_runtime_keeps_on_full_rebuilds_ask_once():
    follows, log, _ = sessions(supported=False)
    cancel = threading.Event()
    assert follows.run("base", {}, wire(100), cancel) is None
    assert follows.run("base", {}, wire(101), cancel) is None
    assert log == [("open", 100, FOLLOW_CONTRACT), ("close",)]
    assert follows.run("base", {}, wire(102, source="edited"), cancel) is None
    assert [entry[0] for entry in log].count("open") == 2


def test_a_failed_extension_falls_back_and_the_next_rebuild_reopens():
    follows, log, workers = sessions(fail_on=101)
    cancel = threading.Event()
    follows.run("base", {}, wire(100), cancel)
    assert follows.run("base", {}, wire(101), cancel) is None  # the ordinary full run decides
    assert workers[0].closed
    assert follows.run("base", {}, wire(102), cancel)["count"] == 102
    assert [entry[0] for entry in log] == ["open", "advance", "extend", "close", "open", "advance"]


def test_cancellation_is_not_a_fallback():
    follows, _, workers = sessions()
    cancel = threading.Event()
    follows.run("base", {}, wire(100), cancel)
    cancel.set()
    with pytest.raises(BacktestError) as stopped:
        follows.run("base", {}, wire(101), cancel)
    assert stopped.value.code == "NATIVE_CANCELLED" and workers[0].closed


def test_runtimes_without_follow_sessions_and_external_runs_are_not_followed():
    follows, log, _ = sessions()
    cancel = threading.Event()
    assert follows.run("base", {}, wire(10, identity={**IDENTITY, "follow_session": None}), cancel) is None
    assert follows.run("base", {}, {**wire(10), "host_settings": {}}, cancel) is None
    assert log == []


def test_sessions_are_a_bounded_cache():
    now = [0.0]
    log, workers = [], []

    def open_worker(plugin, payload, cancelled):
        workers.append(FakeWorker(log, payload))
        return workers[-1]
    follows = FollowSessions(open_worker, capacity=2, idle_seconds=60, clock=lambda: now[0])
    cancel = threading.Event()
    for base in ("a", "b", "c"):
        follows.run(base, {}, wire(10), cancel)
    assert [worker.closed for worker in workers] == [True, False, False]  # least recently used
    now[0] = 61
    follows.run("d", {}, wire(10), cancel)
    assert [worker.closed for worker in workers] == [True, True, True, False]  # idle ones
    follows.close()
    assert all(worker.closed for worker in workers)
    assert follows.run("e", {}, wire(10), cancel) is None


@pytest.fixture
def native(tmp_path):
    host = SimpleNamespace(settings=SimpleNamespace(db_path=tmp_path / "backtest.db", bar_effective=True),
                           local_data=SimpleNamespace(get_manifest=lambda _: {"symbol": "BTCUSDT"}))
    full_runs = []

    def runner(plugin, payload, **kwargs):
        if payload.get("operation") == "describe":
            return {"identity": IDENTITY}
        full_runs.append(len(payload["bars"]))
        return result_of(payload)

    follows, log, _ = sessions()
    service = NativeBacktests(host, resolver=lambda _: {"plugin_id": "candlescope.pine-compat", "command": ["unused"]},
                              runner=runner, follow_sessions=follows)
    service._record_version = lambda record: None
    service.frozen = bars(3)
    service._freeze = lambda _: copy.deepcopy(service.frozen)
    yield SimpleNamespace(service=service, full_runs=full_runs, log=log)
    service.shutdown()


def create(service, key, *, follow_of=None, source="strategy"):
    payload = {"language": "pine", "source": source, "dataset_id": "fixture", "data_epoch": "epoch",
               "snapshot_hash": key, "start_time_ms": 0, "end_time_ms": 1, "interval": "1m",
               "context": {"symbol": "BTCUSDT", "timeframe": "1"}}
    record = service.create(payload, key, follow_of=follow_of)
    deadline = time.monotonic() + 5
    while (state := service.get(record["run_id"])["state"]) not in {"COMPLETED", "FAILED"}:
        assert time.monotonic() < deadline
        time.sleep(.005)
    return service.get(record["run_id"])


def test_follow_rebuilds_use_the_warm_session_and_say_so(native):
    service = native.service
    base = create(service, "user")
    assert native.full_runs == [3] and "follow" not in base
    service.frozen = bars(4)
    first = create(service, "follow-1", follow_of=base["run_id"])
    service.frozen = bars(5)
    second = create(service, "follow-2", follow_of=base["run_id"])
    assert native.full_runs == [3]  # the user's run only
    assert [entry[0] for entry in native.log] == ["open", "advance", "extend"]
    assert first["result"]["count"] == 4 and second["result"]["count"] == 5
    assert first["follow"] == second["follow"] == {"extendable": True}


def test_rebuilds_the_runtime_cannot_extend_run_in_full(native):
    service = native.service
    service.follow_sessions.open_worker = lambda plugin, payload, cancelled: FakeWorker(native.log, payload, supported=False)
    base = create(service, "user")
    service.frozen = bars(4)
    rebuild = create(service, "follow-1", follow_of=base["run_id"])
    assert native.full_runs == [3, 4]
    assert rebuild["state"] == "COMPLETED" and rebuild["follow"] == {"extendable": False}


@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PYTHON"), reason="requires the installed Pine runtime")
def test_real_runtime_extended_rebuilds_equal_full_runs():
    python = os.environ.get("NATIVE_TEST_PINE_PYTHON", os.environ.get("NATIVE_TEST_PYTHON", sys.executable))
    plugin = {"command": [python, "-I", "-m", "candlescope_plugin_pine_compat.native_strategy"],
              "plugin_id": "candlescope.pine-compat"}
    identity = invoke(plugin, {"operation": "describe"})["identity"]
    assert identity.get("follow_session") == FOLLOW_CONTRACT
    source = '''//@version=6
strategy("Follow", initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=30)
if ta.crossover(close, ta.sma(close, 5))
    strategy.entry("L", strategy.long, stop=high)
if ta.crossunder(close, ta.sma(close, 9))
    strategy.entry("S", strategy.short, limit=close + 0.2)
strategy.exit("XL", "L", profit=60, loss=40)
plot(ta.sma(close, 5))
'''
    rows = [{"time": 1_700_000_000 + index * 60, "open": 100 + (index % 9) - 4, "high": 100 + (index % 9) - 2,
             "low": 100 + (index % 9) - 6, "close": 100 + ((index * 5) % 11) - 5, "volume": 1.} for index in range(160)]

    def real_wire(count):
        clocks = [row["time"] * 1000 + 59_999 for row in rows[:count]]
        return {"protocol": PROTOCOL, "identity": identity, "source": source, "parameters": {}, "bars": rows[:count],
                "contexts": [], "interval": "1m", "libraries": {}, "magnifier": None,
                "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"}, "execution_times": clocks,
                "host_inputs": {"executionTimes": clocks}, "clock_policy": "historical-bar-close"}

    follows = FollowSessions()
    cancel = threading.Event()
    try:
        for count in (120, 121, 122, 140, 160):
            extended = follows.run("base", plugin, real_wire(count), cancel)
            assert extended is not None
            full = invoke(plugin, real_wire(count))
            assert extended == full
        assert full["trades"]
    finally:
        follows.close()
