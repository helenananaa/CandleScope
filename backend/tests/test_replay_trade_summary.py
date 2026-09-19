from dataclasses import replace
import random

import pytest

from app.replay import trade_summary
from app.replay.broker.models import OrderSide
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
