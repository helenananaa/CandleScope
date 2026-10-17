"""Causal synthetic OHLCV shared by first-party language adapters.

Construction changes only strategy observations, never market execution prices.
"""
from decimal import Decimal, InvalidOperation


def renko_rows(rows, style, parameter):
    atr = style == "ATR"
    if style not in {"ATR", "Traditional"} or isinstance(parameter, bool):
        raise ValueError("SYNTHETIC_INPUT_INVALID: Renko style must be Traditional or ATR")
    try:
        size = Decimal(str(parameter))
    except InvalidOperation as exc:
        raise ValueError("SYNTHETIC_INPUT_INVALID: invalid Renko parameter") from exc
    if not size.is_finite() or size <= 0 or (atr and (size != int(size) or size > 5000)):
        raise ValueError("SYNTHETIC_INPUT_INVALID: use a positive brick size or ATR length 1..5000")
    length = int(size) if atr else 0
    average, previous, anchor, direction = None, None, None, 0
    seed, pending_volume, result = [], Decimal(0), []
    for source_index, row in enumerate(rows):
        if row.get("is_closed", row.get("isClosed", True)) is False:
            break
        close, high, low, volume = (Decimal(str(row[key])) for key in ("close", "high", "low", "volume"))
        if not all(value.is_finite() for value in (close, high, low, volume)) or low > high:
            raise ValueError("SYNTHETIC_INPUT_INVALID: invalid source OHLCV")
        pending_volume += volume
        if anchor is None:
            anchor = close
        if atr:
            tr = high - low if previous is None else max(high-low, abs(high-previous), abs(low-previous))
            if average is None:
                seed.append(tr)
                if len(seed) == length:
                    average = sum(seed) / length
            else:
                average = (average * (length - 1) + tr) / length
            size = average
        previous = close
        if size is None or size <= 0:
            continue
        cohort = []
        while True:
            movement = close - anchor
            side = 1 if movement >= size else -1 if movement <= -size else 0
            if side == 0 or (direction and side != direction and abs(movement) < size * 2):
                break
            if len(cohort) >= 10_000 or len(result) + len(cohort) >= 200_000:
                raise ValueError("SYNTHETIC_INPUT_BUDGET: increase the Renko brick size")
            open_price = anchor + side * size if direction and side != direction else anchor
            anchor = open_price + side * size
            direction = side
            cohort.append({"time": row["time"], "open": float(open_price),
                "high": float(max(open_price, anchor)), "low": float(min(open_price, anchor)),
                "close": float(anchor), "source_index": source_index,
                "ordinal": len(result) + len(cohort), "is_closed": True})
        if cohort:
            for brick in cohort:
                brick["volume"] = float(pending_volume / len(cohort))
            result.extend(cohort)
            pending_volume = Decimal(0)
    return result
