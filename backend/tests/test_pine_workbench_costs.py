"""Workbench cost scenarios must execute independent Pine decisions and accounts."""

from decimal import Decimal as D
from copy import deepcopy
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.backtests import router
from app.backtest.errors import BacktestError
from app.backtest.native import digest
from app.market_dataset.snapshot import sha256_hex
from tests.test_native_backtests import (
    runtime as runtime,
    terminal,
    pytestmark as pytestmark,
)
from tests.test_pine_workbench_v2_bar import config
from tests.test_external_replay import payload
from tests.test_native_replay import settle


def matrix(report):
    value = report["cost_sensitivity"]
    assert value["baseline_reexecution_verified"] is True
    assert value["decision_source"] == "INDEPENDENT_PINE_HOST_REEXECUTION"
    primary = {
        key: item
        for key, item in report.items()
        if key not in {"cost_sensitivity", "bars", "report_hash"}
    }
    assert value["baseline_execution_hash"] == digest(primary)
    assert value["matrix_hash"] == "sha256:" + sha256_hex(
        {key: item for key, item in value.items() if key != "matrix_hash"}
    )
    for row in value["scenarios"]:
        assert row["scenario_hash"] == "sha256:" + sha256_hex(
            {key: item for key, item in row.items() if key != "scenario_hash"}
        )
    return {row["name"]: row for row in value["scenarios"]}


def test_real_workbench_costs_change_callback_decisions_and_exit_prices(runtime):
    host, main = runtime
    value = config(main, model="LINEAR_PERP_ONE_WAY_V1")
    value["host_settings"]["taker_fee_bps"] = 10
    value["source"] = """//@version=6
strategy("Workbench costs",calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0
    if strategy.netprofit < -.0225
        strategy.close("L")
    else
        strategy.exit("X","L",stop=9.5,limit=10.5)
"""
    record = terminal(
        host.native, host.native.create(value, "workbench-costs")["run_id"]
    )
    assert record["state"] == "COMPLETED", record.get("error")
    report = record["result"]
    rows = matrix(report)
    assert D(rows["BASELINE"]["metrics"]["ending_equity"]) == D("9998.961")
    assert D(rows["COSTS_PLUS_50_PERCENT"]["metrics"]["ending_equity"]) == D("9997.943")
    assert (
        rows["BASELINE"]["hashes"]["decision"]
        != rows["COSTS_PLUS_50_PERCENT"]["hashes"]["decision"]
    )
    assert [D(row["price"]) for row in report["trades"]] == [10, D("9.5")]
    assert rows["LATENCY_PLUS_ONE_TIER"]["status"] == "NOT_APPLICABLE_BAR_CLOCK"


def test_real_workbench_v2_cost_accounts_reprice_gap_and_reduce_participation_independently(
    runtime,
):
    host, main = runtime
    value = config(main)
    value["host_settings"]["initial_balance"] = 100
    value["source"] = """//@version=6
strategy("Margin costs",calc_on_order_fills=true)
if bar_index==0
    strategy.entry("L",strategy.long,qty=50)
"""
    value["account_data"]["events"].append(
        {
            "time_ms": 60000,
            "role": "MARK_INDEX",
            "payload": {"mark_price": "8", "index_price": "8"},
        }
    )
    record = terminal(
        host.native, host.native.create(value, "workbench-margin-costs")["run_id"]
    )
    assert record["state"] == "COMPLETED", record.get("error")
    report = record["result"]
    rows = matrix(report)
    assert D(rows["BASELINE"]["metrics"]["ending_position"]) == 10
    assert D(rows["BASELINE"]["metrics"]["ending_equity"]) == 80
    reduced = rows["PARTICIPATION_DOWN_ONE_TIER"]
    assert (
        reduced["status"] == "COMPLETED"
        and D(reduced["metrics"]["ending_position"]) == 5
    )
    assert (
        D(report["position"]["position_qty"]) == 10
        and D(report["position"]["frozen_order_margin"]) == 0
    )
    assert [D(row["qty"]) for row in report["trades"]] == [5, 5]


@pytest.mark.parametrize(
    "mode", ["TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"]
)
def test_each_existing_print_and_book_profile_reexecutes_cost_accounts(runtime, mode):
    host, main = runtime
    record = terminal(
        host.native,
        host.native.create(payload(main, mode, True), "profile-costs")["run_id"],
    )
    assert record["state"] == "COMPLETED", record.get("error")
    rows = matrix(record["result"])
    assert rows["COSTS_PLUS_50_PERCENT"]["executed"] is True
    assert (
        rows["BASELINE"]["hashes"]["fill"]
        != rows["COSTS_PLUS_50_PERCENT"]["hashes"]["fill"]
    )
    assert (
        rows["LATENCY_PLUS_ONE_TIER"]["status"]
        == "NOT_APPLICABLE_LEGACY_EXECUTION_MODEL"
    )
    assert rows["PARTICIPATION_DOWN_ONE_TIER"]["executed"] is False


def test_spot_scenarios_keep_actual_cash_account_authority(runtime):
    host, main = runtime
    record = terminal(
        host.native,
        host.native.create(config(main, model="SPOT_CASH_V1"), "spot-costs")["run_id"],
    )
    assert record["state"] == "COMPLETED", record.get("error")
    assert record["result"]["account_model"] == "SPOT_CASH_V1"
    rows = matrix(record["result"])
    assert D(rows["BASELINE"]["metrics"]["ending_position"]) == 0


def test_replay_partial_prefix_has_no_future_matrix_and_full_restore_matches_it(
    runtime,
):
    host, main = runtime
    record = terminal(
        host.native, host.native.create(config(main), "cost-replay")["run_id"]
    )
    assert record["state"] == "COMPLETED", record.get("error")
    matrix(record["result"])
    service = host.native.replay
    created = service.create(record["run_id"])
    key = created["replay_id"]

    def seek(target):
        service.command(key, service.get(key)["revision"], "seek", target)
        return settle(service, key)

    first = seek(2)
    assert "cost_sensitivity" not in first["result"]
    saved = service.snapshot(key, first["revision"])["snapshots"][0]["snapshot_id"]
    full = seek(created["total"])
    assert full["result"] == record["result"]
    service.restore(key, full["revision"], saved)
    assert seek(created["total"])["result"] == full["result"]


def track_workers(monkeypatch):
    from app.backtest import native_session

    original = native_session.SessionWorker
    workers = []

    def create(*args, **kwargs):
        worker = original(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(native_session, "SessionWorker", create)
    return workers


def assert_closed(workers):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if all(
            worker.process.poll() is not None
            and worker.process.stdin.closed
            and worker.process.stdout.closed
            and worker.stderr.closed
            for worker in workers
        ):
            return
        time.sleep(0.01)
    raise AssertionError("a cost worker or pipe remained open")


def test_auto_uses_fresh_scenario_workers_and_skip_creates_only_primary(
    runtime, monkeypatch
):
    host, main = runtime
    workers = track_workers(monkeypatch)
    value = config(main)
    record = terminal(host.native, host.native.create(value, "fresh-workers")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    assert (
        len(workers) == 5
    )  # Primary, verified baseline, two cost variants and participation.
    assert_closed(workers)
    skipped = terminal(
        host.native,
        host.native.create({**value, "cost_sensitivity_mode": "SKIP"}, "skip-workers")[
            "run_id"
        ],
    )
    assert skipped["state"] == "COMPLETED", skipped.get("error")
    assert len(workers) == 6
    assert skipped["result"]["cost_sensitivity"]["status"] == "SKIPPED_BY_REQUEST"
    assert skipped["result"]["cost_sensitivity"]["scenarios"] == []
    assert skipped["result"]["trades"] == record["result"]["trades"]
    assert skipped["result"]["position"] == record["result"]["position"]
    assert_closed(workers)


@pytest.mark.parametrize("failure", ["baseline", "variant", "deadline"])
def test_scenario_failures_do_not_publish_partial_results_or_leave_workers(
    runtime, monkeypatch, failure
):
    from app.backtest import workbench_sensitivity as module

    host, main = runtime
    workers = track_workers(monkeypatch)
    execute = module._execute
    calls = 0

    def controlled(plugin, wire, runner, cancelled, deadline):
        nonlocal calls
        calls += 1
        if failure == "deadline":
            return execute(plugin, wire, runner, cancelled, time.monotonic() - 1)
        if failure == "variant" and calls == 2:
            raise BacktestError(
                "CONTROLLED_SCENARIO_FAILURE", "controlled variant failure"
            )
        result = execute(plugin, wire, runner, cancelled, deadline)
        if failure == "baseline":
            result = deepcopy(result)
            result["position"]["equity"] = "changed"
        return result

    monkeypatch.setattr(module, "_execute", controlled)
    record = terminal(
        host.native, host.native.create(config(main), "cost-failure")["run_id"]
    )
    expected = {
        "baseline": "PINE_SENSITIVITY_BASELINE_MISMATCH",
        "variant": "CONTROLLED_SCENARIO_FAILURE",
        "deadline": "NATIVE_TIMEOUT",
    }
    assert (
        record["state"] == "FAILED" and record["error"]["code"] == expected[failure]
    ), record
    assert record["result"] is None
    assert_closed(workers)


def test_cancelling_during_a_scenario_reaps_primary_and_does_not_publish_matrix(
    runtime, monkeypatch
):
    from app.backtest import workbench_sensitivity as module

    host, main = runtime
    workers = track_workers(monkeypatch)
    execute = module._execute
    entered, released = threading.Event(), threading.Event()

    def wait(plugin, wire, runner, cancelled, deadline):
        entered.set()
        assert released.wait(5)
        return execute(plugin, wire, runner, cancelled, deadline)

    monkeypatch.setattr(module, "_execute", wait)
    record = host.native.create(config(main), "cancel-costs")
    try:
        assert entered.wait(10)
        assert host.native.cancel(record["run_id"])["state"] == "CANCELLED"
    finally:
        released.set()
    assert_closed(workers)
    assert host.native.get(record["run_id"])["result"] is None


def test_public_requests_cannot_use_private_flags_to_bypass_cost_execution(runtime):
    host, main = runtime
    app = FastAPI()
    app.state.backtest_runtime = host
    app.include_router(router)
    with TestClient(app) as client:
        value = {**config(main), "_cost_scenario": True}
        response = client.post(
            "/backtests/external/runs",
            json=value,
            headers={"Idempotency-Key": "private-cost-flag"},
        )
        assert response.status_code == 422
