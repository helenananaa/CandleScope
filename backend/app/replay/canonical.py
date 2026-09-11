"""Canonical JSON and hashing used by replay deterministic state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Mapping

try:
    import orjson
except ImportError:  # Keep the deterministic reference available in minimal installs.
    orjson = None

from .models import normalize_decimal_string
from .immutable_json import FrozenDict, FrozenList


def _is_native_canonical_json(value: object) -> bool:
    """Return whether ``json.dumps`` can encode the value without coercion.

    Replay snapshots are overwhelmingly composed of exact JSON primitives.
    Rebuilding those large trees merely to prove that fact made every nested
    state hash walk the retained candle window twice and allocate another full
    object graph.  Keep the strict fallback for Decimal, Enum, dataclass,
    generic Mapping, floats, and malformed keys, but let already-canonical
    dict/list/tuple trees go directly to the deterministic JSON encoder.
    """

    pending = [value]
    while pending:
        candidate = pending.pop()
        candidate_type = type(candidate)
        if candidate_type in (FrozenDict, FrozenList):
            continue
        if candidate is None or candidate_type is str or candidate_type is bool or candidate_type is int:
            continue
        if candidate_type is dict:
            for key, child in candidate.items():
                if type(key) is not str:
                    return False
                pending.append(child)
            continue
        if candidate_type is list or candidate_type is tuple:
            pending.extend(candidate)
            continue
        return False
    return True


def _canonical_value(value: object, *, path: str = "$") -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError(f"{path} contains forbidden binary float")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{path} contains non-finite Decimal")
        return normalize_decimal_string(format(value, "f"), field_name=path)
    if isinstance(value, Enum):
        return _canonical_value(value.value, path=path)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(
                getattr(value, field.name),
                path=f"{path}.{field.name}",
            )
            for field in fields(value)
            if not (
                "canonical_omit_value" in field.metadata
                and getattr(value, field.name) == field.metadata["canonical_omit_value"]
            )
        }
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} contains a non-string object key")
            result[key] = _canonical_value(child, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _canonical_value(child, path=f"{path}[{index}]")
            for index, child in enumerate(value)
        ]
    raise TypeError(f"{path} contains unsupported value {type(value).__name__}")


def canonical_json(value: object) -> str:
    normalized = value if _is_native_canonical_json(value) else _canonical_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_json_encoding(value: object) -> tuple[bytes, bool]:
    if orjson is not None:
        normalized = value if _is_native_canonical_json(value) else _canonical_value(value)
        try:
            return orjson.dumps(normalized, option=orjson.OPT_SORT_KEYS), True
        except orjson.JSONEncodeError:
            # Python's canonical contract also permits arbitrary-size integers
            # and unusual primitive subclasses. Preserve its exact behavior.
            pass
    return canonical_json(value).encode("utf-8"), False


def canonical_json_bytes(value: object) -> bytes:
    return _canonical_json_encoding(value)[0]


def canonical_sha256(value: object) -> str:
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"sha256:{digest}"


def _canonical_object_parts(value: Mapping[str, object], *, encoded_fields):
    """Internal canonical fragments, retaining immutable encoded subtrees."""
    if any(type(key) is not str for key in value):
        raise TypeError("canonical object requires native string keys")
    if not encoded_fields.keys() <= value.keys():
        raise ValueError("encoded field is absent from canonical object")
    yield b"{"
    for index, key in enumerate(sorted(value)):
        if index:
            yield b","
        yield canonical_json_bytes(key)
        yield b":"
        encoded = encoded_fields.get(key)
        if encoded is None:
            yield canonical_json_bytes(value[key])
        elif isinstance(encoded, tuple):
            yield from encoded
        else:
            yield encoded
    yield b"}"


def _canonical_object_bytes(value: Mapping[str, object], *, encoded_fields) -> bytes:
    return b"".join(_canonical_object_parts(value, encoded_fields=encoded_fields))


def _canonical_object_sha256(value: Mapping[str, object], *, encoded_fields) -> str:
    digest = hashlib.sha256()
    for part in _canonical_object_parts(value, encoded_fields=encoded_fields):
        digest.update(part)
    return "sha256:" + digest.hexdigest()
