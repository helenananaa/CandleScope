"""Exact encoding for already-qualified ASCII/string/integer protocol trees.

Callers must exclude floats, non-ASCII and DEL (U+007F), dataclasses and
non-JSON values. Validation belongs to the typed builder, not this encoder.
The stdlib path remains authoritative when the optional accelerator is absent.
"""

import json
from app.core.config import getenv

try:
    import orjson
except ImportError:
    orjson = None

_ENABLED = getenv("BACKTEST_NATIVE_ENCODING_ENABLED", "1").strip() == "1"


def encode_ascii_tree(value):
    if _ENABLED and orjson is not None:
        try:
            return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
        except orjson.JSONEncodeError:
            # Python integers can exceed the native encoder's range.
            pass
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def try_bar_input_bytes(sequence, watermark, bar, trade, features):
    """Native frame hashing only when exact JSON primitives prove compatibility."""
    if not _ENABLED or orjson is None or trade is not None:
        return None
    if type(sequence) is not int or type(watermark) is not int or type(bar) is not dict:
        return None
    for key, value in bar.items():
        if type(key) is not str or (value is not None and type(value) not in (str, int, bool)):
            return None
    if features is not None:
        if type(features) is not dict:
            return None
        for key, value in features.items():
            if type(key) is not str or type(value) is not str:
                return None
    try:
        encoded = orjson.dumps({"sequence": sequence, "watermark": watermark,
            "bar": bar, "trade": trade, "features": features}, option=orjson.OPT_SORT_KEYS)
    except orjson.JSONEncodeError:
        return None
    # UTF-8 and ensure_ascii=True differ for non-ASCII and U+007F.
    return encoded if encoded.isascii() and b"\x7f" not in encoded else None


def bounded_ascii_observation(value, byte_limit):
    """Fast qualification after the caller has checked the fixed schema keys.

    Restrict every dynamic value to an exact primitive first. The encoder then
    proves the 53-bit integer bound and ASCII/message bounds in native code.
    """
    if not _ENABLED or orjson is None:
        return None
    for key in ("runId", "revisionId", "phase", "inputHash"):
        if type(value[key]) is not str:
            return False
    for key in ("generation", "sequence", "eventTimeMs", "watermarkMs"):
        if type(value[key]) is not int:
            return False
    for name in ("market", "features", "accountView"):
        mapping = value[name]
        if type(mapping) is not dict or len(mapping) > 8:
            return False
        for key, item in mapping.items():
            if type(key) is not str or type(item) is not str:
                return False
    bar = value["bar"]
    for key in ("open", "high", "low", "close", "volume"):
        if type(bar[key]) is not str:
            return False
    for key in ("openTimeMs", "closeTimeMs"):
        if type(bar[key]) is not int:
            return False
    try:
        encoded = orjson.dumps(value, option=orjson.OPT_STRICT_INTEGER)
    except orjson.JSONEncodeError:
        return False
    # Each string is bounded by the entire encoding; request wrapping still
    # stays far below the SDK's 256 KiB message ceiling.
    return len(encoded) <= byte_limit and encoded.isascii() and b"\x7f" not in encoded
