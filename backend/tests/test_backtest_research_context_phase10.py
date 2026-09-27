from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.core.config import load_backtest_settings


def _service(tmp_path: Path) -> BacktestService:
    settings = load_backtest_settings(
        {"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"},
        data_dir=tmp_path,
        klines_db_path=tmp_path / "candlescope.db",
        replay_db_path=tmp_path / "replay.db",
    )
    return BacktestService.start(settings, now_ms=10)


def _context(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_workspace_id": "workspace-main",
        "source_cell_id": "cell-main",
        "strategy_draft_id": "draft-12345678",
        "strategy_revision_id": "builtin-sma-cross-v1",
        "parameters": {"fast": 3, "slow": 5},
        "quick_preset_id": "crypto-perp-conservative-v1",
        "chart_session": {
            "exchange": "binance",
            "market_type": "usdm",
            "symbol": "BTCUSDT",
            "interval": "15m",
        },
        "range": {
            "mode": "CUSTOM",
            "start_time_ms": 1_700_000_000_000,
            "end_time_ms": 1_700_086_400_000,
        },
        "dataset_identity": {
            "dataset_id": "local-0123456789abcdef0123456789abcdef",
            "data_epoch": "sha256:" + "ab" * 32,
            "snapshot_hash": "sha256:" + "cd" * 32,
        },
        "latest_run_id": None,
        "baseline_run_id": None,
    }
    payload.update(overrides)
    return payload


def test_execution_overrides_survive_context_round_trip_and_reject_invalid_ranges(tmp_path: Path) -> None:
    from app.backtest.request_contracts import ResearchLaunchContextRequest
    from pydantic import ValidationError
    overrides = {"initialBalance": "2000", "equityPercent": "25", "leverage": "2", "feeBps": "7", "slippageBps": "3"}
    payload = ResearchLaunchContextRequest.model_validate(_context(execution_overrides=overrides))
    service = _service(tmp_path)
    try:
        context = service.create_research_launch_context(payload.model_dump())
        restored = service.get_research_launch_context(str(context["context_id"]))
        assert restored["execution_overrides"] == overrides
        with pytest.raises(ValidationError):
            ResearchLaunchContextRequest.model_validate(_context(execution_overrides={**overrides, "equityPercent": "101"}))
    finally:
        service.shutdown()


def test_research_context_is_immutable_and_integrity_checked(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        created = service.create_research_launch_context(_context(), now_ms=20)
        assert str(created["context_id"]).startswith("brc_")
        assert created["schema_version"] == (
            "candlescope.backtest-research-launch-context/1"
        )
        restored = service.get_research_launch_context(str(created["context_id"]))
        assert restored == created
        row = service.repository.get_research_launch_context(str(created["context_id"]))
        assert row is not None
        mutated = json.loads(str(row["payload_json"]))
        mutated["parameters"]["fast"] = 99
        service.repository.connection.execute(
            "UPDATE backtest_research_launch_contexts SET payload_json = ? WHERE context_id = ?",
            (json.dumps(mutated), created["context_id"]),
        )
        service.repository.connection.commit()
        with pytest.raises(BacktestError, match="IDENTITY_MUTATION"):
            service.get_research_launch_context(str(created["context_id"]))
    finally:
        service.shutdown()


def test_research_context_rejects_unknown_authoritative_ids(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        with pytest.raises(BacktestError, match="unknown run"):
            service.create_research_launch_context(
                _context(latest_run_id="bt_missing_12345678")
            )
        with pytest.raises(BacktestError, match="unknown strategy revision"):
            service.create_research_launch_context(
                _context(strategy_revision_id="rev-missing")
            )
    finally:
        service.shutdown()


def test_research_context_http_round_trip_and_validation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    api = FastAPI()
    from app.api.v1.backtests import router

    api.include_router(router, prefix="/api/v1")
    api.state.backtest_service = service
    api.state.runtime_mode = "LOCAL_OFFLINE"
    client = TestClient(api)
    try:
        capabilities = client.get("/api/v1/backtests/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["runtime_mode"] == "LOCAL_OFFLINE"
        assert capabilities.json()["flags"]["BACKTEST_REPLAY_TRAINING_AVAILABLE"] is False
        api.state.replay_service = type(
            "ReplayServiceProbe", (), {"training": object()}
        )()
        assert client.get("/api/v1/backtests/capabilities").json()["flags"][
            "BACKTEST_REPLAY_TRAINING_AVAILABLE"
        ] is True
        created = client.post(
            "/api/v1/backtests/research/contexts",
            json=_context(entry_task="PARAMETER_ROBUSTNESS"),
        )
        assert created.status_code == 200, created.text
        assert created.json()["entry_task"] == "PARAMETER_ROBUSTNESS"
        context_id = created.json()["context_id"]
        restored = client.get(f"/api/v1/backtests/research/contexts/{context_id}")
        assert restored.status_code == 200
        assert restored.json() == created.json()
        invalid = client.post(
            "/api/v1/backtests/research/contexts",
            json=_context(parameters={}, extra="forbidden"),
        )
        assert invalid.status_code == 422
        invalid_task = client.post(
            "/api/v1/backtests/research/contexts",
            json=_context(entry_task="NOT_A_RESEARCH_TASK"),
        )
        assert invalid_task.status_code == 422
        missing = client.get(
            "/api/v1/backtests/research/contexts/brc_missing_12345678"
        )
        assert missing.status_code == 400
    finally:
        service.shutdown()


def test_schema_v7_rollback_is_empty_only_and_preserves_contexts_on_refusal(
    tmp_path: Path,
) -> None:
    from app.backtest.research_context_rollback import rollback_research_contexts

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    empty_path = empty_root / "backtest.db"
    _create_v7_rollback_fixture(empty_path)
    receipt = rollback_research_contexts(empty_path)
    assert receipt == {
        "schemaVersion": 6,
        "droppedResearchContexts": True,
        "researchContextRows": 0,
    }
    connection = sqlite3.connect(empty_path)
    assert connection.execute(
        "SELECT schema_version FROM backtest_schema_meta"
    ).fetchone()[0] == 6
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='backtest_research_launch_contexts'"
    ).fetchone() is None
    connection.close()

    populated_root = tmp_path / "populated"
    populated_root.mkdir()
    populated_path = populated_root / "backtest.db"
    _create_v7_rollback_fixture(populated_path, populated=True)
    with pytest.raises(RuntimeError, match="context rows exist"):
        rollback_research_contexts(populated_path)
    connection = sqlite3.connect(populated_path)
    assert connection.execute(
        "SELECT schema_version FROM backtest_schema_meta"
    ).fetchone()[0] == 7
    assert connection.execute(
        "SELECT COUNT(*) FROM backtest_research_launch_contexts"
    ).fetchone()[0] == 1
    assert json.loads(connection.execute(
        "SELECT payload_json FROM backtest_research_launch_contexts"
    ).fetchone()[0]) == _context()
    connection.close()


def _create_v7_rollback_fixture(database: Path, *, populated: bool = False) -> None:
    # Historical v7 tables touched by this rollback (5040391f). Do not start the
    # current service here: its schema migrator deliberately upgrades to v9+.
    connection = sqlite3.connect(database)
    try:
        connection.executescript("""
            CREATE TABLE backtest_schema_meta (
                schema_version INTEGER NOT NULL, migrated_at_ms INTEGER NOT NULL
            );
            INSERT INTO backtest_schema_meta VALUES (7, 10);
            CREATE TABLE backtest_research_launch_contexts (
                context_id TEXT PRIMARY KEY, schema_version TEXT NOT NULL,
                payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL
            );
            CREATE INDEX idx_backtest_research_context_created
                ON backtest_research_launch_contexts(created_at_ms DESC);
        """)
        if populated:
            connection.execute(
                "INSERT INTO backtest_research_launch_contexts VALUES (?, ?, ?, ?, ?)",
                ("brc_historical", "candlescope.backtest-research-launch-context/1",
                 json.dumps(_context()), "historical-test-hash", 30),
            )
            connection.commit()
    finally:
        connection.close()


def test_v7_rollback_refuses_current_schema_without_changing_data(tmp_path: Path) -> None:
    from app.backtest.research_context_rollback import rollback_research_contexts
    from app.backtest.schema import SCHEMA_VERSION

    service = _service(tmp_path)
    try:
        context = service.create_research_launch_context(_context(), now_ms=30)
    finally:
        service.shutdown()
    database = tmp_path / "backtest.db"
    connection = sqlite3.connect(database)
    try:
        before = list(connection.iterdump())
        assert connection.execute("SELECT schema_version FROM backtest_schema_meta").fetchone()[0] == SCHEMA_VERSION
        with pytest.raises(RuntimeError, match="requires exact schema version 7"):
            rollback_research_contexts(database)
        assert list(connection.iterdump()) == before
        assert connection.execute(
            "SELECT context_id FROM backtest_research_launch_contexts"
        ).fetchone()[0] == context["context_id"]
    finally:
        connection.close()
