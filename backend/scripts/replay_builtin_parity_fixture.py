"""Regenerate the browser incremental builtins' Python reference fixture."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.atr import ATRIndicator
from app.indicator.indicators.ma import MAIndicator
from app.indicator.indicators.boll import BOLLIndicator
from app.indicator.indicators.ema import EMAIndicator
from app.indicator.indicators.macd import MACDIndicator
from app.indicator.indicators.rsi import RSIIndicator
from app.indicator.indicators.vol import VOLIndicator
from app.indicator.serialization import serialize_indicator_result
from app.indicator.types import IndicatorKey
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.training.indicator_checkpoint import IndicatorCheckpointStore
from app.replay.training.indicator_history import IndicatorHistoryChunk
from app.replay.training.indicator_prefix import CanonicalReplayIndicators


def canonical_seeds(bars, name, params, seed_count, warmup):
    rows = tuple(ReplayDisplayBar(open_time_ms=bar["time"] * 1000,
        close_time_ms=bar["time"] * 1000 + 59999,
        **{key: str(bar[key]) for key in ["open", "high", "low", "close", "volume"]},
        quote_volume=None, trades=None, taker_buy_base=None, taker_buy_quote=None,
        first_base_open_ms=bar["time"] * 1000, last_base_open_ms=bar["time"] * 1000,
        component_count=1, expected_components=1, is_closed=True) for bar in bars)

    class History:
        origin_ms = rows[0].open_time_ms
        revealed_boundary_ms = rows[-1].close_time_ms
        def __init__(self):
            self.identity = {"identity": {"exchange": "fixture", "market_type": "spot",
                                         "symbol": "FIXTURE", "display_interval": "1m"}}

        def read(self, start, stop):
            return IndicatorHistoryChunk(start, stop, tuple(row for row in rows if start <= row.open_time_ms < stop))

    result = []
    with TemporaryDirectory() as directory:
        compute = CanonicalReplayIndicators(IndicatorCheckpointStore(Path(directory) / "math.sqlite3"))
        for prefix in sorted({0, 1, max(0, warmup - 2), warmup - 1, warmup, 47, 110}):
            if not 0 <= prefix < len(rows) - 1:
                continue
            initial_count = min(len(rows) - 1, max(seed_count, prefix + 3))
            result.append({"prefix_count": prefix, "initial_count": initial_count,
                "result": compute.compute(history=History(), name=name, params=params,
                                          rows=rows[prefix:initial_count])})
    return result


def main():
    bars = [
        {
            "time": 1700000000 + i * 60,
            "open": 100 + i % 7,
            "high": 110 + i % 7,
            "low": 90 + i % 3,
            "close": 99 + i % 11,
            "volume": i + 1,
        }
        for i in range(128)
    ]
    cases = []
    for name, params in (
        ("MACD", {}),
        ("MACD", {"fast": 3, "slow": 5, "signal": 2, "source": "hlc3"}),
        ("MACD", {"fast": 1, "slow": 1, "signal": 1}),
        ("VOL", {}),
        ("EMA", {}),
        ("EMA", {"period": 1, "source": "hlc3"}),
        ("EMA", {"period": 100, "source": "ohlc4"}),
        ("RSI", {}),
        ("RSI", {"period": 2, "source": "hlc3"}),
        ("RSI", {"period": 100, "source": "ohlc4"}),
        ("ATR", {}),
        ("ATR", {"period": 1}),
        ("ATR", {"period": 100}),
        ("MA", {}),
        ("MA", {"period": 1, "source": "hlc3"}),
        ("MA", {"period": 100, "source": "ohlc4"}),
        ("BOLL", {}),
        ("BOLL", {"period": 2, "source": "hlc3", "mult": 0.5}),
        ("BOLL", {"period": 100, "source": "ohlc4", "mult": 5}),
    ):
        instance = {
            "MACD": MACDIndicator,
            "VOL": VOLIndicator,
            "EMA": EMAIndicator,
            "RSI": RSIIndicator,
            "ATR": ATRIndicator,
            "MA": MAIndicator,
            "BOLL": BOLLIndicator,
        }[name](params)
        instance.recompute([BarData(**bar) for bar in bars])
        case = {
            "name": name,
            "params": params,
            "outputs": {
                key: [
                    {"time": point.timestamp, "value": round(point.value, 8)}
                    for point in points
                    if point.value is not None
                ]
                for key, points in instance.get_series().items()
            },
        }
        case["seed_count"] = max(32, instance.warmup_period)
        instance.recompute([BarData(**bar) for bar in bars[: case["seed_count"]]])
        case["seed"] = serialize_indicator_result(
            instance.build_result(
                IndicatorKey(
                    "FIXTURE",
                    "1m",
                    name,
                    params,
                    market_type="spot",
                    exchange="fixture",
                )
            )
        )
        case["canonical"] = canonical_seeds(bars, name, params, case["seed_count"], instance.warmup_period)
        cases.append(case)
    target = (
        Path(__file__).resolve().parents[2]
        / "frontend/src/features/replay/__tests__/fixtures/builtin-parity.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    finite = []
    for name, kind, period in (("MA", MAIndicator, 500), ("BOLL", BOLLIndicator, 200)):
        for price in (0.000001, 100_000.0, 1_000_000_000_000.0):
            values = [price + (i % 17 - 8) * price * 1e-7 for i in range(600)]
            rows = [dict(time=1_700_000_000 + i * 60, open=v, high=v, low=v, close=v, volume=1)
                    for i, v in enumerate(values)]
            params = {"period": period}
            instance = kind(params)
            instance.init([BarData(**row) for row in rows])
            finite.append({"name": name, "params": params, "bars": rows,
                "outputs": {key: [{"time": p.timestamp, "value": round(p.value, 8)} for p in points if p.value is not None]
                            for key, points in instance.get_series().items()},
                "canonical": canonical_seeds(rows, name, params, period + 15, period)})
    target.write_text(json.dumps({"bars": bars, "cases": cases, "finite": finite}, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
