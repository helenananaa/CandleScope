from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.api.v1 import stream_indicator_payloads as payload_api
from app.data_engine.data_manager.models import BarData
from app.indicator.runtimes import PINE_COMPAT_RUNTIME_ID
from app.indicator.runtimes import ScriptRuntimeContext
from app.indicator.runtimes import pine_compat_adapter as pine_adapter

from app.indicator.runtimes.pine_history import (
    PINE_HISTORY_MODE_AVAILABLE,
    PINE_HISTORY_MODE_BOUNDED,
    PineHistoryPlan,
    plan_pine_history,
)


def _analysis(*features: str, inputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "compatibility": {
            "supported": [{"feature": feature} for feature in features],
            "unsupported": [],
            "legacyTranslations": [],
        },
        "inputs": list(inputs or []),
    }


def test_pointwise_and_constant_history_scripts_use_bounded_plans() -> None:
    pointwise = plan_pine_history(
        '//@version=6\nindicator("Close")\nplot(close)',
        analysis=_analysis("indicator", "plot"),
    )
    offset = plan_pine_history(
        '//@version=6\nindicator("Offset", max_bars_back=1200)\nplot(close[1000])',
        analysis=_analysis("indicator", "plot"),
    )

    assert pointwise.mode == PINE_HISTORY_MODE_BOUNDED
    assert pointwise.warmup_bars == 0
    assert offset.mode == PINE_HISTORY_MODE_BOUNDED
    assert offset.max_constant_offset == 1000
    assert offset.warmup_bars == 1200


def test_bounded_ta_lookback_uses_effective_input_override() -> None:
    script = (
        '//@version=6\nindicator("SMA")\n'
        'length = input.int(20)\nplot(ta.sma(close, length))'
    )
    analysis = _analysis(
        "indicator",
        "input.int",
        "ta.sma",
        "plot",
        inputs=[{"callSiteId": 7, "name": "input.int", "default": 20}],
    )

    default_plan = plan_pine_history(script, analysis=analysis)
    overridden_plan = plan_pine_history(script, analysis=analysis, params={"7": 80})

    assert default_plan.mode == PINE_HISTORY_MODE_BOUNDED
    assert default_plan.warmup_bars == 20
    assert overridden_plan.warmup_bars == 80


def test_hma_bounded_plan_includes_its_second_smoothing_window() -> None:
    plan = plan_pine_history(
        '//@version=6\nindicator("HMA")\nplot(ta.hma(close, 20))',
        analysis=_analysis("indicator", "ta.hma", "plot"),
    )

    assert plan.mode == PINE_HISTORY_MODE_BOUNDED
    assert plan.warmup_bars == 24


def test_stateful_and_recursive_scripts_require_local_available_history() -> None:
    cumulative = plan_pine_history(
        '//@version=6\nindicator("Cum")\nplot(ta.cum(volume))',
        analysis=_analysis("indicator", "ta.cum", "plot"),
    )
    recursive = plan_pine_history(
        '//@version=6\nindicator("Recursive")\nvar float total = 0\n'
        'total := total + close\nplot(total)',
        analysis=_analysis("indicator", "plot"),
    )

    assert cumulative.mode == PINE_HISTORY_MODE_AVAILABLE
    assert cumulative.features == ("ta.cum",)
    assert recursive.mode == PINE_HISTORY_MODE_AVAILABLE
    assert set(recursive.reasons) == {"persistent-state", "series-reassignment"}


def test_dataset_origin_builtins_require_local_available_history() -> None:
    for expression in ("bar_index", "barstate.isfirst ? close : na"):
        plan = plan_pine_history(
            f'//@version=6\nindicator("Origin")\nplot({expression})',
            analysis=_analysis("indicator", "plot"),
        )
        assert plan.mode == PINE_HISTORY_MODE_AVAILABLE


def test_dataset_end_builtins_require_complete_local_history() -> None:
    for expression in (
        "last_bar_index",
        "last_bar_time",
        "barstate.islast ? close : na",
        "barstate.islastconfirmedhistory ? close : na",
    ):
        plan = plan_pine_history(
            f'//@version=6\nindicator("End")\nplot({expression})',
            analysis=_analysis("indicator", "plot"),
        )
        assert plan.mode == PINE_HISTORY_MODE_AVAILABLE
        assert plan.requires_latest_history is True
        assert plan.to_dict()["historyScope"] == "local-full-history"


def test_tuple_destructuring_is_not_misread_as_dynamic_history() -> None:
    plan = plan_pine_history(
        '//@version=6\nindicator("MACD")\n[a, b, c] = ta.macd(close, 12, 26, 9)\nplot(a)',
        analysis=_analysis("indicator", "ta.macd", "plot"),
    )

    assert plan.has_dynamic_offsets is False
    assert plan.mode == PINE_HISTORY_MODE_AVAILABLE


def test_comments_strings_and_plan_round_trip_preserve_contract() -> None:
    plan = plan_pine_history(
        '//@version=6\nindicator("close[900] ta.cum")\n'
        '// plot(close[800])\nplot(close[2])',
        analysis=_analysis("indicator", "plot"),
    )

    assert plan.max_constant_offset == 2
    assert plan.mode == PINE_HISTORY_MODE_BOUNDED
    assert PineHistoryPlan.from_dict(plan.to_dict()) == plan


def _bars(count: int = 1000) -> list[BarData]:
    return [
        BarData(
            time=1_700_000_000 + index * 60,
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=float(index + 1),
            is_closed=True,
        )
        for index in range(count)
    ]


class _RangeDataManager:
    history_policy = None

    def __init__(self, bars: list[BarData]) -> None:
        self.bars = bars
        self.query_kwargs: list[dict[str, Any]] = []

    def get_bounds(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {
            "cache_earliest": self.bars[0].time,
            "cache_latest": self.bars[-1].time,
            "cache_count": len(self.bars),
            "storage_earliest_ms": self.bars[0].time_ms,
            "storage_latest_ms": self.bars[-1].time_ms,
            "storage_count": len(self.bars),
        }

    def query(self, *args: Any, **kwargs: Any) -> Any:
        del args
        self.query_kwargs.append(dict(kwargs))
        start_s = int(kwargs["start_ms"]) // 1000
        end_s = int(kwargs["end_ms"]) // 1000
        selected = [bar for bar in self.bars if start_s <= bar.time <= end_s]
        return SimpleNamespace(
            bars=selected,
            missing_ranges=[],
            metadata={},
            history_state="ready",
            complete=True,
            retryable=False,
            terminal_reason=None,
            earliest_available_ms=self.bars[0].time_ms,
            availability_revision="test-history",
            excluded_ranges=[],
        )

    def query_latest(self, *args: Any, **kwargs: Any) -> Any:
        del args
        limit = max(1, int(kwargs["limit"]))
        return SimpleNamespace(bars=self.bars[-limit:], missing_ranges=[], metadata={})


def _pine_meta(script: str, plan: PineHistoryPlan) -> dict[str, Any]:
    return {
        "kind": "script",
        "runtime": PINE_COMPAT_RUNTIME_ID,
        "exchange": "binance",
        "market_type": "spot",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "name": "History",
        "script": script,
        "params": {},
        "renderHints": {},
        "indicatorId": "pine-history-test",
        "pineHistoryPlan": plan.to_dict(),
    }


def test_available_history_query_anchors_at_local_series_origin() -> None:
    bars = _bars()
    dm = _RangeDataManager(bars)
    script = '//@version=6\nindicator("Cum")\nplot(ta.cum(volume))'
    plan = plan_pine_history(script, analysis=_analysis("indicator", "ta.cum", "plot"))
    target = bars[-100:]

    selected = payload_api._query_indicator_compute_bars(
        dm,
        _pine_meta(script, plan),
        target[0].time,
        target[-1].time,
        warmup_bars=plan.warmup_bars,
    )

    assert selected == bars
    assert dm.query_kwargs[0]["start_ms"] == bars[0].time_ms


def test_dataset_end_query_extends_a_middle_range_through_local_latest_bar() -> None:
    bars = _bars()
    dm = _RangeDataManager(bars)
    script = '//@version=6\nindicator("Last")\nplot(last_bar_index)'
    plan = plan_pine_history(script, analysis=_analysis("indicator", "plot"))
    target = bars[400:500]

    selected = payload_api._query_indicator_compute_bars(
        dm,
        _pine_meta(script, plan),
        target[0].time,
        target[-1].time,
        warmup_bars=0,
    )

    assert selected == bars
    assert dm.query_kwargs[0]["start_ms"] == bars[0].time_ms
    assert dm.query_kwargs[0]["end_ms"] == bars[-1].time_ms


def test_available_history_query_fails_closed_above_execution_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _bars()
    dm = _RangeDataManager(bars)
    script = '//@version=6\nindicator("Cum")\nplot(ta.cum(volume))'
    plan = plan_pine_history(script, analysis=_analysis("indicator", "ta.cum", "plot"))
    monkeypatch.setattr(payload_api.config, "PINE_MAX_BARS", 500)

    with pytest.raises(ValueError, match="available-history seed requires 1000 bars"):
        payload_api._query_indicator_compute_bars(
            dm,
            _pine_meta(script, plan),
            bars[-100].time,
            bars[-1].time,
            warmup_bars=0,
        )


def test_available_history_query_fails_closed_without_a_provable_origin() -> None:
    bars = _bars()
    dm = _RangeDataManager(bars)
    dm.get_bounds = lambda *args, **kwargs: {}
    script = '//@version=6\nindicator("Cum")\nplot(ta.cum(volume))'
    plan = plan_pine_history(script, analysis=_analysis("indicator", "ta.cum", "plot"))

    with pytest.raises(RuntimeError, match="origin is not available"):
        payload_api._query_indicator_compute_bars(
            dm,
            _pine_meta(script, plan),
            bars[-100].time,
            bars[-1].time,
            warmup_bars=0,
        )


def test_cumulative_range_execution_keeps_origin_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = pine_adapter.PineCompatRuntimeAdapter().descriptor()
    if not descriptor.available:
        pytest.skip(descriptor.reason or "pine-compatible runtime unavailable")
    bars = _bars()
    dm = _RangeDataManager(bars)
    script = '//@version=6\nindicator("Cum")\nplot(ta.cum(volume))'
    plan = pine_adapter.plan_pine_script_history(script)
    meta = _pine_meta(script, plan)
    target = bars[-100:]
    monkeypatch.setattr(pine_adapter.config, "PINE_EXECUTOR_MODE", "inline")

    selected = payload_api._query_indicator_compute_bars(
        dm,
        meta,
        target[0].time,
        target[-1].time,
        warmup_bars=plan.warmup_bars,
    )
    patch = payload_api._compute_pine_range_patch_from_bars(
        "pine-history-test",
        meta,
        target[0].time,
        target[-1].time,
        selected,
        target_bars=len(target),
    )

    assert patch["historyPlan"]["mode"] == PINE_HISTORY_MODE_AVAILABLE
    assert patch["warmupBars"] == 900
    assert patch["lines"][0]["data"][-1]["value"] == pytest.approx(500_500.0)


def test_hma_bounded_range_matches_full_history_at_target_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = pine_adapter.PineCompatRuntimeAdapter().descriptor()
    if not descriptor.available:
        pytest.skip(descriptor.reason or "pine-compatible runtime unavailable")
    bars = _bars()
    script = '//@version=6\nindicator("HMA")\nplot(ta.hma(close, 20))'
    plan = pine_adapter.plan_pine_script_history(script)
    meta = _pine_meta(script, plan)
    target = bars[-100:]
    seed = bars[-(len(target) + plan.warmup_bars):]
    monkeypatch.setattr(pine_adapter.config, "PINE_EXECUTOR_MODE", "inline")

    full = pine_adapter.PineCompatRuntimeAdapter().execute(
        script=script,
        ohlcv=[bar.to_dict() for bar in bars],
        params={},
        render_hints={},
        context=ScriptRuntimeContext("binance", "spot", "BTCUSDT", "1m"),
    )
    patch = payload_api._compute_pine_range_patch_from_bars(
        "pine-history-test",
        meta,
        target[0].time,
        target[-1].time,
        seed,
        target_bars=len(target),
    )

    full_by_time = {point["time"]: point["value"] for point in full.lines[0]["data"]}
    first = patch["lines"][0]["data"][0]
    assert first["time"] == target[0].time
    assert first["value"] == pytest.approx(full_by_time[target[0].time])


def test_dataset_end_range_does_not_treat_a_middle_patch_as_last_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = pine_adapter.PineCompatRuntimeAdapter().descriptor()
    if not descriptor.available:
        pytest.skip(descriptor.reason or "pine-compatible runtime unavailable")
    bars = _bars()
    dm = _RangeDataManager(bars)
    script = (
        '//@version=6\nindicator("Last")\n'
        'plot(last_bar_index)\nplot(barstate.islast ? 1 : 0)'
    )
    plan = pine_adapter.plan_pine_script_history(script)
    meta = _pine_meta(script, plan)
    target = bars[400:500]
    monkeypatch.setattr(pine_adapter.config, "PINE_EXECUTOR_MODE", "inline")

    seed = payload_api._query_indicator_compute_bars(
        dm,
        meta,
        target[0].time,
        target[-1].time,
        warmup_bars=0,
    )
    patch = payload_api._compute_pine_range_patch_from_bars(
        "pine-history-test",
        meta,
        target[0].time,
        target[-1].time,
        seed,
        target_bars=len(target),
    )

    assert {point["value"] for point in patch["lines"][0]["data"]} == {999.0}
    assert {point["value"] for point in patch["lines"][1]["data"]} == {0.0}
    assert patch["meta"]["historyEnd"] == {
        "time": bars[-1].time,
        "scope": "latest-local-closed-bar",
    }

    latest_target = bars[-100:]
    latest_patch = payload_api._compute_pine_range_patch_from_bars(
        "pine-history-test",
        meta,
        latest_target[0].time,
        latest_target[-1].time,
        seed,
        target_bars=len(latest_target),
    )
    assert latest_patch["lines"][1]["data"][-1] == {
        "time": bars[-1].time,
        "value": 1.0,
    }


def test_cumulative_websocket_snapshot_seeds_from_origin_and_trims_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = pine_adapter.PineCompatRuntimeAdapter().descriptor()
    if not descriptor.available:
        pytest.skip(descriptor.reason or "pine-compatible runtime unavailable")
    bars = _bars()
    dm = _RangeDataManager(bars)
    script = '//@version=6\nindicator("Cum")\nplot(ta.cum(volume))'
    plan = pine_adapter.plan_pine_script_history(script)
    meta = {
        **_pine_meta(script, plan),
        "historyLimit": 100,
        "scriptHash": "cum-history",
    }
    monkeypatch.setattr(pine_adapter.config, "PINE_EXECUTOR_MODE", "inline")

    snapshot = payload_api._compute_pine_snapshot_message(
        "pine-history-test",
        dm,
        meta,
    )

    assert snapshot["ok"] is True
    assert snapshot["seedBars"] == 1000
    assert len(snapshot["lines"][0]["data"]) == 100
    assert snapshot["lines"][0]["data"][-1]["value"] == pytest.approx(500_500.0)
    assert snapshot["meta"]["historyOrigin"] == {
        "time": bars[0].time,
        "scope": "local-available-history",
    }


def test_host_analysis_exposes_history_plan_contract() -> None:
    adapter = pine_adapter.PineCompatRuntimeAdapter()
    descriptor = adapter.descriptor()
    if not descriptor.available:
        pytest.skip(descriptor.reason or "pine-compatible runtime unavailable")

    analysis = adapter.analyze(
        script='//@version=6\nindicator("Cum")\nplot(ta.cum(volume))',
        context=ScriptRuntimeContext("binance", "spot", "BTCUSDT", "1m"),
    )

    assert analysis.host_executable is True
    assert analysis.host_compatibility["historyPlan"]["mode"] == PINE_HISTORY_MODE_AVAILABLE
    assert analysis.meta["historyPlan"] == analysis.host_compatibility["historyPlan"]
    assert descriptor.capabilities["historyPlanning"]["schemaVersion"] == 2
    assert (
        descriptor.capabilities["historyPlanning"]["latestHistoryBoundary"]
        == "latest-local-closed-bar"
    )
