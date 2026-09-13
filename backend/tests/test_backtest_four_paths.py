import json
import sqlite3
from decimal import Decimal

import pytest

from app.backtest.checkpoint_history import HistoryEncoder, ENCODING, rollback_history
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json, sha256_hex
from app.backtest.repository import BacktestRepository
from app.simulation.kernel import SimulationKernel, SimulatedOrder, SimulatedFill, _flat_record
from tests.test_generic_native_rows import pipeline, row


@pytest.mark.parametrize("entry,fields", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("bound", [False, True])
def test_native_entry_and_output_fields_transcript_matrix(monkeypatch, entry, fields, bound):
    outcomes = []
    for enabled in (False, True):
        monkeypatch.setenv("BACKTEST_NATIVE_ENTRY_ENABLED", str(int(enabled and entry)))
        monkeypatch.setenv("BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED", str(int(enabled and fields)))
        runner, session, adapter, direct, observe = pipeline(monkeypatch, True, bound)
        assert direct.native_entry == (enabled and entry and fields)
        assert direct.direct_outputs == (enabled and fields)
        try:
            outputs = [observe(row(i), "WARMUP" if i < 3 else "EVALUATION") for i in range(1, 35)]
            outcomes.append(([value.to_wire() if value else None for value in outputs], runner.close()))
        finally:
            adapter.close()
    assert outcomes[0] == outcomes[1]


def test_native_entry_skips_python_completion_and_never_repeats_fallback_callback(monkeypatch):
    runner, session, adapter, direct, observe = pipeline(monkeypatch, True, False)
    assert direct.native_entry and direct.direct_outputs
    original = runner._complete_native
    initial_count = runner._count
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected Python completion")
    runner._complete_native = forbidden
    try:
        observe(row(1), "EVALUATION")
        assert runner._strategy.seen == 1
        runner._complete_native = original
        from candlescope_backtest_sdk import OrderIntent
        def fallback(obs):
            runner._strategy.seen += 1
            return OrderIntent("BUY", "MARKET", "1", client_tag="中文")
        runner._strategy.step = fallback
        observe(row(2), "EVALUATION")
        assert runner._strategy.seen == 2 and runner._count == initial_count + 2
    finally:
        adapter.close()


def test_older_sdk_keeps_python_orchestration(monkeypatch):
    from candlescope_backtest_sdk import models
    monkeypatch.delattr(models, "NATIVE_OUTPUT_LAYOUT")
    runner, _, adapter, direct, observe = pipeline(monkeypatch, True, False)
    try:
        assert not direct.direct_outputs and not direct.native_entry
        assert observe(row(1), "EVALUATION").kind == "TARGET_POSITION"
        assert runner._strategy.seen == 1
    finally:
        adapter.close()


def test_host_specialized_loop_defaults_off(tmp_path, monkeypatch):
    from app.backtest.service import BacktestService
    from app.backtest.strategy.protocol import DeterministicFakeProvider
    from tests.test_backtest_control_plane import _settings, _payload
    from tests.test_backtest_colocated import bars
    monkeypatch.delenv("BACKTEST_SPECIALIZED_BAR_ENABLED", raising=False)
    original, observed = SimulationKernel.run, []
    def run(kernel, *args, **kwargs):
        observed.append(kernel._specialized_bar)
        return original(kernel, *args, **kwargs)
    monkeypatch.setattr(SimulationKernel, "run", run)
    service = BacktestService.start(_settings(tmp_path), now_ms=1)
    try:
        record = service.create_run(_payload(), idempotency_key="default", now_ms=2)
        service.execute_bar_run(record["run_id"], events=bars(12), provider=DeterministicFakeProvider(), now_ms=3)
        assert observed and not any(observed)
    finally:
        service.shutdown()


@pytest.mark.parametrize("mutation", ["method", "subclass", "error"])
def test_output_customization_and_error_exact_fallback(monkeypatch, mutation):
    from candlescope_backtest_sdk import TargetPosition
    outcomes = []
    for enabled in (False, True):
        with monkeypatch.context() as patch:
            patch.setenv("BACKTEST_NATIVE_ENTRY_ENABLED", str(int(enabled)))
            patch.setenv("BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED", str(int(enabled)))
            runner, session, adapter, direct, observe = pipeline(patch, True, False)
            if mutation == "method":
                patch.setattr(TargetPosition, "to_payload", lambda self: {"quantity": "2"})
            if mutation == "subclass":
                class Custom(TargetPosition):
                    def to_payload(self):
                        return {"quantity": "3"}
                runner._strategy.step = lambda obs: Custom("1")
            if mutation == "error":
                def error(self):
                    raise ValueError("custom output error")
                patch.setattr(TargetPosition, "to_payload", error)
            try:
                try:
                    output = observe(row(1), "EVALUATION").to_wire()
                except Exception as exc:
                    output = (type(exc).__name__, str(exc))
                outcomes.append((output, runner.close(), runner._strategy.seen))
            finally:
                adapter.close()
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("warmup", [0, 3])
@pytest.mark.parametrize("funding", ["0", "0.001"])
def test_specialized_loop_matches_full_snapshot(warmup, funding):
    outcomes = []
    for enabled in (False, True):
        kernel = SimulationKernel(funding_rate=Decimal(funding), funding_interval_ms=60000)
        kernel._specialized_bar = enabled
        seen = []
        def strategy(visible, event):
            return [{"side": "BUY" if event.sequence % 2 else "SELL", "type": "MARKET", "qty": "1"}]
        result = kernel.run([row(i) for i in range(1, 25)], strategy, warmup_events=warmup,
                            finalize=True, checkpoint_callback=lambda event: seen.append(event.sequence))
        outcomes.append((result, kernel.snapshot(), seen))
    assert outcomes[0] == outcomes[1]


def make_kernel(count=800):
    kernel = SimulationKernel()
    for i in range(count):
        kernel.orders.append(SimulatedOrder(str(i), "BUY", "MARKET", Decimal("1"), i, status="FILLED"))
        kernel.fills.append(SimulatedFill(str(i), i, i*60000, "BUY", Decimal("100"), Decimal("1"), Decimal("0"), "测试"))
    kernel._record_encoder = _flat_record
    return kernel


def checkpoint(kernel, history, sequence=1):
    history.begin()
    payload = {"schemaVersion": "candlescope.backtest-checkpoint/2", "checkpointMode": "BAR", "run_id": "r",
               "engine": kernel.snapshot(history_encoder=history), "historyEncoding": ENCODING}
    raw = canonical_json(payload)
    full = {key: value for key, value in payload.items() if key != "historyEncoding"}
    full["engine"] = kernel.snapshot()
    expected_size = len(canonical_json(full).encode())
    assert len(raw.encode()) + history.logical_extra - len(canonical_json("historyEncoding") + ":" + canonical_json(ENCODING) + ",") == expected_size
    return {"run_id": "r", "sequence": sequence, "generation": 1, "payload_json": raw,
            "state_hash": "sha256:" + sha256_hex(raw), "created_at_ms": 1, "history_chunks": dict(history.pending)}, full


def repository(tmp_path):
    repo = BacktestRepository(tmp_path / "state.db")
    repo.open(now_ms=1)
    # Populate required columns without depending on unrelated strategy setup.
    columns = repo.connection.execute("PRAGMA table_info(backtest_runs)").fetchall()
    values = {col[1]: (1 if col[2] == "INTEGER" else "x") for col in columns if col[3]}
    values.update(run_id="r", state="RUNNING", generation=1)
    repo.connection.execute("INSERT INTO backtest_runs (" + ",".join(values) + ") VALUES (" + ",".join("?" for _ in values) + ")", tuple(values.values()))
    repo.connection.commit()
    return repo


def test_incremental_durable_resume_and_rollback(tmp_path):
    repo = repository(tmp_path)
    kernel = make_kernel()
    history = HistoryEncoder(_flat_record)
    saved, full = checkpoint(kernel, history)
    assert repo.save_checkpoint(saved)
    history.pending.clear()
    assert len(json.loads(saved["payload_json"])["engine"]["fills"]["tail"]) == 32
    kernel.orders[-1].status = "EXPIRED"
    saved2, full2 = checkpoint(kernel, history, 2)
    assert saved2["history_chunks"] == {}
    assert repo.save_checkpoint(saved2)
    assert not repo.save_checkpoint(saved)  # older publication cannot remove live chunks
    repo.close()
    repo.open(now_ms=2)
    loaded = repo.latest_checkpoint("r")
    assert json.loads(loaded["payload_json"]) == json.loads(canonical_json(full2))
    assert loaded["state_hash"] == "sha256:" + sha256_hex(full2)
    repo.close()
    assert rollback_history(tmp_path / "state.db")["schemaVersion"] == 7
    connection = sqlite3.connect(tmp_path / "state.db")
    assert json.loads(connection.execute("SELECT payload_json FROM backtest_checkpoints").fetchone()[0]) == json.loads(canonical_json(full2))
    connection.close()


@pytest.mark.parametrize("corrupt", ["missing", "bytes", "manifest"])
def test_corruption_fails_closed_and_rollback_is_atomic(tmp_path, corrupt):
    repo = repository(tmp_path)
    saved, _ = checkpoint(make_kernel(), HistoryEncoder(_flat_record))
    assert repo.save_checkpoint(saved)
    if corrupt == "missing":
        repo.connection.execute("DELETE FROM backtest_checkpoint_chunks")
    elif corrupt == "bytes":
        repo.connection.execute("UPDATE backtest_checkpoint_chunks SET payload_json='[]'")
    else:
        repo.connection.execute("UPDATE backtest_checkpoints SET state_hash='bad'")
    repo.connection.commit()
    with pytest.raises(BacktestError, match="checkpoint"):
        repo.latest_checkpoint("r")
    repo.close()
    with pytest.raises(BacktestError):
        rollback_history(tmp_path / "state.db")
    connection = sqlite3.connect(tmp_path / "state.db")
    assert connection.execute("SELECT schema_version FROM backtest_schema_meta").fetchone()[0] == 9
    connection.close()


def test_generation_guard_no_orphans_and_active_order_not_sealed(tmp_path):
    repo = repository(tmp_path)
    kernel = make_kernel()
    kernel.orders[0].status = "OPEN"
    history = HistoryEncoder(_flat_record)
    saved, full = checkpoint(kernel, history)
    assert json.loads(saved["payload_json"])["engine"]["orders"]["chunks"] == []
    saved["generation"] = 2
    assert not repo.save_checkpoint(saved)
    assert repo.connection.execute("SELECT COUNT(*) FROM backtest_checkpoint_chunks").fetchone()[0] == 0
    saved["generation"] = 1
    assert repo.save_checkpoint(saved)
    repo.delete_checkpoints("r")
    assert repo.connection.execute("SELECT COUNT(*) FROM backtest_checkpoint_chunks").fetchone()[0] == 0
    repo.close()


@pytest.mark.parametrize("resume_incremental", [False, True])
def test_real_bar_death_reopen_resume_matches_uninterrupted_hashes(tmp_path, monkeypatch, resume_incremental):
    from dataclasses import replace
    from app.backtest.service import BacktestService
    from app.backtest.strategy.registry import build_default_strategy_registry
    from tests.test_backtest_recovery_m10 import _bar_settings, _bar, _InjectedWorkerDeath
    settings = replace(_bar_settings(tmp_path), checkpoint_event_interval=128)
    registry = build_default_strategy_registry()
    def inject(point, details):
        if point == "before_decision" and details["sequence"] == 701:
            raise _InjectedWorkerDeath("power loss")
    service = BacktestService.start(settings, strategy_registry=registry, fault_injector=inject, now_ms=1)
    payload = {"strategy_revision_id": "builtin-sma-cross-v1", "dataset_id": "history",
        "data_epoch": "sha256:" + "11" * 32, "snapshot_hash": "sha256:" + "22" * 32,
        "fidelity_mode": "BAR_APPROX", "start_time_ms": 0, "end_time_ms": 1000*60000,
        "parameters": {"fast": 1, "slow": 2}, "output_mode": "TARGET_POSITION",
        "execution_model_revision": "EXECUTION_REALISM_V2"}
    run = service.create_run(payload, idempotency_key="interrupted", now_ms=2)
    events = tuple(replace(_bar(i, volume="100"), payload={
        "open": str(100+i%2), "close": str(100+i%2), "high": "102", "low": "99", "volume": "100"})
        for i in range(1, 950))
    factory = registry.require("builtin-sma-cross-v1").factory
    with pytest.raises(_InjectedWorkerDeath):
        service.execute_bar_run(run["run_id"], events=events, provider=factory(), now_ms=3)
    assert service.repository.connection.execute("SELECT COUNT(*) FROM backtest_checkpoint_chunks").fetchone()[0] > 0
    service.shutdown()
    monkeypatch.setenv("BACKTEST_INCREMENTAL_CHECKPOINT_ENABLED", str(int(resume_incremental)))
    service = BacktestService.start(settings, strategy_registry=registry, now_ms=4)
    assert service.requeue_interrupted_run(run["run_id"], expected_generation=1, now_ms=5)
    resumed = service.execute_bar_run(run["run_id"], events=events, provider=factory(), now_ms=6)
    clean = service.create_run(payload, idempotency_key="clean", now_ms=7)
    uninterrupted = service.execute_bar_run(clean["run_id"], events=events, provider=factory(), now_ms=8)
    for name in ("decision_hash", "fill_hash", "ledger_hash", "report_hash"):
        assert resumed["result"][name] == uninterrupted["result"][name]
    assert service.repository.connection.execute("SELECT COUNT(*) FROM backtest_checkpoint_chunks").fetchone()[0] == 0
    service.shutdown()


@pytest.mark.parametrize("case", ["SMA", "FEEDBACK", "ORDERS"])
def test_all_four_flags_spawned_full_report_equality(tmp_path, monkeypatch, case):
    from dataclasses import replace
    from pathlib import Path
    import shutil
    from app.backtest.service import BacktestService
    from app.backtest.strategy.python_provider import PythonHostProvider
    from tests.test_backtest_control_plane import _settings, _payload
    from tests.test_backtest_colocated import bars
    from scripts.generic_strategy_sources import SOURCES
    from scripts.benchmark_four_paths import FLAGS
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    bundle = tmp_path / "script"
    bundle.mkdir()
    if case == "SMA":
        source = Path(__file__).resolve().parents[2] / "packages/candlescope-backtest-sdk/templates/sma_cross/strategy.py"
        shutil.copy2(source, bundle / "strategy.py")
    else:
        (bundle / "strategy.py").write_text(SOURCES[case], encoding="utf-8")
    settings = _settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="128")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(parameters={"fast": 3, "slow": 5},
                                  execution_model_revision="EXECUTION_REALISM_V2"), idempotency_key="same", now_ms=2)
    seed.shutdown()
    results = []
    for enabled in (False, True):
        for flag in FLAGS:
            monkeypatch.setenv(flag, str(int(enabled)))
        db = tmp_path / f"mode-{enabled}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        try:
            provider = PythonHostProvider(bundle, parameters={"fast": 3, "slow": 5},
                                          mode="TRUSTED_LOCAL", trusted_confirmed=True, bound_transcript=True)
            results.append(service.execute_bar_run(run["run_id"], events=bars(850), provider=provider, now_ms=3))
        finally:
            service.shutdown()
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["report"] == results[1]["report"]
