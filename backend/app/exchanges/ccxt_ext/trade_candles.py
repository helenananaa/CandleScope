"""Bounded Kraken trade pagination and deterministic OHLCV reduction.

No tick archive or background recorder: requests exist only for active chart
polls and ordinary history jobs. All pages must succeed before publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.exchanges.trade_candles import fixed_trade_spec
from .unified import make_unified_payload


MAX_TRADE_PAGES = 100
PAGE_SIZE = 1000
MAX_WINDOW_MS = 60_000


@dataclass(frozen=True, slots=True)
class CandleTrade:
    trade_id: str
    timestamp_ns: int
    price: Decimal
    quantity: Decimal


def reduce_trades(trades: list[CandleTrade], interval: str, start_ms: int, end_ms: int) -> list[list]:
    """Reduce [start, end), with dedup and event-time (then source ID) order."""
    spec = fixed_trade_spec(interval)
    seen: dict[str, CandleTrade] = {}
    for trade in trades:
        if not trade.trade_id or trade.timestamp_ns < 0:
            raise ValueError("Missing trade identity or timestamp")
        if not trade.price.is_finite() or trade.price <= 0 or not trade.quantity.is_finite() or trade.quantity <= 0:
            raise ValueError("Invalid trade price or quantity")
        previous = seen.setdefault(trade.trade_id, trade)
        if previous != trade:
            raise ValueError("Conflicting duplicate trade")
    buckets: dict[int, list] = {}
    def order(trade):
        # Numeric exchange IDs retain exchange order, including 9 -> 10.
        return trade.timestamp_ns, (0, int(trade.trade_id)) if trade.trade_id.isdigit() else (1, trade.trade_id)
    for trade in sorted(seen.values(), key=order):
        if not start_ms * 1_000_000 <= trade.timestamp_ns < end_ms * 1_000_000:
            continue
        opened = spec.floor_ms(trade.timestamp_ns // 1_000_000)
        row = buckets.get(opened)
        if row is None:
            buckets[opened] = [opened, trade.price, trade.price, trade.price, trade.price, trade.quantity]
        else:
            row[2] = max(row[2], trade.price)
            row[3] = min(row[3], trade.price)
            row[4] = trade.price
            row[5] += trade.quantity
    return [[row[0], *map(str, row[1:])] for row in buckets.values()]


async def fetch_kraken_trade_candles(exchange: Any, symbol: str, req: Any, *, now_ms: int) -> list[dict]:
    """Return closed candles and a verified coverage marker for one window.

    Kraken's opaque `last` cursor, not milliseconds or assumed consecutive IDs,
    advances pages. A full page never proves exhaustion. Live polls also emit
    the forming bucket, explicitly unclosed until a complete range covers it.
    """
    spec = fixed_trade_spec(req.descriptor.interval)
    width = spec.nominal_ms
    live = req.start_ms is None and req.end_ms is None
    last_closed = spec.floor_ms(now_ms) - width
    end_open = min(spec.floor_ms(req.end_ms), last_closed) if req.end_ms is not None else last_closed
    if req.start_ms is None:
        # Overlap absorbs polling delays; recovery/backfill covers longer gaps.
        start = max(0, end_open - (max(2, min(int(req.limit or 1), 10)) - 1) * width)
    else:
        start = spec.floor_ms(req.start_ms)
        if start < req.start_ms:
            start += width
    end_open = min(end_open, start + (max(1, min(int(req.limit or 1), MAX_WINDOW_MS // width or 1)) - 1) * width)
    if end_open < start:
        raise ValueError("Trade candle range has no settled closed buckets")
    end = now_ms if live else end_open + width
    cursor = max(0, start * 1_000_000 - 1)
    trades: list[CandleTrade] = []
    pair = exchange.market(symbol)["id"]
    complete = False
    for _ in range(MAX_TRADE_PAGES):
        payload = await exchange.public_get_trades({"pair": pair, "since": str(cursor), "count": PAGE_SIZE})
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("Kraken trade history returned an error")
        result = payload.get("result")
        if not isinstance(result, dict) or "last" not in result:
            raise ValueError("Missing Kraken trade cursor")
        keys = [key for key in result if key != "last"]
        if len(keys) != 1 or keys[0] != pair:
            raise ValueError("Kraken trade history market mismatch")
        rows = result[pair]
        next_cursor = int(result["last"])
        if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
            raise ValueError("Invalid Kraken trade page")
        page: list[CandleTrade] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 7:
                raise ValueError("Invalid Kraken trade schema")
            trade_id = str(row[6])
            timestamp = Decimal(str(row[2]))
            if not trade_id.isdigit() or not timestamp.is_finite() or timestamp < 0:
                raise ValueError("Invalid Kraken trade identity or timestamp")
            timestamp_ns = int(timestamp * 1_000_000_000)
            page.append(CandleTrade(trade_id, timestamp_ns, Decimal(str(row[0])), Decimal(str(row[1]))))
        if any(b.timestamp_ns < a.timestamp_ns for a, b in zip(page, page[1:])):
            raise ValueError("Kraken trade page is not chronological")
        # Timestamp representation in JSON can round sub-microsecond values;
        # do not derive the next cursor from a floating-point trade timestamp.
        if next_cursor < cursor or (len(rows) == PAGE_SIZE and next_cursor <= cursor):
            raise ValueError("Kraken trade cursor did not advance")
        trades.extend(page)
        if (page and page[-1].timestamp_ns >= end * 1_000_000) or len(rows) < PAGE_SIZE:
            complete = True
            break
        cursor = next_cursor
    if not complete:
        raise ValueError("Trade history page budget exhausted; coverage not verified")
    bars = reduce_trades(trades, spec.canonical, start, end)
    opened = {int(row[0]) for row in bars}
    empty_ranges = []
    cursor_ms = start
    for value in sorted(opened) + [end]:
        if cursor_ms < value:
            empty_ranges.append([cursor_ms, value - width])
        cursor_ms = value + width
    output = [make_unified_payload("kline", row, is_closed=int(row[0]) + width <= end,
                                  trade_coverage_verified=int(row[0]) + width <= end) for row in bars]
    if not live:
        output.append({"trade_candle_page": "kraken.spot", "interval": spec.canonical,
                       "start_ms": start, "end_ms": end_open, "empty_ranges": empty_ranges})
    return output
