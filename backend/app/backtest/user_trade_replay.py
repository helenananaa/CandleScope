"""Reveal one completed local strategy result at an immutable print cursor."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from decimal import Decimal
import json

from app.data_engine.interval_policy import parse_interval_spec
from app.local_data.user_market_trades import USER_TRADE_SOURCE
from app.market_dataset.snapshot import MarketDatasetError
from app.simulation.closing_tick import REASON as CLOSING_TICK
from app.simulation.spot_cash_account import SpotCashAccount
from app.simulation.trade_bar_builder import TradeBarBuilder

from .errors import BacktestError
from .user_trade_input import open_user_trade_run_snapshot


DISPLAY_INTERVALS = ("1m", "5m", "15m", "1h")
MAX_REVEALED_BARS = 160
MAX_REVEALED_FILLS = 100


def _wire_bar(event, *, closed):
    payload = event.payload
    return {key: str(payload[key]) for key in ("open", "high", "low", "close", "volume")} | {
        "open_time_ms": payload["open_time_ms"], "closed": closed,
    }


def _fill_cursor(fill, events, times):
    sequence = fill.get("source_sequence")
    source_time = fill.get("source_event_time_ms")
    if fill.get("reason") == CLOSING_TICK:
        # A simulated BAR-close fill is emitted by the first source event
        # beyond that close. The prior event's sequence is reused by the
        # matching engine, so that sequence alone cannot reveal this fill.
        position = bisect_right(times, int(fill["event_time_ms"])) + 1
        if position <= len(events):
            return position
    elif (type(sequence) is int and 1 <= sequence <= len(events)
          and source_time == events[sequence - 1].event_time_ms
          and fill.get("source_event_kind") == "AGG_TRADE"):
        return sequence
    raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved fill has no verifiable replay boundary")


def project_user_trade_replay(runtime, run_id: str, *, snapshot_hash: str, report_hash: str, cursor: int, interval: str) -> dict:
    record = runtime.service.get_run(run_id)
    if (record["state"] != "COMPLETED" or record["fidelity_mode"] != "AGG_TRADE_EXECUTION"
            or runtime._manifest(str(record["dataset_id"])).get("source") != USER_TRADE_SOURCE):
        raise BacktestError("FIDELITY_UNSUPPORTED", "Result replay requires a completed user market-trade run")
    if record["snapshot_hash"] != snapshot_hash:
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Result replay snapshot changed")
    config = json.loads(str(record["config_json"]))
    spec = parse_interval_spec(interval)
    if spec is None or (interval not in DISPLAY_INTERVALS and interval != config["signal_interval"]):
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "Unsupported result replay display interval")
    preview, events = open_user_trade_run_snapshot(
        runtime.local_data, record, config, max_events=runtime.settings.max_trade_events,
    )
    if not 0 <= cursor <= len(events):
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "Result replay cursor is outside the frozen input")
    report = runtime.service.get_report(run_id)
    if report["hashes"]["report"] != report_hash:
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Result replay report changed")
    times = [event.event_time_ms for event in events]
    account = SpotCashAccount(quote_balance=Decimal(str(config["initial_balance"])))
    visible_fills = deque(maxlen=MAX_REVEALED_FILLS)
    visible_fill_count = 0
    last_fill_cursor = 0
    try:
        for fill in report["fills"]:
            available = _fill_cursor(fill, events, times)
            if available < last_fill_cursor:
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved fills are not ordered by their reveal boundary")
            last_fill_cursor = available
            if available > cursor:
                break
            account.apply_fill(side=fill["side"], price=Decimal(fill["price"]),
                               qty=Decimal(fill["qty"]), fee=Decimal(fill["fee"]))
            if account.position_qty != Decimal(fill["position_after"]):
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved fill position is inconsistent")
            # Explanations and full-order summaries are report views with their
            # own availability rules. Only sealed fields of this fill are shown.
            visible_fills.append({
                "cursor": available, "event_time_ms": fill["event_time_ms"],
                "order_id": fill["order_id"], "side": fill["side"], "price": fill["price"],
                "qty": fill["qty"], "fee": fill["fee"],
            })
            visible_fill_count += 1

        last = events[cursor - 1] if cursor else None
        bars = deque(maxlen=MAX_REVEALED_BARS)
        if last is not None:
            builder = TradeBarBuilder(interval)
            first_open = spec.floor_ms(last.event_time_ms)
            for _ in range(MAX_REVEALED_BARS - 1):
                if first_open <= times[0]:
                    break
                first_open = spec.previous_ms(first_open)
            for index in range(bisect_left(times, first_open), cursor):
                bars.extend(_wire_bar(bar, closed=True) for bar in builder.push(events[index]))
            bars.append(_wire_bar(builder.forming_bar(last.event_time_ms), closed=False))
            account.mark = Decimal(str(last.payload["price"]))
        if cursor == len(events):
            for field, value in (("quote_balance", account.quote_balance), ("position_qty", account.position_qty),
                                 ("equity", account.equity())):
                if Decimal(report["account"][field]) != value:
                    raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Replay account differs from the sealed result")
    except MarketDatasetError as exc:
        raise BacktestError(exc.code, str(exc)) from exc

    orders = report.get("order_events") or []
    # Older reports can contain a prior-print timestamp for NEW and
    # REJECTED states. Only recorded reveal ordinals are authoritative.
    order_trace_available = all(type(row.get("reveal_sequence")) is int for row in orders)
    visible_orders = deque(maxlen=MAX_REVEALED_FILLS)
    if order_trace_available:
        for row in orders:
            if not 1 <= row["reveal_sequence"] <= len(events):
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved order has an invalid replay boundary")
            if row["reveal_sequence"] <= cursor:
                visible_orders.append({key: row[key] for key in ("ordinal", "order_id", "state", "reveal_sequence")})
    return {
        "schema": "candlescope.user-trade-result-replay/1",
        "run_id": run_id, "snapshot_hash": snapshot_hash, "report_hash": report_hash,
        "symbol": preview["identity"]["instrument"]["base_asset"] + "/" + preview["quality"]["quote_asset"],
        "quote_asset": preview["quality"]["quote_asset"], "interval": interval,
        "signal_interval": config["signal_interval"], "cursor": cursor, "total": len(events),
        "time_ms": last.event_time_ms if last else None,
        "source_sequence": last.payload["source_sequence"] if last else None,
        "bars": list(bars), "fills": list(visible_fills), "fill_count": visible_fill_count,
        "order_events": list(visible_orders), "order_trace_available": order_trace_available,
        "cash": str(account.quote_balance), "position": str(account.position_qty), "equity": str(account.equity()),
    }
