import json
import os
from decimal import Decimal
from dataclasses import replace

import pytest
from app.backtest.strategy.pine_engine import SOURCE_SCHEMA, PineEngineProvider, analyze
from app.backtest.strategy.protocol import ObservationFrame, StrategyProviderError
from app.backtest.strategy.workspace import compile_revision

pytestmark = pytest.mark.skipif(
    not os.environ.get("NATIVE_TEST_PINE_PYTHON"),
    reason="requires installed source-candidate Pine adapter",
)
SOURCE = """//@version=6
strategy("SMA")
average = ta.sma(close, 2)
if close > average
    strategy.entry("L", strategy.long, qty=2)
if close < average
    strategy.close("L")
"""

LIBRARY = '//@version=6\nlibrary("Threshold")\nexport twice(float x) => x * 2\n'
LIBRARY_SOURCE = '//@version=6\nstrategy("import")\nimport local/Threshold/1 as threshold\nif close > threshold.twice(7)\n    strategy.entry("L", strategy.long, qty=2)\n'
PARTIAL_SOURCE = '''//@version=6
strategy("Partial")
if bar_index == 0
    strategy.entry("L", strategy.long, qty=4)
if bar_index == 2
    strategy.close("L", qty_percent=25)
if bar_index == 4
    strategy.close_all()
'''
CLOCK_SOURCE = PARTIAL_SOURCE.replace("bar_index == 0", "timenow == 59999").replace(
    "bar_index == 2", "timenow == 179999").replace("bar_index == 4", "timenow == 299999")
PERP_SOURCE = PARTIAL_SOURCE.replace("bar_index == 0", 'bar_index == 0 and syminfo.tickerid == "BINANCE:BTCUSDT.P"')


@pytest.mark.parametrize("market_type,quantity", [("spot", None), ("usdm", 4), ("futures", 4)])
def test_chart_symbol_uses_the_explicit_market_type_and_survives_restore(market_type, quantity):
    revision = compile_revision({"language": "PINE_ENGINE", "name": "Instrument", "source_text": PERP_SOURCE}, now_ms=1)
    provider = PineEngineProvider()
    try:
        provider.prepare({"source": json.loads(revision["compiled_json"])["executionSource"],
            "parameters": {}, "pineChartMarketType": market_type})
        result = provider.step(frame(0, 20))
        assert (Decimal(result.payload["targetExposure"]) if result else None) == quantity
        provider.restore(provider.snapshot())
        assert provider.context["pineChartMarketType"] == market_type
        assert provider.step(frame(1, 20, position=quantity or 0)) is None
    finally:
        provider.close()


@pytest.mark.parametrize("imported", [False, True])
def test_chart_clock_uses_each_host_observation_and_restores(imported):
    source, libraries = CLOCK_SOURCE, {}
    if imported:
        source = source.replace('strategy("Partial")', 'strategy("Partial")\nimport local/Clock/1 as clock').replace("timenow", "clock.now()")
        libraries = {"local/Clock/1": '//@version=6\nlibrary("Clock")\nexport now() => timenow'}
    revision = compile_revision({"language": "PINE_ENGINE", "name": "Clock", "source_text": source, "libraries": libraries}, now_ms=1)
    context = {"source": json.loads(revision["compiled_json"])["executionSource"], "parameters": {}}
    provider, restored = PineEngineProvider(), PineEngineProvider()
    try:
        provider.prepare(context)
        assert provider.step(frame(0, 20)).payload["targetExposure"] == "4.0"
        assert provider.step(frame(1, 20, position=4)) is None
        snapshot = provider.snapshot()
        assert snapshot["execution_times"] == [59999, 119999]
        restored.restore(snapshot)
        assert provider.step(frame(2, 20, position=4)) == restored.step(frame(2, 20, position=4))
        assert provider.snapshot()["execution_times"] == [59999, 119999, 179999]
    finally:
        provider.close()
        restored.close()


def test_percentage_close_uses_actual_host_quantity_and_restores():
    revision = compile_revision({"language": "PINE_ENGINE", "name": "Partial", "source_text": PARTIAL_SOURCE}, now_ms=1)
    context = {"source": json.loads(revision["compiled_json"])["executionSource"], "parameters": {}}
    provider, restored = PineEngineProvider(), PineEngineProvider()
    try:
        provider.prepare(context)
        assert provider.step(frame(0, 20)).payload["targetExposure"] == "4.0"
        assert provider.step(frame(1, 20, position=8)) is None
        restored.restore(provider.snapshot())
        # Actual ledger position differs from the requested four units.
        close = provider.step(frame(2, 20, position=8))
        assert Decimal(close.payload["targetExposure"]) == 6
        assert restored.step(frame(2, 20, position=8)) == close
        assert provider.step(frame(3, 20)) is None
        assert provider.step(frame(4, 20)) is None
    finally:
        provider.close()
        restored.close()


def test_imported_strategy_freezes_library_content_and_restores_actual_account_execution():
    revisions = [compile_revision({"language": "PINE_ENGINE", "name": "Import", "source_text": LIBRARY_SOURCE,
        "libraries": {"local/Threshold/1": lib}}, now_ms=1)
        for lib in (LIBRARY, LIBRARY.replace("x * 2", "x * 3"))]
    assert revisions[0]["dependency_hash"] != revisions[1]["dependency_hash"]
    assert revisions[0]["compiled_hash"] != revisions[1]["compiled_hash"]
    providers = [PineEngineProvider(), PineEngineProvider()]
    try:
        for provider, revision in zip(providers, revisions, strict=True):
            execution_source = json.loads(revision["compiled_json"])["executionSource"]
            assert "local/Threshold/1" in json.loads(execution_source)["libraries"]
            provider.prepare({"source": execution_source, "parameters": {}})
        assert providers[0].step(frame(0, 20)).payload["targetExposure"] == "2.0"
        assert providers[1].step(frame(0, 20)) is None
        snapshot = providers[0].snapshot()
        providers[0].restore(snapshot)
        assert providers[0].step(frame(1, 20, position=2)) is None
    finally:
        for provider in providers:
            provider.close()


def frame(index, close, position=0):
    return ObservationFrame(
        "pine",
        index + 1,
        (index + 1) * 60000 - 1,
        (index + 1) * 60000 - 1,
        "EVALUATION",
        {"venue": "binance", "symbol": "BTCUSDT"},
        "input",
        bar={
            "open_time_ms": index * 60000,
            "close_time_ms": (index + 1) * 60000 - 1,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 10,
        },
        account_view={
            "position_size": position,
            "position_avg_price": 20 if position else None,
            "equity": 10000,
            "initial_capital": 10000,
            "netprofit": 0,
            "openprofit": 0,
        },
    )


def test_real_engine_runs_arbitrary_sma_with_actual_account_and_restores():
    revision = compile_revision(
        {"language": "PINE_ENGINE", "name": "SMA", "source_text": SOURCE}, now_ms=1
    )
    execution_source = json.loads(revision["compiled_json"])["executionSource"]
    provider, restored = PineEngineProvider(), PineEngineProvider()
    try:
        provider.prepare({"source": execution_source, "parameters": {}})
        assert provider.step(frame(0, 10)) is None
        opened = provider.step(frame(1, 20))
        assert opened.payload["targetExposure"] == "2.0"
        restored.restore(provider.snapshot())
        closed = provider.step(frame(2, 5, position=2))
        assert closed.payload["targetExposure"] == "0"
        assert restored.step(frame(2, 5, position=2)) == closed
        assert provider.identity()["runtime"]["adapter"] == "pine-chart/4"
    finally:
        provider.close()
        restored.close()


@pytest.mark.parametrize("flag", ["calc_on_every_tick"])
def test_native_broker_and_intrabar_profiles_are_not_silently_downgraded(flag):
    with pytest.raises(StrategyProviderError, match="FIDELITY_UNSUPPORTED"):
        analyze(SOURCE.replace('strategy("SMA")', f'strategy("SMA", {flag}=true)'))
    with pytest.raises(StrategyProviderError, match="FIDELITY_UNSUPPORTED"):
        analyze(SOURCE + '\nstrategy.risk.max_position_size(3)\n')


def test_runtime_identity_change_requires_recompile():
    receipt = analyze(SOURCE)
    identity = {**receipt["identity"], "adapter": "different"}
    provider = PineEngineProvider()
    with pytest.raises(StrategyProviderError, match="IDENTITY_MUTATION"):
        provider.prepare(
            {
                "source": json.dumps(
                    {"schema": SOURCE_SCHEMA, "source": SOURCE, "identity": identity}
                )
            }
        )


def test_host_account_is_required_and_not_inferred_from_previous_intents():
    receipt = analyze(SOURCE)
    provider = PineEngineProvider()
    try:
        provider.prepare(
            {
                "source": json.dumps(
                    {
                        "schema": SOURCE_SCHEMA,
                        "source": SOURCE,
                        "identity": receipt["identity"],
                    }
                )
            }
        )
        with pytest.raises(StrategyProviderError, match="authoritative Host account"):
            provider.step(replace(frame(0, 10), account_view={}))
    finally:
        provider.close()


@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.parametrize("source,quantities", [(SOURCE, [2, 2]), (PARTIAL_SOURCE, [4, 1, 3]), (CLOCK_SOURCE, [4, 1, 3]), (PERP_SOURCE, [4, 1, 3])])
def test_chart_workspace_compiles_smokes_and_runs_through_host_ledger(
    tmp_path, monkeypatch, isolated, source, quantities
):
    from app.market_dataset.snapshot import MarketEvent

    from tests.test_backtest_chart_pyne import _service

    service = _service(tmp_path)
    provider = PineEngineProvider()
    try:
        revision = service.create_strategy_revision(
            {"language": "PINE_ENGINE", "name": "SMA Host", "source_text": source}
        )
        payload = {
            "strategy_revision_id": revision["revision_id"],
            "dataset_id": "local-pine",
            "data_epoch": "epoch-20261019",
            "snapshot_hash": "sha256:snapshot",
            "fidelity_mode": "BAR_APPROX",
            "source_event_kind": "BAR",
            "start_time_ms": 0,
            "end_time_ms": 600000,
            "symbol": "BTCUSDT",
            "interval": "1m",
            "parameters": {},
            "output_mode": "TARGET_POSITION",
            "initial_balance": "10000",
            "account_model": "LINEAR_PERP_ONE_WAY_V1",
            "slippage_bps": "0",
            "taker_fee_bps": "0",
            "exchange": "binance",
            "market_type": "usdm",
        }
        service.smoke_strategy_revision(str(revision["revision_id"]), payload, now_ms=2)
        run = service.create_run(payload, idempotency_key="pine-chart", now_ms=3)
        events = tuple(
            MarketEvent(
                sequence=i + 1,
                event_time_ms=(i + 1) * 60000 - 1,
                role="BARS",
                payload={
                    "open_time_ms": i * 60000,
                    "close_time_ms": (i + 1) * 60000 - 1,
                    **{key: str(value) for key in ("open", "high", "low", "close")},
                    "volume": "100",
                },
            )
            for i, value in enumerate([10, 20, 20, 5, 5, 5, 5])
        )
        if isolated:
            from app.backtest.strategy.isolated import IsolatedStrategyProvider
            from app.backtest.strategy.pine_engine import REVISION

            provider = IsolatedStrategyProvider(REVISION, step_timeout_s=5)
        completed = service.execute_bar_run(
            str(run["run_id"]),
            events=events,
            provider=provider,
            now_ms=4,
            observation_market={"venue": "binance", "symbol": "BTCUSDT"},
        )
        assert completed["state"] == "COMPLETED"
        fills = completed["report"]["fills"]
        assert [str(row["side"]) for row in fills] == ["BUY", *(["SELL"] * (len(quantities) - 1))]
        assert [float(row["qty"]) for row in fills] == quantities
    finally:
        provider.close()
        service.shutdown()
