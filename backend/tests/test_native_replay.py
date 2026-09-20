from __future__ import annotations

import json
import time

import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_native_strategy_plugins import PINE, PYNE


def settle(service, key):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = service.get(key)
        with service.native.lock:
            if key not in service.jobs:
                assert value["state"] != "FAILED", value
                return value
        time.sleep(.03)
    raise AssertionError("replay did not settle")


@pytest.mark.parametrize("language,source", [("pine", PINE), ("pyne", PYNE), ("pyne", '''def init(ctx):
    ctx.strategy.configure(initial_capital=10000)
def on_bar(ctx, bar):
    if bar.close > 12:
        ctx.strategy.entry("L", ctx.strategy.long, qty=2)
    if bar.close < 9:
        ctx.strategy.close("L")
''')])
def test_replay_step_checkpoint_seek_and_batch_equivalence(runtime, language, source):
    host, payload = runtime
    origin = host.native.create({**payload, "language": language, "source": source}, "batch")
    origin = terminal(host.native, origin["run_id"])
    replay = host.native.replay
    record = replay.create(origin["run_id"])
    assert record["result"] is None and record["cursor"] == 0
    replay.command(record["replay_id"], record["revision"], "seek", 5)
    record = settle(replay, record["replay_id"])
    assert len(record["result"]["bars"]) == 5
    assert len(record["result"]["equity"]) == 5
    checkpoint = replay.snapshot(record["replay_id"], record["revision"])
    replay.command(record["replay_id"], checkpoint["revision"], "step")
    advanced = settle(replay, record["replay_id"])
    assert advanced["cursor"] == 6
    restored = replay.restore(record["replay_id"], advanced["revision"], checkpoint["snapshots"][0]["snapshot_id"])
    assert restored["result"] == record["result"]
    replay.command(record["replay_id"], restored["revision"], "seek", record["total"])
    final = settle(replay, record["replay_id"])
    assert final["state"] == "COMPLETED"
    assert final["result"] == origin["result"]
    assert host.service.repository.list_runs() == []


def test_replay_revision_and_cross_session_checkpoint_are_rejected(runtime):
    host, payload = runtime
    origin = host.native.create(payload, "origin")
    terminal(host.native, origin["run_id"])
    service = host.native.replay
    first = service.create(origin["run_id"])
    second = service.create(origin["run_id"])
    checkpoint = service.snapshot(first["replay_id"], 0)
    with pytest.raises(ValueError, match="CONFLICT"):
        service.command(first["replay_id"], 0, "step")
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        service.restore(second["replay_id"], 0, checkpoint["snapshots"][0]["snapshot_id"])


def test_replay_pause_discards_late_work_and_survives_restart(runtime):
    import threading
    from app.backtest.native_replay import NativeReplay
    host, payload = runtime
    origin = host.native.create(payload, "origin")
    terminal(host.native, origin["run_id"])
    service = host.native.replay
    record = service.create(origin["run_id"])
    runner = host.native.runner
    entered, release = threading.Event(), threading.Event()
    def slow(plugin, wire, **kwargs):
        if wire.get("operation") != "describe":
            entered.set()
            release.wait(10)
        return runner(plugin, wire, **kwargs)
    host.native.runner = slow
    service.command(record["replay_id"], 0, "play")
    assert entered.wait(5)
    paused = service.command(record["replay_id"], service.get(record["replay_id"])["revision"], "pause")
    release.set()
    assert settle(service, record["replay_id"])["cursor"] == 0
    service.snapshot(record["replay_id"], paused["revision"])
    service.shutdown()
    host.native.replay = NativeReplay(host.native)
    restored = host.native.replay.get(record["replay_id"])
    assert restored["cursor"] == 0 and restored["snapshots"]


def test_replay_clips_future_requested_and_magnifier_data(runtime):
    host, _ = runtime
    wire = {"bars": [{"time": 0}, {"time": 60}], "contexts": [{"bars": [{"time": 0}, {"time": 60}, {"time": 120}]}],
            "magnifier": {"chartBars": [{"chartBarIndex": 0}, {"chartBarIndex": 1}]}}
    result = host.native.replay._prefix(wire, {"interval": "1m", "contexts": [{"interval": "1m"}]}, 1)
    assert result["contexts"][0]["bars"] == [{"time": 0}]
    assert result["magnifier"]["chartBars"] == [{"chartBarIndex": 0}]
    assert len(wire["bars"]) == 2


@pytest.mark.parametrize("language,source", [("pine", PINE), ("pyne", """def init(ctx):
    ctx.strategy.configure(initial_capital=10000)
def on_bar(ctx, bar):
    if ctx.bar_index == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=2)
    if ctx.bar_index == 6:
        ctx.strategy.close("L")
""")])
def test_fixed_history_worker_reuse_backward_seek_and_restart(runtime, language, source):
    from app.backtest.native_replay import NativeReplay
    host, payload = runtime
    origin = terminal(host.native, host.native.create({**payload, "language": language, "source": source}, "fixed")["run_id"])
    assert origin["state"] == "COMPLETED", origin
    service = host.native.replay
    record = service.create(origin["run_id"])
    key = record["replay_id"]
    def seek(target):
        service.command(key, service.get(key)["revision"], "seek", target)
        return settle(service, key)
    first = seek(3)
    assert first["method"] == "FIXED_HORIZON_INCREMENTAL"
    process = service.workers[key].process
    snapshot = service.snapshot(key, first["revision"])
    seek(7)
    assert service.workers[key].process is process and process.poll() is None
    restored = service.restore(key, service.get(key)["revision"], snapshot["snapshots"][0]["snapshot_id"])
    assert restored["result"] == first["result"]
    assert seek(4)["cursor"] == 4
    assert seek(3)["result"] == first["result"]
    service.shutdown()
    assert process.poll() is not None
    service = host.native.replay = NativeReplay(host.native)
    final = seek(record["total"])
    assert final["result"] == origin["result"]
    assert service.workers[key].process.pid != process.pid


def test_pine_fixed_horizon_last_bar_is_not_prefix_endpoint(runtime):
    host, payload = runtime
    source = """//@version=6
strategy("fixed horizon")
if barstate.islast
    strategy.entry("L", strategy.long, qty=1)
plot(barstate.islast ? 1 : 0)
"""
    origin = terminal(host.native, host.native.create({**payload, "source": source}, "horizon")["run_id"])
    assert origin["state"] == "COMPLETED", origin
    replay = host.native.replay
    record = replay.create(origin["run_id"])
    replay.command(record["replay_id"], 0, "seek", 5)
    middle = settle(replay, record["replay_id"])
    assert middle["method"] == "FIXED_HORIZON_INCREMENTAL"
    assert not middle["result"]["orders"]
    replay.command(record["replay_id"], middle["revision"], "play")
    assert settle(replay, record["replay_id"])["result"] == origin["result"]
