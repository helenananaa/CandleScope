"""Readiness for compatibility field names; numeric computation is public."""
from typing import Any
import math


def indicator_readiness(values: dict[str, Any]) -> dict[str, bool]:
    return {key: isinstance(values.get(key), (int, float)) and math.isfinite(values[key])
            for key in ("rsi", "macdHist", "ma20")}
