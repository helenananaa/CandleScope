"""Unified CCXT protocol calls; lifecycle, capture and dispatch belong to CcxtProvider."""
from __future__ import annotations
import time
from typing import Any
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamType, TransportRequest
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
        if descriptor.stream_type == StreamType.KLINE:
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
                values = await exchange.fetch_funding_rate_history(
                    symbol,
                    since=req.start_ms,
                    limit=max(1, int(req.limit or 1)),
                )
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
                values = await exchange.fetch_open_interest_history(
                    symbol,
                    timeframe=descriptor.interval,
                    since=req.start_ms,
                    limit=max(1, int(req.limit or 1)),
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
