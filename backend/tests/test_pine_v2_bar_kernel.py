from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pytest

from app.market_dataset.snapshot import MarketEvent, MarketDatasetError
from app.simulation.execution_realism import EXECUTION_REALISM_V2, PINE_BAR_PATH_SCENARIO
from app.simulation.pine_chart_kernel import PineChartBarKernel
from app.simulation.pine_v2_bar_kernel import PineV2BarKernel
from tests.test_backtest_account_v2_m4 import rules
from tests.test_pine_bar_kernel import bar


def numbered(*events):
    return tuple(replace(event, sequence=index + 1) for index, event in enumerate(events))


def mark(stamp, price):
    return MarketEvent(1, stamp, "MARK_INDEX", {"mark_price": str(price), "index_price": str(price)})


def kernel(**extra):
    return PineV2BarKernel(slippage_bps=D(0), participation_rate=D(".5"),
        execution_model_revision=EXECUTION_REALISM_V2, bar_path_scenario=PINE_BAR_PATH_SCENARIO, **extra)


def run(subject, rows, *, quantity=2, callback=None, finalize=False):
    def strategy(_window, event):
        return [{"type": "MARKET", "side": "BUY", "qty": str(quantity)}] if event.payload["open_time_ms"] == 0 else []
    return subject.run(rows, strategy, fill_callback=callback or (lambda *_: []), finalize=finalize)


def test_capacity_is_shared_across_vertices_callbacks_brackets_and_closing_tick():
    subject = kernel()
    rows = numbered(*(replace(bar(begin=i * 60000), payload={**bar(begin=i * 60000).payload, "volume": "10"}) for i in range(3)))
    seen = []
    def callback(*_):
        seen.append(subject.account.position_qty)
        return [{"type": "LIMIT", "side": "SELL", "qty": "5", "limit_price": "108", "reduce_only": True}] if len(seen) == 1 else []
    result = run(subject, rows, quantity=7, callback=callback)
    assert [D(fill["qty"]) for fill in result.fills] == [5, 2, 3]
    assert seen == [5, 7, 4]
    assert subject._capacity_left == 0
    assert subject.orders[1].status == "PARTIAL" and subject.orders[1].qty == 2
    assert all(fill["synthetic_path"] and fill["source_event_kind"] == "SYNTHETIC_BAR_PATH" for fill in result.fills)


def test_mark_and_funding_are_applied_at_their_times_without_ohlc_overwriting_mark():
    subject = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", initial_balance=D(1000), leverage=D(10), funding_mode="HISTORICAL_REQUIRED")
    rows = numbered(rules(-2), mark(-1, 100), bar(100, 110, 90, 100), mark(70000, 200),
        MarketEvent(1, 80000, "FUNDING", {"funding_rate": ".01", "period_id": "actual"}),
        bar(100, 110, 90, 100, begin=60000))
    seen = []
    result = run(subject, rows, callback=lambda *_: seen.append(subject.account.mark) or [])
    assert seen == [100]  # The 70-second mark cannot leak into the open fill.
    assert subject.account.mark == 200
    assert subject.account.cumulative_funding == -4
    assert subject.account.equity() == 1196
    assert result.fills[0]["event_time_ms"] == 60000
    assert subject.account.position_qty == 2


@pytest.mark.parametrize("stamp,trigger", [(60000, "FILL"), (70000, "MARK_INDEX")])
def test_actual_margin_liquidation_has_distinct_callback_and_does_not_consume_capacity(stamp, trigger):
    subject = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", initial_balance=D(1000), leverage=D(10))
    rows = numbered(rules(-2), mark(-1, 100), bar(100, 110, 90, 100), mark(stamp, 80), bar(100, 110, 90, 100, begin=60000))
    seen = []
    result = run(subject, rows, quantity=50, callback=lambda *_: seen.append(subject.account.position_qty) or [])
    assert seen == [50, 0]
    assert len(result.fills) == 2
    assert result.fills[-1]["account_liquidation"]["trigger"] == trigger
    assert result.fills[-1]["event_time_ms"] == stamp
    if trigger == "MARK_INDEX":
        assert result.fills[-1]["triggering_event_kind"] == "MARK_INDEX"
        assert not result.fills[-1]["synthetic_path"]
    assert subject._capacity_left == 0
    assert subject.account.position_qty == 0
    curve_sequences = [row["sequence"] for row in result.equity_curve]
    assert curve_sequences == sorted(curve_sequences)
    restored = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", initial_balance=D(1000), leverage=D(10))
    restored.restore(deepcopy(subject.snapshot()))
    assert restored.result() == result


def test_complete_bar_restore_reproduces_source_path_capacity_and_account():
    rows = numbered(rules(-2), mark(-1, 100), bar(100, 110, 90, 100), mark(70000, 105),
        bar(100, 110, 90, 100, begin=60000))
    original = kernel(account_model="LINEAR_PERP_ONE_WAY_V2")
    expected = run(original, rows)
    interrupted = kernel(account_model="LINEAR_PERP_ONE_WAY_V2")
    run(interrupted, rows[:3])
    saved = deepcopy(interrupted.snapshot())
    restored = kernel(account_model="LINEAR_PERP_ONE_WAY_V2")
    restored.restore(saved)
    actual = run(restored, rows[3:])
    assert actual == expected
    assert restored.snapshot() == original.snapshot()
    with pytest.raises(MarketDatasetError, match="own matcher"):
        PineChartBarKernel().restore(saved)


def test_tail_account_settlement_and_undelivered_callback_survive_snapshot():
    subject = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", initial_balance=D(1000), leverage=D(10))
    rows = numbered(rules(-2), mark(-1, 100), bar(100, 110, 90, 100), bar(100, 110, 90, 100, begin=60000), mark(130000, 80))
    seen = []
    run(subject, rows, quantity=50, callback=lambda *_: seen.append(subject.account.position_qty) or [])
    assert seen == [50]
    assert subject.account.position_qty == 0 and len(subject._pending_callbacks) == 1
    saved = subject.snapshot()
    restored = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", initial_balance=D(1000), leverage=D(10))
    restored.restore(saved)
    callbacks = []
    restored.run([replace(bar(100, 110, 90, 100, begin=180000), sequence=6)], lambda *_: [],
        fill_callback=lambda *_: callbacks.append(restored.account.position_qty) or [])
    assert callbacks == [0] and restored._pending_callbacks == []
    assert len(restored.fills) == 2
    continuous = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", initial_balance=D(1000), leverage=D(10))
    future = replace(bar(100, 110, 90, 100, begin=180000), sequence=6)
    run(continuous, [*rows, future], quantity=50)
    assert restored.result() == continuous.result()
    assert restored.snapshot() == continuous.snapshot()


def test_simulated_close_does_not_reset_the_bar_capacity():
    subject = kernel(process_orders_on_close=True)
    values = numbered(replace(bar(), payload={**bar().payload, "volume": "10"}))
    callbacks = []
    run(subject, values, quantity=7, callback=lambda *_: callbacks.append(subject.account.position_qty) or [])
    assert [row.qty for row in subject.fills] == [5]
    assert subject.orders[0].qty == 2 and subject._capacity_left == 0
    assert callbacks == [5]


def test_participation_dust_is_not_filled_as_fractional_quantity_steps():
    subject = kernel(account_model="LINEAR_PERP_ONE_WAY_V2")
    small = replace(bar(100, 110, 90, 100, begin=60000), payload={**bar(100, 110, 90, 100, begin=60000).payload, "volume": ".015"})
    values = numbered(rules(-2), mark(-1, 100), bar(100, 110, 90, 100), small)
    run(subject, values, quantity=1)
    assert [row.qty for row in subject.fills] == [D(".007")]
    assert subject._capacity_left == D(".0005")
    assert subject.orders[0].qty == D(".993")


def test_v2_path_fee_and_margin_reservation_include_actual_contract_multiplier():
    subject = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", taker_fee_bps=D(10))
    source_rules = rules(-2)
    source_rules = replace(source_rules, payload={**source_rules.payload, "contract_multiplier": "5"})
    values = numbered(source_rules, mark(-1, 100), bar(100, 110, 90, 100), bar(100, 110, 90, 100, begin=60000))
    run(subject, values, quantity=2)
    assert subject.fills[0].fee == 1 and subject.account.cumulative_fees == 1
    assert subject.account.order_margins == {}
    reserved = [row for row in subject.account.ledger_entries if row["kind"] == "ORDER_MARGIN_RESERVED"]
    assert D(reserved[0]["details"]["amount"]) == 1000


def test_failed_bar_cannot_be_saved_and_must_restore_its_preceding_checkpoint():
    subject = kernel()
    values = numbered(bar(), bar(begin=60000))
    run(subject, values[:1])
    saved = deepcopy(subject.snapshot())
    def fail(*_):
        raise KeyboardInterrupt("controlled intrabar stop")
    with pytest.raises(KeyboardInterrupt):
        run(subject, values[1:], callback=fail)
    with pytest.raises(MarketDatasetError, match="complete Pine V2 bar"):
        subject.snapshot()
    subject.restore(saved)
    result = run(subject, values[1:])
    assert len(result.fills) == 1


def test_ioc_partial_fill_expires_its_remainder_and_releases_v2_margin():
    subject = kernel(account_model="LINEAR_PERP_ONE_WAY_V2")
    first = numbered(rules(-2), mark(-1, 100), bar(100, 110, 90, 100))
    subject.run(first, lambda *_: [{"type": "MARKET", "side": "BUY", "qty": "7", "tif": "IOC"}], fill_callback=lambda *_: [])
    small = replace(bar(100, 110, 90, 100, begin=60000), payload={**bar(100, 110, 90, 100, begin=60000).payload, "volume": "10"}, sequence=4)
    subject.run([small], lambda *_: [], fill_callback=lambda *_: [])
    assert subject.orders[0].status == "EXPIRED" and subject.orders[0].qty == 2
    assert subject.account.position_qty == 5
    assert subject.account.frozen_order_margin == 0


def test_tail_account_events_preserve_last_path_quote_instead_of_manufacturing_a_mark_quote():
    subject = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="HISTORICAL_REQUIRED")
    values = numbered(rules(-2), mark(-1, 10), bar(10, 11, 9, 10), bar(10, 11, 9, 10, begin=60000),
        mark(130000, 20), MarketEvent(1, 140000, "FUNDING", {"funding_rate": ".01", "period_id": "tail"}))
    quotes = []
    def observe(event):
        if event.event_time_ms >= 130000:
            quotes.append(D(event.payload["price"]))
    subject.market_observer = observe
    run(subject, values)
    assert quotes and set(quotes) == {D(10)}
    assert subject.account.mark == 20 and subject._last_path_price == 10
    saved = subject.snapshot()
    restored = kernel(account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="HISTORICAL_REQUIRED")
    restored.restore(saved)
    assert restored._last_path_price == 10 and restored.result() == subject.result()


def test_account_updates_cannot_revise_a_committed_bar_at_the_same_timestamp():
    subject = kernel(account_model="LINEAR_PERP_ONE_WAY_V2")
    values = numbered(rules(-2), mark(-1, 100), bar(100, 110, 90, 100), mark(59999, 105))
    with pytest.raises(MarketDatasetError, match="revise a committed Pine bar"):
        run(subject, values)
