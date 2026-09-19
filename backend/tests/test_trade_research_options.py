import json
from decimal import Decimal

import pytest

from app.backtest.errors import BacktestError
from app.backtest.reports import verify_report_hash
from app.backtest.service import BacktestService
from app.backtest.strategy.builtin import BuiltinOrderCommandProvider
from scripts.benchmark_trade_strategy import events, payload, settings


class Orders(BuiltinOrderCommandProvider):
    def prepare(self, context):
        return super().prepare({**context, "source": json.dumps({"commands": [
            {"sequence": i, "side": "BUY" if i % 2 else "SELL",
             "type": "MARKET", "qty": "0.1"}
            for i in range(1, 26)
        ]})})


def request(dual):
    value = payload()
    value.update(output_mode="ORDER_INTENT", warmup_bars=0)
    if not dual:
        for key in ("signal_clock", "signal_interval", "execution_clock", "bar_builder", "timezone"):
            value.pop(key)
        value["fidelity_mode"] = "AGG_TRADE_TAPE"
    return value


@pytest.mark.parametrize("dual", [False, True])
def test_research_options_preserve_primary_and_control_work(tmp_path, monkeypatch, dual):
    service = BacktestService.start(settings(tmp_path, 10000), now_ms=1)
    execute = service.execute_dual_clock_run if dual else service.execute_trade_run
    publications = []
    save = service.repository.save_checkpoint

    def record_checkpoint(value):
        publications.append(value["sequence"])
        return save(value)

    monkeypatch.setattr(service.repository, "save_checkpoint", record_checkpoint)
    baseline = None
    try:
        for mode in ("FULL", "SKIP"):
            for policy, expected in (("INTERVAL", [0, 10, 20, 25]), ("FINAL_ONLY", [25]), ("NONE", [])):
                value = request(dual)
                value.update(cost_sensitivity_mode=mode, checkpoint_policy=policy)
                if policy == "INTERVAL":
                    value["checkpoint_interval"] = 10
                run = service.create_run(value, idempotency_key=mode + policy, now_ms=2)
                publications.clear()
                if mode == "SKIP":
                    def forbidden(*args, **kwargs):
                        raise AssertionError("skipped sensitivity must not run")
                    monkeypatch.setattr("app.backtest.service.build_cost_sensitivity_matrix", forbidden)
                completed = execute(run["run_id"], events=events(25, 1), provider=Orders(), now_ms=3)
                assert publications == expected
                assert completed["state"] == "COMPLETED"
                assert verify_report_hash(completed["report"])
                result = dict(completed["result"])
                sensitivity = result.pop("cost_sensitivity")
                result.pop("report_hash")
                if baseline is None:
                    baseline = result
                assert result == baseline
                if mode == "SKIP":
                    assert sensitivity == {"status": "SKIPPED_BY_REQUEST", "scenarios": []}
                    assert completed["report"]["cost_sensitivity"] == sensitivity
                else:
                    assert len(sensitivity["scenarios"]) == 5
    finally:
        service.shutdown()


@pytest.mark.parametrize("options", [
    {"cost_sensitivity_mode": "FAST"}, {"cost_sensitivity_mode": False},
    {"checkpoint_policy": "BAD"}, {"checkpoint_interval": True},
    {"checkpoint_interval": 0}, {"checkpoint_policy": "NONE", "checkpoint_interval": 10},
])
def test_invalid_research_options_rejected(tmp_path, options):
    service = BacktestService.start(settings(tmp_path), now_ms=1)
    try:
        with pytest.raises(BacktestError):
            service.create_run({**request(True), **options}, idempotency_key="invalid", now_ms=2)
    finally:
        service.shutdown()


def test_public_request_accepts_research_options():
    from app.api.v1.backtests import RunCreateRequest
    value = RunCreateRequest(**{**request(True), "cost_sensitivity_mode": "SKIP", "checkpoint_policy": "FINAL_ONLY"})
    assert value.model_dump()["cost_sensitivity_mode"] == "SKIP"


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("point", ["after_order", "after_partial_fill"])
def test_fault_injection_still_saves_and_resumes(tmp_path, dual, point):
    class WorkerDeath(BaseException):
        pass

    def inject(name, details):
        if name == point:
            raise WorkerDeath(name)

    service = BacktestService.start(settings(tmp_path, 10000), now_ms=1, fault_injector=inject)
    execute = service.execute_dual_clock_run if dual else service.execute_trade_run
    tape = events(25, 1)
    for event in tape:
        event.payload["qty"] = "0.1"
    value = {**request(dual), "participation_rate": "0.1"}
    try:
        run = service.create_run(value, idempotency_key="fault", now_ms=2)
        with pytest.raises(WorkerDeath):
            execute(run["run_id"], events=tape, provider=Orders(), now_ms=3)
        assert service.repository.latest_checkpoint(run["run_id"])["sequence"] > 0
        service._fault_injector = None
        assert service.requeue_interrupted_run(run["run_id"], expected_generation=1, now_ms=4)
        resumed = execute(run["run_id"], events=tape, provider=Orders(), now_ms=5)
        clean = service.create_run(value, idempotency_key="clean", now_ms=6)
        normal = execute(clean["run_id"], events=tape, provider=Orders(), now_ms=7)
        assert resumed["result"] == normal["result"]
    finally:
        service.shutdown()


@pytest.mark.parametrize("daily", [False, True])
def test_sampled_curve_matches_full_curve_with_fewer_equity_calls(monkeypatch, daily):
    from app.simulation.trade_kernel import TradeSimulationKernel
    from tests.test_trade_strategy_performance import mixed_orders

    options = {"checkpoint_event_interval": 0, "execution_model_revision": "EXECUTION_REALISM_V2",
               "participation_rate": Decimal("0.03")}
    if daily:
        options["equity_curve_mode"] = "UTC_DAILY_CLOSE_V1"
    dense = TradeSimulationKernel(**options)
    sparse = TradeSimulationKernel(**options, equity_curve_event_interval=100)
    account_type = type(dense.account)
    original = account_type.equity
    calls = []

    def equity(account):
        calls.append(account)
        return original(account)

    monkeypatch.setattr(account_type, "equity", equity)
    full = dense.run(events(251), mixed_orders, finalize=True)
    dense_count = len(calls)
    calls.clear()
    sampled = sparse.run(events(251), mixed_orders, finalize=True)
    sparse_count = len(calls)
    assert sampled.fills == full.fills
    assert sampled.orders == full.orders
    assert sampled.ledger_hash == full.ledger_hash
    assert sampled.equity_curve == [point for point in full.equity_curve
        if daily or point["sequence"] in (1, 100, 200, 251)]
    if daily:
        assert sparse_count == dense_count
    else:
        assert dense_count - sparse_count == 247
