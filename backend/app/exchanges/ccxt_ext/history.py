"""Unified CCXT protocol calls; lifecycle, capture and dispatch belong to CcxtProvider."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Any
from app.data_engine.bar_basis import is_gate_linear_5m
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamType, TransportRequest
from app.exchanges.okx_intervals import OKX_FUNDING_HISTORY_LIMIT
from .generic import _GENERIC_STREAM_METHODS, _rest_method_for, resolve_market_selection, _timestamp
from .catalog import market_selection_parts
from .unified import make_unified_payload

async def fetch_unified_history(
    context,
    req: TransportRequest,
    config: IngestionConfig,
    pool,
) -> list[RawMessage]:
    descriptor = req.descriptor
    methods = _GENERIC_STREAM_METHODS.get(descriptor.stream_type)
    rest_method = _rest_method_for(req, context.entry)
    if (
        methods is None
        or rest_method is None
        or not context.entry.supports(rest_method)
    ):
        raise ValueError(
            f"{context.entry.exchange_id} does not support CCXT REST {descriptor.stream_type.value}",
        )
    selection = resolve_market_selection(context.entry, descriptor.market_type)
    if descriptor.stream_type in {
        StreamType.MARK_PRICE,
        StreamType.INDEX_PRICE,
        StreamType.FUNDING_RATE,
        StreamType.OPEN_INTEREST,
        StreamType.LIQUIDATION,
        StreamType.PREMIUM_INDEX,
    } and market_selection_parts(selection)[0] not in {"swap", "future"}:
        raise ValueError(
            f"{context.entry.exchange_id} derivatives stream requires a contract market",
        )
    async with pool.request(selection) as exchange:
        symbol = await pool.resolve_symbol(
            selection,
            exchange,
            descriptor,
            market_type=selection,
        )
        rows: list[dict[str, Any]] = []
        from app.exchanges.trade_candles import uses_trade_candles
        if descriptor.stream_type == StreamType.KLINE and uses_trade_candles(context.entry.exchange_id, descriptor.market_type, descriptor.interval):
            from .trade_candles import fetch_trade_candles
            rows = await fetch_trade_candles(exchange, symbol, req, now_ms=int(time.time() * 1000))
        elif descriptor.stream_type == StreamType.KLINE and context.entry.exchange_id == "gate" and descriptor.interval == "1s":
            if selection != "spot":
                raise ValueError("Gate native 1s candles are supported only for spot")
            limit = min(max(1, int(req.limit or 1)), 1000)
            params: dict[str, Any] = {
                "currency_pair": exchange.market(symbol)["id"], "interval": "1s",
            }
            if req.start_ms is not None:
                start_s = (int(req.start_ms) + 999) // 1000
                params["from"] = start_s
                params["to"] = min(
                    start_s + limit - 1,
                    int(req.end_ms) // 1000 if req.end_ms is not None else int(time.time()),
                )
            elif req.end_ms is not None:
                params["to"] = int(req.end_ms) // 1000
                params["from"] = max(0, params["to"] - limit + 1)
            else:
                # The latest few Gate rows can remain unconfirmed. Fetch
                # an overlap so a two-second poll still sees final bars.
                params["limit"] = max(limit, 10)
            values = await exchange.publicSpotGetCandlesticks(params)
            for row in values:
                if not isinstance(row, (list, tuple)) or len(row) != 8:
                    raise ValueError("Unexpected Gate spot candle schema")
                open_ms = int(row[0]) * 1000
                rows.append(make_unified_payload(
                    "kline", [open_ms, row[5], row[3], row[4], row[2], row[6]],
                    is_closed=str(row[7]).lower() == "true",
                ))
        elif descriptor.stream_type == StreamType.KLINE and context.entry.exchange_id == "upbit" and descriptor.interval == "1s":
            if selection != "spot":
                raise ValueError("Upbit native 1s candles require spot")
            limit = min(max(1, int(req.limit or 1)), 200)
            params = {"market": exchange.market(symbol)["id"], "count": limit}
            page_start = None
            page_end = None
            if req.start_ms is not None:
                from app.data_engine.history.native_seconds import native_second_history_start
                now_ms = int(time.time() * 1000)
                cutoff = native_second_history_start("upbit", "1s", now_ms)
                page_start = ((max(int(req.start_ms), cutoff or 0) + 999) // 1000) * 1000
                page_end = min(
                    page_start + (limit - 1) * 1000,
                    int(req.end_ms) if req.end_ms is not None else now_ms - 1000,
                    (now_ms // 1000 - 1) * 1000,
                ) // 1000 * 1000
                if page_end < page_start:
                    raise ValueError("Upbit requested range is outside available closed 1s history")
                # At most count seconds: the reverse API cannot truncate
                # this window, including when it returns older candles.
                params["to"] = datetime.fromtimestamp((page_end + 1000) / 1000, timezone.utc).isoformat()
            elif req.end_ms is not None:
                params["to"] = datetime.fromtimestamp((int(req.end_ms) // 1000 + 1), timezone.utc).isoformat()
            values = await exchange.public_get_candles_seconds(params)
            if not isinstance(values, list) or len(values) > limit:
                raise ValueError("Unexpected Upbit candle page size")
            now_ms = int(time.time() * 1000)
            opens = set()
            observed_opens = set()
            for value in values:
                if value.get("market") != params["market"]:
                    raise ValueError("Unexpected Upbit candle market")
                open_ms = int(datetime.fromisoformat(value["candle_date_time_utc"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
                if open_ms % 1000:
                    raise ValueError("Unexpected Upbit second candle timestamp")
                if open_ms in observed_opens or (page_end is not None and open_ms > page_end):
                    raise ValueError("Unexpected Upbit candle page boundary or duplicate")
                observed_opens.add(open_ms)
                if page_start is not None and not page_start <= open_ms <= page_end:
                    continue
                opens.add(open_ms)
                rows.append(make_unified_payload("kline", [
                    open_ms, value["opening_price"], value["high_price"], value["low_price"],
                    value["trade_price"], value["candle_acc_trade_volume"],
                ], is_closed=open_ms + 1000 <= now_ms))
            if page_start is not None:
                empty_ranges = []
                cursor = page_start
                for opened in sorted(opens) + [page_end + 1000]:
                    if cursor < opened:
                        empty_ranges.append([cursor, opened - 1000])
                    cursor = opened + 1000
                rows.append({"native_second_page": "upbit.spot", "start_ms": page_start,
                             "end_ms": page_end, "empty_ranges": empty_ranges})
        elif descriptor.stream_type == StreamType.KLINE and is_gate_linear_5m(
            context.entry.exchange_id, descriptor.market_type, descriptor.interval,
        ):
            from .gate_candles import fetch_linear_candles
            limit = min(max(1, int(req.limit or 1)), context.entry.history_limit)
            rows = await fetch_linear_candles(exchange, symbol, req, limit=limit, now_ms=int(time.time() * 1000))
        elif descriptor.stream_type == StreamType.KLINE:
            limit = min(max(1, int(req.limit or 1)), context.entry.history_limit)
            values = await exchange.fetch_ohlcv(
                symbol,
                timeframe=descriptor.interval,
                since=req.start_ms,
                limit=limit,
            )
            from app.data_engine.interval_policy import parse_interval_spec
            spec = parse_interval_spec(descriptor.interval)
            if spec is None:
                raise ValueError("native_bar_basis_unknown")
            now_ms = int(time.time() * 1000)
            rows = [
                make_unified_payload(
                    "kline",
                    list(row),
                    is_closed=spec.next_ms(int(row[0])) <= now_ms,
                )
                for row in values
                if isinstance(row, (list, tuple))
                and len(row) >= 6
                and (req.end_ms is None or int(row[0]) <= req.end_ms)
            ]
        elif descriptor.stream_type == StreamType.TRADE:
            values = await exchange.fetch_trades(
                symbol,
                since=req.start_ms,
                limit=max(1, int(req.limit or 1)),
            )
            rows = [
                make_unified_payload("trade", dict(value))
                for value in values
                if isinstance(value, dict)
                and (
                    req.end_ms is None
                    or _timestamp(value.get("timestamp")) is None
                    or int(value["timestamp"]) <= req.end_ms
                )
            ]
        elif descriptor.stream_type == StreamType.DEPTH:
            value = await exchange.fetch_order_book(
                symbol,
            )
            context.rest_book_revision += 1
            rows = [
                make_unified_payload(
                    "order_book",
                    dict(value),
                    local_revision=context.rest_book_revision,
                )
            ]
        elif descriptor.stream_type in {StreamType.TICKER, StreamType.MINI_TICKER}:
            value = await exchange.fetch_ticker(symbol)
            rows = [make_unified_payload("ticker", dict(value))]
        elif descriptor.stream_type in {
            StreamType.MARK_PRICE,
            StreamType.INDEX_PRICE,
        }:
            value = await exchange.fetch_mark_price(symbol)
            rows = [make_unified_payload("derivatives_summary", dict(value))]
        elif descriptor.stream_type == StreamType.FUNDING_RATE:
            if req.history or req.start_ms is not None or req.end_ms is not None:
                limit = max(1, int(req.limit or 1))
                options = {}
                if context.entry.exchange_id == "okx":
                    limit = min(limit, OKX_FUNDING_HISTORY_LIMIT)
                    if req.end_ms is not None:
                        options["params"] = {"after": req.end_ms + 1}
                values = await exchange.fetch_funding_rate_history(
                    symbol, since=req.start_ms, limit=limit, **options,
                )
                if context.entry.exchange_id == "okx":
                    # The pinned method only sets this field from realizedRate.
                    # Do not fall through to the raw projected rate in normalization.
                    values = [value for value in values
                              if isinstance(value, dict) and value.get("fundingRate") is not None]
            else:
                values = [await exchange.fetch_funding_rate(symbol)]
            rows = [
                make_unified_payload("funding_rate", dict(value))
                for value in values
                if isinstance(value, dict)
            ]
        elif descriptor.stream_type == StreamType.OPEN_INTEREST:
            if (
                req.history or req.start_ms is not None or req.end_ms is not None
            ) and context.entry.supports("fetchOpenInterestHistory"):
                if context.entry.exchange_id == "okx":
                    from .venue_history import fetch_okx_contract_oi
                    values = await fetch_okx_contract_oi(exchange, symbol, req)
                else:
                    options = {}
                    if context.entry.exchange_id == "gate":
                        # Keep CCXT's unified since filter in milliseconds.
                        # Gate's contract statistics query takes Unix seconds.
                        params = {}
                        if req.start_ms is not None:
                            params["from"] = (req.start_ms + 999) // 1000
                        if req.end_ms is not None:
                            params["to"] = req.end_ms // 1000
                        if "from" in params and "to" in params and params["from"] > params["to"]:
                            return []
                        if params:
                            options["params"] = params
                    values = await exchange.fetch_open_interest_history(
                        symbol,
                        timeframe=descriptor.interval,
                        since=req.start_ms,
                        limit=max(1, int(req.limit or 1)),
                        **options,
                    )
            else:
                values = [await exchange.fetch_open_interest(symbol)]
            rows = [
                make_unified_payload("open_interest", dict(value))
                for value in values
                if isinstance(value, dict)
            ]
        elif descriptor.stream_type == StreamType.LIQUIDATION:
            values = await exchange.fetch_liquidations(
                symbol,
                since=req.start_ms,
                limit=max(1, int(req.limit or 1)),
            )
            rows = [
                make_unified_payload("liquidation", dict(value))
                for value in values
                if isinstance(value, dict)
            ]
        elif descriptor.stream_type == StreamType.PREMIUM_INDEX:
            values = await exchange.fetch_premium_index_ohlcv(
                symbol,
                timeframe=descriptor.interval,
                since=req.start_ms,
                limit=max(1, int(req.limit or 1)),
            )
            rows = [
                make_unified_payload("premium_index", list(value[:6]))
                for value in values
                if isinstance(value, (list, tuple)) and len(value) >= 6
            ]
        received = int(time.time() * 1000)
        return [
            RawMessage(
                payload=row,
                source=DataSource.HTTP,
                stream_type=descriptor.stream_type,
                received_at_ms=received,
                endpoint=f"ccxt+rest://{context.entry.exchange_id}",
                http_status=200,
                request_limit=req.limit,
            )
            for row in rows
        ]
