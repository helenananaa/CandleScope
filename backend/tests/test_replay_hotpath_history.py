from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext

from app.replay.broker.ledger import LedgerBook
from app.replay.broker.models import (
    LedgerAccount,
    OrderSide,
    OrderType,
    decimal_to_string,
)
from tests.fixtures.replay.broker_fakes import CONFIG, LIMITS, bar, make_broker, request


def _history_broker():
    limits = replace(
        LIMITS,
        max_orders=20_000,
        max_fills=20_000,
        max_ledger_entries=80_000,
        max_warnings=20_000,
        max_position_notional="500000",
    )
    config = replace(CONFIG, limits=limits, initial_equity="100000")
    return make_broker(config=config)


def _seed_live_book(round_trips: int):
    broker = _history_broker()
    index = 0
    broker.place_order(request(client_order_id="entry"), command_id="cmd-entry")
    broker.apply_bar(bar(index, 100))
    index += 1
    for trip in range(round_trips):
        broker.place_order(
            request(client_order_id=f"s{trip}", side=OrderSide.SELL),
            command_id=f"cs{trip}",
        )
        broker.apply_bar(bar(index, 100))
        index += 1
        broker.place_order(
            request(client_order_id=f"b{trip}"),
            command_id=f"cb{trip}",
        )
        broker.apply_bar(bar(index, 100))
        index += 1
    broker.place_order(
        request(
            client_order_id="rest",
            order_type=OrderType.LIMIT,
            limit_price="90",
        ),
        command_id="cmd-rest",
    )
    return broker, index


def _scanned_cash(broker) -> str:
    with localcontext() as context:
        context.prec = 60
        total = sum(
            (
                Decimal(entry.amount)
                for entry in broker.ledger_entries
                if entry.account is LedgerAccount.CASH
            ),
            Decimal(0),
        )
    return decimal_to_string(total, field_name="cash")


def test_mark_only_apply_does_not_rescan_historical_ledger_entries() -> None:
    long_history, index = _seed_live_book(80)
    assert len(long_history.open_orders) == 1
    assert long_history.position.quantity == "1"
    visits = LedgerBook.balance_sort_visits
    posting_visits = long_history._ledger.posting_balance_visits
    long_history.apply_bar(bar(index, 101))
    assert LedgerBook.balance_sort_visits == visits
    assert long_history._ledger.posting_balance_visits == posting_visits
    assert long_history.position.quantity == "1"
    assert long_history.account.cash_balance == _scanned_cash(long_history)
    LedgerBook.assert_entries_balanced(long_history.ledger_entries)
    assert LedgerBook.balance_sort_visits == visits + len(long_history.ledger_entries)


def test_same_live_book_history_length_does_not_increase_apply_or_snapshot_work() -> None:
    work = []
    for trips in (0, 20, 200):
        broker, index = _seed_live_book(trips)
        assert len(broker.open_orders) == 1
        assert broker.position.quantity == "1"
        broker.snapshot()
        visits = LedgerBook.balance_sort_visits
        fill_encodes = broker._snapshot_component_encodes["fills"]
        ledger_encodes = broker._snapshot_component_encodes["ledger"]
        entry_encodes = broker._ledger.entry_encodes
        before = {
            "fills": tuple(fill.to_dict() for fill in broker.fills),
            "cash": broker.account.cash_balance,
            "position": broker.position.to_dict(),
            "equity": broker.account.equity,
        }
        broker.apply_bar(bar(index, 101))
        after = broker.snapshot()
        work.append(
            {
                "fills": len(broker.fills),
                "historical_visits": LedgerBook.balance_sort_visits - visits,
                "fill_encodes": broker._snapshot_component_encodes["fills"]
                - fill_encodes,
                "ledger_encodes": broker._snapshot_component_encodes["ledger"]
                - ledger_encodes,
                "entry_encodes": broker._ledger.entry_encodes - entry_encodes,
            }
        )
        assert broker.fills[-1].to_dict() == before["fills"][-1]
        assert len(broker.fills) == len(before["fills"])
        assert broker.account.cash_balance == before["cash"]
        assert broker.position.quantity == before["position"]["quantity"]
        assert Decimal(broker.account.equity) != Decimal("0")
        restored = _history_broker()
        restored.restore(after)
        assert restored.account.cash_balance == broker.account.cash_balance
        assert restored.position.to_dict() == broker.position.to_dict()
        assert restored.fills == broker.fills
        assert restored._ledger.tail_hash == broker._ledger.tail_hash
        assert restored.account.equity == broker.account.equity
    assert [item["historical_visits"] for item in work] == [0, 0, 0]
    assert [item["fill_encodes"] for item in work] == [0, 0, 0]
    assert [item["ledger_encodes"] for item in work] == [0, 0, 0]
    assert [item["entry_encodes"] for item in work] == [0, 0, 0]
    assert work[0]["fills"] < work[1]["fills"] < work[2]["fills"]


def test_new_fill_reencodes_fill_and_ledger_components() -> None:
    broker, index = _seed_live_book(20)
    broker.snapshot()
    fills = broker._snapshot_component_encodes["fills"]
    ledger = broker._snapshot_component_encodes["ledger"]
    broker.place_order(request(client_order_id="exit", side=OrderSide.SELL), command_id="cmd-exit")
    result = broker.apply_bar(bar(index, 101))
    assert result.fills
    broker.snapshot()
    assert broker._snapshot_component_encodes["fills"] == fills + 1
    assert broker._snapshot_component_encodes["ledger"] == ledger + 1
    assert broker.account.cash_balance == _scanned_cash(broker)
    restored = _history_broker()
    restored.restore(broker.snapshot())
    assert restored.fills == broker.fills
    assert restored.account.cash_balance == broker.account.cash_balance
    assert restored.position.to_dict() == broker.position.to_dict()


def test_mutating_nested_public_snapshot_does_not_poison_encoding_cache():
    from copy import deepcopy
    broker, _ = _seed_live_book(0)
    exposed = broker.snapshot()
    expected = deepcopy(exposed)
    exposed["orders"][0]["status_history"].append("INVALID")
    exposed["ledger"]["entries"][0]["amount"] = "-1"
    assert broker.snapshot() == expected
    restored = _history_broker()
    restored.restore(broker.snapshot())
    assert restored.snapshot() == expected
