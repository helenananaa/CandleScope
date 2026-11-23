"""ADR-BACKTEST-015 P5c: run again with changed settings, from a stored run's configuration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backtest.errors import BacktestError
from app.backtest.strategy.builtin import BuiltinRsiWilderLongShortProvider
from tests.test_backtest_strategy_workspace_m9 import _events, _payload, _revision, _service


def _completed(tmp_path: Path):
    service = _service(tmp_path)
    revision = _revision(service)
    payload = _payload(str(revision["revision_id"]))
    service.smoke_strategy_revision(str(revision["revision_id"]), payload, now_ms=3)
    run = service.create_run(payload, idempotency_key="origin", now_ms=4)
    service.execute_bar_run(str(run["run_id"]), events=_events(), provider=BuiltinRsiWilderLongShortProvider(), now_ms=5)
    return service, run


def test_a_derived_run_keeps_the_input_and_strategy_and_changes_only_the_given_settings(tmp_path: Path) -> None:
    service, run = _completed(tmp_path)
    derived = service.derive_run(str(run["run_id"]), overrides={
        "parameters": {"length": 3}, "taker_fee_bps": "5", "initial_balance": "20000",
    }, idempotency_key="derive-1")
    before, after = json.loads(str(run["config_json"])), json.loads(str(derived["config_json"]))
    assert derived["run_id"] != run["run_id"]
    for key in ("strategy_revision_id", "dataset_id", "snapshot_hash", "start_time_ms", "end_time_ms"):
        assert after[key] == before[key], key
    assert after["parameters"] == {**before["parameters"], "length": 3}
    assert (after["taker_fee_bps"], after["initial_balance"], after["fee_source"]) == ("5", "20000", "user-defined")
    again = service.derive_run(str(run["run_id"]), overrides={"parameters": {"length": 3}, "taker_fee_bps": "5",
                                                              "initial_balance": "20000"}, idempotency_key="derive-1")
    assert again["run_id"] == derived["run_id"], "the same key is the same derived run"
    service.shutdown()


@pytest.mark.parametrize("overrides, code", [
    ({}, "IDENTITY_MUTATION"),
    ({"parameters": {"length": 2}}, "IDENTITY_MUTATION"),
    ({"dataset_id": "other"}, "SCHEMA_UNKNOWN_FIELD"),
    ({"snapshot_hash": "sha256:other"}, "SCHEMA_UNKNOWN_FIELD"),
    ({"parameters": {"unknown": 1}}, "SCHEMA_UNKNOWN_FIELD"),
    ({"parameters": [1]}, "SCHEMA_UNKNOWN_FIELD"),
])
def test_a_derived_run_never_changes_its_input_or_strategy(tmp_path: Path, overrides, code) -> None:
    service, run = _completed(tmp_path)
    with pytest.raises(BacktestError) as refused:
        service.derive_run(str(run["run_id"]), overrides=overrides, idempotency_key="refused")
    assert refused.value.code == code
    service.shutdown()
