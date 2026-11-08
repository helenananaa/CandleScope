"""QA-only independent arithmetic for captured final 250-bar alert windows.

RSI uses Wilder's initial 14-change mean; EMA seeds use arithmetic means.
The application's histogram convention is twice (DIF minus signal).
No production application or indicator code is imported.
"""
import json
import math
import sys


def ema(values, period):
    result = [None] * (period - 1)
    current = math.fsum(values[:period]) / period
    result.append(current)
    alpha = 2 / (period + 1)
    for value in values[period:]:
        current = alpha * value + (1 - alpha) * current
        result.append(current)
    return result


def compute(rows):
    assert len(rows) == 250
    times = [row["time"] for row in rows]
    # Public kline range rows expose seconds; evaluationCursor.barTime is ms.
    assert all(b - a == 60 for a, b in zip(times, times[1:])), "Non-contiguous minute window"
    closes = [float(row["close"]) for row in rows]
    assert all(math.isfinite(c) and c > 0 for c in closes)
    changes = [b - a for a, b in zip(closes, closes[1:])]
    gain = math.fsum(max(0, c) for c in changes[:14]) / 14
    loss = math.fsum(max(0, -c) for c in changes[:14]) / 14
    for change in changes[14:]:
        gain = (13 * gain + max(0, change)) / 14
        loss = (13 * loss + max(0, -change)) / 14
    rsi = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    fast, slow = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(fast[25:], slow[25:])]
    signal = ema(dif, 9)[-1]
    return {"rsi": rsi, "macdHist": 2 * (dif[-1] - signal),
            "ma20": math.fsum(closes[-20:]) / 20}


if __name__ == "__main__":
    print(json.dumps(compute(json.load(sys.stdin))))
