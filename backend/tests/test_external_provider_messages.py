from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from app.backtest.external_provider.contracts import parse_manifest
from app.backtest.external_provider.messages import observation_payload, validate_reply
from app.backtest.external_provider.wire import decode, digest, encode
from app.backtest.strategy.protocol import (
    ObservationFrame,
    StrategyProviderError,
    canonical_hash,
)

from tests.test_external_provider_contracts import manifest


def frame(**changes):
    original = ObservationFrame("run_one", 7, 100, 100, "EVALUATION", {"symbol": "LTC"}, "sha256:input",
                                bar={"close_time_ms": 100, "close": "12.5"},
                                features={"close": "12.5", "volume": "3"})
    return replace(original, **changes)


def reply(decision=None, state=None):
    return {"decision": decision, "model_state": {} if state is None else state}


def target(quantity="0.01", **changes):
    return {"sequence": 7, "kind": "TARGET_POSITION", "payload": {"targetExposure": quantity}, **changes}


def validate(result, *, operation="step", observation=None, parsed=None, budget=8192):
    return validate_reply(parsed or parse_manifest(manifest()), operation,
                          {"observation": observation or observation_payload(frame(), parse_manifest(manifest()))},
                          result, max_state_bytes=budget)


def test_wire_hash_matches_host_including_unicode_and_decimal_strings():
    value = {"中文": [1, True, None, "λ"], "price": "1.25"}
    assert digest(value) == canonical_hash(value)
    assert decode(encode({"price": Decimal("1.25")})) == {"price": "1.25"}


@pytest.mark.parametrize("raw", ['{"secret":1,"secret":2}', '{"n":NaN}', '{"n":1e999}', b'\xff',
                                 '{"n":9007199254740992}', '\ud800', '[' * 40 + '0' + ']' * 40])
def test_ambiguous_nonfinite_inexact_or_overdeep_json_is_rejected(raw):
    with pytest.raises(StrategyProviderError):
        decode(raw)


def test_wire_size_limits_apply_to_encoded_bytes_and_errors_hide_input():
    secret = "private-test-credential"
    with pytest.raises(StrategyProviderError) as failure:
        decode('{"credential":"' + secret + '",oops}')
    assert secret not in str(failure.value)
    with pytest.raises(StrategyProviderError, match="byte budget"):
        encode({"unicode": "中"}, max_bytes=10)


def test_observation_keeps_feature_order_and_only_detached_visible_values():
    parsed = parse_manifest(manifest(required_features=["volume", "close"]))
    original = frame()
    result = observation_payload(original, parsed)
    assert result["feature_names"] == ["volume", "close"]
    result["bar"]["close"] = "999"
    assert original.bar["close"] == "12.5"
    assert result["account_view"] == {}


@pytest.mark.parametrize("change", [
    {"event_time_ms": 101}, {"bar": {"close_time_ms": 101}},
    {"bar": {"close_time_ms": True}}, {"bar": {"close_time_ms": 100.5}},
    {"trade": {"price": "12"}}, {"features": {"close": "12.5", "future_close": "30"}},
    {"phase": "LIVE"}, {"sequence": True}, {"event_time_ms": 99.5},
])
def test_future_unclosed_or_undeclared_observations_are_rejected(change):
    with pytest.raises(StrategyProviderError):
        observation_payload(frame(**change), parse_manifest(manifest()))


def test_host_computes_output_and_state_hashes_and_uses_absolute_quantity_contract():
    decision = target("-0.125")
    state = {"last_sequence": 7, "mean": "12.4"}
    validated = validate(reply(decision, state))
    assert validated.output.payload == {"targetExposure": "-0.125"}
    assert validated.output.output_hash == canonical_hash(decision)
    assert validated.state_hash == canonical_hash(state)
    assert validated.recorded == {"decision": decision, "model_state_hash": canonical_hash(state)}
    assert "model_state" not in validated.recorded


@pytest.mark.parametrize("operation", ["prepare", "warmup", "onExecutionReport", "close"])
def test_only_evaluation_step_can_emit_decisions(operation):
    with pytest.raises(StrategyProviderError, match="only during step"):
        validate(reply(target()), operation=operation)
    assert validate(reply(), operation=operation).output is None


@pytest.mark.parametrize("decision", [target(sequence=True), target(sequence=8),
                                       target(kind="ACCOUNT_UPDATE"), target(balance="999"),
                                       target(payload={"targetExposure": "1", "equity": "999"})])
def test_sequence_and_host_write_authority_are_enforced(decision):
    with pytest.raises(StrategyProviderError):
        validate(reply(decision))


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "1e999999999", " 1", "１", "1_000", 1, True])
def test_decimal_fields_reject_nonfinite_ambiguous_and_expansion_bombs(quantity):
    with pytest.raises(StrategyProviderError):
        validate(reply(target(quantity)))


def test_warmup_frame_cannot_be_submitted_as_an_evaluation_step():
    with pytest.raises(StrategyProviderError, match="evaluation"):
        validate(reply(target()), observation={"phase": "WARMUP", "sequence": 7})


def test_order_intents_use_host_fields_without_order_id_or_eligibility_authority():
    parsed = parse_manifest(manifest(provider_kind="STRATEGY", output_modes=["ORDER_INTENT"]))
    order = {"side": "BUY", "type": "STOP_LIMIT", "qty": "0.01", "limit_price": "13",
             "stop_price": "12.9", "tif": "GTC", "reduce_only": False, "oco_group": "group_one"}
    decision = {"sequence": 7, "kind": "ORDER_INTENT", "payload": {"intents": [order]}}
    assert validate(reply(decision), parsed=parsed).output.payload == decision["payload"]
    for key, value in (("order_id", "external"), ("eligible_after_sequence", 0), ("limitPrice", "13")):
        with pytest.raises(StrategyProviderError):
            validate(reply({**decision, "payload": {**order, key: value}}), parsed=parsed)


def test_state_budget_and_error_grammar_are_bounded():
    with pytest.raises(StrategyProviderError, match="byte budget"):
        validate(reply(state={"large": "x" * 100}), budget=64)
    for code in ([], {}, "LOOKAHEAD_VIOLATION"):
        with pytest.raises(StrategyProviderError):
            validate({"error": {"code": code, "message": "invalid"}})
    result = validate({"error": {"code": "PROVIDER_TIMEOUT", "message": "model budget exceeded"}})
    assert result.state_json is None and result.output is None
