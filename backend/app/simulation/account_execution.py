"""Execution receipts for settlements already booked by the V2 account.

These receipts consume neither market capacity nor cash a second time. The
ledger entry is the authority; kernel orders only give downstream allocators a
stable execution identity and an auditable close of their actual owned lots.
"""
from copy import deepcopy
from decimal import Decimal

from app.market_dataset.snapshot import MarketDatasetError
from .linear_perp_account_v2 import LinearPerpetualAccountV2
from .execution_realism import EXECUTION_REALISM_V2

CONTRACT = "candlescope.account-liquidation-execution/1"
REASON = "ACCOUNT_LIQUIDATION"


def publish_account_liquidation(kernel):
    account = kernel.account
    from .v2_margin import reprice
    reprice(kernel)
    if not isinstance(account, LinearPerpetualAccountV2) or account.liquidation_event is None:
        return
    if kernel._account_execution_receipts:
        return  # This account's liquidation is terminal; no history scan per later tick.
    entries = [row for row in account.ledger_entries if row["kind"] == "LIQUIDATION"]
    if len(entries) != 1 or entries[0]["details"] != account.liquidation_event:
        raise MarketDatasetError("invalid account liquidation ledger", code="LEDGER_IMBALANCE")
    entry = entries[0]
    if any(row["ledger_entry_hash"] == entry["entry_hash"] for row in kernel._account_execution_receipts.values()):
        return
    if kernel._last_event is None or account.position_qty != 0:
        raise MarketDatasetError("liquidation needs its causal account event", code="LEDGER_IMBALANCE")
    from .kernel import SimulatedFill, SimulatedOrder
    event = kernel._last_event
    detail = entry["details"]
    before = Decimal(detail["position_qty_before"])
    price = Decimal(detail["price"])
    side = "SELL" if before > 0 else "BUY"
    # Account liquidation is terminal. Account._liquidate already released all
    # reservations, so cancellation must not debit or reserve anything again.
    working = kernel._live_orders() if hasattr(kernel, "_live_orders") else kernel._working_orders()
    for pending in tuple(working):
        if pending.status in {"OPEN", "PARTIAL"}:
            pending.status = "CANCELLED"
            kernel._active_orders.pop(pending.order_id, None)
            kernel._lifecycle(pending, "CANCELLED", reason=REASON)
    order_id = f"ord-{kernel._next_order_id}"
    kernel._next_order_id += 1
    order = SimulatedOrder(order_id, side, "MARKET", Decimal(0), event.sequence,
        status="FILLED", fill_price=price, fill_sequence=event.sequence, reduce_only=True)
    fill = SimulatedFill(order_id, event.sequence, entry["event_time_ms"], side,
        price, abs(before), Decimal(0), REASON, "CLOSE", before, Decimal(0))
    receipt = {"contract": CONTRACT, "ledger_entry_hash": entry["entry_hash"],
        "ledger_ordinal": entry["ordinal"], **deepcopy(detail)}
    kernel.orders.append(order)
    kernel.fills.append(fill)
    kernel._account_execution_receipts[order_id] = receipt
    if kernel.execution_model_revision == EXECUTION_REALISM_V2:
        kernel._fill_source_events.append(event)
        kernel._lifecycle(order, "FILLED", reason=REASON, fill_qty=abs(before))
    # A terminal account event can be the last input, or fall between sampled
    # trades. Keep its actual loss visible to equity/drawdown reports as well.
    sequence = ((kernel._market_event_count or event.sequence)
        if event.role in {"BARS", "TRADES"} else event.sequence)
    sequence_policy = getattr(kernel, "_account_curve_sequence", None)
    if sequence_policy is not None:
        sequence = sequence_policy(event)
    kernel._record_equity_point({"sequence": sequence, "event_time_ms": event.event_time_ms,
        "equity": str(account.equity()), "position_qty": str(account.position_qty),
        "wallet_balance": str(account.quote_balance), "available_balance": str(account.available_balance())})
    if kernel.execution_reporter is not None:
        kernel.execution_reporter({"accepted": True, "order_id": order_id,
            "order": kernel._record_encoder(order), "fill": kernel._record_encoder(fill),
            "account_liquidation": deepcopy(receipt)})


def enrich_account_executions(kernel, fills):
    for fill in fills:
        receipt = kernel._account_execution_receipts.get(fill["order_id"])
        if receipt is not None:
            fill["account_liquidation"] = deepcopy(receipt)
            if "source_event_kind" in fill:
                fill["triggering_event_kind"] = fill["source_event_kind"]
            fill["source_event_kind"] = REASON


def restore_account_executions(kernel, payload):
    receipts = deepcopy(dict(payload.get("account_execution_receipts") or {}))
    actual = {fill.order_id: fill for fill in kernel.fills if fill.reason == REASON}
    if actual.keys() != receipts.keys():
        raise MarketDatasetError("liquidation receipt/fill checkpoint differs", code="CHECKPOINT_CORRUPT")
    entries = {row["entry_hash"]: row for row in getattr(kernel.account, "ledger_entries", [])
        if row["kind"] == "LIQUIDATION"}
    if len(entries) != len(receipts):
        raise MarketDatasetError("liquidation ledger receipt missing", code="CHECKPOINT_CORRUPT")
    for order_id, receipt in receipts.items():
        entry = entries.get(receipt.get("ledger_entry_hash"))
        fill = actual[order_id]
        orders = [order for order in kernel.orders if order.order_id == order_id]
        if (entry is None or receipt != {"contract": CONTRACT, "ledger_entry_hash": entry["entry_hash"],
                "ledger_ordinal": entry["ordinal"], **entry["details"]}
                or fill.event_time_ms != entry["event_time_ms"] or fill.fee != 0
                or fill.position_before != Decimal(entry["details"]["position_qty_before"])
                or fill.qty != abs(fill.position_before) or fill.position_after != 0
                or fill.price != Decimal(entry["details"]["price"])
                or fill.side != ("SELL" if fill.position_before > 0 else "BUY")
                or len(orders) != 1 or orders[0].status != "FILLED" or orders[0].qty != 0
                or orders[0].fill_price != fill.price or orders[0].side != fill.side):
            raise MarketDatasetError("invalid liquidation execution checkpoint", code="CHECKPOINT_CORRUPT")
    kernel._account_execution_receipts = receipts
