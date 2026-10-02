from __future__ import annotations

import copy
import math
import sqlite3
import statistics
import threading
import time
from types import SimpleNamespace

import pytest

from app.backtest.native import NativeBacktests, PROTOCOL, digest, encoded
from app.backtest.native_replay import NativeReplay
from app.backtest.native_replay_storage import ResultJournal, MAX_DELTAS
from app.data_engine.data_manager.models import BarData
from app.indicator.engine import IndicatorEngine
from app.indicator.data_manager_bridge import _indicator_refresh_limit
from app.indicator.indicators.boll import BOLLIndicator


def bar(index, value):
    return BarData(time=(index + 1) * 60, open=value, high=value, low=value, close=value, volume=1)


@pytest.mark.parametrize("period", [20, 200])
def test_boll_high_price_small_variance_and_long_updates(period):
    values = [100000. + (index % 2) * .01 for index in range(period + 1200)]
    indicator = BOLLIndicator({"period": period})
    indicator.init([bar(index, value) for index, value in enumerate(values[:period])])
    for index in range(period, len(values)):
        before = indicator.get_latest()
        indicator.update_partial(bar(index, values[index]))
        expected = statistics.pstdev(values[index-period+1:index+1])
        preview = indicator.get_preview()
        assert (preview["upper"] - preview["lower"]) / 4 == pytest.approx(expected, abs=2e-8)
        assert indicator.get_latest() == before
        indicator.update_closed(bar(index, values[index]))
        result = indicator.get_latest()
        assert (result["upper"] - result["lower"]) / 4 == pytest.approx(expected, abs=2e-8)


def test_live_output_retention_preserves_recursive_state_and_reseed_span():
    from app.indicator.indicators.ema import EMAIndicator
    engine = IndicatorEngine(max_output_points=32)
    events = []
    engine.add_listener(events.append)
    bars = [bar(index, 100. + math.sin(index / 7)) for index in range(6000)]
    key, _ = engine.subscribe("BTCUSDT", "1m", "spot", "EMA", {"period": 20}, bars=bars[:40])
    for item in bars[40:]:
        engine.on_bar_closed("BTCUSDT", "1m", item)
    instance = engine._instances[key]
    reference = EMAIndicator({"period": 20})
    reference.init(bars)
    assert instance.get_latest() == reference.get_latest()
    assert len(instance.get_series()["ema"]) == 32
    assert instance.bar_count == 6000
    plan = engine.plan_series_correction("BTCUSDT", "1m", dirty_range={"start": 60, "end": 60})
    assert _indicator_refresh_limit(SimpleNamespace(), "1m", exchange="binance", market_type="spot",
                                    required_target_bars=plan["requiredTargetBars"]) == 6000
    bars[0] = bar(0, 200.)
    engine.on_bars_backfilled("BTCUSDT", "1m", bars)
    reference.recompute(bars)
    assert instance.get_latest() == reference.get_latest()
    assert len(instance.get_series()["ema"]) == 32
    assert events[-1].detail["computedRange"] == {"start": bars[-32].time, "end": bars[-1].time}
    # Independent HTTP/range computation still returns the full requested window.
    result = IndicatorEngine(max_output_points=32).compute("BTCUSDT", "1m", "spot", "EMA", {"period": 20}, bars)
    assert len(result.outputs["ema"].data) == len(bars)


@pytest.mark.anyio
async def test_short_correction_snapshot_cannot_reset_recursive_seed(monkeypatch):
    from app.indicator import data_manager_bridge as bridge
    from app.data_engine.data_manager.models import DataEventType
    from tests.test_indicator_data_manager_bridge import _DataManager, _amended_event, _install_bridge_fakes, _wait_until
    engine = IndicatorEngine(max_output_points=32)
    bars = [bar(index, 100. + math.sin(index)) for index in range(6000)]
    key, _ = engine.subscribe("BTCUSDT", "3m", "spot", "EMA", {"period": 20}, bars=bars)
    instance = engine._instances[key]
    before = instance.get_latest()
    class ShortHistory(_DataManager):
        def query_latest(self, *args, **kwargs):
            self.query_calls.append((args, kwargs))
            return SimpleNamespace(bars=bars[-32:], missing_ranges=[], retryable=False, complete=True)
    dm = ShortHistory()
    _install_bridge_fakes(monkeypatch, engine)
    bridge.bridge_indicator_engine(dm)
    callback = next(callback for callback, events in dm.subscriptions if events == {DataEventType.BAR_AMENDED})
    await callback(_amended_event(bars[0].time))
    await _wait_until(lambda: bool(dm.query_calls))
    assert dm.query_calls[0][1]["limit"] == 6001
    assert instance.bar_count == 6000
    assert instance.get_latest() == before


IDENTITY = {"protocol": PROTOCOL, "historical_session": "fixed-history/1"}


def output(bars):
    rows = [{"time": item["time"], "value": item["close"]} for item in bars]
    return {"identity": IDENTITY, "execution_mode": "NATIVE", "account_authority": "pine-compat-runtime",
            "equity": rows, "raw_output": {"plots": [{"data": copy.deepcopy(rows)}]}}


@pytest.fixture
def native(tmp_path):
    bars = [{"time": index * 60, "open": 1., "high": 2., "low": 1., "close": 1. + index, "volume": 1.}
            for index in range(80)]
    host = SimpleNamespace(settings=SimpleNamespace(db_path=tmp_path / "backtest.db", bar_effective=True),
                           local_data=SimpleNamespace(get_manifest=lambda _: {"symbol": "BTCUSDT"}))
    def runner(plugin, wire, **kwargs):
        return {"identity": IDENTITY} if wire.get("operation") == "describe" else output(wire["bars"])
    service = NativeBacktests(host, resolver=lambda _: {"plugin_id": "candlescope.pine-compat", "command": ["unused"]}, runner=runner)
    service._freeze = lambda _: copy.deepcopy(bars)
    payload = {"language": "pine", "source": "fixture", "dataset_id": "fixture", "interval": "1m",
               "context": {"symbol": "BTCUSDT", "timeframe": "1"}}
    record = service.create(payload, "fixture")
    deadline = time.monotonic() + 5
    while service.get(record["run_id"])["state"] not in {"COMPLETED", "FAILED"}:
        assert time.monotonic() < deadline
        time.sleep(.01)
    assert service.get(record["run_id"])["state"] == "COMPLETED"
    yield service, record["run_id"], bars
    service.shutdown()


def settled(service, key):
    deadline = time.monotonic() + 5
    while True:
        with service.native.lock:
            if key not in service.jobs:
                value = service.get(key)
                assert value["state"] != "FAILED", value
                return value
        assert time.monotonic() < deadline
        time.sleep(.005)


def test_native_list_reads_only_independent_summary(native):
    service, key, _ = native
    summary = service.list()
    assert summary[0]["state"] == "COMPLETED"
    assert "result" not in summary[0] and "config" not in summary[0]
    # A list has no reason to parse any report bytes.
    service.db.execute("UPDATE runs SET record='not JSON' WHERE id=?", (key,))
    service.db.commit()
    assert service.list() == summary


def test_incremental_replay_never_builds_prefix_and_restores_without_runtime(native):
    service, run_id, bars = native
    replay = service.replay
    replay._worker = lambda *args: SimpleNamespace(advance=lambda count, _: output(bars[:count]))
    replay._prefix = lambda *args: pytest.fail("incremental path must not copy historical prefixes")
    created = replay.create(run_id)
    key = created["replay_id"]
    replay.command(key, created["revision"], "seek", 30)
    first = settled(replay, key)
    assert first["result"]["bars"] == bars[:30]
    saved = replay.snapshot(key, first["revision"])
    replay.command(key, saved["revision"], "seek", 65)
    second = settled(replay, key)
    assert replay.restore(key, second["revision"], saved["snapshots"][0]["snapshot_id"])["result"] == first["result"]
    header = service.db.execute("SELECT record FROM native_replays WHERE id=?", (key,)).fetchone()[0]
    assert '"result":null' in header and '"bars"' not in header
    replay.shutdown()
    service.replay = replay = NativeReplay(service)
    assert replay.get(key)["result"] == first["result"]
    replay._worker = lambda *args: SimpleNamespace(advance=lambda count, _: output(bars[:count]))
    replay.command(key, replay.get(key)["revision"], "seek", len(bars))
    final = settled(replay, key)
    assert final["result"] == service.get(run_id)["result"]


def test_replay_cursor_and_result_rollback_together(native):
    service, run_id, bars = native
    replay = service.replay
    record = replay.create(run_id)
    key = record["replay_id"]
    changed = {**record, "cursor": 2, "result": output(bars[:2])}
    service.db.execute("CREATE TEMP TRIGGER reject_cursor BEFORE INSERT ON native_replays BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        replay._save(changed)
    service.db.execute("DROP TRIGGER reject_cursor")
    assert replay.get(key) == record


def test_journal_append_write_size_and_compaction_recovery():
    db = sqlite3.connect(":memory:")
    journal = ResultJournal(db)
    value = {"equity": [{"time": index, "value": index} for index in range(10000)],
             "nested": {"plots": [{"data": list(range(10000))}]}}
    with db:
        journal.save("r", value)
    for index in range(MAX_DELTAS + 2):
        value["equity"].append({"time": 10000 + index, "value": index})
        value["nested"]["plots"][0]["data"].append(index)
        with db:
            journal.save("r", value)
        journal.cache.clear()
        assert journal.load("r") == value
    rows = db.execute("SELECT payload FROM native_replay_result_deltas").fetchall()
    assert len(rows) < MAX_DELTAS
    assert max(len(row[0]) for row in rows) < 512
    db.execute("UPDATE native_replay_result_deltas SET payload='[]'")
    journal.cache.clear()
    with pytest.raises(ValueError, match="checksum"):
        journal.load("r")
    db.close()


@pytest.mark.parametrize("before,after", [(1, 1.0), (1, True), (0.0, -0.0),
                                         ({"nested": [1, 0.0]}, {"nested": [True, -0.0]}),
                                         ([1] * 20, [1.0] * 20)])
def test_journal_preserves_json_numeric_types_and_negative_zero(before, after):
    db = sqlite3.connect(":memory:")
    journal = ResultJournal(db)
    with db:
        journal.save("r", {"value": before})
        journal.save("r", {"value": after})
    journal.cache.clear()
    assert encoded(journal.load("r")) == encoded({"value": after})
    db.close()


def test_legacy_native_summary_and_replay_migrate_on_restart(native):
    service, key, bars = native
    origin = service.get(key)
    replay = service.replay
    record = replay.create(key)
    replay_id = record["replay_id"]
    record.update(cursor=7, result={**output(bars[:7]), "bars": bars[:7]})
    record["result"]["report_hash"] = digest(record["result"])
    service.db.execute("UPDATE native_replays SET record=? WHERE id=?", (encoded(record), replay_id))
    service.db.execute("DELETE FROM native_run_summaries")
    service.db.commit()
    host, runner, resolver = service.runtime, service.runner, service.resolver
    service.shutdown()
    replacement = NativeBacktests(host, runner=runner, resolver=resolver)
    try:
        assert replacement.list()[0]["run_id"] == key
        assert replacement.get(key) == origin
        assert replacement.replay.get(replay_id) == record
    finally:
        replacement.shutdown()
    # The fixture still owns its original instance; avoid closing it twice.
    service.shutdown = lambda: None


def test_prefix_copies_only_revealed_bars_and_detaches():
    class Future(dict):
        def __deepcopy__(self, memo):
            raise AssertionError("copied future bar")
    wire = {"bars": [{"time": 0}, Future(time=60)], "contexts": [], "magnifier": None}
    prefix = NativeReplay._prefix(None, wire, {"interval": "1m"}, 1)
    prefix["bars"][0]["time"] = 5
    assert wire["bars"][0]["time"] == 0


@pytest.mark.anyio
async def test_large_sidecar_conversion_and_adaptation_are_off_event_loop(monkeypatch):
    from dataclasses import replace
    from app.indicator.runtime_service import IndicatorRuntimeRequest, IndicatorRuntimeService
    from tests.test_indicator_runtime_service import _Host, _request, _routes
    loop_thread = threading.get_ident()
    observed = []
    original = IndicatorRuntimeRequest.to_sdk_request
    def convert(request):
        observed.append(("convert", threading.get_ident()))
        return original(request)
    def adapt(result):
        observed.append(("adapt", threading.get_ident()))
        return {"ok": result.ok}
    monkeypatch.setattr(IndicatorRuntimeRequest, "to_sdk_request", convert)
    async def forbidden():
        pytest.fail("sidecar must not fall back")
    request = _request()
    host = _Host()
    service = IndicatorRuntimeService(_routes("sidecar"), host=host)
    try:
        assert await service.execute(replace(request, bars=request.bars * 100), legacy=forbidden, adapt_sidecar=adapt) == {"ok": True}
        assert {name for name, _ in observed} == {"convert", "adapt"}
        assert all(thread != loop_thread for _, thread in observed)
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_supervisor_codec_runs_in_worker_threads(monkeypatch):
    import app.plugin_runtime.supervisor as module
    from candlescope_plugin_sdk import ExecuteBatchRequest, ExecuteBatchResult
    from tests.test_plugin_runtime_supervisor import _supervisor, _fake_spec, _execute_request
    loop_thread = threading.get_ident()
    observed = []
    def wrap(name, function):
        def call(*args, **kwargs):
            observed.append((name, threading.get_ident()))
            return function(*args, **kwargs)
        return call
    monkeypatch.setattr(module, "compact_json_bytes", wrap("encode", module.compact_json_bytes))
    monkeypatch.setattr(module, "strict_json_loads", wrap("decode", module.strict_json_loads))
    monkeypatch.setattr(ExecuteBatchRequest, "to_wire", wrap("wire", ExecuteBatchRequest.to_wire))
    monkeypatch.setattr(ExecuteBatchResult, "from_wire", staticmethod(wrap("parse", ExecuteBatchResult.from_wire)))
    supervisor = _supervisor(_fake_spec())
    try:
        result = await supervisor.execute_batch(_execute_request())
        assert result.ok
        assert {name for name, _ in observed} == {"encode", "decode", "wire", "parse"}
        assert all(thread != loop_thread for _, thread in observed)
    finally:
        await supervisor.stop()


@pytest.mark.anyio
async def test_cancellation_during_large_conversion_does_not_send_ipc(monkeypatch):
    import asyncio
    from dataclasses import replace
    from app.indicator.runtime_service import IndicatorRuntimeRequest, IndicatorRuntimeService
    from tests.test_indicator_runtime_service import _Host, _request, _routes
    entered, release = threading.Event(), threading.Event()
    original = IndicatorRuntimeRequest.to_sdk_request
    def convert(request):
        entered.set()
        assert release.wait(3)
        return original(request)
    monkeypatch.setattr(IndicatorRuntimeRequest, "to_sdk_request", convert)
    host = _Host()
    service = IndicatorRuntimeService(_routes("sidecar"), host=host)
    request = _request()
    async def forbidden():
        pytest.fail("unexpected legacy execution")
    task = asyncio.create_task(service.execute(replace(request, bars=request.bars * 100), legacy=forbidden,
                                               adapt_sidecar=lambda result: {"ok": result.ok}))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not host.requests
    finally:
        release.set()
        await service.stop()


def test_chunked_runtime_encoder_preserves_bytes_and_strict_limits():
    from app.plugin_host.framing import compact_json_bytes, JsonLineError
    from app.plugin_runtime.supervisor import _encode_request, METHOD_EXECUTE_BATCH
    request = {"jsonrpc": "2.0", "id": "request-1", "method": METHOD_EXECUTE_BATCH,
               "params": {"source": "绘制(close)", "bars": [{"time": index, "close": 100000.01} for index in range(1200)],
                          "params": {"enabled": True, "name": "订单"}}}
    reference = compact_json_bytes(request, max_message_bytes=1_000_000)
    assert _encode_request(request, max_message_bytes=len(reference)) == reference
    with pytest.raises(JsonLineError, match="byte limit"):
        _encode_request(request, max_message_bytes=len(reference) - 1)
    request["params"]["bars"][-1]["close"] = float("nan")
    with pytest.raises(JsonLineError, match="strict JSON"):
        _encode_request(request, max_message_bytes=1_000_000)


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["_encode_request", "strict_json_loads"])
async def test_startup_codec_capacity_failure_reaps_child_and_can_retry(monkeypatch, stage):
    import app.plugin_runtime.supervisor as module
    from app.core.bounded_executor import ExecutorBusyError
    from app.plugin_runtime.errors import PluginRequestError
    from tests.test_plugin_runtime_supervisor import _supervisor, _fake_spec
    run = module.run_indicator
    async def saturated(function, *args, **kwargs):
        if function.__name__ == stage:
            raise ExecutorBusyError("indicator")
        return await run(function, *args, **kwargs)
    supervisor = _supervisor(_fake_spec())
    try:
        monkeypatch.setattr(module, "run_indicator", saturated)
        with pytest.raises(PluginRequestError, match="retry later"):
            await supervisor.start()
        assert supervisor._process is None
        assert supervisor.snapshot()["state"] == "failed"
        monkeypatch.setattr(module, "run_indicator", run)
        await supervisor.start()
        assert supervisor.snapshot()["state"] == "ready"
    finally:
        await supervisor.stop()
