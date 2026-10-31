from copy import deepcopy
import json

import pytest

from app.backtest.errors import BacktestError
from app.backtest.pine_risk_state import PineRiskState


def configuration(*rules):
    return {"schemaVersion": 1, "unresolvedCallSiteIds": [], "rules": [
        {"callSiteId": index, "function": "strategy.risk." + name, "value": value,
         "resolved": True, **extra} for index, (name, value, extra) in enumerate(rules)]}


def cash(name, value, **extra):
    return name, value, {"valueType": "strategy.cash", **extra}


def percent(name, value):
    return name, value, {"valueType": "strategy.percent_of_equity"}


def model(*rules):
    return PineRiskState(configuration(*rules), initial_equity=1000, window_policy="EXPLICIT_TEST_WINDOWS_V1")


def observe(state, time, equity, profit=0, session=0, intraday=0, fill=None):
    return state.observe(time_ms=time, equity=equity, netprofit=profit,
        session=session, intraday=intraday, filled_order_id=fill)


def test_drawdown_trips_on_market_equity_without_a_fill_and_never_resets():
    state = model(cash("max_drawdown", 100, alertMessage="DD"))
    assert observe(state, 0, 1000) == []
    assert observe(state, 1, 1200) == []
    trips = observe(state, 2, 1100)
    assert len(trips) == 1 and trips[0]["permanent"] and trips[0]["alert_message"] == "DD"
    assert state.blocked
    assert observe(state, 3, 1500, session=1, intraday=1) == []
    assert state.blocked and len(state.trips) == 1


def test_duplicate_cash_and_percent_rules_are_independent_and_use_global_peak():
    state = model(cash("max_drawdown", 150), percent("max_drawdown", 10))
    observe(state, 0, 1200)
    assert [trip["callSiteId"] for trip in observe(state, 1, 1080)] == [1]
    assert [trip["callSiteId"] for trip in observe(state, 2, 1050)] == [0]
    assert state.permanent == {0, 1}


@pytest.mark.parametrize("name", ["max_drawdown", "max_intraday_loss"])
def test_nonpositive_equity_percent_rule_is_permanent_even_after_a_new_window(name):
    state = model(percent(name, 100))
    trips = observe(state, 0, 0, profit=-1000)
    assert trips[0]["permanent"] and state.blocked
    observe(state, 1, 1000, profit=0, session=1, intraday=1)
    assert state.blocked


def test_intraday_loss_uses_window_peak_and_resets_at_explicit_window_only():
    state = model(percent("max_intraday_loss", 10))
    observe(state, 0, 1200)
    assert not observe(state, 1, 1081)
    assert observe(state, 2, 1080)[0]["permanent"] is False
    observe(state, 3, 1100, session=1, intraday=0)  # A trading day may differ from a >1D chart window.
    assert state.blocked
    observe(state, 4, 1000, session=1, intraday=1)
    assert not state.blocked and str(state.intraday_peak) == "1000"


def test_fill_count_counts_actual_order_ids_once_per_window_including_partial_fills():
    state = model(("max_intraday_filled_orders", 2, {}))
    observe(state, 0, 1000)
    assert not observe(state, 1, 999, profit=-1, fill="A")
    assert not observe(state, 1, 998, profit=-2, fill="A")
    trips = observe(state, 1, 997, profit=-3, fill="B")
    assert state.blocked and trips[0]["filled_order_count"] == 2
    observe(state, 2, 996, profit=-4)  # The risk-generated close is not a third script order.
    assert state.filled_orders == {"A", "B"}
    observe(state, 3, 996, profit=-4, intraday=1, session=1, fill="A")
    assert not state.blocked and state.filled_orders == {"A"}


def test_completed_realized_loss_days_trip_at_the_next_session_boundary():
    state = model(("max_cons_loss_days", 2, {}))
    observe(state, 0, 1000)
    observe(state, 1, 800, profit=0)  # Floating loss alone is not a realized loss day.
    observe(state, 2, 995, profit=-5)
    observe(state, 3, 995, profit=-5, session=1, intraday=1)
    assert state.loss_days == 1 and not state.blocked
    observe(state, 4, 992, profit=-8, session=1, intraday=1)
    trips = observe(state, 5, 900, profit=-10, session=2, intraday=2)
    assert trips[0]["consecutive_loss_days"] == 2 and state.blocked
    # The first update in session 2 belongs to that new session, not session 1.
    assert str(state.session_netprofit) == "-8"


@pytest.mark.parametrize("second_profit", [-5, 0])
def test_zero_or_winning_session_breaks_consecutive_realized_loss_days(second_profit):
    state = model(("max_cons_loss_days", 2, {}))
    observe(state, 0, 995, profit=-5)
    observe(state, 1, 995, profit=-5, session=1, intraday=1)
    observe(state, 2, 1000+second_profit, profit=second_profit, session=1, intraday=1)
    observe(state, 3, 1000+second_profit, profit=second_profit, session=2, intraday=2)
    assert state.loss_days == 0 and not state.blocked


def test_json_checkpoint_preserves_peaks_halts_partial_fill_ids_and_rollover_baselines():
    rules = (cash("max_drawdown", 200), percent("max_intraday_loss", 10),
        ("max_intraday_filled_orders", 3, {}), ("max_cons_loss_days", 2, {}))
    state = model(*rules)
    observe(state, 0, 1200)
    observe(state, 1, 1100, profit=-5, fill="A")
    restored = model(*rules)
    restored.restore(json.loads(json.dumps(state.snapshot())))
    for args in [(2, 1090, -8, 0, 0, "A"), (3, 1080, -10, 0, 0, "B"),
                 (4, 1000, -10, 1, 1, None), (5, 990, -20, 1, 1, "C"),
                 (6, 990, -20, 2, 2, None)]:
        assert observe(state, *args) == observe(restored, *args)
        assert state.snapshot() == restored.snapshot()


@pytest.mark.parametrize("change", [
    {"time": -1}, {"time": 0}, {"session": -1}, {"intraday": -1},
    {"session": 3}, {"equity": "NaN"}, {"fill": ""},
])
def test_noncausal_or_missing_account_windows_leave_state_unchanged(change):
    state = model(("max_cons_loss_days", 2, {}), ("max_intraday_filled_orders", 2, {}))
    observe(state, 1, 1000, session=1, intraday=1)
    before = deepcopy(state.snapshot())
    arguments = dict(time=2, equity=999, profit=-1, session=1, intraday=1, fill=None)
    arguments.update(change)
    with pytest.raises(BacktestError):
        observe(state, **arguments)
    assert state.snapshot() == before


def test_restore_rejects_changed_policy_or_rules_before_mutation():
    state = model(cash("max_drawdown", 100))
    observe(state, 0, 1200)
    before = deepcopy(state.snapshot())
    bad = deepcopy(before)
    bad["window_policy"] = "GUESS_UTC"
    with pytest.raises(BacktestError, match="CHECKPOINT_CORRUPT"):
        state.restore(bad)
    assert state.snapshot() == before


def test_windowed_rules_never_guess_a_session_from_the_wall_clock():
    state = model(cash("max_intraday_loss", 100))
    before = state.snapshot()
    with pytest.raises(BacktestError, match="explicit ordered risk windows"):
        state.observe(time_ms=86_400_000, equity=900, netprofit=-100)
    assert state.snapshot() == before
    drawdown = model(cash("max_drawdown", 100))
    assert drawdown.observe(time_ms=86_400_000, equity=900, netprofit=-100)[0]["permanent"]
