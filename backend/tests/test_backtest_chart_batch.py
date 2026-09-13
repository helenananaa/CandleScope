from dataclasses import replace
from decimal import Decimal, localcontext
from types import SimpleNamespace
import math
import shutil

import pytest

from app.backtest.colocated import _GuardedProvider
from app.backtest.strategy.chart_batch import ChartBatch, SeriesWindow, build_chart_batch
from app.backtest.strategy.chart_pyne import ChartPyneStrategyProvider, CHART_PYNE_REVISION
from app.backtest.strategy.protocol import ObservationFrame, StrategyProviderSession, StrategyProviderError
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.backtest.service import BacktestService
from app.market_dataset.snapshot import MarketEvent
from scripts.strategy_benchmark_sources import SMA, RSI
from tests.test_backtest_control_plane import _settings, _payload
from tests.test_backtest_host_policy_m5 import config


BREAKOUT = '''strategy("breakout")
upper = highest(high, 20)
lower = lowest(low, 20)
if close > upper[1]
  target_position(1)
else if close < lower[1]
  target_position(0)
'''


def events(count=400):
    return tuple(MarketEvent(sequence=i, event_time_ms=(i // 2)*60000, role="BARS", payload={
        "open": str(round(100 + 10*math.sin(i/3), 5)),
        "high": str(round(100 + 10*math.sin(i/3), 5)),
        "low": str(round(100 + 10*math.sin(i/3), 5)),
        "close": str(round(100 + 10*math.sin(i/3), 5)), "volume": "10000",
    }) for i in range(1, count+1))


def session(source):
    provider = ChartPyneStrategyProvider()
    guarded = _GuardedProvider(provider, SimpleNamespace(value=0.), 2., 2.)
    result = StrategyProviderSession(guarded, run_id="same")
    result.prepare({"inputPlan": {}, "source": source, "tradeExplanationEnabled": True})
    return result


@pytest.mark.parametrize("source", [SMA, RSI, BREAKOUT])
@pytest.mark.parametrize("precision", [6, 28])
def test_batch_every_output_snapshot_and_trace_matches_reference(source, precision):
    with localcontext() as context:
        context.prec = precision
        reference, fast = session(source), session(source)
        data = events()
        lane = ChartBatch(fast.provider, fast, data, 0, 0, 17)
        for index, event in enumerate(data):
            phase = "WARMUP" if index < 17 else "EVALUATION"
            frame = ObservationFrame("same", event.sequence, event.event_time_ms, event.event_time_ms,
                                     phase, {}, "hash", bar=event.payload)
            expected = reference.warmup(frame) if phase == "WARMUP" else reference.step(frame)
            assert lane.observe(event, phase) == expected
            assert fast.snapshot() == reference.snapshot()
            if index in (15, 129, 256):
                # Resume in the middle of a speculative chunk, using only durable state.
                restored = session(source)
                restored.restore(fast.snapshot())
                fast = restored
                lane = ChartBatch(fast.provider, fast, data, event.sequence, index+1, 17)
        assert fast.close() == reference.close()


def test_batch_defers_bad_future_bar_and_rejects_backward_time():
    data = list(events(6))
    data[4] = replace(data[4], payload={**data[4].payload, "close": "NaN"})
    current = session(SMA)
    lane = ChartBatch(current.provider, current, tuple(data), 0, 0, 0)
    for event in data[:4]:
        lane.observe(event, "EVALUATION")
    assert current.snapshot()["lastSequence"] == 4
    with pytest.raises(StrategyProviderError, match="DATA_QUALITY_FAILED"):
        lane.observe(data[4], "EVALUATION")
    data = (events(6)[-1], events(6)[0])
    current = session(SMA)
    lane = ChartBatch(current.provider, current, data, 0, 0, 0)
    lane.observe(data[0], "EVALUATION")
    with pytest.raises(StrategyProviderError, match="LOOKAHEAD_VIOLATION"):
        lane.observe(data[1], "EVALUATION")


def test_batch_selector_is_exact_and_can_be_disabled(monkeypatch):
    current = session(SMA)
    data = events(3)
    assert build_chart_batch(current.provider, current, data, 0, 0, 0) is not None
    assert build_chart_batch(current.provider.provider, current, data, 0, 0, 0) is None
    assert build_chart_batch(current.provider, current, iter(data), 0, 0, 0) is None
    local_data = tuple(replace(e, payload={**e.payload, "open_time_ms": e.event_time_ms - 60000,
                                        "close_time_ms": e.event_time_ms}) for e in data)
    assert build_chart_batch(current.provider, current, local_data, 0, 0, 0) is not None
    unsupported = (replace(data[0], payload={**data[0].payload, "extra": {"nested": True}}),)
    assert build_chart_batch(current.provider, current, unsupported, 0, 0, 0) is None
    monkeypatch.setenv("BACKTEST_CHART_BATCH_ENABLED", "0")
    assert build_chart_batch(current.provider, current, data, 0, 0, 0) is None


@pytest.mark.parametrize("source", [SMA, RSI, BREAKOUT])
@pytest.mark.parametrize("policy", [False, True])
def test_full_report_and_financial_result_equal_across_spawned_lanes(tmp_path, monkeypatch, source, policy):
    settings = _settings(tmp_path, BACKTEST_TRADE_EXPLANATION_ENABLED="1", BACKTEST_CHECKPOINT_EVENT_INTERVAL="31")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(strategy_source=source, execution_model_revision="EXECUTION_REALISM_V2",
                                  **(config("FIXED_QTY_V1", max_notional="50") if policy else {})),
                          idempotency_key="same", now_ms=2)
    seed.shutdown()
    results = []
    for flag in ("0", "1"):
        db = tmp_path / f"lane-{flag}.db"
        shutil.copy2(settings.db_path, db)
        monkeypatch.setenv("BACKTEST_CHART_BATCH_ENABLED", flag)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        try:
            results.append(service.execute_bar_run(run["run_id"], events=events(),
                provider=IsolatedStrategyProvider(CHART_PYNE_REVISION, step_timeout_s=2), now_ms=3, warmup_events=17))
        finally:
            service.shutdown()
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["report"] == results[1]["report"]


@pytest.mark.parametrize("function", ["sma", "rsi", "highest", "lowest"])
@pytest.mark.parametrize("precision", [6, 28])
def test_window_preserves_decimal_spelling_rounding_and_equal_extrema(function, precision):
    provider = ChartPyneStrategyProvider()
    provider.prepare({"source": f'strategy("window")\nx = {function}(close, 3)\nif x > 0\n  target_position(1)'})
    values = ["1.00", "1.0", "1", "-0.00", "0", "-2", "100000000000000000000",
              "0.00000000000001", "-1.2", "3E+2", "3.00", "0E-8"] * 4
    with localcontext() as context:
        context.prec = precision
        window = SeriesWindow(provider._program.series[0], [])
        for i, value in enumerate(values):
            expected = provider._observe_bar(dict.fromkeys(("open", "high", "low", "close"), value), i+1)
            actual = window.push(Decimal(value))
            expected = provider._series_history["x"][-1]
            assert str(actual) == str(expected)


def test_sealed_trace_keeps_ordinals_without_building_discarded_rows(monkeypatch):
    from app.backtest.strategy import chart_pyne
    monkeypatch.setattr(chart_pyne, "MAX_TRADE_EXPLANATION_TRACE_BYTES", 1)
    current = session('strategy("always")\nif close > 0\n  target_position(1)')
    data = events(4)
    lane = ChartBatch(current.provider, current, data, 0, 0, 0)
    lane.observe(data[0], "EVALUATION")
    def forbidden(*args):
        raise AssertionError("discarded trace must not be built")
    monkeypatch.setattr(current.provider.provider, "_decision_variables", forbidden)
    for event in data[1:]:
        lane.observe(event, "EVALUATION")
    snapshot = current.snapshot()["provider"]
    assert snapshot["tradeExplanationDropped"] == 4
    assert snapshot["decisionTraceOrdinal"] == 4
    assert snapshot["decisionTimeCounts"] == {"0": 1, "60000": 2, "120000": 1}
    assert snapshot["tradeExplanationTrace"] == []


def test_batch_calculation_and_consumption_share_step_budget(monkeypatch):
    from app.backtest.strategy import chart_batch
    current = session('strategy("always")\nif close > 0\n  target_position(1)')
    data = events(1)
    lane = ChartBatch(current.provider, current, data, 0, 0, 0)
    # 1.5 s calculation plus 0.6 s consumption exceeds a single 2 s step.
    readings = iter([0., 1.5, 10., 10.6])
    monkeypatch.setattr(chart_batch, "time", SimpleNamespace(monotonic=lambda: next(readings)))
    with pytest.raises(StrategyProviderError, match="PROVIDER_TIMEOUT"):
        lane.observe(data[0], "EVALUATION")
    assert current.provider.deadline.value == 0.
