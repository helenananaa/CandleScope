from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from app.replay.broker.execution import (
    BROKER_STATE_HASH_SCHEMA_VERSION,
    apply_position_fill,
)
from app.replay.broker.ledger import LedgerBook
from app.replay.broker.models import (
    LedgerAccount,
    LedgerKind,
    OrderSide,
    Position,
    decimal_to_string,
)
from app.replay.canonical import canonical_sha256
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from tests.fixtures.replay.broker_fakes import CONFIG, bar, make_broker, request


def test_one_way_position_add_reduce_full_close_and_reversal() -> None:
    position = Position.flat(mark_price="100")
    opened = apply_position_fill(position, OrderSide.BUY, "2", "100", "100")
    added = apply_position_fill(opened.position, OrderSide.BUY, "1", "103", "103")
    assert added.position.quantity == "3"
    assert added.position.entry_price == "101"

    reduced = apply_position_fill(added.position, OrderSide.SELL, "1", "104", "104")
    assert reduced.realized_pnl == "3"
    assert reduced.position.quantity == "2"
    assert reduced.position.entry_price == "101"

    reversed_fill = apply_position_fill(
        reduced.position,
        OrderSide.SELL,
        "3",
        "99",
        "99",
    )
    assert reversed_fill.realized_pnl == "-4"
    assert reversed_fill.position.quantity == "-1"
    assert reversed_fill.position.entry_price == "99"


def test_every_ledger_transaction_is_balanced_and_hash_restores_exactly() -> None:
    broker = make_broker()
    broker.place_order(request(client_order_id="entry"), command_id="cmd-entry")
    broker.apply_bar(bar(0, 100))
    broker.close_position(command_id="cmd-close")
    broker.apply_bar(bar(1, 105))

    LedgerBook.assert_entries_balanced(broker.ledger_entries)
    assert (
        sum((Decimal(entry.amount) for entry in broker.ledger_entries), Decimal(0)) == 0
    )
    assert (
        broker.account.cash_balance
        == (
            Decimal(CONFIG.initial_equity)
            + Decimal(broker.account.realized_pnl)
            - Decimal(broker.account.fees_paid)
        )
        .normalize()
        .to_eng_string()
    )

    snapshot = broker.snapshot()
    restored = make_broker()
    restored.restore(snapshot)
    assert restored.snapshot() == snapshot
    assert restored.ledger_entries == broker.ledger_entries
    assert restored.state_hash == broker.state_hash


def test_late_checkpoint_validation_failure_is_atomic_and_fail_closed() -> None:
    broker = make_broker()
    broker.place_order(request(client_order_id="entry"), command_id="cmd-entry")
    broker.apply_bar(bar(0, 100))
    before = broker.snapshot()

    tampered = deepcopy(before)
    tampered["next_order"] = 99
    unhashed = dict(tampered)
    unhashed.pop("state_hash")
    tampered["state_hash"] = canonical_sha256(
        {
            "schema_version": BROKER_STATE_HASH_SCHEMA_VERSION,
            "state": unhashed,
        }
    )

    with pytest.raises(ReplayDomainError) as rejected:
        broker.restore(tampered)
    assert rejected.value.code is ReplayErrorCode.DATASET_MISMATCH
    assert broker.snapshot() == before


def _scanned_account_total(ledger: LedgerBook, account: LedgerAccount) -> str:
    with localcontext() as context:
        context.prec = 60
        total = sum(
            (
                Decimal(entry.amount)
                for entry in ledger.entries
                if entry.account is account
            ),
            Decimal(0),
        )
    return decimal_to_string(total, field_name="ledger account total")


def test_incremental_account_totals_match_full_scan_after_post_clone_and_restore() -> None:
    broker = make_broker()
    ledger = broker._ledger
    for index in range(40):
        ledger.post(
            kind=LedgerKind.FEE,
            source_sequence=index + 1,
            event_time_ms=index + 1,
            postings=(
                (LedgerAccount.CASH, "-0.25"),
                (LedgerAccount.FEE_EXPENSE, "0.25"),
            ),
        )
        ledger.post(
            kind=LedgerKind.REALIZED_PNL,
            source_sequence=index + 1,
            event_time_ms=index + 1,
            postings=(
                (LedgerAccount.CASH, "1.5"),
                (LedgerAccount.REALIZED_PNL, "-1.5"),
            ),
        )
    for account in LedgerAccount:
        assert ledger.account_total(account) == _scanned_account_total(ledger, account)

    cloned = ledger.clone()
    for account in LedgerAccount:
        assert cloned.account_total(account) == ledger.account_total(account)
    cloned.post(
        kind=LedgerKind.FEE,
        source_sequence=100,
        event_time_ms=100,
        postings=(
            (LedgerAccount.CASH, "-3"),
            (LedgerAccount.FEE_EXPENSE, "3"),
        ),
    )
    assert cloned.account_total(LedgerAccount.CASH) != ledger.account_total(
        LedgerAccount.CASH
    )
    assert cloned.account_total(LedgerAccount.CASH) == _scanned_account_total(
        cloned, LedgerAccount.CASH
    )
    assert ledger.account_total(LedgerAccount.CASH) == _scanned_account_total(
        ledger, LedgerAccount.CASH
    )
    assert cloned._verified_through == len(cloned.entries)
    assert ledger._verified_through == len(ledger.entries)


    snapshot = ledger.snapshot()
    restored = make_broker()._ledger
    visits_before = LedgerBook.balance_sort_visits
    restored.restore(snapshot)
    assert LedgerBook.balance_sort_visits == visits_before + len(restored.entries)
    assert restored._verified_through == len(restored.entries)
    for account in LedgerAccount:
        assert restored.account_total(account) == ledger.account_total(account)
        assert restored.account_total(account) == _scanned_account_total(
            restored, account
        )


def test_assert_entries_balanced_counts_the_sorted_entries() -> None:
    broker = make_broker()
    entries = broker.ledger_entries
    before = LedgerBook.balance_sort_visits
    LedgerBook.assert_entries_balanced(entries)
    assert LedgerBook.balance_sort_visits == before + len(entries)


def test_clone_post_rolls_back_entries_totals_and_watermark_together() -> None:
    broker = make_broker()
    ledger = broker._ledger
    watermark = ledger._verified_through
    entry_count = len(ledger.entries)
    cash = ledger.account_total(LedgerAccount.CASH)
    cloned = ledger.clone()
    cloned.post(
        kind=LedgerKind.FEE,
        source_sequence=1,
        event_time_ms=1,
        postings=(
            (LedgerAccount.CASH, "-2"),
            (LedgerAccount.FEE_EXPENSE, "2"),
        ),
    )
    assert cloned._verified_through == watermark + 2
    assert len(cloned.entries) == entry_count + 2
    assert cloned.account_total(LedgerAccount.CASH) != cash
    assert ledger._verified_through == watermark
    assert len(ledger.entries) == entry_count
    assert ledger.account_total(LedgerAccount.CASH) == cash
    assert cloned.account_total(LedgerAccount.CASH) == _scanned_account_total(
        cloned, LedgerAccount.CASH
    )


def test_failed_ledger_restore_does_not_change_totals_or_entries() -> None:
    broker = make_broker()
    ledger = broker._ledger
    before_entries = len(ledger.entries)
    cash = ledger.account_total(LedgerAccount.CASH)
    cloned = ledger.clone()
    cloned.post(
        kind=LedgerKind.FEE,
        source_sequence=1,
        event_time_ms=1,
        postings=(
            (LedgerAccount.CASH, "-1"),
            (LedgerAccount.FEE_EXPENSE, "1"),
        ),
    )
    payload = cloned.snapshot()
    payload["tail_hash"] = "sha256:" + "0" * 64
    payload["state_hash"] = canonical_sha256({key: value for key, value in payload.items() if key != "state_hash"})
    with pytest.raises(ReplayDomainError):
        ledger.restore(payload)
    assert len(ledger.entries) == before_entries
    assert ledger.account_total(LedgerAccount.CASH) == cash
