"""ADR-BACKTEST-015 P6e3: fixed and forward runs choose the practice account model explicitly.

``account_rules: PRACTICE_V1`` puts a run on the Host kernel's PRACTICE clock. It is part of
the run identity, and refused where the practice model has nothing to offer. The P0 oracles
(``test_strategy_run_oracles``) prove a forward run on it reproduces the fixed run.
"""
from __future__ import annotations

import json

import pytest

from app.backtest.continuous_definition import prepare_definition
from app.backtest.errors import BacktestError
from app.backtest.identity import config_hash
from app.backtest.strategy.registry import BUILTIN_SMA_REVISION
from tests.test_continuous_definition import KEY
from tests.test_continuous_provider import spec
from tests.test_strategy_run_oracles import BAR, PRACTICE, service  # noqa: F401 - fixture


def test_practice_rules_are_part_of_the_run_identity(service):  # noqa: F811
    bar = service.validate_run({**BAR, "strategy_revision_id": BUILTIN_SMA_REVISION})
    practice = service.validate_run({**PRACTICE, "strategy_revision_id": BUILTIN_SMA_REVISION})
    assert bar["config_hash"] != practice["config_hash"]
    row = service.create_run({**PRACTICE, "strategy_revision_id": BUILTIN_SMA_REVISION}, idempotency_key="practice-row")
    config = json.loads(str(row["config_json"]))
    assert (config["account_rules"], config["leverage"]) == ("PRACTICE_V1", "10")
    assert config_hash(service._identity_from_payload({**PRACTICE, "strategy_revision_id": BUILTIN_SMA_REVISION})) == practice["config_hash"]


@pytest.mark.parametrize("override,code", [
    ({"account_rules": "PRACTICE_V2"}, "SCHEMA_UNKNOWN_FIELD"),
    ({"account_model": "LINEAR_PERP_ONE_WAY_V2"}, None),  # refused earlier: V2 needs contract history
    ({"execution_model_revision": "EXECUTION_REALISM_V2", "participation_rate": "0.5"}, "FIDELITY_UNSUPPORTED"),
    ({"funding_rate": "0.0001"}, "FIDELITY_UNSUPPORTED"),
])
def test_fixed_runs_refuse_what_the_practice_model_does_not_have(service, override, code):  # noqa: F811
    with pytest.raises(BacktestError) as refused:
        service.validate_run({**PRACTICE, "strategy_revision_id": BUILTIN_SMA_REVISION, **override})
    assert code is None or refused.value.code == code


def test_forward_runs_take_the_practice_model_with_its_leverage():
    prepared = prepare_definition(spec(), {"account_rules": "PRACTICE_V1", "leverage": "10"}, KEY)
    assert (prepared["configuration"]["account_rules"], prepared["configuration"]["leverage"]) == ("PRACTICE_V1", "10")
    # The qualified V1 contract account keeps leverage 1 without the practice model.
    with pytest.raises(BacktestError):
        prepare_definition(spec(), {"leverage": "10"}, KEY)
    for execution in ({"account_rules": "PRACTICE_V2"},
                      {"account_rules": "PRACTICE_V1", "execution_model_revision": "EXECUTION_REALISM_V2",
                       "participation_rate": "0.5"}):
        with pytest.raises(BacktestError):
            prepare_definition(spec(), execution, KEY)


def test_the_http_run_contract_carries_the_practice_rules():
    """/backtests/runs validates its body with RunCreateRequest, which forbids unknown fields."""
    from app.backtest.request_contracts import RunCreateRequest

    body = RunCreateRequest.model_validate({**PRACTICE, "strategy_revision_id": BUILTIN_SMA_REVISION}).model_dump()
    assert body["account_rules"] == "PRACTICE_V1"
