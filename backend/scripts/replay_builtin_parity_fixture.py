"""Regenerate the browser incremental builtins' Python reference fixture."""
import json
from pathlib import Path

from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.macd import MACDIndicator
from app.indicator.indicators.vol import VOLIndicator


def main():
    bars = [dict(time=1700000000 + i * 60, open=100 + i % 7,
                 high=110 + i % 7, low=90 + i % 3, close=99 + i % 11,
                 volume=i + 1) for i in range(48)]
    cases = []
    for name, params in (("MACD", {}), ("MACD", {"fast": 3, "slow": 5, "signal": 2, "source": "hlc3"}),
                         ("MACD", {"fast": 1, "slow": 1, "signal": 1}), ("VOL", {})):
        instance = (MACDIndicator if name == "MACD" else VOLIndicator)(params)
        instance.recompute([BarData(**bar) for bar in bars])
        cases.append(dict(name=name, params=params, outputs={
            key: [dict(time=point.timestamp, value=round(point.value, 8)) for point in points if point.value is not None]
            for key, points in instance.get_series().items()
        }))
    target = Path(__file__).resolve().parents[2] / "frontend/src/features/replay/__tests__/fixtures/builtin-parity.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(bars=bars, cases=cases), separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
