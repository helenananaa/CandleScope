from dataclasses import asdict, replace
from decimal import Decimal
import json
from pathlib import Path
import shutil

import pytest

from app.backtest.checkpoint_history import (
    HistoryEncoder,
    TRADE_ENCODING,
    rollback_history,
)
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json, sha256_hex
from app.backtest.repository import BacktestRepository
from app.backtest.service import BacktestService
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.backtest.strategy.python_provider import PythonHostProvider
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from scripts.benchmark_trade_strategy import events, payload, settings, FLAGS


@pytest.mark.parametrize("python", [False, True])
def test_dual_clock_whole_worker_full_equivalence(tmp_path, monkeypatch, python):
    config = settings(tmp_path, 32)
    seed = BacktestService.start(config, now_ms=1)
    created = seed.create_run(payload(), idempotency_key="same", now_ms=2)
    seed.shutdown()
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    outcomes = []
    bundle = (
        Path(__file__).resolve().parents[2]
        / "packages/candlescope-backtest-sdk/templates/sma_cross"
    )
    for enabled in (0, 1):
        for flag in FLAGS:
            monkeypatch.setenv(flag, str(enabled))
        db = tmp_path / f"lane-{enabled}.db"
        shutil.copy2(config.db_path, db)
        service = BacktestService.start(replace(config, db_path=db), now_ms=1)
        provider = (
            PythonHostProvider(
                bundle,
                parameters={"fast": 3, "slow": 5},
                mode="TRUSTED_LOCAL",
                trusted_confirmed=True,
            )
            if python
            else IsolatedStrategyProvider("builtin-sma-cross-v1", step_timeout_s=5)
        )
        try:
            completed = service.execute_dual_clock_run(
                created["run_id"], events=events(500), provider=provider, now_ms=3
            )
            if enabled:
                assert completed["execution_lane"] == "COLOCATED_DUAL_CLOCK_V1"
            outcomes.append(completed)
        finally:
            service.shutdown()
    assert outcomes[0]["result"] == outcomes[1]["result"]
    assert outcomes[0]["report"] == outcomes[1]["report"]


def mixed_orders(visible, event):
    n = event.sequence
    if n % 7 == 0:
        return [
            {
                "side": "BUY",
                "type": "LIMIT",
                "qty": "0.4",
                "limit_price": "103",
                "tif": "IOC",
            }
        ]
    if n % 11 == 0:
        return [
            {
                "side": "SELL",
                "type": "STOP",
                "qty": "0.6",
                "stop_price": "103",
                "reduce_only": True,
                "oco_group": str(n),
            },
            {
                "side": "SELL",
                "type": "LIMIT",
                "qty": "0.6",
                "limit_price": "106",
                "reduce_only": True,
                "oco_group": str(n),
            },
        ]
    if n % 13 == 0:
        return [
            {
                "side": "BUY",
                "type": "STOP_LIMIT",
                "qty": "0.5",
                "stop_price": "104",
                "limit_price": "105",
            }
        ]
    return [{"side": "BUY" if n % 2 else "SELL", "type": "MARKET", "qty": "0.3"}]


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("v2", [False, True])
def test_active_orders_mixed_lifecycle_and_resume_equivalence(monkeypatch, dual, v2):
    outcomes = []
    for enabled in (0, 1):
        monkeypatch.setenv(FLAGS[0], str(enabled))
        options = {
            "checkpoint_event_interval": 0,
            "funding_rate": Decimal("0.001"),
            "funding_interval_ms": 60000,
        }
        if v2:
            options.update(
                execution_model_revision="EXECUTION_REALISM_V2",
                participation_rate=Decimal("0.03"),
                latency_events=1,
                latency_ms=5,
            )

        def factory():
            return (
                DualClockSimulationKernel("1m", **options)
                if dual
                else TradeSimulationKernel(**options)
            )

        kernel = factory()
        tape = events(1000, 2)
        kernel.run(tape[:501], mixed_orders)
        state = kernel.snapshot()
        restored = factory()
        restored.restore(state)
        result = restored.run(tape[501:], mixed_orders, finalize=True)
        uninterrupted = kernel.run(tape[501:], mixed_orders, finalize=True)
        assert result == uninterrupted
        outcomes.append((result, restored.snapshot()))
    assert outcomes[0] == outcomes[1]


def repository(tmp_path):
    repo = BacktestRepository(tmp_path / "state.db")
    repo.open(now_ms=1)
    columns = repo.connection.execute("PRAGMA table_info(backtest_runs)").fetchall()
    values = {c[1]: (1 if c[2] == "INTEGER" else "x") for c in columns if c[3]}
    values.update(run_id="r", state="RUNNING", generation=1)
    repo.connection.execute(
        "INSERT INTO backtest_runs ("
        + ",".join(values)
        + ") VALUES ("
        + ",".join("?" for _ in values)
        + ")",
        tuple(values.values()),
    )
    repo.connection.commit()
    return repo


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("corruption", [None, "missing", "bytes"])
def test_trade_chunks_durable_restore_budget_and_corruption(tmp_path, dual, corruption):
    kernel = (
        DualClockSimulationKernel("1m")
        if dual
        else TradeSimulationKernel(checkpoint_event_interval=0)
    )
    kernel.run(
        events(700, 1),
        lambda _, e: [
            {"side": "BUY" if e.sequence % 2 else "SELL", "type": "MARKET", "qty": "1"}
        ],
    )
    history = HistoryEncoder(asdict)
    history.begin()
    full = {
        "checkpointMode": "DUAL_CLOCK" if dual else "TRADE_TAPE",
        "engine": kernel.snapshot(),
    }
    packed = {
        **full,
        "engine": kernel.snapshot(history_encoder=history),
        "historyEncoding": TRADE_ENCODING,
    }
    raw = canonical_json(packed)
    assert len(raw.encode()) + history.logical_extra - len(
        canonical_json("historyEncoding") + ":" + canonical_json(TRADE_ENCODING) + ","
    ) == len(canonical_json(full).encode())
    repo = repository(tmp_path)
    record = {
        "run_id": "r",
        "sequence": 700,
        "generation": 1,
        "payload_json": raw,
        "state_hash": "sha256:" + sha256_hex(raw),
        "created_at_ms": 1,
        "history_chunks": dict(history.pending),
    }
    assert history.pending and repo.save_checkpoint(record)
    history.pending.clear()
    history.begin()
    assert kernel.snapshot(history_encoder=history) == packed["engine"]
    assert not history.pending
    if corruption:
        sql = (
            "DELETE FROM backtest_checkpoint_chunks"
            if corruption == "missing"
            else "UPDATE backtest_checkpoint_chunks SET payload_json='[]'"
        )
        repo.connection.execute(sql)
        repo.connection.commit()
        with pytest.raises(BacktestError, match="CHECKPOINT_CORRUPT"):
            repo.latest_checkpoint("r")
        repo.close()
        with pytest.raises(BacktestError):
            rollback_history(tmp_path / "state.db")
        return
    repo.close()
    repo.open(now_ms=2)
    loaded = json.loads(repo.latest_checkpoint("r")["payload_json"])
    assert loaded == json.loads(canonical_json(full))
    restored = (
        DualClockSimulationKernel("1m")
        if dual
        else TradeSimulationKernel(checkpoint_event_interval=0)
    )
    restored.restore(loaded["engine"])
    assert canonical_json(restored.snapshot()) == canonical_json(kernel.snapshot())
    repo.close()
    assert rollback_history(tmp_path / "state.db")["schemaVersion"] == 7


def test_dual_worker_timeout_and_resume(tmp_path, monkeypatch):
    from tests.test_backtest_colocated import hanging_provider
    import multiprocessing

    bundle, marker = hanging_provider(tmp_path, monkeypatch)
    monkeypatch.setenv("BACKTEST_COLOCATED_DUAL_CLOCK_ENABLED", "1")
    config = replace(settings(tmp_path, 32), provider_step_timeout_ms=200)
    service = BacktestService.start(config, now_ms=1)

    def provider():
        return PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True)

    created = service.create_run(payload(), idempotency_key="interrupted", now_ms=2)
    tape = events(1000)
    try:
        with pytest.raises(BacktestError, match="PROVIDER_TIMEOUT"):
            service.execute_dual_clock_run(
                created["run_id"], events=tape, provider=provider(), now_ms=3
            )
        saved = service.repository.latest_checkpoint(created["run_id"])
        assert saved is not None and saved["sequence"] == 640
        assert not [
            p
            for p in multiprocessing.active_children()
            if p.name.startswith("backtest-run-")
        ]
        marker.unlink()
        service.resume_failed_run(created["run_id"], now_ms=4)
        resumed = service.execute_dual_clock_run(
            created["run_id"], events=tape, provider=provider(), now_ms=5
        )
        clean = service.create_run(payload(), idempotency_key="clean", now_ms=6)
        normal = service.execute_dual_clock_run(
            clean["run_id"], events=tape, provider=provider(), now_ms=7
        )
        for key in (
            "decision_hash",
            "fill_hash",
            "ledger_hash",
            "fills",
            "equity_curve",
            "ledger",
        ):
            assert resumed["result"][key] == normal["result"][key]
    finally:
        service.shutdown()


def test_dual_sandbox_stays_isolated(tmp_path, monkeypatch):
    from app.backtest.colocated import provider_spec

    monkeypatch.setattr(
        "app.backtest.strategy.python_runner.sandbox_available", lambda: True
    )
    assert (
        provider_spec(
            PythonHostProvider(tmp_path, mode="SANDBOXED_LOCAL"),
            fidelity="AGG_TRADE_EXECUTION",
        )
        is None
    )


def test_closed_history_not_scanned_per_print():
    from app.simulation.kernel import SimulatedOrder

    class History(list):
        reads = 0

        def __iter__(self):
            for item in super().__iter__():
                self.reads += 1
                yield item

    orders = History(
        SimulatedOrder(str(i), "BUY", "MARKET", Decimal("0"), i, status="FILLED")
        for i in range(10000)
    )
    kernel = TradeSimulationKernel(orders=orders)
    kernel._working_orders()
    orders.reads = 0
    for event in events(100):
        kernel._match(event)
        assert kernel.projected_position_qty == 0
    assert orders.reads == 0


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize(
    "switch",
    [
        "BACKTEST_TRADE_INCREMENTAL_CHECKPOINT_ENABLED",
        "BACKTEST_EXTENDED_TRADE_HISTORY_ENABLED",
    ],
)
def test_service_chunked_checkpoint_resume_with_new_orders(
    tmp_path, monkeypatch, dual, switch
):
    from app.backtest.strategy.builtin import BuiltinOrderCommandProvider

    config = settings(tmp_path, 300)
    service = BacktestService.start(config, now_ms=1)
    request = payload()
    request.update(output_mode="ORDER_INTENT", warmup_bars=0)

    class DenseProvider(BuiltinOrderCommandProvider):
        def prepare(self, context):
            super().prepare(
                {
                    **context,
                    "source": json.dumps(
                        {
                            "commands": [
                                {
                                    "sequence": i,
                                    "side": "BUY" if i % 2 else "SELL",
                                    "type": "MARKET",
                                    "qty": "0.1",
                                }
                                for i in range(1, 801)
                            ]
                        }
                    ),
                }
            )

    if not dual:
        for key in (
            "signal_clock",
            "signal_interval",
            "execution_clock",
            "bar_builder",
            "timezone",
        ):
            request.pop(key)
        request["fidelity_mode"] = "AGG_TRADE_TAPE"
    run = service.create_run(request, idempotency_key="interrupted", now_ms=2)
    execute = service.execute_dual_clock_run if dual else service.execute_trade_run
    original = service.repository.save_checkpoint

    def interrupt_after_durable(record):
        saved = original(record)
        if record["sequence"] == 600:
            assert record["history_chunks"]
            raise KeyboardInterrupt("test durable interruption")
        return saved

    service.repository.save_checkpoint = interrupt_after_durable
    try:
        with pytest.raises(KeyboardInterrupt):
            execute(
                run["run_id"], events=events(850, 1), provider=DenseProvider(), now_ms=3
            )
        service.repository.save_checkpoint = original
        assert service.requeue_interrupted_run(
            run["run_id"], expected_generation=1, now_ms=4
        )
        # New writes can use the old full format after reading chunked state.
        monkeypatch.setenv(switch, "0")
        resumed = execute(
            run["run_id"], events=events(850, 1), provider=DenseProvider(), now_ms=5
        )
        clean = service.create_run(request, idempotency_key="clean", now_ms=6)
        normal = execute(
            clean["run_id"], events=events(850, 1), provider=DenseProvider(), now_ms=7
        )
        assert resumed["result"] == normal["result"]
    finally:
        service.shutdown()


def test_resting_order_prevents_sealing_mutable_prefix():
    kernel = TradeSimulationKernel(checkpoint_event_interval=0)
    kernel._enqueue(
        {"side": "BUY", "type": "LIMIT", "qty": "1", "limit_price": "1"},
        current_sequence=0,
    )
    kernel.run(
        events(600),
        lambda _, e: [
            {"side": "BUY" if e.sequence % 2 else "SELL", "type": "MARKET", "qty": "1"}
        ],
    )
    history = HistoryEncoder(asdict)
    history.begin()
    snapshot = kernel.snapshot(history_encoder=history)
    assert snapshot["orders"]["chunks"] == []
    assert snapshot["fills"]["chunks"]
    assert len(snapshot["orders"]["tail"]) == len(kernel.orders)
    assert len(kernel._working_orders()) == 2  # resting limit and last market order
