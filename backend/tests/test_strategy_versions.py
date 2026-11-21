"""ADR-BACKTEST-015 P3b: content-addressed strategy versions for every run family."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.models import ENGINE_VERSION
from app.backtest.strategy_versions import (
    StrategyVersions, continuous_material, host_material, material, native_material, version_hash,
)
from app.data_engine.data_manager.strategy import StrategyDataManager
from tests.test_run_result import runtime_run  # noqa: F401 - fixture
from tests.test_strategy_run_oracles import BUILTIN_SMA_REVISION

PINE = "//@version=6\nstrategy(\"S\")\nif close > open\n    strategy.entry(\"L\", strategy.long)"


def test_a_version_is_its_code_and_nothing_else():
    base = material("pine", PINE, {"lib/x/1": "export f() => 1"}, {"engine": {"version": "1"}})
    assert version_hash(base) == version_hash(dict(base)) and version_hash(base).startswith("sha256:")
    for changed in (
        {**base, "language": "python"}, {**base, "source": PINE + "\n"},
        {**base, "libraries": {}}, {**base, "runtime": {"engine": {"version": "2"}}},
    ):
        assert version_hash(changed) != version_hash(base)


def test_each_family_record_names_its_code():
    revision = {"language": "PINE_ENGINE", "source_text": PINE, "runtime_revision": "rt/2", "dependency_hash": "sha256:d",
                "base_revision_id": "pine-engine-chart-v1",
                "compiled_json": json.dumps({"executionSource": json.dumps({"source": PINE, "libraries": {"a/b/1": "x"}})})}
    host = host_material(SimpleNamespace(get_strategy_revision=lambda _: revision), None,
                         {"strategy_revision_id": "rev", "config_json": "{}", "engine_version": "e"})
    assert host == material("pine", PINE, {"a/b/1": "x"}, {"compiler": "PINE_ENGINE", "runtime_revision": "rt/2",
                                                         "dependency_hash": "sha256:d", "base_revision_id": "pine-engine-chart-v1"})
    native = native_material({"config": {"language": "pine", "source": PINE, "libraries": {"a/b/1": "x"}, "parameters": {"n": 3}},
                              "runtime_identity": {"engine": {"package": "p", "version": "1"}}})
    assert native == material("pine", PINE, {"a/b/1": "x"}, {"engine": {"engine": {"package": "p", "version": "1"}}})
    python = continuous_material({"engine_version": "e", "provider": {"schema": "s", "language": "python", "source_text": "code"}})
    assert python == material("python", "code", {}, {"engine_version": "e", "provider_schema": "s"})
    with pytest.raises(BacktestError):
        native_material({"config": {}})


def test_host_runs_are_linked_at_creation_and_builtins_are_one_version_everywhere(runtime_run):
    runtime, run_id = runtime_run
    versions = StrategyVersions(runtime.service.repository)
    expected = version_hash(material("builtin", BUILTIN_SMA_REVISION, {}, {"engine_version": ENGINE_VERSION}))
    assert versions.for_run(run_id) == expected
    # The same builtin on the same engine, run forward, is the same version (the definition a forward run stores).
    assert version_hash(continuous_material({"engine_version": ENGINE_VERSION, "provider": {
        "schema": "x", "language": "builtin", "builtin_id": BUILTIN_SMA_REVISION, "source_text": ""}})) == expected
    stored = versions.get(expected)
    assert (stored["language"], stored["source"], stored["runtime"], stored["names"]) == (
        "builtin", BUILTIN_SMA_REVISION, {"engine_version": ENGINE_VERSION}, [])
    assert [row["run_id"] for row in versions.runs(expected)["runs"]] == [run_id]


def test_a_run_without_a_link_is_linked_when_the_facade_reads_it(runtime_run):
    runtime, run_id = runtime_run
    repository = runtime.service.repository
    expected = StrategyVersions(repository).for_run(run_id)
    with repository._lock:
        repository.connection.execute("DELETE FROM backtest_strategy_version_runs WHERE run_id = ?", (run_id,))
        repository.connection.commit()
    status = asyncio.run(StrategyDataManager(runtime.service, runtime=runtime).runs().status(run_id))
    assert status["version_hash"] == expected
    assert StrategyVersions(repository).for_run(run_id) == expected


def test_recording_a_version_never_fails_run_creation(runtime_run, monkeypatch):
    import app.backtest.strategy_versions as module
    runtime, run_id = runtime_run
    service = runtime.service
    record = service.get_run(run_id)

    def broken(*_args, **_kwargs):
        raise RuntimeError("index unavailable")
    monkeypatch.setattr(module, "host_material", broken)
    with service.repository._lock:
        service.repository.connection.execute("DELETE FROM backtest_strategy_version_runs WHERE run_id = ?", (run_id,))
        service.repository.connection.commit()
    service._record_run_version(record, 5)  # logs, does not raise
    assert StrategyVersions(service.repository).for_run(run_id) is None
    status = asyncio.run(StrategyDataManager(service, runtime=runtime).runs().status(run_id))
    assert status["version_hash"] is None and status["state"] == "COMPLETED"
    monkeypatch.undo()
    status = asyncio.run(StrategyDataManager(service, runtime=runtime).runs().status(run_id))
    assert status["version_hash"] is not None


def test_names_point_at_versions(runtime_run):
    runtime, run_id = runtime_run
    versions = StrategyVersions(runtime.service.repository)
    first = versions.for_run(run_id)
    second = versions.record(material("pine", PINE, {}, {"engine": {}}), now_ms=1)
    assert versions.name("My SMA", first, now_ms=2) == {"name": "My SMA", "version_hash": first}
    assert versions.get(first)["names"] == ["My SMA"]
    versions.name("My SMA", second, now_ms=3)  # naming again moves the name
    assert versions.get(first)["names"] == [] and versions.get(second)["names"] == ["My SMA"]
    versions.name("Also SMA", second, now_ms=4)
    assert [row["name"] for row in versions.names()["names"]] == ["Also SMA", "My SMA"]
    assert versions.unname("Also SMA") == {"name": "Also SMA", "removed": True}
    for bad in ("", " padded", "a/b", "x" * 121, "line\nbreak"):
        with pytest.raises(BacktestError) as invalid:
            versions.name(bad, second, now_ms=5)
        assert invalid.value.code == "VERSION_NAME_INVALID"
    for unknown in ("sha256:" + "0" * 64, "not-a-hash"):
        with pytest.raises(BacktestError) as missing:
            versions.name("Ghost", unknown, now_ms=6)
        assert missing.value.code == "VERSION_NOT_FOUND"


def test_the_version_routes(runtime_run):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.strategy_runs import router as runs_router
    from app.api.v1.strategy_versions import router

    runtime, run_id = runtime_run
    app = FastAPI()
    app.state.data_manager_core = SimpleNamespace(strategy=StrategyDataManager(runtime.service, runtime=runtime))
    app.include_router(router)
    app.include_router(runs_router)
    with TestClient(app) as client:
        digest = client.get(f"/strategy-runs/{run_id}").json()["version_hash"]
        version = client.get(f"/strategy-versions/{digest}")
        runs = client.get(f"/strategy-versions/{digest}/runs?limit=5")
        named = client.put("/strategy-versions/names/SMA%20crossing", json={"version_hash": digest})
        names = client.get("/strategy-versions/names")
        bad = client.put("/strategy-versions/names/SMA", json={"hash": digest})
        missing = client.get("/strategy-versions/sha256:" + "0" * 64)
        removed = client.delete("/strategy-versions/names/SMA%20crossing")
    assert version.status_code == 200 and version.json()["source"] == BUILTIN_SMA_REVISION
    assert runs.json()["runs"][0]["run_id"] == run_id
    assert named.json() == {"name": "SMA crossing", "version_hash": digest}
    assert names.json()["names"][0]["name"] == "SMA crossing"
    assert bad.status_code == 400 and missing.status_code == 404
    assert removed.json() == {"name": "SMA crossing", "removed": True}
