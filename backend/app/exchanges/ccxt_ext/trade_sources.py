"""Public endpoint contracts used by trade candles.

Raw responses are intentional: unified fetch_trades may filter/truncate pages
and discard exhaustion flags. A saturated time window is split, never advanced
by last_timestamp + 1 (which loses executions sharing that timestamp).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from . import trade_candles as engine
from .trade_candles import CandleTrade


class _Budget:
    def __init__(self):
        self.remaining = engine.MAX_TRADE_PAGES

    async def call(self, method, params):
        if self.remaining <= 0:
            raise ValueError("Trade history page budget exhausted; coverage not verified")
        self.remaining -= 1
        return await method(params)


def _rows(value, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("Invalid public trade page")
    return value


def _integer(value):
    text = str(value)
    if not text.isdigit():
        raise ValueError("Invalid trade identity or timestamp")
    return int(text)


def _trade(identity, timestamp_ms, price, quantity, *, ns=None, sequence=None):
    if not isinstance(identity, (str, int)) or isinstance(identity, bool) or not str(identity):
        raise ValueError("Missing trade identity")
    timestamp_ms = _integer(timestamp_ms)
    timestamp_ns = _integer(ns) if ns is not None else timestamp_ms * 1_000_000
    if timestamp_ns // 1_000_000 != timestamp_ms:
        raise ValueError("Inconsistent trade timestamps")
    p, q = Decimal(str(price)), Decimal(str(quantity))
    if not p.is_finite() or p <= 0 or not q.is_finite() or q <= 0:
        raise ValueError("Invalid trade price or quantity")
    return CandleTrade(str(identity), timestamp_ns, p, q, _integer(sequence) if sequence is not None else None)


def _match(row, key, expected):
    if row.get(key) != expected:
        raise ValueError("Trade history market mismatch")


def _base_contracts(amount, price, market):
    size = Decimal(str(market.get("contractSize")))
    if not size.is_finite() or size <= 0:
        raise ValueError("Missing contract size for trade volume")
    quantity = Decimal(str(amount)) * size
    return quantity / Decimal(str(price)) if market.get("inverse") else quantity


async def _bounded(fetch_page, start, end):
    """fetch_page owns the shared budget and returns (trades, exhausted)."""
    count = (end - start + engine.MAX_WINDOW_MS - 1) // engine.MAX_WINDOW_MS
    if count > engine.MAX_TRADE_PAGES:
        raise ValueError("Trade history page budget exhausted; coverage not verified")
    pending = list(reversed([(lo, min(end, lo + engine.MAX_WINDOW_MS))
                             for lo in range(start, end, engine.MAX_WINDOW_MS)]))
    result = []
    while pending:
        lo, hi = pending.pop()
        trades, exhausted = await fetch_page(lo, hi)
        # Some venue bounds are exclusive/undocumented; callers request one
        # adjacent millisecond as overlap. Reject ignored or changed filters.
        if any(not (lo - 1) * 1_000_000 <= t.timestamp_ns < (hi + 1) * 1_000_000 for t in trades):
            raise ValueError("Trade endpoint did not honor requested time window")
        if exhausted:
            result.extend(t for t in trades if lo * 1_000_000 <= t.timestamp_ns < hi * 1_000_000)
        else:
            if hi - lo <= 1:
                raise ValueError("Trade history saturated within one millisecond; coverage not verified")
            mid = (lo + hi) // 2
            pending.extend([(mid, hi), (lo, mid)])
    return result


async def fetch_public_trades(exchange: Any, symbol: str, venue: str, start: int, end: int, *, now_ms: int):
    budget = _Budget()
    market = exchange.market(symbol)
    if venue == "coinbaseexchange":
        return await _coinbase(exchange, market, start, budget)
    if venue == "bitget":
        return await _bitget(exchange, market, start, end, now_ms, budget)

    async def page(lo, hi):
        limit = min(engine.PAGE_SIZE, 100 if venue == "krakenfutures" else 1000)
        exhausted = None
        if venue == "bitfinex":
            rows = _rows(await budget.call(exchange.publicGetTradesSymbolHist, {
                "symbol": market["id"], "start": lo, "end": hi - 1, "sort": 1, "limit": limit,
            }), limit)
            trades = []
            for row in rows:
                if not isinstance(row, list) or len(row) != 4:
                    raise ValueError("Invalid Bitfinex trade schema")
                trades.append(_trade(_integer(row[0]), row[1], row[3], abs(Decimal(str(row[2])))))
        elif venue == "bitvavo":
            rows = _rows(await budget.call(exchange.publicGetMarketTrades, {
                "market": market["id"], "start": lo, "end": hi - 1, "limit": limit,
            }), limit)
            # UUIDs do not encode execution order. Preserve the source order
            # within equal timestamps instead of sorting UUIDs lexicographically.
            trades = [_trade(r["id"], r["timestamp"], r["price"], r["amount"]) for r in reversed(rows)]
        elif venue in {"binanceusdm", "binancecoinm"}:
            method = exchange.dapiPublicGetAggTrades if market.get("inverse") else exchange.fapiPublicGetAggTrades
            rows = _rows(await budget.call(method, {
                "symbol": market["id"], "startTime": lo, "endTime": hi - 1, "limit": limit,
            }), limit)
            trades = [_trade(_integer(r["a"]), r["T"], r["p"],
                             _base_contracts(r["q"], r["p"], market) if market.get("inverse") else r["q"])
                      for r in rows]
        elif venue == "cryptocom":
            # The documented default is 25; use it instead of assuming a
            # larger undocumented server cap and mistaking truncation for EOF.
            limit = min(engine.PAGE_SIZE, 25)
            payload = await budget.call(exchange.v1PublicGetPublicGetTrades, {
                "instrument_name": market["id"], "start_ts": lo - 1, "end_ts": hi, "count": limit,
            })
            if not isinstance(payload, dict) or payload.get("code") != 0:
                raise ValueError("Invalid Crypto.com trade response")
            rows = _rows(payload["result"]["data"], limit)
            trades = []
            for r in reversed(rows):
                _match(r, "i", market["id"])
                trades.append(_trade(r["d"], r["t"], r["p"], r["q"], ns=r.get("tn")))
        elif venue == "deribit":
            payload = await budget.call(exchange.publicGetGetLastTradesByInstrumentAndTime, {
                "instrument_name": market["id"], "start_timestamp": lo, "end_timestamp": hi - 1,
                "count": limit, "sorting": "asc",
            })
            if not isinstance(payload, dict) or payload.get("error") or not isinstance(payload.get("result"), dict):
                raise ValueError("Invalid Deribit trade response")
            result = payload["result"]
            if not isinstance(result.get("has_more"), bool):
                raise ValueError("Missing Deribit exhaustion flag")
            rows = _rows(result.get("trades"), limit)
            exhausted = not result["has_more"]
            trades = []
            for r in rows:
                _match(r, "instrument_name", market["id"])
                # Inverse tape amounts are USD notionals, not contract counts.
                q = Decimal(str(r["amount"]))
                if market.get("inverse"):
                    q /= Decimal(str(r["price"]))
                trades.append(_trade(r["trade_id"], r["timestamp"], r["price"], q,
                                     ns=r.get("starbase_timestamp"), sequence=r["trade_seq"]))
        elif venue == "krakenfutures":
            payload = await budget.call(exchange.historyGetMarketSymbolExecutions, {
                "symbol": market["id"], "since": lo - 1, "before": hi, "count": limit, "sort": "asc",
            })
            if not isinstance(payload, dict) or "len" not in payload:
                raise ValueError("Invalid Kraken Futures trade response")
            rows = _rows(payload.get("elements"), limit)
            if _integer(payload["len"]) != len(rows):
                raise ValueError("Invalid Kraken Futures page length")
            exhausted = not payload.get("continuationToken") and len(rows) < limit
            trades = []
            for item in rows:
                r = item["event"]["Execution"]["execution"]
                _match(r["makerOrder"], "tradeable", market["id"])
                _match(r["takerOrder"], "tradeable", market["id"])
                trades.append(_trade(r["uid"], r["timestamp"], r["price"], _base_contracts(r["quantity"], r["price"], market)))
        else:
            raise ValueError("Unsupported public trade endpoint")
        return trades, len(rows) < limit if exhausted is None else exhausted

    return await _bounded(page, start, end)


def _iso_ns(value):
    # Preserve micro/nanoseconds; datetime.timestamp() is a float and CCXT's
    # unified timestamp truncates to ms before OHLC ordering.
    date, clock = value.rstrip("Z").split("T")
    seconds, _, fraction = clock.partition(".")
    epoch = datetime.fromisoformat(f"{date}T{seconds}").replace(tzinfo=timezone.utc)
    return int(epoch.timestamp()) * 1_000_000_000 + int((fraction + "000000000")[:9])


async def _coinbase(exchange, market, start, budget):
    cursor = None
    collected = []
    limit = min(engine.PAGE_SIZE, 1000)
    while True:
        params = {"id": market["id"], "limit": limit}
        if cursor is not None:
            params["after"] = str(cursor)
        rows = _rows(await budget.call(exchange.publicGetProductsIdTrades, params), limit)
        page = []
        for r in rows:
            ns = _iso_ns(r["time"])
            page.append(_trade(_integer(r["trade_id"]), ns // 1_000_000, r["price"], r["size"], ns=ns))
        if not page:
            # An empty/short recent page cannot certify unavailable older data.
            raise ValueError("Coinbase trade cursor ended before requested history; coverage not verified")
        ids = [int(t.trade_id) for t in page]
        if any(b >= a for a, b in zip(ids, ids[1:])) or (cursor is not None and ids[0] >= cursor):
            raise ValueError("Coinbase trade cursor did not advance")
        if any(b.timestamp_ns > a.timestamp_ns for a, b in zip(page, page[1:])):
            raise ValueError("Coinbase trade page is not chronological")
        collected.extend(page)
        # Strict inequality consumes *all* executions on the first boundary.
        if page[-1].timestamp_ns < start * 1_000_000:
            return list(reversed(collected))
        cursor = ids[-1]


def _bitget_rows(payload, market, limit):
    if not isinstance(payload, dict) or payload.get("code") != "00000":
        raise ValueError("Invalid Bitget trade response")
    rows = _rows(payload.get("data"), limit)
    result = []
    for r in rows:
        _match(r, "symbol", market["id"])
        result.append(_trade(_integer(r["tradeId"]), r["ts"], r["price"], r["size"]))
    return result


async def _bitget(exchange, market, start, end, now_ms, budget):
    spot = bool(market.get("spot"))
    params = {"symbol": market["id"]}
    if not spot:
        params["productType"] = "COIN-FUTURES" if market.get("inverse") else f"{market['settle']}-FUTURES"
    history = exchange.publicSpotGetV2SpotMarketFillsHistory if spot else exchange.publicMixGetV2MixMarketFillsHistory
    recent = exchange.publicSpotGetV2SpotMarketFills if spot else exchange.publicMixGetV2MixMarketFills
    limit = min(engine.PAGE_SIZE, 500 if spot else 1000)
    tail = _bitget_rows(await budget.call(recent, {**params, "limit": limit}), market, limit)
    # Latest fills can precede the history index. The oldest recent millisecond
    # may be truncated by the count cap, so only its following millisecond is
    # safe to use as a joining boundary.
    cut = min(end, min(t.timestamp_ns // 1_000_000 for t in tail) + 1) if tail else end
    if cut <= start:
        return tail
    latest = _bitget_rows(await budget.call(history, {
        **params, "startTime": now_ms - 7 * 86_400_000, "endTime": now_ms, "limit": 1,
    }), market, 1)
    if not latest or max(t.timestamp_ns for t in latest) < cut * 1_000_000:
        raise ValueError("Bitget trade history is not caught up to the requested window; coverage not verified")

    async def page(lo, hi):
        # Overlap both bounds: documentation uses after/before rather than
        # promising inclusivity. The reducer discards adjacent executions.
        count = min(engine.PAGE_SIZE, 1000)
        trades = _bitget_rows(await budget.call(history, {
            **params, "startTime": lo - 1, "endTime": hi, "limit": count,
        }), market, count)
        return trades, len(trades) < count

    past = await _bounded(page, start, cut)
    return past + [t for t in tail if t.timestamp_ns >= cut * 1_000_000]
