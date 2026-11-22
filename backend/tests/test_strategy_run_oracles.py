"""ADR-BACKTEST-015 P0: host-owned execution paths pinned to financial oracles.

The Pine paths need the installed Pine runtime and live in
``test_strategy_run_oracles_pine.py``. See ``tests/strategy_run_oracles.py``
for the scenario and for how to regenerate goldens on purpose.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.models import ENGINE_VERSION
from app.backtest.service import BacktestService
from app.backtest.strategy.python_provider import PythonHostProvider
from app.backtest.strategy.registry import BUILTIN_SMA_REVISION, build_default_strategy_registry
from app.core.config import load_backtest_settings
from tests import strategy_run_oracles as oracles

SMA_TEMPLATE = Path(__file__).resolve().parents[2] / "packages" / "candlescope-backtest-sdk" / "templates" / "sma_cross"
COMMON = {
    "dataset_id": f"oracle-{oracles.SCENARIO_ID}",
    "data_epoch": "sha256:" + "a1" * 32,
    "snapshot_hash": "sha256:" + "b2" * 32,
    "start_time_ms": 0,
    "end_time_ms": oracles.MINUTES * 60_000,
    "interval": "1m",
    "warmup_bars": 5,
    "parameters": oracles.SMA_PARAMETERS,
    "output_mode": "TARGET_POSITION",
    "slippage_bps": "1",
    "taker_fee_bps": "3",
    "maker_fee_bps": "1",
}
BAR = {**COMMON, "fidelity_mode": "BAR_APPROX", "source_event_kind": "BAR"}
# P6e3: the same BAR run on the practice account model, at a practice account's default leverage.
PRACTICE = {**BAR, "account_rules": "PRACTICE_V1", "leverage": "10"}
RULES = {"bar": BAR, "practice": PRACTICE}
DUAL_CLOCK = {
    **COMMON,
    "fidelity_mode": "AGG_TRADE_EXECUTION",
    "source_event_kind": "AGG_TRADE",
    "signal_clock": "DERIVED_BAR_CLOSE",
    "signal_interval": "1m",
    "execution_clock": "NEXT_AGG_TRADE",
    "bar_builder": "TRADE_DERIVED_COMPLETE_BUCKETS_V1",
    "timezone": "UTC",
}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    settings = load_backtest_settings(
        {"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1", "BACKTEST_TRADE_TAPE_ENABLED": "1"},
        data_dir=tmp_path, klines_db_path=tmp_path / "candlescope.db", replay_db_path=tmp_path / "replay.db")
    running = BacktestService.start(settings, strategy_registry=build_default_strategy_registry(),
                                    enforce_registered_revisions=True, now_ms=1)
    yield running
    running.shutdown()


def python_provider() -> PythonHostProvider:
    return PythonHostProvider(SMA_TEMPLATE, parameters=oracles.SMA_PARAMETERS,
                              mode="TRUSTED_LOCAL", trusted_confirmed=True)


def builtin_provider():
    return build_default_strategy_registry().require(BUILTIN_SMA_REVISION).factory()


def python_revision(service) -> str:
    bundle = service.create_python_strategy_bundle(directory=str(SMA_TEMPLATE), now_ms=2)
    return str(service.create_python_strategy_revision(bundle["bundle_id"], now_ms=3)["revision_id"])


def fixed_run(service, provider_name: str, rules: str = "bar"):
    """One fixed-history BAR run. Returns the created row and the completed run."""
    revision = BUILTIN_SMA_REVISION if provider_name == "builtin" else python_revision(service)
    payload = {**RULES[rules], "strategy_revision_id": revision}
    if provider_name == "python":
        payload.update(python_runtime_mode="TRUSTED_LOCAL", python_trusted_confirmed=True)
        # Registered Python revisions must pass the bounded smoke for the snapshot first.
        service.smoke_strategy_revision(revision, payload, now_ms=4)
    row = service.create_run(payload, idempotency_key=f"oracle-{rules}-{provider_name}", now_ms=4)
    provider = builtin_provider() if provider_name == "builtin" else python_provider()
    completed = service.execute_bar_run(str(row["run_id"]), events=oracles.bars(), provider=provider, now_ms=5)
    assert completed["state"] == "COMPLETED"
    return row, completed


@pytest.mark.parametrize("provider_name", ["builtin", "python"])
def test_fixed_host_bar_oracle(service, provider_name):
    _, completed = fixed_run(service, provider_name)
    oracles.assert_oracle(oracles.host_oracle(f"host-bar-{provider_name}", completed["result"]))


@pytest.mark.parametrize("provider_name", ["builtin", "python"])
def test_fixed_host_practice_oracle(service, provider_name):
    row, completed = fixed_run(service, provider_name, "practice")
    config = json.loads(str(row["config_json"]))
    assert (config["account_rules"], config["leverage"]) == ("PRACTICE_V1", "10")
    assert completed["report"]["fill_model"]["name"] == "PRACTICE_CANDLE_PATH_V1"
    oracles.assert_oracle(oracles.host_oracle(f"host-practice-{provider_name}", completed["result"]))


def test_fixed_host_aggtrade_dual_clock_oracle(service):
    row = service.create_run({**DUAL_CLOCK, "strategy_revision_id": BUILTIN_SMA_REVISION},
                             idempotency_key="oracle-dual-clock", now_ms=4)
    completed = service.execute_dual_clock_run(str(row["run_id"]), events=oracles.trades(),
                                               provider=builtin_provider(), now_ms=5)
    assert completed["state"] == "COMPLETED"
    assert completed["report"]["report_label"] == "AGGREGATED_TRADE_SEQUENCE"
    oracles.assert_oracle(oracles.host_oracle("host-aggtrade-dual-clock", completed["result"]))


# Batch boundaries for the FORWARD run; "|" marks a full store close and resume.
SPLITS = {
    "one-batch": [47],
    "per-bar": [1] * 47,
    "uneven-with-restart": [11, "|", 9, 27],
}


@pytest.mark.parametrize("split", sorted(SPLITS))
@pytest.mark.parametrize("rules", sorted(RULES))
@pytest.mark.parametrize("provider_name", ["builtin", "python"])
def test_forward_continuous_run_reproduces_the_fixed_oracle(service, tmp_path, provider_name, rules, split):
    """The FOLLOW/FORWARD premise: batching and restarts never change closed-bar results."""
    row, _ = fixed_run(service, provider_name, rules)
    config = json.loads(str(row["config_json"]))
    definition = {"engine_version": ENGINE_VERSION, "configuration": config,
                  "input_plan": {"roles": ["BARS"], "parameters": config["parameters"]},
                  "market": {"venue": "local", "symbol": str(row["dataset_id"])}}
    factory = (lambda _: builtin_provider()) if provider_name == "builtin" else (lambda _: python_provider())
    database = tmp_path / "continuous.db"
    store = ContinuousStrategyStore(database)
    ContinuousBarHost.create_run(store, "oracle-forward", definition=definition, mode="HISTORY_LIVE",
                                 data_revision="r1", event_time_ms=0, provider_factory=factory)
    host = ContinuousBarHost.resume(store, "oracle-forward", factory)
    events, offset = oracles.bars(), 0
    sizes = [size for size in SPLITS[split] if size != "|"]
    assert sum(sizes) == len(events)
    try:
        for size in SPLITS[split]:
            if size == "|":
                host.close(); store.close()
                store = ContinuousStrategyStore(database)
                host = ContinuousBarHost.resume(store, "oracle-forward", factory)
                assert host.row["sequence"] == events[offset - 1].sequence
                continue
            batch = events[offset:offset + size]
            offset += size
            host.apply_batch(batch, data_revision="r1", revealed_through_ms=batch[-1].event_time_ms,
                             coverage_complete=True, caught_up=offset == len(events))
        actual = asdict(host.kernel.run((), host._observe, finalize=True))
    finally:
        host.close(); store.close()
    path = f"host-{rules}-{provider_name}"
    oracle = oracles.host_oracle(path, actual)
    golden = oracles.load_golden(path)
    assert oracle["digests"] == golden["digests"], f"{split}: FORWARD diverged from the FIXED {path} golden"
    assert oracle["summary"] == golden["summary"]


def test_every_listed_execution_path_keeps_a_golden():
    """A path may only leave this list with an ADR change; renames must keep its golden."""
    files = {path.stem for path in oracles.GOLDEN_DIR.glob("*.json")}
    assert files == set(oracles.PATHS), {"missing": sorted(set(oracles.PATHS) - files),
                                         "orphaned": sorted(files - set(oracles.PATHS))}
    for path in oracles.PATHS:
        golden = oracles.load_golden(path)
        assert golden["schema"] == oracles.SCHEMA and golden["path"] == path
        assert golden["scenario"] == oracles.scenario(), f"{path}: scenario drifted from its golden"
        assert golden["summary"].get("orders"), f"{path}: the oracle scenario must trade"
