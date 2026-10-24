from decimal import Decimal as D
from copy import deepcopy

import pytest

from app.market_dataset.snapshot import MarketEvent, MarketDatasetError
from app.simulation.account_execution import publish_account_liquidation
from app.simulation.book_kernel import BookAssistedKernel
from app.simulation.depth_kernel import DepthQueueKernel
from app.simulation.sampled_book_kernel import SampledBookKernel
from app.simulation.kernel import SimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from app.simulation.execution_realism import EXECUTION_REALISM_V2, BAR_PATH_SCENARIO
from app.simulation.v2_margin import reprice, REASON
from tests.test_backtest_account_v2_m4 import ready


def test_mark_initial_margin_shortfall_is_not_a_maintenance_liquidation():
    account = ready(balance="100", leverage="10")
    account.apply_fill(side="BUY", price=D(100), qty=D(9))
    account.apply(
        MarketEvent(1, 1, "MARK_INDEX", {"mark_price": "98", "index_price": "98"})
    )
    assert account.equity() == 82 and account.available_balance() == D("-6.2")
    assert account.liquidation_state == "ACTIVE" and account.position_qty == 9
    saved = deepcopy(account.snapshot())
    restored = ready()
    restored.restore(saved)
    assert restored.snapshot() == saved
    account.reserve_order_margin(order_id="close", qty=D(0), estimated_fee=D(1))
    account.apply_fill(side="SELL", price=D(98), qty=D(9), fee=D(1), order_id="close")
    assert account.position_qty == 0 and account.quote_balance == 81


@pytest.mark.parametrize("kind", [SimulationKernel, TradeSimulationKernel])
def test_market_orders_reserve_independent_directional_opening_quantities(kind):
    subject = kind(account_model="LINEAR_PERP_ONE_WAY_V2")
    subject.account = ready()
    subject._enqueue({"side": "BUY", "type": "MARKET", "qty": "10"}, current_sequence=0)
    subject._enqueue(
        {"side": "SELL", "type": "MARKET", "qty": "10"}, current_sequence=0
    )
    assert subject.account.order_margins == {"ord-1": D(100), "ord-2": D(100)}


def subject(kind=SimulationKernel, *, balance="1000", funding_mode="OFF", **extra):
    value = kind(
        account_model="LINEAR_PERP_ONE_WAY_V2",
        execution_model_revision=EXECUTION_REALISM_V2,
        participation_rate=D(1),
        **(
            {"bar_path_scenario": BAR_PATH_SCENARIO} if kind is SimulationKernel else {}
        ),
        **extra,
    )
    value.account = ready(balance=balance, funding_mode=funding_mode)
    return value


def enqueue(value, side="BUY", quantity="10", **extra):
    value._enqueue(
        {"side": side, "type": "MARKET", "qty": quantity, **extra}, current_sequence=0
    )
    return value.orders[-1]


@pytest.mark.parametrize("kind", [SimulationKernel, TradeSimulationKernel])
def test_reprice_keeps_fifo_priority_and_does_not_repeat_ledger_entries(kind):
    value = subject(kind, balance="250")
    first, second = enqueue(value), enqueue(value)
    event = MarketEvent(
        1, 5000, "MARK_INDEX", {"mark_price": "150", "index_price": "150"}
    )
    value._last_event = event
    value.account.apply(event)
    publish_account_liquidation(value)
    assert [first.status, second.status] == ["OPEN", "CANCELLED"]
    assert value.account.order_margins == {first.order_id: D(150)}
    assert value.account.frozen_order_margin == 150
    rejected = [
        row
        for row in value.account.ledger_entries
        if row["kind"] == "ORDER_MARGIN_REPRICE_REJECTED"
    ]
    assert len(rejected) == 1 and rejected[0]["details"]["order_id"] == second.order_id
    assert value._order_events[-1]["reason"] == REASON
    assert value._order_events[-1]["event_time_ms"] == 5000
    assert value.fills == []
    saved = deepcopy(value.snapshot())
    reprice(value)
    assert value.snapshot() == saved
    restored = subject(kind, balance="250")
    restored.restore(saved)
    assert restored.snapshot() == saved


@pytest.mark.parametrize("kind", [SimulationKernel, TradeSimulationKernel])
def test_repricing_preserves_reduce_only_close_when_initial_collateral_is_negative(
    kind,
):
    value = subject(kind, balance="100")
    value.account.apply_fill(side="BUY", price=D(100), qty=D(9))
    opening = enqueue(value, quantity=".1")
    closing = enqueue(value, side="SELL", quantity="9", reduce_only=True)
    event = MarketEvent(
        1, 1000, "MARK_INDEX", {"mark_price": "98", "index_price": "98"}
    )
    value._last_event = event
    value.account.apply(event)
    publish_account_liquidation(value)
    assert opening.status == "CANCELLED" and closing.status == "OPEN"
    assert value.account.position_qty == 9 and value.account.available_balance() == D(
        "-6.2"
    )
    assert value.account.liquidation_state == "ACTIVE" and not value.fills
    value.account.apply_fill(
        side="SELL", price=D(98), qty=D(9), order_id=closing.order_id
    )
    assert value.account.quote_balance == 82 and value.account.position_qty == 0


@pytest.mark.parametrize("kind", [SimulationKernel, TradeSimulationKernel])
def test_closing_allowance_is_consumed_by_prior_reduce_only_orders(kind):
    value = subject(kind)
    value.account.apply_fill(side="BUY", price=D(100), qty=D(5))
    first = enqueue(value, side="SELL", quantity="5", reduce_only=True)
    second = enqueue(value, side="SELL", quantity="6")
    assert value.account.order_margins == {first.order_id: D(0), second.order_id: D(60)}


def test_funding_cancels_unfunded_working_exposure_without_a_trading_fill():
    value = subject(funding_mode="HISTORICAL_REQUIRED")
    value.account.apply_fill(side="BUY", price=D(100), qty=D(5))
    order = enqueue(value, quantity="80")
    event = MarketEvent(1, 7000, "FUNDING", {"funding_rate": "1", "period_id": "one"})
    value._last_event = event
    value.account.apply(event)
    publish_account_liquidation(value)
    assert order.status == "CANCELLED" and value.account.frozen_order_margin == 0
    assert value.account.position_qty == 5 and value.account.equity() == 500
    assert value.account.liquidation_state == "ACTIVE" and value.fills == []


def test_working_order_fee_estimates_share_the_same_fifo_collateral_budget():
    value = subject(balance="200.15", taker_fee_bps=D(1))
    first, second = enqueue(value), enqueue(value)
    reprice(value)
    assert [first.status, second.status] == ["OPEN", "CANCELLED"]
    assert value.account.order_margins == {first.order_id: D(100)}
    assert value.account.cumulative_fees == 0 and not value.fills


@pytest.mark.parametrize("kind", [BookAssistedKernel, DepthQueueKernel])
def test_invalid_book_cannot_cancel_orders_before_validation(kind):
    value = subject(kind, balance="150")
    order = enqueue(value)
    payload = (
        {"bid": "200", "ask": "199"}
        if kind is BookAssistedKernel
        else {
            "book_sequence": 1,
            "snapshot": True,
            "depth_complete": True,
            "bids": [["200", "10"]],
            "asks": [["199", "10"]],
        }
    )
    before = deepcopy(value.account.snapshot())
    with pytest.raises(MarketDatasetError):
        value._match(MarketEvent(1, 1000, "ORDER_BOOK", payload))
    assert order.status == "OPEN" and value.account.snapshot() == before


@pytest.mark.parametrize(
    "kind", [BookAssistedKernel, DepthQueueKernel, SampledBookKernel]
)
def test_validated_visible_book_reprices_orders_before_a_later_print(kind):
    value = subject(kind, balance="150")
    order = enqueue(value)
    if kind is BookAssistedKernel:
        payload = {"bid": "199", "ask": "200"}
    else:
        payload = {
            "book_sequence": 1,
            "snapshot": True,
            "depth_complete": True,
            "bids": [["199", "100"]],
            "asks": [["200", "100"]],
        }
        if kind is SampledBookKernel:
            payload.pop("book_sequence")
            payload.update(
                sample_index=1,
                sample_time_ms=1000,
                depth_complete=False,
                depth_scope="BOUNDED_SAMPLED",
            )
    event = MarketEvent(1, 1000, "ORDER_BOOK", payload)
    value._last_event = event
    value._match(event)
    assert order.status == "CANCELLED" and value.fills == []
    assert value.account.order_margins == {} and value.account.position_qty == 0


def test_reversal_rejection_is_atomic_instead_of_becoming_an_unrequested_close():
    value = subject(balance="100")
    value.account.apply_fill(side="BUY", price=D(100), qty=D(5))
    order = enqueue(value, side="SELL", quantity="10")
    event = MarketEvent(1, 1000, "BARS", {"price": "200"})
    value._last_event = event
    reprice(value, event)
    assert order.status == "CANCELLED" and order.qty == 10
    assert value.account.position_qty == 5 and not value.fills
    assert value.account.frozen_order_margin == 0


def test_account_only_v2_retains_repricing_rejection_evidence_without_v2_execution_trace():
    value = SimulationKernel(account_model="LINEAR_PERP_ONE_WAY_V2")
    value.account = ready(balance="100")
    enqueue(value)
    event = MarketEvent(1, 1000, "BARS", {"price": "200"})
    value._last_event = event
    reprice(value, event)
    assert value._order_events == []
    rejected = [
        row
        for row in value.account.ledger_entries
        if row["kind"] == "ORDER_MARGIN_REPRICE_REJECTED"
    ]
    assert len(rejected) == 1 and rejected[0]["event_time_ms"] == 1000
    assert rejected[0]["details"]["policy"] == value.account.snapshot()["margin_policy"]


@pytest.mark.parametrize("kind", [SimulationKernel, TradeSimulationKernel])
def test_actual_fill_fees_include_contract_multiplier_once(kind):
    value = subject(kind, taker_fee_bps=D(10), slippage_bps=D(0))
    value.account.multiplier = D(5)
    enqueue(value, quantity="2")
    event = MarketEvent(
        1,
        1000,
        "BARS" if kind is SimulationKernel else "TRADES",
        {
            "open": "100",
            "high": "100",
            "low": "100",
            "close": "100",
            "volume": "100",
            "price": "100",
            "qty": "100",
        },
    )
    value._last_event = event
    value._match(event)
    assert len(value.fills) == 1 and value.fills[0].fee == 1
    assert value.account.cumulative_fees == 1


def test_account_default_fee_uses_multiplier_and_allows_solvent_negative_wallet_to_close():
    account = ready(balance="100")
    account.multiplier = D(5)
    account.taker_fee_bps = D(10)
    account.apply_fill(side="BUY", price=D(100), qty=D(1))
    assert account.cumulative_fees == D(".5")
    account.apply(
        MarketEvent(1, 1, "MARK_INDEX", {"mark_price": "200", "index_price": "200"})
    )
    account.compensate(amount=D(-110), reason="recorded debit", event_time_ms=2)
    assert (
        account.wallet_balance() < 0 and account.equity() > account.maintenance_margin()
    )
    account.apply_fill(side="SELL", price=D(200), qty=D(1))
    assert account.position_qty == 0 and account.insolvency_state == "SOLVENT"


def test_fee_induced_flat_insolvency_has_no_manufactured_liquidation_fill():
    account = ready(balance="100")
    account.apply_fill(side="BUY", price=D(100), qty=D(1))
    account.apply_fill(side="SELL", price=D(100), qty=D(1), fee=D(101))
    assert account.quote_balance == -1 and account.insolvency_state == "INSOLVENT"
    assert account.liquidation_state == "ACTIVE" and account.liquidation_event is None
    restored = ready()
    restored.restore(account.snapshot())
    with pytest.raises(MarketDatasetError, match="insolvent"):
        restored.reserve_order_margin(order_id="new", qty=D(1))
    changed = deepcopy(account.snapshot())
    changed["margin_policy"] = "unknown"
    with pytest.raises(MarketDatasetError, match="margin policy"):
        restored.restore(changed)


@pytest.mark.parametrize(
    "amount,price", [("-1", "100"), ("NaN", "100"), ("1", "Infinity"), ("1", "0")]
)
def test_repricing_rejects_invalid_money_without_mutating_ledger(amount, price):
    account = ready()
    saved = deepcopy(account.snapshot())
    with pytest.raises(MarketDatasetError, match="repricing"):
        account.reprice_order_margin(
            "order", D(amount), event_time_ms=0, reference_price=D(price)
        )
    assert account.snapshot() == saved


@pytest.mark.parametrize("kind", [SimulationKernel, TradeSimulationKernel])
def test_same_direction_market_orders_do_not_reserve_the_whole_batch_twice(kind):
    subject = kind(account_model="LINEAR_PERP_ONE_WAY_V2")
    subject.account = ready()
    for _ in range(2):
        subject._enqueue(
            {"side": "BUY", "type": "MARKET", "qty": "10"}, current_sequence=0
        )
    assert subject.account.order_margins == {"ord-1": D(100), "ord-2": D(100)}
