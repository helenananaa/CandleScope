"""S1: one builtin indicator, one bar, one value -- across every consumer path.

A builtin's value at a bar should be a pure function of the series, the
definition and parameters, and the bar time. These tests feed the same
canonical bars through each production seed policy and compare:

  reference  IndicatorEngine.compute over the whole series (converged anchor)
  local      local_data.compute_local_indicator_batch (whole imported dataset)
  chart      api.v1.indicator_range_batch: start - warmup, one shared bar query
             per batch, results cached by IndicatorRangeResultService
  realtime   IndicatorEngine.subscribe seeded with the client's historyLimit
             (the process owner runs this same engine out of process)
  alerts     the numeric history worker over alerts.indicator_requests slots

Window-only builtins (MA, BOLL, VOL) are path independent. Recursive builtins
(EMA, RSI, ATR, MACD) are not: their value near the start of a computation
depends on where that computation began. Those cases are strict xfails until a
canonical seed lands, so they turn red as soon as the behaviour changes.

Run ``python -m tests.test_indicator_seed_consistency`` from ``backend`` for
the divergence table.
"""
from __future__ import annotations

import asyncio
import random
import statistics
from types import SimpleNamespace

import pytest

from app.alerts.indicator_requests import ALIASES, request_for
from app.api.v1.indicator_range_batch import (
    IndicatorRangeBatchJob,
    compute_indicator_range_batch_async,
)
from app.api.v1.stream_indicator_payloads import confirmed_indicator_seed_bars
from app.core import config
from app.data_engine.data_manager.models import BarData
from app.indicator import create_engine
from app.indicator.engine import indicator_code_hash
from app.indicator.history_worker import _dispatch
from app.indicator.range_result_service import IndicatorRangeResultService
from app.indicator.series_revision import SeriesRevisionRegistry
from app.indicator.types import IndicatorKey
from app.indicator.warmup import indicator_warmup_bars
from app.local_data.indicator_compute import compute_local_indicator_batch

SYMBOL, INTERVAL, EXCHANGE, MARKET = "BTCUSDT", "1m", "binance", "spot"
STEP = 60
BAR_COUNT = 2_600
# One chart page, and the backend default WS historyLimit.
CHART_BARS = 500
# frontend INDICATOR_HISTORY_LIMIT caps the realtime seed a chart can request.
FRONTEND_HISTORY_CAP = 2_000
# Payloads round values to 8 decimals.
WIRE_TOLERANCE = 2e-8
LEFT_EDGE_BARS = 50

INDICATORS = {
    "MA20": ("MA", {"period": 20, "source": "close"}),
    "BOLL20": ("BOLL", {"period": 20, "mult": 2.0, "source": "close"}),
    "VOL": ("VOL", {}),
    "EMA20": ("EMA", {"period": 20, "source": "close"}),
    "EMA200": ("EMA", {"period": 200, "source": "close"}),
    "RSI14": ("RSI", {"period": 14, "source": "close"}),
    "ATR14": ("ATR", {"period": 14}),
    "MACD": ("MACD", {"fast": 12, "slow": 26, "signal": 9, "source": "close"}),
}
WINDOW_ONLY = ("MA20", "BOLL20", "VOL")
RECURSIVE = ("EMA20", "EMA200", "RSI14", "ATR14", "MACD")
# A long EMA is the common chart partner with the largest warmup (5 x 200).
BATCH_PARTNER = "EMA200"
ALERT_LABELS = {"rsi": ("RSI14", "rsi"), "macdHist": ("MACD", "hist"), "ma20": ("MA20", "ma")}

SeriesValues = dict[str, dict[int, float]]


def market_bars(count: int = BAR_COUNT, seed: int = 20261111) -> list[BarData]:
    """Deterministic 1m random walk with BTC-like price and candle sizes."""
    rng = random.Random(seed)
    start = 1_760_000_000 - 1_760_000_000 % STEP
    price, bars = 60_000.0, []
    for index in range(count):
        open_ = round(price, 2)
        close = round(open_ * (1 + rng.gauss(0, 0.001)), 2)
        high = round(max(open_, close) * (1 + abs(rng.gauss(0, 0.0004))), 2)
        low = round(min(open_, close) * (1 - abs(rng.gauss(0, 0.0004))), 2)
        bars.append(BarData(
            time=start + index * STEP, open=open_, high=max(high, open_, close),
            low=min(low, open_, close), close=close,
            volume=round(rng.uniform(1, 50), 4), is_closed=True,
        ))
        price = close
    return bars


def meta(label: str) -> dict:
    name, params = INDICATORS[label]
    key = IndicatorKey(SYMBOL, INTERVAL, name, params, exchange=EXCHANGE,
                       market_type=MARKET, code_hash=indicator_code_hash(name))
    return {"kind": "builtin", "exchange": EXCHANGE, "market_type": MARKET,
            "symbol": SYMBOL, "interval": INTERVAL, "name": name,
            "params": dict(params), "indicatorId": key.uid}


def _lines(lines: list[dict]) -> SeriesValues:
    return {
        line["outputName"]: {
            int(point["time"]): float(point["value"])
            for point in line["data"] if point.get("value") is not None
        }
        for line in lines
    }


def _payload_lines(payload: dict) -> SeriesValues:
    assert payload.get("ok") is True, payload.get("error")
    return _lines(payload["lines"])


def _engine_lines(result) -> SeriesValues:
    assert result is not None and not result.error, getattr(result, "error", None)
    return _lines(list(result.to_dict()["outputs"].values()))


# --- consumer paths -------------------------------------------------------

def reference(bars: list[BarData], label: str) -> SeriesValues:
    name, params = INDICATORS[label]
    engine = create_engine()
    try:
        return _engine_lines(engine.compute(
            SYMBOL, INTERVAL, MARKET, name, dict(params), list(bars), exchange=EXCHANGE))
    finally:
        engine.stop()


def local_dataset(bars: list[BarData], label: str) -> SeriesValues:
    name, params = INDICATORS[label]
    rows = [{"time": bar.time, "open": bar.open, "high": bar.high, "low": bar.low,
             "close": bar.close, "volume": bar.volume} for bar in bars]
    batch = compute_local_indicator_batch(
        dataset_id="s1-dataset", data_epoch="s1", symbol=SYMBOL, interval=INTERVAL,
        volume_available=True, rows=rows,
        requests=[{"jobKey": "s1", "clientId": "s1", "name": name, "params": dict(params)}],
    )
    return _payload_lines(batch["results"][0]["payload"])


class _WindowDataManager:
    """Storage stand-in that honours the window and limit the API queries."""

    def __init__(self, bars: list[BarData]) -> None:
        self.bars = bars

    def query(self, symbol, interval, *, start_ms, end_ms, limit, **_kwargs):
        window = [bar for bar in self.bars if start_ms <= bar.time * 1000 <= end_ms]
        return SimpleNamespace(bars=window[-limit:], missing_ranges=[], metadata={})


def range_service() -> IndicatorRangeResultService:
    return IndicatorRangeResultService(
        enabled=True, max_entries=64, ttl_seconds=600,
        revision_registry=SeriesRevisionRegistry(server_epoch="s1"),
    )


async def chart_async(bars, labels, start, end, service) -> list[tuple[SeriesValues, bool]]:
    jobs = [IndicatorRangeBatchJob(client_id=label.lower(), meta=meta(label),
                                   start=start, end=end, reason="s1") for label in labels]
    results = await compute_indicator_range_batch_async(
        dm=_WindowDataManager(bars), jobs=jobs, range_service=service)
    for item in results:
        if isinstance(item, BaseException):
            raise item
    return [(_payload_lines(item), bool(item.get("cacheHit"))) for item in results]


def chart(bars, labels, start=None, end=None) -> dict[str, SeriesValues]:
    start = bars[-CHART_BARS].time if start is None else start
    end = bars[-1].time if end is None else end
    results = asyncio.run(chart_async(bars, labels, start, end, range_service()))
    return {label: values for label, (values, _) in zip(labels, results)}


def realtime(bars: list[BarData], label: str, history_limit: int) -> SeriesValues:
    name, params = INDICATORS[label]
    seed = confirmed_indicator_seed_bars(bars)[-history_limit:]
    engine = create_engine()
    try:
        _, result = engine.subscribe(
            SYMBOL, INTERVAL, MARKET, name, dict(params), bars=seed,
            exchange=EXCHANGE, desired_seed_bars=history_limit)
        return _engine_lines(result)
    finally:
        engine.stop()


def alerts(bars: list[BarData]) -> dict[str, float]:
    """Latest alert values keyed by alert field, via the worker's numeric path."""
    target = {"symbol": SYMBOL, "interval": INTERVAL, "exchange": EXCHANGE,
              "marketType": MARKET}
    request = request_for(target, tuple(ALIASES))
    source = {"symbol": SYMBOL, "interval": INTERVAL, "market_type": MARKET,
              "exchange": EXCHANGE}
    seed = confirmed_indicator_seed_bars(bars)[-request.source_slots:]
    values, _ = _dispatch(("numeric", request.outputs, source, seed))
    return {field: float(values[ALIASES[field]]) for field in ALIASES}


# --- comparison -------------------------------------------------------------

def deltas(candidate: SeriesValues, expected: SeriesValues, times) -> list[float]:
    found = []
    for output, series in expected.items():
        for time in times:
            if time in series and time in candidate.get(output, {}):
                found.append(abs(candidate[output][time] - series[time]))
    return found


def max_delta(candidate: SeriesValues, expected: SeriesValues, times) -> float:
    found = deltas(candidate, expected, times)
    assert found, "no overlapping values to compare"
    return max(found)


@pytest.fixture(scope="module")
def bars() -> list[BarData]:
    return market_bars()


@pytest.fixture(autouse=True)
def in_process_history(monkeypatch):
    # Same arithmetic as the history process pool, without spawning it.
    monkeypatch.setattr(config, "INDICATOR_HISTORY_PROCESS_ENABLED", False)


def _range_times(bars, count=CHART_BARS):
    return [bar.time for bar in bars[-count:]]


# --- paths that already agree ----------------------------------------------

@pytest.mark.parametrize("label", tuple(INDICATORS))
def test_local_dataset_matches_converged_reference(bars, label):
    times = [bar.time for bar in bars]
    assert max_delta(local_dataset(bars, label), reference(bars, label), times) <= WIRE_TOLERANCE


@pytest.mark.parametrize("label", WINDOW_ONLY)
def test_window_only_builtins_are_path_independent(bars, label):
    expected, times = reference(bars, label), _range_times(bars)
    charted = chart(bars, (label, BATCH_PARTNER))
    assert max_delta(chart(bars, (label,))[label], expected, times) <= WIRE_TOLERANCE
    assert max_delta(charted[label], expected, times) <= WIRE_TOLERANCE
    assert max_delta(realtime(bars, label, CHART_BARS), expected, times) <= WIRE_TOLERANCE


@pytest.mark.parametrize("label", ("EMA20", "RSI14", "ATR14", "MACD"))
def test_short_memory_builtins_agree_at_latest_closed_bar(bars, label):
    """Guard: with a full page of history the newest value has converged."""
    expected, latest = reference(bars, label), [bars[-1].time]
    assert max_delta(chart(bars, (label,))[label], expected, latest) <= WIRE_TOLERANCE
    assert max_delta(realtime(bars, label, CHART_BARS), expected, latest) <= WIRE_TOLERANCE


def _alert_matches_chart(bars, field):
    label, output = ALERT_LABELS[field]
    alert = alerts(bars)[field]
    shown = chart(bars, (label,))[label][output][bars[-1].time]
    assert abs(alert - shown) <= WIRE_TOLERANCE, (field, alert, shown)


@pytest.mark.parametrize("field", ("rsi", "ma20"))
def test_alert_values_match_chart_at_latest_closed_bar(bars, field):
    """Guard: alert fields equal what the chart shows for the newest bar."""
    _alert_matches_chart(bars, field)


# --- known divergence: strict xfails until a canonical seed lands ------------

SEED_XFAIL = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S1: builtin results depend on where each computation started (fix: S4 canonical seed)",
)


@SEED_XFAIL
def test_alert_macd_histogram_matches_chart_at_latest_closed_bar(bars):
    """Alerts seed MACD from 250 slots, the chart from its page plus warmup;
    the newest histogram value differs (~5e-7 here: invisible, not identical)."""
    _alert_matches_chart(bars, "macdHist")


@SEED_XFAIL
@pytest.mark.parametrize("label", RECURSIVE)
def test_chart_page_left_edge_matches_converged_value(bars, label):
    """The first bars of every range request (initial load, scroll-left page,
    jump-to-date window) are computed from only ``indicator_warmup_bars``."""
    edge = _range_times(bars)[:LEFT_EDGE_BARS]
    assert max_delta(chart(bars, (label,))[label], reference(bars, label), edge) <= WIRE_TOLERANCE


@SEED_XFAIL
def test_scrolled_left_pages_stitch_without_a_seam(bars):
    """Scrolling left, the frontend scheduler requests only ``desired - cached``
    (indicatorRangeScheduler.ts), so the older page ends where the cached page
    began. Each page is seeded from its own start, and the cached page's
    under-warmed first bars are never recomputed: the stitched line steps."""
    newer_start = bars[-CHART_BARS].time
    older = chart(bars, ("RSI14",), bars[-2 * CHART_BARS].time, newer_start - STEP)["RSI14"]
    newer = chart(bars, ("RSI14",), newer_start, bars[-1].time)["RSI14"]
    stitched = {output: {**older[output], **newer[output]} for output in newer}
    one_shot = chart(bars, ("RSI14",), bars[-2 * CHART_BARS].time, bars[-1].time)["RSI14"]
    seam = [bar.time for bar in bars[-CHART_BARS - 5:-CHART_BARS + LEFT_EDGE_BARS]]
    assert max_delta(stitched, one_shot, seam) <= WIRE_TOLERANCE


@SEED_XFAIL
def test_chart_value_does_not_depend_on_batch_partners(bars):
    """A batch shares one bar query seeded by its largest warmup, so RSI's
    values change when the chart also shows a long EMA."""
    edge = _range_times(bars)[:LEFT_EDGE_BARS]
    alone = chart(bars, ("RSI14",))["RSI14"]
    together = chart(bars, ("RSI14", BATCH_PARTNER))["RSI14"]
    assert max_delta(alone, together, edge) <= WIRE_TOLERANCE


@SEED_XFAIL
def test_cached_chart_value_does_not_depend_on_request_order(bars):
    """The range cache key omits the seed origin, so an identical request is
    answered from whichever earlier batch happened to compute it."""
    start, end = bars[-CHART_BARS].time, bars[-1].time
    edge = _range_times(bars)[:LEFT_EDGE_BARS]

    async def run():
        fresh = (await chart_async(bars, ("RSI14",), start, end, range_service()))[0]
        service = range_service()
        await chart_async(bars, ("RSI14", BATCH_PARTNER), start, end, service)
        reused = (await chart_async(bars, ("RSI14",), start, end, service))[0]
        return fresh, reused

    (fresh, fresh_hit), (reused, reused_hit) = asyncio.run(run())
    assert (fresh_hit, reused_hit) == (False, True)
    assert max_delta(fresh, reused, edge) <= WIRE_TOLERANCE


@SEED_XFAIL
def test_realtime_long_ema_matches_chart_history_at_latest_bar(bars):
    """A realtime instance is seeded with the chart's loaded bar count, which
    is too short for EMA200 to converge, so the live tail steps away from the
    historical line where they meet."""
    latest = [bars[-1].time]
    charted = chart(bars, ("EMA200",))["EMA200"]
    assert max_delta(realtime(bars, "EMA200", CHART_BARS), charted, latest) <= WIRE_TOLERANCE


# --- divergence table ---------------------------------------------------------

def divergence_rows(bars: list[BarData]) -> list[dict]:
    candle = statistics.median(bar.high - bar.low for bar in bars)
    edge, latest = _range_times(bars)[:LEFT_EDGE_BARS], [bars[-1].time]
    rows = []
    for label in (*WINDOW_ONLY, *RECURSIVE):
        name, params = INDICATORS[label]
        expected = reference(bars, label)
        alone = chart(bars, (label,))[label]
        partner = alone if label == BATCH_PARTNER else chart(bars, (label, BATCH_PARTNER))[label]
        rows.append({
            "label": label,
            "warmup": indicator_warmup_bars(name, params),
            "chart_edge": max_delta(alone, expected, edge),
            "chart_edge_batched": max_delta(partner, expected, edge),
            "realtime_500_latest": max_delta(realtime(bars, label, CHART_BARS), expected, latest),
            "realtime_2000_latest": max_delta(
                realtime(bars, label, FRONTEND_HISTORY_CAP), expected, latest),
            "unit": "points" if label == "RSI14" else ("volume" if label == "VOL" else "price"),
            "candle": candle,
        })
    return rows


def _format(value: float, row: dict) -> str:
    if value <= WIRE_TOLERANCE:
        return "0"
    if row["unit"] == "price":
        return f"{value:.4g} ({value / row['candle']:.1%} of candle)"
    return f"{value:.4g}"


def main() -> None:
    config.INDICATOR_HISTORY_PROCESS_ENABLED = False
    sample = market_bars()
    rows = divergence_rows(sample)
    print(f"{BAR_COUNT} bars; chart page = last {CHART_BARS}; left edge = first "
          f"{LEFT_EDGE_BARS} bars of the page; median candle = {rows[0]['candle']:.2f}")
    print("| builtin | warmup | chart edge | chart edge, batched w/ EMA200 "
          "| realtime(500) latest | realtime(2000) latest |")
    print("|---|---:|---|---|---|---|")
    columns = ("chart_edge", "chart_edge_batched", "realtime_500_latest", "realtime_2000_latest")
    for row in rows:
        cells = " | ".join(_format(row[key], row) for key in columns)
        print(f"| {row['label']} | {row['warmup']} | {cells} |")


if __name__ == "__main__":
    main()
