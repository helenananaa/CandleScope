from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.backtest.strategy.protocol import StrategyProviderError
from app.backtest.strategy.workspace import compile_revision
from app.core.config import load_backtest_settings

from tests.test_external_provider_contracts import manifest


def service(tmp_path, *, enabled=True):
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1",
                                       "BACKTEST_EXTERNAL_PROVIDER_ENABLED": "1" if enabled else "0"},
                                      data_dir=tmp_path, klines_db_path=tmp_path / "market.db", replay_db_path=tmp_path / "replay.db")
    return BacktestService.start(settings, enforce_registered_revisions=True)


def revision(owner):
    return owner.create_strategy_revision({"name": "model", "language": "EXTERNAL_PROVIDER", "source_text": manifest()})


def test_compiler_has_explicit_external_identity_and_never_builds_builtin_fallback():
    record = compile_revision({"name": "model", "language": "EXTERNAL_PROVIDER", "source_text": manifest()}, now_ms=1)
    capabilities = json.loads(record["capabilities_json"])
    assert record["base_revision_id"] == "external-decision-provider-v1"
    assert capabilities["external_provider"]["reproducibility"] == "RECORDED_OUTPUT_ONLY"
    assert capabilities["warmup_requirement"] == {"kind": "FIXED_BARS", "bars": 3}
    assert json.loads(record["compiled_json"])["executionSource"] == manifest()


def test_default_off_does_not_create_connection_files_or_databases(tmp_path):
    owner = service(tmp_path, enabled=False)
    try:
        assert owner.capabilities()["flags"]["BACKTEST_EXTERNAL_PROVIDER_ENABLED"] is False
        with pytest.raises(BacktestError, match="FLAG_DISABLED"):
            revision(owner)
        with pytest.raises(StrategyProviderError, match="FLAG_DISABLED"):
            owner.external.list()
        assert not owner.external.directory.exists()
    finally:
        owner.shutdown()


def test_private_connection_freezes_scope_and_never_returns_the_credential(tmp_path):
    owner = service(tmp_path)
    try:
        selected = revision(owner)
        bound = owner.external.create(revision_id=selected["revision_id"], dataset_id="local_one",
                                       data_epoch="epoch_one", snapshot_hash="sha256:original")
        private = Path(bound["connection_file"])
        token = json.loads(private.read_text())["token"]
        assert "token" not in bound and token not in json.dumps(owner.external.list())
        assert private.stat().st_mode & 0o077 == 0
        payload = {**bound["scope"], "external_connection_id": bound["connection_id"]}
        with pytest.raises(StrategyProviderError, match="PROVIDER_CONNECTION_REQUIRED"):
            owner.external.validate_binding(payload)
        assert owner.external.validate_binding(payload, require_ready=False)["external_scope_hash"] == bound["scope_hash"]
        for key in ("strategy_revision_id", "dataset_id", "data_epoch", "snapshot_hash"):
            with pytest.raises(StrategyProviderError):
                owner.external.validate_binding({**payload, key: "another"}, require_ready=False)
        with pytest.raises(StrategyProviderError, match="invalid external client"):
            owner.external.store.connect(bound["connection_id"], token=token, client_id=token, now_ms=101)
        owner.external.revoke(bound["connection_id"])
        assert not private.exists() and owner.external.list() == []
    finally:
        owner.shutdown()


def test_existing_prepare_only_smoke_cannot_certify_an_external_model(tmp_path):
    owner = service(tmp_path)
    try:
        selected = revision(owner)
        with pytest.raises(BacktestError, match="actual verified Host snapshot"):
            owner.smoke_strategy_revision(selected["revision_id"], {"start_time_ms": 1, "end_time_ms": 2})
        assert owner.repository.strategy_smoke_for_snapshot(selected["revision_id"], "local_one", "sha256:original") is None
        owner.enforce_registered_revisions = False
        with pytest.raises(BacktestError, match="SMOKE_REQUIRED"):
            owner.create_run({"strategy_revision_id": selected["revision_id"], "dataset_id": "local_one",
                              "data_epoch": "epoch_one", "snapshot_hash": "sha256:original", "fidelity_mode": "BAR_APPROX",
                              "start_time_ms": 0, "end_time_ms": 1000}, idempotency_key="cannot-bypass-external-smoke")
    finally:
        owner.shutdown()
