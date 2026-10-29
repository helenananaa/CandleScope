"""Anchor identity through local freezing and real Pine execution."""
import asyncio
import json
import os

import httpx
import pytest
from fastapi import FastAPI

from app.backtest.errors import BacktestError
from app.backtest.native import timeframe
from app.backtest.native import validate_context_grids
from app.data_preparation.models import PreparationError
from app.data_preparation.native_plan import context_grids
from app.data_engine.interval_policy import parse_interval_spec
from app.local_data import LocalDatasetService, LocalImportOptions
from app.local_data.resampling import LocalResamplingError, resolve_local_resample_plan
from tests.test_data_preparation import START, async_test, terminal

ANCHOR = START + 23 * 60_000
INTERVAL = f"7m~a1~{ANCHOR}"


def minute(timestamp):
    index = (timestamp - START) // 60_000
    price = 100 + (index % 28)
    return dict(open_time=timestamp, close_time=timestamp + 59_999,
                open=price, high=price + 3, low=price - 2, close=price + 1,
                volume=index % 7 + 1, source="backfill")


def expected_bars(interval, start, end):
    # Independent oracle: enumerate whole minutes around the supplied event.
    duration, anchor = interval.split("~a1~")
    width, anchor = int(duration.removesuffix("m")) * 60_000, int(anchor)
    result = []
    for at in range(anchor + ((start - anchor) // width) * width, end, width):
        if at < start or at + width > end:
            continue
        rows = [minute(t) for t in range(at, at + width, 60_000)]
        result.append(dict(time=at // 1000, open=rows[0]["open"], high=max(r["high"] for r in rows),
                           low=min(r["low"] for r in rows), close=rows[-1]["close"],
                           volume=sum(r["volume"] for r in rows)))
    return result


def test_pine_timeframe_retains_duration_but_validates_anchor():
    assert timeframe(INTERVAL) == "7"
    for invalid in ("7m~a1~27000", "7m~a2~60000", "1w~a1~60000"):
        with pytest.raises(BacktestError):
            timeframe(invalid)


def test_local_resampling_requires_phase_congruence():
    plan = resolve_local_resample_plan("5m~a1~120000", "10m~a1~120000", alignment_offset_ms=120000)
    assert plan.factor == 2
    with pytest.raises(LocalResamplingError):
        resolve_local_resample_plan("5m", "10m~a1~120000", alignment_offset_ms=0)


def test_pine_context_pair_cannot_silently_override_chart_grid():
    primary = dict(exchange="binance", symbol="BTCUSDT", interval=INTERVAL)
    assert context_grids(primary, [primary])[("BINANCE:BTCUSDT", "7")] == parse_interval_spec(INTERVAL).canonical
    with pytest.raises(PreparationError, match="different anchor grids"):
        context_grids(primary, [{**primary, "interval": "7m"}])
    payload = dict(interval=INTERVAL, context=dict(symbol="BINANCE:BTCUSDT", timeframe="7"),
                   contexts=[dict(symbol="BINANCE:BTCUSDT", timeframe="7", interval="7m")])
    with pytest.raises(BacktestError, match="different anchor grids"):
        validate_context_grids(payload)


def test_local_minute_snapshot_matches_both_sides_and_separate_phases(tmp_path):
    service = LocalDatasetService(tmp_path / "local-data")
    path = tmp_path / "minute.csv"
    rows = [minute(START + i * 60_000) for i in range(70)]
    path.write_text("time,open,high,low,close,volume\n" + "\n".join(
        ",".join(str(row[k]) for k in ("open_time", "open", "high", "low", "close", "volume")) for row in rows))
    manifest = service.import_csv(path, LocalImportOptions(name="Anchor", symbol="BTCUSDT", interval="1m", timestamp_unit="ms"))
    for interval in (INTERVAL, f"7m~a1~{ANCHOR + 120000}"):
        data = service.query(manifest["dataset_id"], interval=interval, limit=100)["data"]
        actual = [{k: row[k] for k in ("time", "open", "high", "low", "close", "volume")} for row in data]
        assert actual == expected_bars(interval, START, START + 70 * 60_000)
        assert data[0]["time"] * 1000 < ANCHOR < data[-1]["time"] * 1000


@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PYTHON"), reason="requires qualified installed Pine engine")
@async_test
@pytest.mark.parametrize("phase_delta", [0, 120000])
async def test_real_pine_preparation_preserves_anchor_and_self_request(tmp_path, phase_delta):
    from app.api.v1.data_preparation import router
    from app.data_preparation.bar_adapter import BarPreparationAdapter
    from app.data_preparation.repository import PreparationRepository
    from app.data_preparation.service import PreparationService
    from tests.test_backtest_chart_context import _runtime
    from tests.test_native_strategy_plugins import plugin

    runtime = _runtime(tmp_path)
    runtime.native.resolver = plugin
    inventory = {}

    class Coordinator:
        async def request_and_wait(self, repair):
            inventory.update({t: minute(t) for t in range(repair.start_ms, repair.end_ms + 1, 60_000)})

    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(),
        local_data=runtime.local_data, backtest_runtime=runtime,
        query=lambda *a, **kw: [row for t, row in sorted(inventory.items()) if kw["start_ms"] <= t <= kw["end_ms"]])
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    app = FastAPI()
    app.state.data_preparation_service, app.state.backtest_runtime = service, runtime
    app.include_router(router)
    source = '''//@version=6
strategy("Anchored integration", initial_capital=10000)
if close > 120
    strategy.entry("L", strategy.long, qty=2)
if close < 110
    strategy.close("L")
plot(time, "Time")
plot(time_close, "Close time")
plot(close, "Close")
plot(request.security(syminfo.tickerid, timeframe.period, close), "Self close")
plot(ta.sma(close, 3), "SMA")
plot(request.security(syminfo.tickerid, "14", time), "Requested time")
'''
    selected_interval = f"7m~a1~{ANCHOR + phase_delta}"
    body = dict(idempotency_key="anchor-native-001", language="pine", parameters={}, source=source,
        contexts=[dict(exchange="binance", market_type="futures", symbol="BTCUSDT", interval=f"14m~a1~{ANCHOR + phase_delta}")],
        context=dict(exchange="binance", market_type="futures", symbol="BTCUSDT", interval=selected_interval,
            range_mode="CUSTOM", fidelity_preference="FAST", start_time_ms=START, end_time_ms=START + 600 * 60_000 - 1))
    await service.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            conflict = {**body, "contexts": [dict(exchange="binance", market_type="futures", symbol="BTCUSDT", interval="7m")]}
            rejected = await client.post("/data-preparations/native-strategy", json=conflict)
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["detail"]["code"] == "NATIVE_CONTEXT_GRID_CONFLICT"
            assert not inventory
            response = await client.post("/data-preparations/native-strategy", json=body)
            assert response.status_code == 202, response.text
            job = await terminal(service, response.json()["id"], timeout=30)
            assert job["state"] == "READY", job
            run_id = job["result"]["native_run"]["run_id"]
            for _ in range(500):
                run = runtime.native.get(run_id)
                if run["state"] in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.02)
            assert run["state"] == "COMPLETED", run
            config = run["config"]
            wire = json.loads(runtime.native.db.execute("SELECT wire FROM native_inputs WHERE id=?", (run_id,)).fetchone()[0])
            assert wire["interval"] == parse_interval_spec(selected_interval).canonical
            assert wire["bars"] == expected_bars(selected_interval, config["start_time_ms"], config["end_time_ms"] + 1)
            own = next(c for c in wire["contexts"] if c["timeframe"] == "7")
            higher = next(c for c in wire["contexts"] if c["timeframe"] == "14")
            assert own["interval"] == wire["interval"]
            assert higher["interval"] == parse_interval_spec(body["contexts"][0]["interval"]).canonical
            result = run["result"]
            assert len(result["orders"]) == 42 and len(result["trades"]) == 21
            for i, trade in enumerate(result["trades"]):
                assert trade["entryTime"] * 1000 == ANCHOR + phase_delta + i * 28 * 60_000
                assert trade["exitTime"] * 1000 == ANCHOR + phase_delta + (i * 28 + 7) * 60_000
                assert trade["entryPrice"] == 123 + phase_delta // 60_000
                assert trade["exitPrice"] == 102 + phase_delta // 60_000
            assert result["equity"][-1]["value"] == 9118
            plots = result["graphics"]
            assert plots[0]["values"] == [row["time"] * 1000 for row in wire["bars"]]
            assert plots[1]["values"] == [row["time"] * 1000 + 420000 for row in wire["bars"]]
            closes = [row["close"] for row in wire["bars"]]
            assert plots[2]["values"] == closes
            assert plots[3]["values"] == closes
            assert plots[4]["values"][2:] == pytest.approx([sum(closes[i-2:i+1]) / 3 for i in range(2, len(closes))])
            # Default lookahead_off exposes a requested bar only on its close.
            available = []
            for bar in wire["bars"]:
                closed = [row for row in higher["bars"] if row["time"] + 840 <= bar["time"] + 420]
                available.append(closed[-1]["time"] * 1000 if closed else None)
            assert plots[5]["values"] == available
            repeated = await client.post("/data-preparations/native-strategy", json=body)
            assert repeated.json()["id"] == job["id"]
            replay = runtime.native.replay
            created = replay.create(run_id)
            replay.command(created["replay_id"], created["revision"], "seek", created["total"])
            for _ in range(500):
                final = replay.get(created["replay_id"])
                if final["state"] in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.02)
            assert final["state"] == "COMPLETED", final
            assert final["result"] == result
            saved = replay.snapshot(final["replay_id"], final["revision"])
    finally:
        await service.shutdown()
        runtime.shutdown()
    restarted = _runtime(tmp_path)
    try:
        restored = restarted.native.get(run_id)
        assert restored["state"] == "COMPLETED"
        assert restored["input_hash"] == run["input_hash"]
        assert restored["result"] == result
        replayed = restarted.native.replay.get(saved["replay_id"])
        assert replayed["cursor"] == saved["cursor"]
        assert replayed["snapshots"] == saved["snapshots"]
        assert replayed["result"] == result
    finally:
        restarted.shutdown()
