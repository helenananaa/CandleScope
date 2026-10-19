"""Validate explicit, effective-time FX inputs; never acquire or infer rates."""
import math
import re
from collections.abc import Mapping


def currency_rates(value):
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"schemaVersion", "pairs"} or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("PINE_CURRENCY_INPUT_INVALID: expected schemaVersion=1 and pairs")
    pairs = value["pairs"]
    if not isinstance(pairs, list) or len(pairs) > 64:
        raise ValueError("PINE_CURRENCY_INPUT_INVALID: at most 64 currency pairs")
    seen, total = set(), 0
    for pair in pairs:
        if not isinstance(pair, Mapping) or set(pair) not in ({"from", "to", "rates"}, {"from", "to", "unavailable"}):
            raise ValueError("PINE_CURRENCY_INPUT_INVALID: each pair requires rates or unavailable")
        codes = pair["from"], pair["to"]
        if any(not isinstance(code, str) or not re.fullmatch(r"[A-Z]{1,20}", code) for code in codes) or codes in seen:
            raise ValueError("PINE_CURRENCY_INPUT_INVALID: use unique uppercase currency pairs")
        seen.add(codes)
        if "unavailable" in pair:
            if pair["unavailable"] is not True:
                raise ValueError("PINE_CURRENCY_INPUT_INVALID: unavailable must be true")
            continue
        rows = pair["rates"]
        if not isinstance(rows, list):
            raise ValueError("PINE_CURRENCY_INPUT_INVALID: rates must be an array")
        total += len(rows)
        if total > 100_000:
            raise ValueError("PINE_CURRENCY_INPUT_INVALID: at most 100000 effective rates")
        previous = None
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"effectiveTime", "rate"}:
                raise ValueError("PINE_CURRENCY_INPUT_INVALID: each rate needs effectiveTime and rate")
            timestamp, rate = row["effectiveTime"], row["rate"]
            if type(timestamp) is not int or abs(timestamp) > 9_007_199_254_740_991 or (previous is not None and timestamp <= previous) or type(rate) not in (int, float) or rate <= 0 or rate > 1.7976931348623157e308 or not math.isfinite(rate):
                raise ValueError("PINE_CURRENCY_INPUT_INVALID: strictly ordered milliseconds and finite positive rates required")
            previous = timestamp
    return {"schemaVersion": 1, "pairs": pairs}
