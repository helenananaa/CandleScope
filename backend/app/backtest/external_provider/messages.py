"""Turn recorded external decisions into the existing Host output contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.backtest.strategy.protocol import (
    ObservationFrame,
    StrategyOutput,
    StrategyProviderError,
)

from .contracts import ExternalProviderManifest
from .wire import decode, digest, encode

OPERATIONS = frozenset({"prepare", "warmup", "step", "onExecutionReport", "close"})
_ERRORS = frozenset({"PROVIDER_PROTOCOL_VIOLATION", "PROVIDER_TIMEOUT", "PROVIDER_CRASH_UNRECOVERABLE", "BUDGET_EXCEEDED"})


def _object(value: object, required: set[str], optional: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or not required.issubset(value) or set(value) - required - optional:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", f"invalid fields in external {label}")
    return value


def _decimal(value: object, label: str) -> None:
    if (type(value) is not str or len(value) > 128
            or re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value) is None):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", f"external {label} must be a finite decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", f"external {label} must be a finite decimal string") from None
    if not number.is_finite():
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", f"external {label} must be finite")
    # Bound the representation before any downstream formatter can expand a
    # short exponent string into an enormous fixed-point allocation.
    if abs(number.as_tuple().exponent) > 128 or len(number.as_tuple().digits) > 128:
        raise StrategyProviderError("BUDGET_EXCEEDED", "external decimal precision exceeds its representation budget")


def _reason(payload: dict[str, Any]) -> None:
    if "reasonCode" in payload and (type(payload["reasonCode"]) is not str or len(payload["reasonCode"]) > 128):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external reason code")


def _order(value: object) -> None:
    order = _object(value, {"side", "type", "qty"},
                    {"limit_price", "stop_price", "tif", "reduce_only", "oco_group"}, "order intent")
    if order["side"] not in ("BUY", "SELL") or order["type"] not in ("MARKET", "LIMIT", "STOP", "STOP_LIMIT"):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external order side or type")
    _decimal(order["qty"], "order quantity")
    for key, types in (("limit_price", ("LIMIT", "STOP_LIMIT")), ("stop_price", ("STOP", "STOP_LIMIT"))):
        if (key in order) != (order["type"] in types):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external order price fields do not match its type")
        if key in order:
            _decimal(order[key], key)
    if "tif" in order and order["tif"] not in ("GTC", "IOC", "FOK"):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external time in force")
    if "reduce_only" in order and type(order["reduce_only"]) is not bool:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external reduce_only must be boolean")
    if "oco_group" in order and (type(order["oco_group"]) is not str or len(order["oco_group"]) > 128):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external OCO group")


def decision_output(manifest: ExternalProviderManifest, value: object, *, sequence: int,
                    state_hash: str) -> StrategyOutput | None:
    if value is None:
        return None
    decision = _object(value, {"sequence", "kind", "payload"}, set(), "decision")
    if type(decision["sequence"]) is not int or decision["sequence"] != sequence:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external decision sequence does not match its observation")
    kind = decision["kind"]
    if kind not in manifest.output_modes:
        raise StrategyProviderError("PROVIDER_UNAUTHORIZED_WRITE", "external decision kind was not declared")
    if kind == "TARGET_POSITION":
        payload = _object(decision["payload"], {"targetExposure"}, {"reasonCode"}, "target position")
        _decimal(payload["targetExposure"], "absolute target quantity")
        _reason(payload)
    elif kind == "SIGNAL":
        payload = _object(decision["payload"], {"direction"}, {"score", "confidence", "horizon", "reasonCode"}, "signal")
        if payload["direction"] not in ("LONG", "SHORT", "FLAT"):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external signal direction")
        for name in ("score", "confidence", "horizon"):
            if name in payload:
                _decimal(payload[name], name)
        _reason(payload)
    else:
        payload = decision["payload"]
        if type(payload) is dict and set(payload) == {"intents"}:
            intents = payload["intents"]
            if type(intents) is not list or not 1 <= len(intents) <= 64:
                raise StrategyProviderError("BUDGET_EXCEEDED", "external order batch must contain 1–64 intents")
            for intent in intents:
                _order(intent)
        else:
            _order(payload)
    detached = decode(encode(decision))
    return StrategyOutput(sequence=sequence, kind=kind, payload=detached["payload"],
                          state_hash=state_hash, output_hash=digest(detached))


def observation_payload(frame: ObservationFrame, manifest: ExternalProviderManifest) -> dict[str, Any]:
    if (frame.phase not in ("WARMUP", "EVALUATION") or type(frame.sequence) is not int or frame.sequence < 1
            or type(frame.event_time_ms) is not int or type(frame.watermark_ms) is not int):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external Host observation identity")
    if frame.event_time_ms > frame.watermark_ms:
        raise StrategyProviderError("LOOKAHEAD_VIOLATION", "external observation exceeds the Host watermark")
    if frame.bar is None or frame.trade is not None or frame.book is not None:
        raise StrategyProviderError("FIDELITY_UNSUPPORTED", "external version one requires a closed BAR observation")
    close_time = frame.bar.get("close_time_ms", frame.bar.get("closeTimeMs"))
    if close_time is not None:
        if type(close_time) is not int:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external BAR close time must be an integer")
        if close_time > frame.watermark_ms:
            raise StrategyProviderError("LOOKAHEAD_VIOLATION", "external BAR has not closed at the Host watermark")
    names = manifest.required_features
    if set(frame.features) != set(names):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external observation features differ from the frozen manifest")
    return decode(encode({
        "schema_version": "candlescope.external-observation/1",
        "run_id": frame.run_id, "sequence": frame.sequence,
        "event_time_ms": frame.event_time_ms, "watermark_ms": frame.watermark_ms,
        "phase": frame.phase, "market": dict(frame.market), "bar": dict(frame.bar),
        "features": dict(frame.features), "feature_names": list(names),
        "account_view": dict(frame.account_view), "host_input_hash": frame.input_hash,
    }))


@dataclass(frozen=True, slots=True)
class ValidatedReply:
    recorded: dict[str, Any]
    state_json: str | None
    state_hash: str | None
    output: StrategyOutput | None


def validate_reply(manifest: ExternalProviderManifest, operation: str, payload: dict[str, Any],
                   result: object, *, max_state_bytes: int) -> ValidatedReply:
    if operation not in OPERATIONS:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "unknown external operation")
    if type(result) is dict and "error" in result:
        root = _object(result, {"error"}, set(), "error reply")
        error = _object(root["error"], {"code", "message"}, set(), "provider error")
        if (type(error["code"]) is not str or error["code"] not in _ERRORS
                or type(error["message"]) is not str or len(error["message"]) > 1024):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external provider error")
        return ValidatedReply(decode(encode(root)), None, None, None)
    root = _object(result, {"decision", "model_state"}, set(), "reply")
    if type(root["model_state"]) is not dict:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external model state must be a JSON object")
    state_json = encode(root["model_state"], max_bytes=max_state_bytes)
    state_hash = digest(root["model_state"])
    if operation != "step" and root["decision"] is not None:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external decisions are allowed only during step")
    output = None
    if operation == "step":
        observation = payload.get("observation")
        if type(observation) is not dict or observation.get("phase") != "EVALUATION":
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external step requires an evaluation Host observation")
        sequence = observation.get("sequence")
        if type(sequence) is not int or sequence < 1:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external Host sequence")
        output = decision_output(manifest, root["decision"], sequence=sequence, state_hash=state_hash)
    recorded = decode(encode({"decision": root["decision"], "model_state_hash": state_hash}))
    return ValidatedReply(recorded, state_json, state_hash, output)
