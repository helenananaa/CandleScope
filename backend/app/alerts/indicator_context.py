"""Readiness of the indicator fields an alert rule requires."""
from typing import Any
import math


def indicator_readiness(values: dict[str, Any]) -> dict[str, bool]:
    return {key: isinstance(value, (int, float)) and math.isfinite(value)
            for key, value in values.items()}
