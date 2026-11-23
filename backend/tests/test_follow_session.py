"""ADR-BACKTEST-015 P4b: FOLLOW for HOST strategies equals FIXED on the same bars (§3.4)."""
from __future__ import annotations

import json

import pytest

from app.backtest.errors import BacktestError
from app.backtest.follow_session import FollowSession, FollowSessions, follow_identity
from app.backtest.models import ENGINE_VERSION
from app.backtest.run_result import from_host_result
from app.market_dataset.snapshot import MarketEvent
from app.simulation.trade_bar_builder import derive_complete_trade_bars
from tests import strategy_run_oracles as oracles
from tests.test_strategy_run_oracles import (  # noqa: F401 - service is a fixture
    BAR, BUILTIN_SMA_REVISION, builtin_provider, fixed_run, python_provider, service,
)


def definition_of(row) -> dict:
    """The FOLLOW definition of a FIXED run: the same configuration and input plan."""
    config = json.loads(str(row["config_json"]))
    return {"engine_version": ENGINE_VERSION, "configuration": config,
            "input_plan": {"roles": ["BARS"], "parameters": config["parameters"]},
            "market": {"venue": "local", "symbol": str(row["dataset_id"])}}


def chunked(bars, sizes):
    start = 0
    for size in sizes:
        yield bars[start:start + size]
        start += size
    yield bars[start:]


def assert_follow_equals_fixed(follow: dict, fixed_result: dict, *, interval: str) -> None:
    """Equal in everything but the end: FIXED cancels the orders still working when its data ends."""
    fixed = from_host_result(fixed_result, interval=interval, fidelity="BAR_APPROX")
    assert (follow["clock_policy"], fixed["clock_policy"]) == ("FOLLOW", "FIXED")
    for key in fixed:
        if key not in {"clock_policy", "pending_orders"}:
            assert follow[key] == fixed[key], key
    cancelled_at_end = {order["order_id"] for order in fixed_result["orders"] if order["status"] == "CANCELLED_EOF"}
    assert {order["order_id"] for order in follow["pending_orders"]} == cancelled_at_end
    assert fixed["pending_orders"] == []


@pytest.mark.parametrize("sizes", [(), (1, 1, 1, 1, 1), (1, 2, 7), (46,)], ids=["one-pass", "bar-by-bar-start", "uneven", "all-but-last"])
@pytest.mark.parametrize("provider_name", ["builtin", "python"])
def test_follow_advanced_in_any_batches_equals_the_fixed_run(service, provider_name, sizes):
    row, completed = fixed_run(service, provider_name)
    factory = (lambda _: builtin_provider()) if provider_name == "builtin" else (lambda _: python_provider())
    session = FollowSession("fl_oracle", definition_of(row), factory, interval="1m")
    try:
        for batch in chunked(list(oracles.bars()), sizes):
            session.extend(batch)
        assert session.through_ms == oracles.bars()[-1].event_time_ms
        assert_follow_equals_fixed(session.result(), completed["result"], interval="1m")
        assert session.result()["fills"], "the oracle strategy trades"
    finally:
        session.close()


def test_follow_on_a_5m_chart_equals_the_fixed_5m_run(service):
    bars = derive_complete_trade_bars(oracles.trades(), "5m")
    row = service.create_run({**BAR, "interval": "5m", "warmup_bars": 1, "strategy_revision_id": BUILTIN_SMA_REVISION},
                             idempotency_key="oracle-5m", now_ms=4)
    completed = service.execute_bar_run(str(row["run_id"]), events=bars, provider=builtin_provider(), now_ms=5)
    assert completed["state"] == "COMPLETED"
    session = FollowSession("fl_5m", definition_of(row), lambda _: builtin_provider(), interval="5m")
    try:
        for bar in bars:  # one closed 5m bar at a time, as a live chart delivers them
            session.extend([bar])
        assert_follow_equals_fixed(session.result(), completed["result"], interval="5m")
        assert session.revision == len(bars)
    finally:
        session.close()


def test_follow_takes_only_consecutive_closed_bars_of_its_interval(service):
    row, _ = fixed_run(service, "builtin")
    bars = list(oracles.bars())
    session = FollowSession("fl_guard", definition_of(row), lambda _: builtin_provider(), interval="1m")

    def bar(index, **changes):
        base = bars[index]
        return MarketEvent(sequence=changes.pop("sequence", base.sequence), event_time_ms=base.event_time_ms,
                           role=base.role, payload={**base.payload, **changes})
    try:
        session.extend(bars[:3])
        for wrong in ([bar(4, sequence=4)], [bar(3, sequence=5)], [bar(3, is_closed=False)],
                      [bar(3, close_time_ms=bars[3].payload["close_time_ms"] + 60_000)]):
            with pytest.raises(BacktestError) as refused:
                session.extend(wrong)
            assert refused.value.code == "FOLLOW_INPUT_INVALID"
        assert (session.revision, session.through_ms) == (1, bars[2].event_time_ms), "a refused batch changes nothing"
        assert session.extend([]) == 1
        session.extend(bars[3:5])
        assert session.revision == 2
    finally:
        session.close()
    with pytest.raises(BacktestError) as stopped:
        session.extend(bars[5:6])
    assert stopped.value.code == "FOLLOW_CLOSED"
    with pytest.raises(BacktestError) as calendar:
        FollowSession("fl_month", definition_of(row), lambda _: builtin_provider(), interval="1M")
    assert calendar.value.code == "FIDELITY_UNSUPPORTED"


def test_a_failed_advance_must_start_over(service, monkeypatch):
    row, _ = fixed_run(service, "builtin")
    session = FollowSession("fl_fail", definition_of(row), lambda _: builtin_provider(), interval="1m")
    try:
        def broken(*_args, **_kwargs):
            raise RuntimeError("provider crashed")
        monkeypatch.setattr(session.host, "_observe", broken)  # the strategy raises mid-batch
        with pytest.raises(RuntimeError):
            session.extend(list(oracles.bars())[:2])
        for action in (lambda: session.extend([]), session.result):
            with pytest.raises(BacktestError) as failed:
                action()
            assert failed.value.code == "FOLLOW_FAILED"
    finally:
        session.close()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_follow_runs_are_shared_by_input_held_by_leases_and_bounded(service):
    row, _ = fixed_run(service, "builtin")
    definition = definition_of(row)
    clock = Clock()
    sessions = FollowSessions(lambda _: builtin_provider(), capacity=2, lease_ms=10_000, clock=clock)
    first, created = sessions.open(definition, interval="1m", holder="cell-a")
    shared, created_again = sessions.open(definition, interval="1m", holder="cell-b")
    assert created and not created_again and shared is first
    assert first.follow_id.startswith("fl_") and follow_identity(definition, "1m") != follow_identity(definition, "5m")
    other, _ = sessions.open(definition, interval="5m", holder="cell-c")
    with pytest.raises(BacktestError) as full:
        sessions.open({**definition, "market": {"venue": "local", "symbol": "other"}}, interval="1m", holder="cell-d")
    assert full.value.code == "FOLLOW_CAPACITY_EXCEEDED"
    sessions.release(first.follow_id, "cell-a")
    assert sessions.get(first.follow_id) is first, "another cell still holds it"
    clock.now += 6
    sessions.renew(first.follow_id, "cell-b")
    clock.now += 6  # cell-c's lease expired; cell-b renewed
    assert sessions.diagnostics() == {"runs": 2, "leases": 2}, "an expired lease counts until a sweep"
    sessions.sweep()
    assert sessions.diagnostics() == {"runs": 1, "leases": 1}
    assert other.closed, "a run no chart holds stops"
    with pytest.raises(BacktestError) as gone:
        sessions.get(other.follow_id)
    assert gone.value.code == "RUN_NOT_FOUND"
    sessions.release(first.follow_id, "cell-b")
    assert first.closed and sessions.diagnostics() == {"runs": 0, "leases": 0}
    again, created = sessions.open(definition, interval="1m", holder="cell-a")
    assert created and again is not first, "a stopped run is recomputed, not revived"
    sessions.close()
    assert again.closed
