"""ADR-BACKTEST-015 P2: one run facade over every run family.

A real host runtime run, plus native and forward records shaped as their stores
write them. Real Pine runs through the facade: ``test_strategy_runs_pine.py``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.models import RunState
from app.backtest.native import TERMINAL as NATIVE_TERMINAL
from app.data_engine.data_manager.strategy import StrategyDataManager
from app.data_engine.data_manager.strategy_runs import (
    CONTINUOUS_CREATION_PHASES, CONTINUOUS_PHASES, HOST_STATES, NATIVE_STATES, STATES, STATUS_SCHEMA,
)
from tests import strategy_run_oracles as oracles
from tests.test_run_result import runtime_run  # noqa: F401 - fixture


def _client(runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.strategy_runs import router

    manager = StrategyDataManager(runtime.service, runtime=runtime)
    app = FastAPI()
    app.state.data_manager_core = SimpleNamespace(strategy=manager)
    app.include_router(router)
    return TestClient(app), manager


def _native_record(runtime, record, key):
    native = runtime.native
    with native.lock:
        native.db.execute("INSERT INTO runs VALUES (?,?,?,?)", (record["run_id"], key, "hash", json.dumps(record)))
        native._save_summary(record)
        native.db.commit()


class _Forward:
    """A continuous access whose status is whatever the test sets."""

    def __init__(self, value=None, *, enabled=True):
        self.value = value
        self.enabled = enabled
        self.subscriptions = ()

    def controller(self):
        return SimpleNamespace(execution_enabled=self.enabled)

    async def status(self, run_id):
        if self.value is None:
            raise BacktestError("CONTINUOUS_RUN_NOT_FOUND", "Unknown continuous strategy run")
        return self.value

    def close_views(self):
        pass


def test_every_family_state_maps_onto_the_shared_lifecycle():
    assert set(HOST_STATES) == {state.value for state in RunState}
    assert set(NATIVE_STATES) == set(NATIVE_TERMINAL) | {"QUEUED", "RUNNING"}
    for mapping in (HOST_STATES, NATIVE_STATES, CONTINUOUS_PHASES, CONTINUOUS_CREATION_PHASES):
        assert set(mapping.values()) <= set(STATES)


def test_a_host_run_reads_the_same_through_the_facade(runtime_run):
    runtime, run_id = runtime_run
    client, _ = _client(runtime)
    with client:
        status = client.get(f"/strategy-runs/{run_id}")
        result = client.get(f"/strategy-runs/{run_id}/result")
        cancelled = client.post(f"/strategy-runs/{run_id}/cancel")
    assert status.status_code == 200
    assert status.json() == {
        "schema": STATUS_SCHEMA, "run_id": run_id, "family": "host", "authority": "HOST", "clock_policy": "FIXED",
        "fidelity": "BAR_APPROX", "language": None, "state": "COMPLETED", "source_state": "COMPLETED",
        "terminal": True, "generation": runtime.service.get_run(run_id)["generation"], "result_available": True,
        "error": None,
    }
    assert result.status_code == 200 and result.json() == runtime.run_result(run_id)
    # The frontend parser's contract fixture is exactly this status, minus the per-run id.
    oracles.assert_frontend_fixture("host-completed", {**status.json(), "run_id": "bt_fixture"}, kind="strategy-run")
    # Cancelling a finished run changes nothing and is not an error.
    assert cancelled.status_code == 200 and cancelled.json() == status.json()
    assert runtime.service.get_run(run_id)["state"] == "COMPLETED"


def test_unknown_and_forged_ids_are_not_found_in_any_family(runtime_run):
    runtime, run_id = runtime_run
    client, _ = _client(runtime)
    with client:
        responses = [client.get(f"/strategy-runs/{run_id}")]
        for missing in ("bt_missing", "native_missing", "missing", "x" * 129, f"native_{run_id}"):
            responses.append(client.get(f"/strategy-runs/{missing}"))
            responses.append(client.get(f"/strategy-runs/{missing}/result"))
    assert responses[0].status_code == 200
    for response in responses[1:]:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_native_and_external_records_report_their_own_authority(runtime_run):
    runtime, _ = runtime_run
    _native_record(runtime, {"run_id": "native_external", "execution_mode": "CANDLESCOPE", "state": "QUEUED",
                             "config": {"language": "pine", "execution_fidelity": "TRADE_TAPE"},
                             "result": None, "error": None}, "external")
    _native_record(runtime, {"run_id": "native_interrupted", "execution_mode": "NATIVE", "state": "INTERRUPTED",
                             "config": {"language": "pine"}, "result": None,
                             "error": {"code": "HOST_RESTARTED", "message": "rerun explicitly"}}, "interrupted")
    client, _ = _client(runtime)
    with client:
        external = client.get("/strategy-runs/native_external").json()
        interrupted = client.get("/strategy-runs/native_interrupted").json()
        not_ready = client.get("/strategy-runs/native_external/result")
        cancelled = client.post("/strategy-runs/native_external/cancel")
    assert {key: external[key] for key in ("family", "authority", "clock_policy", "fidelity", "language", "state",
                                           "terminal", "result_available", "generation")} == {
        "family": "external", "authority": "HOST", "clock_policy": "FIXED", "fidelity": "TRADE_TAPE",
        "language": "pine", "state": "QUEUED", "terminal": False, "result_available": False, "generation": None}
    # A native run fills by the script's own model: no host fidelity.
    assert interrupted["family"] == "native" and interrupted["authority"] == "SCRIPT" and interrupted["fidelity"] is None
    assert (interrupted["state"], interrupted["source_state"], interrupted["terminal"]) == ("FAILED", "INTERRUPTED", True)
    assert interrupted["error"] == {"code": "HOST_RESTARTED", "message": "rerun explicitly"}
    assert not_ready.status_code == 400
    assert cancelled.status_code == 200
    assert (cancelled.json()["state"], cancelled.json()["terminal"]) == ("CANCELLED", True)
    assert runtime.native.get("native_external")["state"] == "CANCELLED"


@pytest.mark.parametrize("value,expected", [
    ({"creation": {"phase": "READY", "error": None}, "run": None}, ("QUEUED", "READY", None, False)),
    ({"creation": {"phase": "FAILED", "error": {"code": "INPUT", "message": "m"}}, "run": None},
     ("FAILED", "FAILED", None, True)),
    ({"creation": None, "run": {"phase": "LIVE", "generation": 1, "error": None}}, ("RUNNING", "LIVE", 1, False)),
    ({"creation": None, "run": {"phase": "REPAIR_REQUIRED", "generation": 3, "error": {"code": "GAP", "message": "m"}}},
     ("BLOCKED", "REPAIR_REQUIRED", 3, False)),
])
def test_forward_runs_report_status_but_not_a_result_yet(runtime_run, monkeypatch, value, expected):
    runtime, _ = runtime_run
    client, manager = _client(runtime)
    monkeypatch.setattr(manager, "continuous_access", lambda: _Forward(value))
    with client:
        status = client.get("/strategy-runs/cs_run").json()
        result = client.get("/strategy-runs/cs_run/result")
        cancel = client.post("/strategy-runs/cs_run/cancel")
    assert (status["state"], status["source_state"], status["generation"], status["terminal"]) == expected
    assert (status["family"], status["authority"], status["clock_policy"], status["fidelity"]) == (
        "continuous", "HOST", "FORWARD", "BAR_APPROX")
    assert status["result_available"] is False
    assert result.status_code == 409 and result.json()["error"]["code"] == "RUN_RESULT_UNAVAILABLE"
    if status["terminal"]:
        assert cancel.status_code == 200 and cancel.json() == status
    else:
        # Forward-run controls need the account's committed identity.
        assert cancel.status_code == 409 and cancel.json()["error"]["code"] == "RUN_CONTROL_UNSUPPORTED"


def test_forward_ids_resolve_only_in_their_own_store(runtime_run, monkeypatch):
    runtime, _ = runtime_run
    client, manager = _client(runtime)
    with client:
        unbound = client.get("/strategy-runs/cs_run")
        monkeypatch.setattr(manager, "continuous_access", lambda: _Forward(None))
        missing = client.get("/strategy-runs/cs_run")
        monkeypatch.setattr(manager, "continuous_access", lambda: _Forward({"creation": None, "run": {
            "phase": "SOMETHING_NEW", "generation": 1, "error": None}}))
        unknown_phase = client.get("/strategy-runs/cs_run")
    assert unbound.status_code == 503 and unbound.json()["error"]["code"] == "CONTINUOUS_NOT_READY"
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "RUN_NOT_FOUND"
    # A state the facade does not know is refused rather than guessed.
    assert unknown_phase.status_code == 400 and unknown_phase.json()["error"]["code"] == "RUN_STATE_UNKNOWN"


def test_one_capability_matrix_covers_every_family(runtime_run, monkeypatch):
    runtime, _ = runtime_run
    monkeypatch.delenv("BACKTEST_PYTHON_STRATEGY_ENABLED", raising=False)
    monkeypatch.setattr(runtime.native, "capabilities", lambda: {"engines": [
        {"language": "pine", "available": True, "external_available": False}]})
    client, manager = _client(runtime)
    with client:
        without_forward = client.get("/strategy-runs/capabilities").json()
        monkeypatch.setattr(manager, "continuous_access", lambda: _Forward(enabled=False))
        matrix = client.get("/strategy-runs/capabilities").json()
    assert without_forward["families"]["continuous"] == {"available": False, "reason": "CONTINUOUS_NOT_READY"}
    assert not [row for row in without_forward["profiles"] if row["family"] == "continuous"]
    assert matrix["schema"] == "candlescope.strategy-run-capabilities/1"
    oracles.assert_frontend_fixture("matrix", matrix, kind="strategy-run-capabilities")
    assert matrix["families"] == {
        "host": {"available": True, "reason": None}, "native": {"available": True, "reason": None},
        "external": {"available": False, "reason": "ENGINE_UNAVAILABLE"},
        "continuous": {"available": False, "reason": "READ_ONLY"},
    }
    rows = {(row["family"], row["language"]): row for row in matrix["profiles"]}
    assert set(rows) == {("host", "builtin"), ("host", "pine"), ("host", "python"), ("native", "pine"),
                         ("external", "pine"), ("continuous", "builtin"), ("continuous", "python")}
    host = rows["host", "builtin"]
    assert host["available"] and host["authority"] == "HOST" and host["clock_policy"] == "FIXED"
    assert host["fidelities"] == runtime.service.capabilities()["fidelity_modes"] and "BAR_APPROX" in host["fidelities"]
    assert rows["host", "python"]["available"] is False and rows["host", "python"]["reason"] == "FLAG_DISABLED"
    native = rows["native", "pine"]
    assert (native["available"], native["authority"], native["fidelities"], native["account_models"]) == (
        True, "SCRIPT", None, None)
    assert rows["external", "pine"]["authority"] == "HOST" and rows["external", "pine"]["reason"] == "ENGINE_UNAVAILABLE"
    assert "BAR_APPROX" in rows["external", "pine"]["fidelities"]
    forward = rows["continuous", "builtin"]
    assert (forward["clock_policy"], forward["intervals"], forward["starts"], forward["controls"]) == (
        "FORWARD", ["1m"], ["HISTORY_LIVE", "LIVE_ONLY"], {"cancel": False})
    assert forward["available"] is False and forward["reason"] == "READ_ONLY"


def test_a_closed_manager_serves_nothing(runtime_run):
    runtime, run_id = runtime_run
    client, manager = _client(runtime)
    manager.close()
    with client:
        response = client.get(f"/strategy-runs/{run_id}")
        capabilities = client.get("/strategy-runs/capabilities")
    assert response.status_code == capabilities.status_code == 503
    assert response.json()["error"]["code"] == "STRATEGY_MANAGER_CLOSED"
