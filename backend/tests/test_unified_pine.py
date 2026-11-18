"""Real Pine through the bundled unified entry and pinned strategy launch."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.backtest.errors import BacktestError
from app.backtest.native import PROTOCOL, invoke, pin_native_launch, resolve_plugin
from app.indicator.runtime_routes import IndicatorRuntimeRoutes
from app.indicator.runtime_service import (
    IndicatorRuntimeRequest,
    IndicatorRuntimeService,
    removed_in_process_runtime,
)
from app.plugin_compat_v1 import V1ScriptRuntimeCompatibilityBridge
from app.plugin_lifecycle.pine import (
    PINE_ENTRY,
    PINE_ID,
    PineRuntimeHost,
    bind_strategy_runtime,
    import_pine_observations,
)
from app.plugin_lifecycle.pine_bundle import build_pine_package
from app.plugin_lifecycle.runtime import UnifiedRuntime
from app.plugin_lifecycle.store import LifecycleError, PackageStore
from app.plugin_runtime import RuntimeHostService
from candlescope_plugin_sdk import (
    AnalyzeRequest,
    Bar,
    ExecuteBatchRequest,
    MarketContext,
)

from tests.test_native_backtests import runtime_at, terminal
from tests.test_native_replay import settle
from tests.test_native_strategy_plugins import BARS, PINE


@pytest.mark.anyio
async def test_bundled_pine_chart_strategy_and_restart(tmp_path):
    wheel_dir = os.environ.get("CANDLESCOPE_TEST_UNIFIED_PINE_WHEELS")
    if not wheel_dir:
        pytest.skip(
            "set CANDLESCOPE_TEST_UNIFIED_PINE_WHEELS to current SDK, bridge and pinned engine wheels"
        )
    wheels = sorted(Path(wheel_dir).glob("*.whl"))
    assert len(wheels) == 3
    archive = tmp_path / "pine.cspkg"
    package = build_pine_package(wheels, "0.4.0", archive)
    descriptor = tmp_path / "bundled-pine.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema": "candlescope.bundled-unified-pine/1",
                "filename": archive.name,
                "sha256": package.sha256,
                "size": package.size,
            }
        )
    )
    app = SimpleNamespace(state=SimpleNamespace())
    store = PackageStore(tmp_path / "profile")
    runtime = UnifiedRuntime(app, store)
    bind_strategy_runtime(runtime, required=True)
    start_time = 1_700_000_000
    script = '//@version=6\nindicator("Unified")\nplot(close * 2, title="double")'
    context = MarketContext(
        exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m"
    )
    bars = tuple(
        Bar(
            time=start_time + i * 60,
            open=10 + i,
            high=11 + i,
            low=9 + i,
            close=10 + i,
            volume=3,
        )
        for i in range(3)
    )
    request = ExecuteBatchRequest(
        source=script,
        context=context,
        bars=bars,
        options={"pineSessionId": "fixture"},
        output_stream="fixture",
    )
    ticks = replace(
        request,
        source='//@version=6\nindicator("Ticks")\nvarip int n = 0\nn += 1\nplot(n)',
        bars=(*bars[:-1], replace(bars[-1], is_closed=False)),
        options={"pineSessionId": "ticks"},
        output_stream="ticks",
    )

    def verify_replay(backtest, payload):
        backtest.native.resolver = resolve_plugin
        native = backtest.native
        origin = terminal(native, native.create(payload, "unified-origin")["run_id"])
        assert origin["state"] == "COMPLETED", origin
        assert origin["result"]["trades"] and origin["result"]["graphics"]
        replay = native.replay
        record = replay.create(origin["run_id"])
        key = record["replay_id"]
        replay.command(key, record["revision"], "seek", 5)
        prefix = settle(replay, key)
        assert len(prefix["result"]["bars"]) == 5
        assert prefix["method"] == "FIXED_HORIZON_INCREMENTAL"
        checkpoint = replay.snapshot(key, prefix["revision"])
        return origin, checkpoint, prefix["result"], replay.workers[key].process

    def verify_replay_after_restart(backtest, origin, checkpoint, expected):
        from app.backtest.native_replay import NativeReplay

        backtest.native.replay.shutdown()
        replay = backtest.native.replay = NativeReplay(backtest.native)
        key = checkpoint["replay_id"]
        record = replay.get(key)
        restored = replay.restore(
            key, record["revision"], checkpoint["snapshots"][0]["snapshot_id"]
        )
        assert restored["result"] == expected
        replay.command(key, restored["revision"], "seek", record["total"])
        assert settle(replay, key)["result"] == origin["result"]
        return replay.workers[key].process

    async def verify_calculation(host):
        result = await host.execute_batch(PINE_ID, request)
        assert result.ok, result.diagnostics
        assert [point.value for point in result.output.series[0].points] == [20, 22, 24]
        snapshot = await host.read_output(PINE_ID, "fixture")
        assert snapshot and snapshot.output == result.output
        return snapshot.reference

    fixture = runtime_at(tmp_path)
    backtest, payload = next(fixture)
    try:
        await runtime.prepare_startup(bundled_pine=descriptor)
        assert not runtime.errors, runtime.errors
        run = runtime.running[(PINE_ID, PINE_ENTRY)]
        host = PineRuntimeHost(runtime, None)
        assert (await host.descriptor(PINE_ID)).id == PINE_ID
        assert (
            await host.analyze(PINE_ID, AnalyzeRequest(source=script, context=context))
        ).executable
        snapshot = await verify_calculation(host)
        launch = resolve_plugin("pine")
        strategy = invoke(launch, {"operation": "describe"}, timeout=15)
        assert strategy["identity"]["protocol"] == "candlescope.native-strategy/1"
        assert launch["installation"]["packageSha256"] == package.sha256
        strategy_wire = {
            "protocol": PROTOCOL,
            "identity": strategy["identity"],
            "source": PINE,
            "bars": BARS,
            "parameters": {},
            "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"},
        }
        strategy_result = await asyncio.to_thread(invoke, launch, strategy_wire)
        assert strategy_result["orders"] and strategy_result["trades"]
        assert len(strategy_result["equity"]) == len(BARS)
        assert strategy_result["graphics"][0]["values"] == [
            bar["close"] for bar in BARS
        ]
        with pytest.raises(BacktestError, match="rejected"):
            await asyncio.to_thread(
                invoke, launch, {**strategy_wire, "source": "invalid()"}
            )
        origin, checkpoint, prefix, first_process = await asyncio.to_thread(
            verify_replay, backtest, payload
        )
        tick = await host.execute_batch(PINE_ID, ticks)
        assert tick.output.series[0].points[-1].value == 3
        tick = await host.execute_batch(
            PINE_ID,
            replace(
                ticks, bars=(*ticks.bars[:-1], replace(ticks.bars[-1], close=12.5))
            ),
        )
        assert tick.output.series[0].points[-1].value == 4

        frame = {
            "schema": "candlescope.unified-chart/1",
            "documentId": "window",
            "chartId": "chart",
            "instanceId": "chart-instance",
            "mode": "replay",
            "runId": "run",
            "trackId": "track",
            "seriesId": "btc-1m",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "dataRevision": "rev",
            "visibleThroughMs": (start_time + 180) * 1000 - 1,
        }
        projected = [
            {
                "openTimeMs": bar.time * 1000,
                "observedThroughMs": (bar.time + 60) * 1000 - 1,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "closed": True,
            }
            for bar in bars
        ]
        reply = await runtime.invoke(
            PINE_ID,
            PINE_ENTRY,
            run.identity.to_wire(),
            run.instance,
            {
                "scope": frame,
                "bars": projected,
                "input": {"source": script, "parameters": {}},
            },
            chart=True,
        )
        assert [point["value"] for point in reply["points"]] == [20, 22, 24]

        with pytest.raises(LifecycleError, match="one Pine line"):
            await runtime.invoke(
                PINE_ID,
                PINE_ENTRY,
                run.identity.to_wire(),
                run.instance,
                {
                    "scope": frame,
                    "bars": projected,
                    "input": {"source": script + "\nhline(10)", "parameters": {}},
                },
                chart=True,
            )
        assert await host.descriptor(PINE_ID)
        await runtime.stop()
        assert not run.executor.context.root.exists()
        assert first_process.poll() is not None
        assert await host.read_output(PINE_ID, "fixture", expected=snapshot) is None
        replacement = UnifiedRuntime(app, store)
        bind_strategy_runtime(replacement, required=True)
        try:
            await replacement.prepare_startup(bundled_pine=descriptor)
            assert replacement.running[(PINE_ID, PINE_ENTRY)].instance != run.instance
            rebound = pin_native_launch(launch, restore=True)
            assert rebound["installation"] == launch["installation"]
            assert rebound["instanceId"] != launch["instanceId"]
            legacy = RuntimeHostService.disabled(
                host_name="CandleScope", host_version="test"
            )
            replacement_host = PineRuntimeHost(replacement, legacy)
            indicators = IndicatorRuntimeService(
                IndicatorRuntimeRoutes.first_party_sidecar_default(),
                host=replacement_host,
                legacy_languages=frozenset(),
            )
            app.state.indicator_runtime_service = indicators
            bridge = V1ScriptRuntimeCompatibilityBridge(
                root=tmp_path / "compatibility",
                indicator_source=indicators,
                runtime_host=legacy,
                excluded_runtime_ids=frozenset({PINE_ID}),
            )
            indicators.bind_catalog_projector(bridge.project_indicator_catalog)

            async def pine_available():
                catalog = await indicators.public_catalog()
                return next(
                    item["available"]
                    for item in catalog["languages"]
                    if item["id"] == "pine"
                )

            assert await pine_available()
            rendered = await indicators.execute(
                IndicatorRuntimeRequest(
                    language="pine",
                    source=script + "\nhline(19)",
                    exchange=context.exchange,
                    market_type=context.market_type,
                    symbol=context.symbol,
                    interval=context.interval,
                    bars=bars,
                    options={"pineSessionId": "render"},
                    transport="websocket.range",
                ),
                legacy=removed_in_process_runtime,
                adapt_sidecar=lambda result: result.to_wire(),
            )
            assert rendered["ok"], rendered
            assert rendered["output"]["collections"]["hlines"]
            assert [
                point["value"] for point in rendered["output"]["series"][0]["data"]
            ] == [20, 22, 24]
            assert all(
                row["runtimeId"] != PINE_ID
                for row in bridge.public_catalog()["contributions"]
            )
            assert (
                await verify_calculation(replacement_host)
            ).owner_epoch != snapshot.owner_epoch
            resumed = await replacement_host.execute_batch(
                PINE_ID,
                replace(
                    ticks, bars=(*ticks.bars[:-1], replace(ticks.bars[-1], close=12.75))
                ),
            )
            assert (
                resumed.meta["sessionRecovered"]
                and resumed.output.series[0].points[-1].value == 5
            )
            next_process = await asyncio.to_thread(
                verify_replay_after_restart, backtest, origin, checkpoint, prefix
            )
            assert next_process.pid != first_process.pid
            store.disable(PINE_ID, expected_revision=store.snapshot()["revision"])
            await replacement.start()
            assert not replacement.running
            assert not await pine_available()
            assert next_process.poll() is not None
            with pytest.raises(BacktestError, match="Enable or restore"):
                resolve_plugin("pine")
            store.activate(
                package.sha256,
                expected_revision=store.snapshot()["revision"],
                acknowledgement=f"full-trust:{package.sha256}",
            )
            await replacement.reconcile()
            assert await pine_available()
        finally:
            await replacement.stop()
    finally:
        await runtime.stop()
        bind_strategy_runtime(None, required=False)
        next(fixture, None)


def test_previous_pine_journal_copy_is_consistent_and_once_only(tmp_path):
    old = tmp_path / "legacy.db"
    storage = tmp_path / "private"
    storage.mkdir()
    with closing(sqlite3.connect(old)) as source:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE observations (value INTEGER)")
        source.execute("INSERT INTO observations VALUES (1)")
        source.commit()
        previous = old.read_bytes()
        environ = {"CANDLESCOPE_PINE_JOURNAL": str(old)}
        import_pine_observations(storage, environ)
        assert old.read_bytes() == previous
        source.execute("INSERT INTO observations VALUES (2)")
        source.commit()
        import_pine_observations(storage, environ)
    with closing(sqlite3.connect(storage / "observations-v1.sqlite3")) as result:
        assert result.execute("SELECT value FROM observations").fetchall() == [(1,)]
