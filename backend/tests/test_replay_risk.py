from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.replay.broker.models import (
    BrokerConfig,
    OrderCapacityRequest,
    OrderSide,
    OrderType,
    OrderRequest,
    PositionMode,
    PositionSide,
    TOUCH_OR_TAPE_EXECUTION_MODE,
    PAPER_LINEAR_EXECUTION_MODE,
)
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from tests.fixtures.replay.broker_fakes import CONFIG, bar, make_broker, request


def _limited(**changes) -> BrokerConfig:
    return replace(CONFIG, limits=replace(CONFIG.limits, **changes))


@pytest.mark.parametrize(
    ("request_kwargs", "limit_changes"),
    [
        ({"quantity": "10.001"}, {}),
        ({"quantity": "2"}, {"max_position_notional": "150"}),
        ({"quantity": "10"}, {"max_leverage": "0.05"}),
    ],
)
def test_order_quantity_position_notional_and_available_equity_fail_closed(
    request_kwargs,
    limit_changes,
) -> None:
    broker = make_broker(config=_limited(**limit_changes))
    before = broker.state_hash
    with pytest.raises(ReplayDomainError) as rejected:
        broker.place_order(
            request(client_order_id="risk", **request_kwargs),
            command_id="cmd-risk",
        )
    assert rejected.value.code is ReplayErrorCode.RISK_LIMIT_EXCEEDED
    assert broker.state_hash == before


def test_open_order_reservations_are_bounded_and_released_on_fill() -> None:
    broker = make_broker()
    order = broker.place_order(
        request(
            client_order_id="reserved",
            order_type=OrderType.LIMIT,
            quantity="2",
            limit_price="95",
        ),
        command_id="cmd-reserved",
    )
    assert order.reserved_margin == "38.076"
    assert broker.account.available_equity == "9961.924"

    broker.apply_bar(bar(0, 94))
    assert broker.account.reserved_margin == "0"
    assert broker.account.margin_used == "38"


def test_trigger_time_gap_cannot_bypass_hard_position_notional_limit() -> None:
    broker = make_broker(config=_limited(max_position_notional="150"))
    order = broker.place_order(
        request(client_order_id="market", quantity="1"),
        command_id="cmd-market",
    )
    result = broker.apply_bar(bar(0, 200))
    assert result.fills == ()
    assert broker.order(order.order_id).status.value == "REJECTED"
    assert broker.position.quantity == "0"


@pytest.mark.parametrize("mode", [PositionMode.ONE_WAY, PositionMode.HEDGE])
@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
def test_full_capacity_includes_fees_and_adverse_execution(mode, side):
    config = replace(CONFIG, initial_equity="100", initial_mark_price="109.67", position_mode=mode,
                     taker_bps="5", instrument=replace(CONFIG.instrument, price_tick="0.000001", quantity_step="0.00000001"),
                     limits=replace(CONFIG.limits, max_leverage="100", max_order_quantity="100"))
    broker = make_broker(config=config, execution_mode=TOUCH_OR_TAPE_EXECUTION_MODE if mode is PositionMode.HEDGE else PAPER_LINEAR_EXECUTION_MODE)
    leg = None if mode is PositionMode.ONE_WAY else (PositionSide.LONG if side is OrderSide.BUY else PositionSide.SHORT)
    context = OrderCapacityRequest(side=side, order_type=OrderType.MARKET, reduce_only=False, position_side=leg)
    maximum = broker.order_capacity(context)["max_quantity"]
    assert Decimal(maximum) < Decimal("91.18263882")
    order = OrderRequest(client_order_id="maximum", side=side, order_type=OrderType.MARKET,
                         quantity=maximum, reduce_only=False, limit_price=None, stop_price=None, position_side=leg)
    broker.place_order(order, command_id="maximum")
    assert Decimal(broker.account.available_equity) >= 0
    broker.apply_bar(replace(bar(0, "109.67"), open="109.67", high="109.67", low="109.67", close="109.67"))
    assert len(broker.fills) == 1
    assert Decimal(broker.account.available_equity) >= 0
    assert Decimal(broker.account.fees_paid) > 0


def test_direct_order_cannot_spend_fee_and_slippage_budget_as_margin():
    config = replace(CONFIG, initial_equity="100", limits=replace(CONFIG.limits, max_leverage="10"))
    broker = make_broker(config=config)
    with pytest.raises(ReplayDomainError, match="available equity"):
        broker.place_order(request(client_order_id="over-budget", quantity="10"), command_id="over-budget")
    assert not broker.orders


def test_later_gap_rechecks_cash_after_margin_and_fee_before_filling():
    config = replace(CONFIG, initial_equity="100", limits=replace(CONFIG.limits, max_leverage="10"))
    broker = make_broker(config=config)
    quantity = broker.order_capacity(OrderCapacityRequest(side=OrderSide.BUY, order_type=OrderType.MARKET, reduce_only=False))["max_quantity"]
    order = broker.place_order(request(client_order_id="gap-budget", quantity=quantity), command_id="gap-budget")
    broker.apply_bar(bar(0, 200))
    assert not broker.fills
    assert broker.order(order.order_id).status.value == "REJECTED"
    assert broker.account.available_equity == "100"


def test_reduce_only_can_close_position_below_minimum_notional() -> None:
    broker = make_broker()
    broker.place_order(
        request(client_order_id="dust-entry", quantity="0.05"),
        command_id="cmd-dust-entry",
    )
    broker.apply_bar(bar(0, 101))
    broker.apply_bar(bar(1, 81))

    assert broker.position.quantity == "0.05"
    assert broker.position.notional == "4.1"
    assert broker.order_capacity(
        OrderCapacityRequest(
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            reduce_only=True,
        )
    )["max_quantity"] == "0.05"

    order = broker.close_position(command_id="cmd-dust-close")
    assert order.reduce_only is True
    broker.apply_bar(bar(2, 81))
    assert broker.position.quantity == "0"
