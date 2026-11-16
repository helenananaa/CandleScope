"""Input warmup for builtin indicators, shared by live and replay display math.

Recursive builtins (EMA, Wilder RSI/ATR, MACD) depend on where a computation
starts. Their warmup is derived from each smoothing factor so that the seed's
residual weight at the first requested bar is at most ``SEED_RESIDUAL``. That
makes a value independent of the request window, batch partners, cache order
and the client's loaded bar count, to well below the 8-decimal wire precision
(ADR-INDICATOR-001). Finite windows (MA, BOLL) need exactly ``period - 1``.
"""

import math
from typing import Any

SEED_RESIDUAL = 1e-12


def _decay_bars(retained: float) -> int:
    """Bars until a ``retained`` per-bar weight falls to ``SEED_RESIDUAL``."""
    if not 0.0 < retained < 1.0:
        return 0
    return math.ceil(math.log(SEED_RESIDUAL) / math.log(retained))


def _ema_warmup(period: int) -> int:
    # SMA initialisation over ``period`` bars, then alpha = 2 / (period + 1).
    return period + _decay_bars((period - 1) / (period + 1))


def _wilder_warmup(period: int) -> int:
    # SMA initialisation over ``period`` bars, then alpha = 1 / period.
    return period + _decay_bars((period - 1) / period)


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
        return _wilder_warmup(_param_int("period", 14))
    if normalized == "EMA":
        return _ema_warmup(_param_int("period", 20))
    if normalized == "MACD":
        # The signal EMA consumes the difference of two EMAs; chaining the
        # slower line's warmup with the signal's is a conservative bound.
        slow = max(_param_int("fast", 12), _param_int("slow", 26))
        return _ema_warmup(slow) + _ema_warmup(_param_int("signal", 9))
    return _param_int("warmup", 200)


def replay_display_warmup_bars(name: str, params: dict[str, Any]) -> int:
    """The replay display viewport's bounded read budget (not the value contract).

    Replay data preparation sizes its local context to this budget, and the
    viewport keeps durable anchors so panning never rebases shown values.
    Moving it to ``indicator_warmup_bars`` must also resize that prepared
    context; until then it keeps its original multiples (ADR-INDICATOR-001 O4).
    """
    normalized = str(name or "").upper().strip()

    def _param_int(key: str, fallback: int) -> int:
        try:
            return max(1, int(params.get(key, fallback)))
        except (TypeError, ValueError):
            return fallback

    if normalized in {"RSI", "ATR"}:
        return _param_int("period", 14) * 3
    if normalized == "EMA":
        return _param_int("period", 20) * 5
    if normalized == "MACD":
        return _param_int("slow", 26) * 5 + _param_int("signal", 9) * 3
    return indicator_warmup_bars(name, params)
