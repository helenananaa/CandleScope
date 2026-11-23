"""ADR-BACKTEST-015 P3c: the strategy pages' references, stored in the backend."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.data_engine.data_manager.strategy import StrategyDataManager
from tests.test_strategy_drafts import _settings, service  # noqa: F401 - fixture

SCOPE = json.dumps(["workspace\u0000cell-1", "draft-abcdefgh"])  # a chart scope, as the continuous panel keys it


def reference(request_key="chart/1", run_id=None):
    return {"schema": 1, "requestKey": request_key, "runId": run_id, "inputRevision": "42", "createdAtMs": 5,
            "settings": {"from": "2026-11-01T00:00", "balance": "10000", "percent": "10", "fee": "4", "slippage": "1",
                         "output": "TARGET_POSITION"}}


def test_references_are_kept_listed_and_removed(service):
    refs = StrategyDataManager(service).references()
    stored = refs.put("continuous-run", {"key": SCOPE, "value": reference()}, now_ms=10)
    assert (stored["key"], stored["value"], stored["updated_at_ms"]) == (SCOPE, reference(), 10)
    refs.put("continuous-run", {"key": f"{SCOPE}::chart/1", "value": reference()}, now_ms=11)
    refs.put("continuous-run", {"key": f"{SCOPE}::chart/2", "value": reference("chart/2", "cs_2")}, now_ms=12)
    refs.put("continuous-run", {"key": "[\"other\"]", "value": reference("chart/9")}, now_ms=13)
    archive = refs.list("continuous-run", prefix=f"{SCOPE}::")["entries"]
    assert [entry["key"] for entry in archive] == [f"{SCOPE}::chart/2", f"{SCOPE}::chart/1"]
    updated = refs.put("continuous-run", {"key": SCOPE, "value": reference("chart/2", "cs_2")}, now_ms=14)
    assert updated["value"]["runId"] == "cs_2"
    assert refs.remove("continuous-run", "[\"other\"]")["removed"] is True
    with pytest.raises(BacktestError) as missing:
        refs.get("continuous-run", "[\"other\"]")
    assert missing.value.code == "REFERENCE_NOT_FOUND"
    for kind, body, code in (
        ("unknown-kind", {"key": "k", "value": {}}, "REFERENCE_NOT_FOUND"),
        ("continuous-run", {"key": "", "value": {}}, "REFERENCE_INVALID"),
        ("continuous-run", {"key": "x" * 513, "value": {}}, "REFERENCE_INVALID"),
        ("continuous-run", {"key": "k", "value": [1]}, "REFERENCE_INVALID"),
        ("continuous-run", {"key": "k", "value": {"big": "x" * 70_000}}, "REFERENCE_INVALID"),
        ("continuous-run", {"key": "k"}, "REFERENCE_INVALID"),
    ):
        with pytest.raises(BacktestError) as invalid:
            refs.put(kind, body)
        assert invalid.value.code == code


def test_references_survive_a_full_restart(tmp_path):
    """The P3 gate: a chart's forward-run reference is still there after quitting."""
    first = BacktestService.start(_settings(tmp_path), now_ms=1)
    try:
        StrategyDataManager(first).references().put("continuous-run", {"key": SCOPE, "value": reference("chart/1", "cs_1")})
    finally:
        first.shutdown()
    second = BacktestService.start(_settings(tmp_path), now_ms=2)
    try:
        assert StrategyDataManager(second).references().get("continuous-run", SCOPE)["value"]["runId"] == "cs_1"
    finally:
        second.shutdown()


def test_forward_references_refuse_when_full_and_hand_offs_drop_the_oldest(service, monkeypatch):
    import app.backtest.strategy_references as module
    monkeypatch.setitem(module.KINDS, "continuous-run", (2, False))
    monkeypatch.setitem(module.KINDS, "research-handoff", (2, True))
    refs = StrategyDataManager(service).references()
    refs.put("continuous-run", {"key": "a", "value": reference()}, now_ms=1)
    refs.put("continuous-run", {"key": "b", "value": reference()}, now_ms=2)
    with pytest.raises(BacktestError) as full:
        refs.put("continuous-run", {"key": "c", "value": reference()}, now_ms=3)
    assert full.value.code == "REFERENCE_CAPACITY_EXCEEDED"
    refs.put("continuous-run", {"key": "a", "value": reference("chart/2")}, now_ms=4)  # an existing key still updates
    for index in range(4):
        refs.put("research-handoff", {"key": f"h{index}", "value": {"n": index}}, now_ms=10 + index)
    assert [entry["key"] for entry in refs.list("research-handoff")["entries"]] == ["h3", "h2"]


def test_importing_browser_entries_keeps_backend_entries_and_is_idempotent(service):
    refs = StrategyDataManager(service).references()
    refs.put("continuous-run", {"key": SCOPE, "value": reference("chart/backend", "cs_b")}, now_ms=1)
    entries = [{"key": SCOPE, "value": reference("chart/browser")}, {"key": f"{SCOPE}::chart/browser", "value": reference("chart/browser")}]
    assert refs.import_entries("continuous-run", {"entries": entries}) == {
        "kind": "continuous-run", "imported": [f"{SCOPE}::chart/browser"], "kept": [SCOPE]}
    assert refs.import_entries("continuous-run", {"entries": entries})["imported"] == []
    assert refs.get("continuous-run", SCOPE)["value"]["requestKey"] == "chart/backend"
    with pytest.raises(BacktestError):
        refs.import_entries("continuous-run", {"entries": [entries[0], entries[0]]})


def test_the_reference_routes(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.strategy_references import router

    app = FastAPI()
    app.state.data_manager_core = SimpleNamespace(strategy=StrategyDataManager(service))
    app.include_router(router)
    with TestClient(app) as client:
        put = client.put("/strategy-references/continuous-run/entry", json={"key": SCOPE, "value": reference()})
        got = client.get("/strategy-references/continuous-run/entry", params={"key": SCOPE})
        listed = client.get("/strategy-references/continuous-run", params={"prefix": SCOPE[:10]})
        imported = client.post("/strategy-references/research-return/import",
                               json={"entries": [{"key": "ret-1", "value": {"schema": 1}}]})
        missing = client.get("/strategy-references/continuous-run/entry", params={"key": "nope"})
        unknown = client.get("/strategy-references/elsewhere")
        removed = client.delete("/strategy-references/continuous-run/entry", params={"key": SCOPE})
    assert put.status_code == 200 and got.json()["value"] == reference()
    assert [entry["key"] for entry in listed.json()["entries"]] == [SCOPE]
    assert imported.json()["imported"] == ["ret-1"]
    assert missing.status_code == 404 and unknown.status_code == 404
    assert removed.json()["removed"] is True
