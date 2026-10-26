"""Shared bounded input budgets for live and replay display indicators."""

from typing import Any


def indicator_warmup_bars(name: str, params: dict[str, Any]) -> int:
    normalized = str(name or "").upper().strip()

    def _param_int(key: str, fallback: int) -> int:
        try:
            return max(1, int(params.get(key, fallback)))
        except (TypeError, ValueError):
            return fallback

    if normalized == "VOL":
        return 0
    if normalized in {"MA", "SMA", "BOLL"}:
        return max(0, _param_int("period", 20) - 1)
    if normalized in {"RSI", "ATR"}:
        return _param_int("period", 14) * 3
    if normalized == "EMA":
        return _param_int("period", 20) * 5
    if normalized == "MACD":
        return _param_int("slow", 26) * 5 + _param_int("signal", 9) * 3
    return _param_int("warmup", 200)
