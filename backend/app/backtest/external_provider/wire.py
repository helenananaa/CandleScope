"""Bounded, strict JSON for the external decision connection."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

from app.backtest.strategy.protocol import StrategyProviderError

MAX_MESSAGE_BYTES = 16_777_216
MAX_JSON_NODES = 1_000_000
MAX_JSON_DEPTH = 32
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _scan(value: object, *, depth: int, budget: list[int]) -> None:
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_JSON_DEPTH:
        raise StrategyProviderError("BUDGET_EXCEEDED", "external JSON structure exceeds its budget")
    kind = type(value)
    if value is None or kind in (bool, str):
        return
    if kind is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external JSON integer exceeds the exact interoperable range")
        return
    if kind is float:
        if not math.isfinite(value):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external JSON numbers must be finite")
        return
    if kind is Decimal:
        if not value.is_finite():
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external decimal must be finite")
        return
    if kind in (list, tuple):
        for child in value:
            _scan(child, depth=depth + 1, budget=budget)
        return
    if kind is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external JSON object keys must be strings")
            _scan(child, depth=depth + 1, budget=budget)
        return
    raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "unsupported external JSON value")


def _decimal(value: object) -> str:
    if type(value) is Decimal and value.is_finite():
        return str(value)
    raise TypeError("unsupported external JSON value")


def encode(value: object, *, max_bytes: int = MAX_MESSAGE_BYTES) -> str:
    _scan(value, depth=1, budget=[MAX_JSON_NODES])
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False, default=_decimal)
    except (ValueError, TypeError, RecursionError):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external JSON value") from None
    if len(text.encode("utf-8")) > max_bytes:
        raise StrategyProviderError("BUDGET_EXCEEDED", "external JSON message exceeds its byte budget")
    return text


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate external JSON field")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ValueError("non-finite external JSON number")


def decode(raw: bytes | str, *, max_bytes: int = MAX_MESSAGE_BYTES) -> Any:
    if type(raw) not in (bytes, str):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external JSON must be UTF-8 text")
    try:
        raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
    except UnicodeError:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external JSON must be UTF-8 text") from None
    if len(raw_bytes) > max_bytes:
        raise StrategyProviderError("BUDGET_EXCEEDED", "external JSON message exceeds its byte budget")
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        value = json.loads(text, object_pairs_hook=_unique, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid or ambiguous external JSON message") from None
    _scan(value, depth=1, budget=[MAX_JSON_NODES])
    return value


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(encode(value).encode("utf-8")).hexdigest()
