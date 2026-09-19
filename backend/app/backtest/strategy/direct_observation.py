"""Bounded object seam for host-created observations, never arbitrary JSON.

Accepted trees have a fixed schema, interoperable integers and small flat
maps. The native qualifier bounds the entire observation to 64 KiB; the
portable qualifier bounds individual strings to 128 characters. Both keep
depth below 8 and container size below 32. Other inputs use the original
SDK JSON validator instead of relaxing a limit.
"""

from __future__ import annotations
import hashlib
from candlescope_backtest_sdk import models as _models

# Captured before user prepare/step can alter SDK methods. Native code also
# checks current methods and slot descriptors on every output.
_OUTPUT_KIND = _models.output_kind
_OUTPUT_SPECS = tuple((kind, kind.to_payload, names, wire, label, kind.__name__) for kind, names, wire, label in (
    (_models.Signal, ("direction", "score", "confidence", "horizon"), ("direction", "score", "confidence", "horizon"), "SIGNAL"),
    (_models.TargetPosition, ("quantity",), ("quantity",), "TARGET_POSITION"),
    (_models.OrderIntent, ("side", "type", "quantity", "limit_price", "stop_price", "tif", "client_tag"),
     ("side", "type", "quantity", "limitPrice", "stopPrice", "tif", "clientTag"), "ORDER_INTENT"),
))


def bind_native_outputs(factory):
    if getattr(_models, "NATIVE_OUTPUT_LAYOUT", None) != 1 or not hasattr(factory, "bind_outputs"):
        return False
    try:
        factory.bind_outputs(_models, _OUTPUT_KIND, _OUTPUT_SPECS)
    except ValueError:
        return False
    return True

from candlescope_backtest_sdk.contract import (
    DEFAULT_MAX_CONTAINER_ITEMS, DEFAULT_MAX_JSON_DEPTH, DEFAULT_MAX_MESSAGE_BYTES,
    DEFAULT_MAX_STRING_BYTES, MAX_SAFE_INTEGER, OBSERVATION_SCHEMA,
)

_BOUNDS_COMPATIBLE = (
    DEFAULT_MAX_CONTAINER_ITEMS >= 32 and DEFAULT_MAX_JSON_DEPTH >= 8
    and DEFAULT_MAX_MESSAGE_BYTES >= 65536 and DEFAULT_MAX_STRING_BYTES >= 128
    and MAX_SAFE_INTEGER >= 9007199254740991
    and OBSERVATION_SCHEMA == "candlescope.python-strategy-observation/1"
)
_NATIVE_OBSERVATION_BYTES = min(65536, DEFAULT_MAX_STRING_BYTES, DEFAULT_MAX_MESSAGE_BYTES // 2)

_OBSERVATION_KEYS = frozenset(("schemaVersion", "runId", "revisionId", "generation", "sequence",
    "eventTimeMs", "watermarkMs", "phase", "market", "bar", "features", "accountView", "inputHash"))
_BAR_KEYS = frozenset(("openTimeMs", "closeTimeMs", "open", "high", "low", "close", "volume"))


def small_text(value):
    return type(value) is str and len(value) <= 128 and value.isascii() and "\x7f" not in value


def small_integer(value):
    return type(value) is int and abs(value) <= 9007199254740991


def small_text_map(value):
    if type(value) is not dict or len(value) > 8:
        return False
    for key, item in value.items():
        if type(key) is not str or len(key) > 128 or not key.isascii() or "\x7f" in key:
            return False
        if type(item) is not str or len(item) > 128 or not item.isascii() or "\x7f" in item:
            return False
    return True


def encode_output(sequence, value):
    from candlescope_backtest_sdk import models
    from .qualified_json import encode_ascii_tree

    # Construct the same SDK envelope and call to_payload exactly once.
    kind = models.output_kind(value)
    payload = value.to_payload()
    wire = {"schemaVersion": models.OUTPUT_SCHEMA, "sequence": sequence,
            "kind": kind, "payload": payload}
    qualified = (type(value) in (models.Signal, models.TargetPosition, models.OrderIntent)
                 and small_text_map(payload) and small_text(wire["schemaVersion"])
                 and small_text(kind) and small_integer(sequence))
    wire["outputHash"] = ("sha256:" + hashlib.sha256(encode_ascii_tree(wire)).hexdigest()
                          if qualified else models.canonical_sha256(wire))
    return wire, qualified


def encode_prepared_output(sequence, value, factory, *, host_parts=False, object_fields=False):
    from candlescope_backtest_sdk import models
    if host_parts and object_fields and hasattr(factory, "object_output"):
        from .python_provider import _target_state_hash
        direct = factory.object_output(sequence, value, _target_state_hash)
        if direct is not None:
            return direct[0], True, direct[1]
    kind = models.output_kind(value)
    payload = value.to_payload()
    native = None
    if type(value) in (models.Signal, models.TargetPosition, models.OrderIntent):
        if host_parts:
            from .python_provider import _target_state_hash
            native = factory.output_parts(sequence, kind, payload, models.OUTPUT_SCHEMA, _target_state_hash)
        else:
            native = factory.output_wire(sequence, kind, payload, models.OUTPUT_SCHEMA)
    if native is not None and host_parts:
        return native[0], True, native[1]
    wire = {"schemaVersion": models.OUTPUT_SCHEMA, "sequence": sequence, "kind": kind, "payload": payload}
    if native is not None:
        wire["outputHash"], encoded = native
        return wire, True, encoded
    wire["outputHash"] = models.canonical_sha256(wire)
    return wire, False, None


def bounded_observation(value):
    if not (_BOUNDS_COMPATIBLE and type(value) is dict and value.keys() == _OBSERVATION_KEYS
            and value["schemaVersion"] == "candlescope.python-strategy-observation/1"
            and type(value["bar"]) is dict and value["bar"].keys() == _BAR_KEYS):
        return False
    from .qualified_json import bounded_ascii_observation
    native = bounded_ascii_observation(value, _NATIVE_OBSERVATION_BYTES)
    if native is not None:
        return native
    # These loops deliberately avoid per-field Python helper/generator calls.
    for name in ("runId", "revisionId", "phase", "inputHash"):
        item = value[name]
        if type(item) is not str or len(item) > 128 or not item.isascii() or "\x7f" in item:
            return False
    for name in ("generation", "sequence", "eventTimeMs", "watermarkMs"):
        item = value[name]
        if type(item) is not int or not -9007199254740991 <= item <= 9007199254740991:
            return False
    for name in ("market", "features", "accountView"):
        if not small_text_map(value[name]):
            return False
    bar = value["bar"]
    for name in ("open", "high", "low", "close", "volume"):
        item = bar[name]
        if type(item) is not str or len(item) > 128 or not item.isascii() or "\x7f" in item:
            return False
    for name in ("openTimeMs", "closeTimeMs"):
        item = bar[name]
        if type(item) is not int or not -9007199254740991 <= item <= 9007199254740991:
            return False
    return True


def make_observation(value):
    from candlescope_backtest_sdk.models import Bar, Observation, _decimal_string

    bar = value["bar"]
    open_text = bar["open"]
    opened = _decimal_string(open_text, "bar.open")
    # Reuse only identical raw spellings, preserving trailing-zero semantics.
    high = opened if bar["high"] == open_text else _decimal_string(bar["high"], "bar.high")
    low = opened if bar["low"] == open_text else _decimal_string(bar["low"], "bar.low")
    close = opened if bar["close"] == open_text else _decimal_string(bar["close"], "bar.close")
    volume = _decimal_string(bar["volume"], "bar.volume")
    return Observation(
        run_id=value["runId"], revision_id=value["revisionId"],
        generation=value["generation"], sequence=value["sequence"],
        event_time_ms=value["eventTimeMs"], watermark_ms=value["watermarkMs"],
        phase=value["phase"], market=dict(value["market"]),
        bar=Bar(bar["openTimeMs"], bar["closeTimeMs"], opened, high, low, close, volume),
        features=dict(value["features"]), account_view=dict(value["accountView"]),
        input_hash=value["inputHash"],
    )
