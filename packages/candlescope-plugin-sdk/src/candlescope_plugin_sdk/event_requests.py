"""Derive event-row requests from pinned physical sources and their close clock."""
from copy import deepcopy
import hashlib
import json
import math

from candlescope_plugin_sdk.synthetic_ohlcv import renko_rows

CONTRACT = "candlescope.pine-event-requests/1"


def renko_descriptor(symbol):
    try:
        value = json.loads(symbol)
    except (TypeError, ValueError):
        return None
    if (not isinstance(value, dict) or set(value) != {"chart", "symbol", "style", "param"}
            or value["chart"] != "renko" or not isinstance(value["symbol"], str)
            or not value["symbol"] or value["symbol"] != value["symbol"].strip()):
        return None
    return value


def build_renko_stream(symbol, timeframe, physical_streams):
    """Construction reads frozen prices; delivery reveals only closed cohorts.

    The caller supplies a descriptor reached by Pine, not parsed script text.
    This helper does not execute Pine, select accounts or modify a broker ledger.
    """
    descriptor = renko_descriptor(symbol)
    if descriptor is None:
        raise ValueError("PINE_EVENT_REQUEST_INVALID: exact Renko descriptor required")
    sources = [item for item in physical_streams
               if (item["symbol"], item["timeframe"]) == (descriptor["symbol"], timeframe)]
    if len(sources) != 1:
        raise ValueError("PINE_EVENT_SOURCE_REQUIRED: freeze one exact physical source context")
    source = sources[0]
    if renko_descriptor(source["symbol"]) is not None:
        raise ValueError("PINE_EVENT_SOURCE_REQUIRED: a physical source context is required")
    bars, closes = source["bars"], source["closes"]
    if len(bars) != len(closes) or len(bars) > 100_000:
        raise ValueError("PINE_EVENT_SOURCE_INVALID: bounded closed physical rows required")
    previous_open = previous_close = None
    for row, close in zip(bars, closes, strict=True):
        if (type(row.get("time")) is not int or type(close) is not int
                or close < row["time"] * 1000
                or previous_open is not None and row["time"] <= previous_open
                or previous_close is not None and close <= previous_close
                or any(type(row.get(name)) not in (int,float) for name in ("open","high","low","close","volume"))
                or any(not math.isfinite(float(row[name])) for name in ("open","high","low","close","volume"))
                or row["high"] < max(row["open"], row["close"])
                or row["low"] > min(row["open"], row["close"]) or row["volume"] < 0):
            raise ValueError("PINE_EVENT_SOURCE_INVALID: ordered valid physical rows required")
        previous_open, previous_close = row["time"], close
    source_hash = hashlib.sha256(json.dumps([source], sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    bricks = renko_rows(source["bars"], descriptor["style"], descriptor["param"])
    bars = [{key: brick[key] for key in ("time", "open", "high", "low", "close", "volume")}
            for brick in bricks]
    closes = [source["closes"][brick["source_index"]] for brick in bricks]
    recipe = dict(contract=CONTRACT, symbol=symbol, timeframe=timeframe,
                  source_hash=source_hash)
    recipe_hash = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False).encode()).hexdigest()
    return dict(symbol=symbol, timeframe=timeframe, bars=bars, closes=closes,
                event_series_contract=CONTRACT, source_hash=source_hash,
                recipe_hash=recipe_hash,
                **({"metadata": deepcopy(source["metadata"])} if source.get("metadata") else {}))
