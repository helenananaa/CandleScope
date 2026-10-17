import random
from dataclasses import replace

import pytest
from app.replay import trade_summary
from app.replay.broker.models import (
    TOUCH_OR_TAPE_EXECUTION_MODE,
    OrderSide,
    PositionMode,
    PositionSide,
)

from tests.fixtures.replay.broker_fakes import request
from tests.test_replay_execution_tape import _broker, _trade


@pytest.mark.parametrize("side", [None, OrderSide.BUY, OrderSide.SELL])
@pytest.mark.parametrize("seed", range(4))
def test_summary_matches_scalar_full_checkpoint_and_avoids_reducers(
    side, seed, monkeypatch
):
    scalar, summary = _broker(minutes=10), _broker(minutes=10)
    for broker in (scalar, summary):
        if side:
            broker.place_order(
                request(client_order_id="position", side=side), command_id="open"
            )
        broker.apply_trade(_trade(0))
    rng = random.Random(seed)
    trades = [
        replace(
            _trade(
                i,
                price=str(rng.randrange(70, 130)),
                quantity="0.125",
                time_offset_ms=(i // 25) * (120000 if seed == 3 else 60000) + 1000,
            ),
            is_buyer_maker=bool(i % 2),
            last_trade_id=10000 + i + i % 3,
        )
        for i in range(1, 100)
    ]
    for trade in trades:
        scalar.apply_source_event(trade)

    def forbidden(*args, **kwargs):
        raise AssertionError("summary called a per-trade reducer")

    monkeypatch.setattr(summary, "apply_source_event", forbidden)
    monkeypatch.setattr(summary, "apply_source_events_final_state", forbidden)
    account_calls = []
    account_from = summary._account_from

    def count_accounts(*args):
        account_calls.append(1)
        return account_from(*args)

    monkeypatch.setattr(summary, "_account_from", count_accounts)
    # Split inside a forming candle, then span several candle boundaries.
    assert trade_summary.apply(summary, trades[:7])
    assert trade_summary.apply(summary, trades[7:])
    assert len(account_calls) == 2
    assert summary.snapshot() == scalar.snapshot()


def test_unusual_precision_uses_exact_fallback():
    scalar, summary = _broker(), _broker()
    trades = [_trade(i, price="100.0000000000001") for i in range(4)]
    for trade in trades:
        scalar.apply_source_event(trade)
    assert trade_summary.apply(summary, trades) is False
    assert summary.snapshot() == scalar.snapshot()


def test_market_summary_cache_is_bounded_and_shared_without_accounts():
    trade_summary._CACHE.clear()
    broker = _broker()
    trades = [_trade(i) for i in range(4)]
    first = trade_summary.prepare(trades, broker._bar_builder)
    assert trade_summary.prepare(trades, _broker()._bar_builder) is first
    for i in range(20):
        trade_summary.prepare([_trade(i, price=str(100 + i))], broker._bar_builder)
    assert len(trade_summary._CACHE) == trade_summary.CACHE_BLOCKS


@pytest.mark.parametrize("quantities", [("1", "0"), ("0", "2"), ("1", "1"), ("1", "2")])
def test_hedge_summary_preserves_two_entries_and_gross_legs(quantities):
    brokers = [_broker(minutes=10), _broker(minutes=10)]
    for broker in brokers:
        config = replace(broker.config, position_mode=PositionMode.HEDGE)
        broker.__init__(config=config, bar_builder=broker._bar_builder, execution_mode=TOUCH_OR_TAPE_EXECUTION_MODE)
        for i, (quantity, side, leg) in enumerate(zip(
            quantities, (OrderSide.BUY, OrderSide.SELL), (PositionSide.LONG, PositionSide.SHORT), strict=True
        )):
            if quantity != "0":
                broker.place_order(replace(request(client_order_id=str(i), side=side, quantity=quantity),
                                           position_side=leg), command_id=str(i))
            broker.apply_trade(_trade(i, price=str(100 + i * 10), quantity="10"))
    scalar, summary = brokers
    trades = [_trade(i, price=str(90 + (i * 17) % 45), time_offset_ms=i * 1000)
              for i in range(2, 100)]
    for trade in trades:
        scalar.apply_source_event(trade)
    assert trade_summary.apply(summary, trades)
    assert summary.snapshot() == scalar.snapshot()
