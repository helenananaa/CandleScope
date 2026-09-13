from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from app.backtest.service import BacktestService
from app.backtest.strategy.python_market_batch import PythonMarketBatchProvider, certified_source
from app.backtest.strategy.protocol import ObservationFrame, StrategyProviderError, StrategyProviderSession
from app.backtest.strategy.python_provider import PythonHostProvider
from app.backtest.colocated import _GuardedProvider
from tests.test_backtest_chart_batch import events
from tests.test_backtest_control_plane import _settings, _payload
from tests.test_backtest_host_policy_m5 import config

BUNDLE = Path(__file__).resolve().parents[2] / 'packages/candlescope-backtest-sdk/templates/sma_cross_batch'


def _slow_batch_worker(*args):
    import time
    from app.backtest.colocated import _worker
    original = PythonMarketBatchProvider.step
    def delayed(self, row):
        if self.offset == 300:
            time.sleep(10)
        return original(self, row)
    PythonMarketBatchProvider.step = delayed
    _worker(*args)


def prepared(data, warmup=17):
    provider = PythonMarketBatchProvider(BUNDLE, data, warmup_events=warmup)
    provider.prepare({"runId": "same", "parameters": {"fast": 3, "slow": 5}})
    return provider


def frame(event, warmup=17, index=None):
    return ObservationFrame("same", event.sequence, event.event_time_ms, event.event_time_ms,
                            "WARMUP" if (event.sequence-1 if index is None else index) < warmup else "EVALUATION",
                            {}, "input", bar=event.payload)


def test_every_output_and_pending_restore_match_scalar_sdk():
    from candlescope_backtest_sdk.worker import _load_strategy
    from candlescope_backtest_sdk import StrategyContext, Observation, encode_output
    from app.backtest.strategy.python_provider import _author_observation, _to_host_output
    data = events(1100)
    batch = prepared(data)
    scalar = _load_strategy(BUNDLE, "strategy:Strategy")
    scalar.prepare(StrategyContext("same", "same", {"fast": 3, "slow": 5}))
    for i, event in enumerate(data):
        row = frame(event)
        observation = Observation.from_wire(_author_observation(row))
        expected = (scalar.warmup(observation) if i < 17 else
                    _to_host_output(event.sequence, encode_output(event.sequence, scalar.step(observation))))
        assert batch.step(row) == expected
        if i in (15, 255, 278, 900):
            snapshot = batch.snapshot()
            restored = prepared(data)
            restored.restore(snapshot)
            assert restored.snapshot() == snapshot
            batch = restored
    assert batch.offset == len(data)
    assert batch.pending is None
    assert sum(r["rowCount"] for r in batch.receipts) == len(data)


def test_future_rows_do_not_change_earlier_targets():
    data = events(400)
    modified = tuple(replace(e, payload={**e.payload, "close": "999999"}) if i >= 137 else e
                     for i, e in enumerate(data))
    original, changed = prepared(data, 0), prepared(modified, 0)
    for i in range(137):
        assert original.step(frame(data[i], 0)) == changed.step(frame(modified[i], 0))


def test_sdk_can_verify_report_batch_hashes():
    from candlescope_backtest_sdk import market_batch_hashes
    provider = prepared(events(400), 0)
    provider.step(frame(provider.events[0], 0))
    batch, _ = provider._batch(0)
    hashes = market_batch_hashes(batch, provider.pending["targets"], provider.parameters)
    assert hashes["inputHash"] == provider.pending["inputHash"]
    assert hashes["outputHash"] == provider.pending["outputHash"]
    partial = provider.report_metadata()["pythonBatchReceipt"]["partialBatch"]
    assert partial["plannedRows"] == 256 and partial["consumedRows"] == 1


def test_bad_source_and_pending_receipt_fail_closed(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / "changed")
    with (tmp_path / "changed/strategy.py").open("ab") as stream:
        stream.write(b"\n# unqualified edit\n")
    with pytest.raises(StrategyProviderError, match="certified"):
        certified_source(tmp_path / "changed")
    data = events(400)
    batch = prepared(data)
    batch.step(frame(data[0]))
    state = batch.snapshot()
    state["pending"]["targets"][19] = "999"
    with pytest.raises(StrategyProviderError, match="receipt mismatch"):
        prepared(data).restore(state)
    state = batch.snapshot()
    altered = (replace(data[0], payload={**data[0].payload, "close": "999"}), *data[1:])
    with pytest.raises(StrategyProviderError, match="receipt mismatch"):
        prepared(altered).restore(state)


def test_limits_precede_large_decimal_expansion_and_bad_outputs():
    data = (replace(events(1)[0], payload={**events(1)[0].payload, "close": "1e999999999"}),)
    with pytest.raises(StrategyProviderError, match="expansion"):
        prepared(data, 0).step(frame(data[0], 0))
    batch = prepared(events(10), 0)
    batch.calculate = lambda *args: ()
    with pytest.raises(StrategyProviderError, match="length mismatch"):
        batch.step(frame(batch.events[0], 0))
    assert batch.offset == 0


@pytest.mark.parametrize("policy", [False, True])
def test_spawned_scalar_and_batch_financial_results_and_explanations_equal(tmp_path, monkeypatch, policy):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    settings = _settings(tmp_path, BACKTEST_TRADE_EXPLANATION_ENABLED="1", BACKTEST_CHECKPOINT_EVENT_INTERVAL="31")
    service = BacktestService.start(settings, now_ms=1)
    bundle = service.create_python_strategy_bundle(directory=str(BUNDLE), now_ms=1)
    revision = service.create_python_strategy_revision(bundle["bundle_id"], now_ms=2)
    payload = _payload(strategy_revision_id=revision["revision_id"], parameters={"fast":3, "slow":5},
        python_runtime_mode="TRUSTED_LOCAL", python_trusted_confirmed=True, warmup_bars=17,
        execution_model_revision="EXECUTION_REALISM_V2", **(config("FIXED_QTY_V1") if policy else {}))
    outcomes = []
    try:
        for batch in (False, True):
            run = service.create_run({**payload, **({"python_execution_protocol":"MARKET_BATCH_V1"} if batch else {})},
                                     idempotency_key=str(batch), now_ms=3)
            provider = service.build_python_host_provider(revision["revision_id"], parameters=payload["parameters"],
                                                          mode="TRUSTED_LOCAL", trusted_confirmed=True)
            outcomes.append(service.execute_bar_run(run["run_id"], events=events(700), provider=provider, now_ms=4))
        first, second = [value["result"] for value in outcomes]
        for key in ("decision_hash", "fill_hash", "ledger_hash", "fills", "ledger", "equity_curve", "cost_sensitivity"):
            assert first[key] == second[key], key
        for key in ("trades", "orders", "rejected_orders", "metrics", "fill_model"):
            assert outcomes[0]["report"].get(key) == outcomes[1]["report"].get(key), key
        assert outcomes[0]["report"]["identity"]["config_hash"] != outcomes[1]["report"]["identity"]["config_hash"]
        assert second["strategy_metadata"]["pythonBatchReceipt"]["consumedRows"] == 700
    finally:
        service.shutdown()


def test_receipt_and_complete_report_survive_mid_batch_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    settings = _settings(tmp_path, BACKTEST_TRADE_EXPLANATION_ENABLED="1", BACKTEST_CHECKPOINT_EVENT_INTERVAL="31")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(parameters={"fast":3, "slow":5}, execution_model_revision="EXECUTION_REALISM_V2"),
                          idempotency_key="same", now_ms=2)
    seed.shutdown()
    results = []
    for interrupted in (False, True):
        db = tmp_path / f"recovery-{interrupted}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        service._colocated_worker = True
        data = events(700)
        def make_provider():
            from types import SimpleNamespace
            return _GuardedProvider(PythonMarketBatchProvider(BUNDLE, data), SimpleNamespace(value=0.), 2., 2.)
        try:
            if interrupted:
                def fault(point, context):
                    if point == "before_decision" and context["sequence"] == 279:
                        raise StrategyProviderError("PROVIDER_TIMEOUT", "batch recovery test")
                service._fault_injector = fault
                with pytest.raises(StrategyProviderError, match="PROVIDER_TIMEOUT"):
                    service.execute_bar_run(run["run_id"], events=data, provider=make_provider(), now_ms=3)
                checkpoint = service.repository.latest_checkpoint(run["run_id"])
                assert 256 < checkpoint["sequence"] < 279
                saved = json.loads(checkpoint["payload_json"])["provider"]["provider"]
                assert saved["pending"]["start"] == 256
                service._fault_injector = None
                service.resume_failed_run(run["run_id"], now_ms=4)
            results.append(service.execute_bar_run(run["run_id"], events=data, provider=make_provider(), now_ms=5))
        finally:
            service.shutdown()
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["report"] == results[1]["report"]


def test_actual_worker_timeout_resume_preserves_batch_receipt(tmp_path, monkeypatch):
    import app.backtest.colocated as colocated
    from app.backtest.errors import BacktestError
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    settings = _settings(tmp_path, BACKTEST_TRADE_EXPLANATION_ENABLED="1", BACKTEST_CHECKPOINT_EVENT_INTERVAL="31",
                         BACKTEST_PROVIDER_STEP_TIMEOUT_MS="200")
    seed = BacktestService.start(settings, now_ms=1)
    bundle = seed.create_python_strategy_bundle(directory=str(BUNDLE), now_ms=1)
    revision = seed.create_python_strategy_revision(bundle["bundle_id"], now_ms=2)
    run = seed.create_run(_payload(strategy_revision_id=revision["revision_id"], parameters={"fast":3,"slow":5},
        python_runtime_mode="TRUSTED_LOCAL", python_trusted_confirmed=True, python_execution_protocol="MARKET_BATCH_V1",
        execution_model_revision="EXECUTION_REALISM_V2"), idempotency_key="same", now_ms=2)
    seed.shutdown()
    outcomes = []
    normal_worker = colocated._worker
    for interrupted in (False, True):
        db = tmp_path / f"real-{interrupted}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        def provider():
            return service.build_python_host_provider(revision["revision_id"], parameters={"fast":3,"slow":5},
                mode="TRUSTED_LOCAL", trusted_confirmed=True)
        try:
            if interrupted:
                monkeypatch.setattr(colocated, "_worker", _slow_batch_worker)
                with pytest.raises(BacktestError, match="PROVIDER_TIMEOUT"):
                    service.execute_bar_run(run["run_id"], events=events(700), provider=provider(), now_ms=3)
                assert service.repository.latest_checkpoint(run["run_id"])["sequence"] == 279
                assert service.repository.get_report(run["run_id"]) is None
                monkeypatch.setattr(colocated, "_worker", normal_worker)
                service.resume_failed_run(run["run_id"], now_ms=4)
            outcomes.append(service.execute_bar_run(run["run_id"], events=events(700), provider=provider(), now_ms=5))
        finally:
            service.shutdown()
    assert outcomes[0]["result"] == outcomes[1]["result"]
    assert outcomes[0]["report"] == outcomes[1]["report"]


def test_explicit_protocol_never_silently_uses_scalar_route(tmp_path, monkeypatch):
    from app.backtest.errors import BacktestError
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    service = BacktestService.start(_settings(tmp_path), now_ms=1)
    try:
        bundle = service.create_python_strategy_bundle(directory=str(BUNDLE), now_ms=1)
        revision = service.create_python_strategy_revision(bundle["bundle_id"], now_ms=2)
        payload = _payload(strategy_revision_id=revision["revision_id"], parameters={"fast":3,"slow":5},
            python_runtime_mode="TRUSTED_LOCAL", python_trusted_confirmed=True,
            python_execution_protocol="MARKET_BATCH_V1")
        with pytest.raises(BacktestError, match="FIDELITY_UNSUPPORTED"):
            service.validate_run({**payload, "python_runtime_mode": "SANDBOXED_LOCAL"})
        with pytest.raises(BacktestError, match="FIDELITY_UNSUPPORTED"):
            service.validate_run({**payload, "python_execution_protocol": "UNKNOWN"})
        run = service.create_run(payload, idempotency_key="disabled", now_ms=3)
        monkeypatch.setenv("BACKTEST_COLOCATED_BAR_ENABLED", "0")
        provider = service.build_python_host_provider(revision["revision_id"], parameters=payload["parameters"],
                                                     mode="TRUSTED_LOCAL", trusted_confirmed=True)
        with pytest.raises(BacktestError, match="supervised"):
            service.execute_bar_run(run["run_id"], events=events(10), provider=provider, now_ms=4)
        assert service.get_run(run["run_id"])["state"] == "FAILED"
        assert service.repository.get_report(run["run_id"]) is None
    finally:
        service.shutdown()
