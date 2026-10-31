"""Finite venue protocol strategies; no registry, client ownership or business queue."""
from __future__ import annotations
import asyncio
import time
from typing import Any
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType, TransportRequest
from app.exchanges.okx_intervals import okx_utc_interval as _okx_interval
from .unified import make_unified_payload

async def _fetch_binance_raw(
    req: TransportRequest,
    config: IngestionConfig,
    pool,
) -> list[RawMessage]:
    descriptor = req.descriptor
    selection = (
        "swap.linear"
        if descriptor.market_type == "futures"
        else descriptor.market_type
    )
    async with pool.request(selection) as exchange:
        symbol = await pool.resolve_symbol(
            selection,
            exchange,
            descriptor,
            market_type=selection,
        )
        market_id = str(exchange.market(symbol)["id"])
        params: dict[str, Any] = {
            "symbol": market_id,
            "limit": max(1, int(req.limit or 1)),
        }
        futures = descriptor.market_type == "futures"
        if (
            descriptor.stream_type == StreamType.KLINE
            and config.ccxt_fork_kline_enabled
        ):
            from .fork_kline import require_fork, prepare_source_messages
            from app.core.executors import run_storage
            from app.data_engine.storage import kline_sources

            require_fork(exchange)
            limit = min(params["limit"], 1500 if futures else 1000)
            fork_params = (
                {"until": int(req.end_ms)} if req.end_ms is not None else {}
            )
            for attempt in range(3):
                watermark = await run_storage(kline_sources.rest_watermark)
                # Observe exchange time BEFORE requesting the candle, so
                # local clock skew cannot invent or delay its finality.
                server_time = await exchange.fetch_time(
                    {"type": "swap", "subType": "linear"}
                    if futures
                    else {"type": "spot"}
                )
                if type(server_time) is not int or server_time <= 0:
                    raise RuntimeError(
                        "missing exchange time for fork REST snapshot"
                    )
                values = await exchange.fetch_candlescope_klines(
                    symbol,
                    descriptor.interval,
                    req.start_ms,
                    limit,
                    fork_params,
                )
                values = [
                    dict(value, _source_rest_server_time_ms=server_time)
                    for value in values
                ]
                messages = _raw_messages(
                    descriptor,
                    values,
                    "/fapi/v1/klines" if futures else "/api/v3/klines",
                    request_limit=limit,
                    headers=exchange.last_response_headers,
                )
                await prepare_source_messages(
                    messages, descriptor, watermark=watermark,
                    history_projection=req.history_projection,
                )
                if all(
                    message.payload["_source_receipt"]["status"] == "selected"
                    for message in messages
                ):
                    return messages
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
            raise RuntimeError(
                "source_read_conflict: K-line changed during REST request; retry page"
            )
        if descriptor.stream_type == StreamType.KLINE:
            params["interval"] = descriptor.interval
            if req.start_ms is not None:
                params["startTime"] = int(req.start_ms)
            if req.end_ms is not None:
                params["endTime"] = int(req.end_ms)
            params["limit"] = min(params["limit"], 1500 if futures else 1000)
            method = (
                exchange.fapipublic_get_klines
                if futures
                else exchange.public_get_klines
            )
            values = await method(params)
        elif descriptor.stream_type == StreamType.PREMIUM_INDEX:
            params["interval"] = descriptor.interval or "1m"
            params["limit"] = min(params["limit"], 1500)
            if req.start_ms is not None:
                params["startTime"] = int(req.start_ms)
            if req.end_ms is not None:
                params["endTime"] = int(req.end_ms)
            values = await exchange.fapipublic_get_premiumindexklines(params)
        elif descriptor.stream_type == StreamType.AGG_TRADE:
            params["limit"] = min(params["limit"], 1000)
            if req.from_id is not None:
                params["fromId"] = int(req.from_id)
            else:
                if req.start_ms is not None:
                    params["startTime"] = int(req.start_ms)
                if req.end_ms is not None:
                    params["endTime"] = int(req.end_ms)
            method = (
                exchange.fapipublic_get_aggtrades
                if futures
                else exchange.public_get_aggtrades
            )
            values = await method(params)
        elif descriptor.stream_type == StreamType.FUNDING_RATE:
            params["limit"] = min(params["limit"], 1000)
            if req.start_ms is not None:
                params["startTime"] = int(req.start_ms)
            if req.end_ms is not None:
                params["endTime"] = int(req.end_ms)
            values = await exchange.fapipublic_get_fundingrate(params)
        elif descriptor.stream_type == StreamType.OPEN_INTEREST:
            if req.history or req.start_ms is not None or req.end_ms is not None:
                params["period"] = descriptor.interval or "5m"
                params["limit"] = min(params["limit"], 500)
                if req.start_ms is not None:
                    params["startTime"] = int(req.start_ms)
                if req.end_ms is not None:
                    params["endTime"] = int(req.end_ms)
                values = await exchange.fapidata_get_openinteresthist(params)
            else:
                params.pop("limit", None)
                values = [await exchange.fapipublic_get_openinterest(params)]
        else:
            params["limit"] = min(max(params["limit"], 100), 1000)
            method = (
                exchange.fapipublic_get_depth
                if futures
                else exchange.public_get_depth
            )
            values = [await method(params)]
        return _raw_messages(
            descriptor,
            values,
            "ccxt+rest://binance",
            request_limit=params.get("limit"),
            headers=getattr(exchange, "last_response_headers", None),
        )


async def _fetch_binance_summary(
    req: TransportRequest,
    config: IngestionConfig,
    pool,
) -> list[RawMessage]:
    descriptor = req.descriptor
    async with pool.request("swap.linear") as exchange:
        symbol = await pool.resolve_symbol(
            "swap.linear",
            exchange,
            descriptor,
            market_type="swap.linear",
        )
        mark, funding = await asyncio.gather(
            exchange.fetch_mark_price(symbol),
            exchange.fetch_funding_rate(symbol),
        )
        mark = mark if isinstance(mark, dict) else {}
        funding = funding if isinstance(funding, dict) else {}
        value = {
            "markPrice": mark.get("markPrice"),
            "indexPrice": mark.get("indexPrice"),
            "fundingRate": funding.get("fundingRate"),
            "nextFundingTimestamp": funding.get("nextFundingTimestamp"),
            "timestamp": max(
                int(mark.get("timestamp") or 0),
                int(funding.get("timestamp") or 0),
            ),
            "info": {
                "mark": mark.get("info"),
                "funding": funding.get("info"),
            },
        }
        return _raw_messages(
            descriptor,
            [make_unified_payload("derivatives_summary", value)],
            "ccxt+rest://binance",
            headers=getattr(exchange, "last_response_headers", None),
        )


async def _fetch_okx_kline_raw(
    req: TransportRequest,
    config: IngestionConfig,
    pool,
) -> list[RawMessage]:
    descriptor = req.descriptor
    selection = (
        "swap.linear"
        if descriptor.market_type == "futures"
        else descriptor.market_type
    )
    async with pool.request(selection) as exchange:
        symbol = await pool.resolve_symbol(
            selection,
            exchange,
            descriptor,
            market_type=selection,
        )
        if config.ccxt_fork_kline_enabled:
            from .fork_kline import require_fork, prepare_source_messages
            from app.core.executors import run_storage
            from app.data_engine.storage import kline_sources

            require_fork(exchange)
            limit = min(max(1, int(req.limit or 1)), 300)
            until = {"until": int(req.end_ms)} if req.end_ms is not None else {}
            for attempt in range(3):
                watermark = await run_storage(kline_sources.rest_watermark)
                rows = await exchange.fetch_candlescope_klines(
                    symbol, descriptor.interval, req.start_ms, limit, until
                )
                messages = _raw_messages(
                    descriptor,
                    rows,
                    "/api/v5/market/history-candles",
                    request_limit=limit,
                    headers=getattr(exchange, "last_response_headers", None),
                )
                await prepare_source_messages(
                    messages, descriptor, watermark=watermark,
                    history_projection=req.history_projection,
                )
                if all(
                    m.payload["_source_receipt"]["status"] == "selected"
                    for m in messages
                ):
                    return messages
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
            raise RuntimeError(
                "source_read_conflict: OKX K-line changed during REST request; retry page"
            )
        params: dict[str, Any] = {
            "instId": str(exchange.market(symbol)["id"]),
            "bar": _okx_interval(descriptor.interval or "1m"),
            "limit": min(max(1, int(req.limit or 1)), 300),
        }
        if req.end_ms is not None:
            params["after"] = str(max(0, int(req.end_ms) + 1))
        if req.start_ms is not None:
            params["before"] = str(max(0, int(req.start_ms) - 1))
        response = await exchange.public_get_market_history_candles(params)
        if not isinstance(response, dict) or str(response.get("code", "0")) not in {
            "",
            "0",
        }:
            raise RuntimeError(f"OKX CCXT REST error: {response!r}")
        values = response.get("data") if isinstance(response, dict) else None
        rows = list(reversed(values)) if isinstance(values, list) else []
        return _raw_messages(
            descriptor,
            rows,
            "ccxt+rest://okx",
            headers=getattr(exchange, "last_response_headers", None),
        )


async def _fetch_okx_summary(
    req: TransportRequest,
    config: IngestionConfig,
    pool,
) -> list[RawMessage]:
    descriptor = req.descriptor
    async with pool.request("swap.linear") as exchange:
        symbol = await pool.resolve_symbol(
            "swap.linear",
            exchange,
            descriptor,
            market_type="swap.linear",
        )
        index_symbol = _okx_index_symbol(exchange, symbol)
        index_id = str(exchange.market(index_symbol)["id"])
        mark, funding, index_response = await asyncio.gather(
            exchange.fetch_mark_price(symbol),
            exchange.fetch_funding_rate(symbol),
            exchange.public_get_market_index_tickers({"instId": index_id}),
        )
        index_rows = (
            index_response.get("data") if isinstance(index_response, dict) else None
        )
        index_row = (
            index_rows[0]
            if isinstance(index_rows, list)
            and index_rows
            and isinstance(index_rows[0], dict)
            else {}
        )
        value = {
            "markPrice": mark.get("markPrice") if isinstance(mark, dict) else None,
            "indexPrice": index_row.get("idxPx"),
            "fundingRate": (
                funding.get("fundingRate") if isinstance(funding, dict) else None
            ),
            "nextFundingTimestamp": (
                funding.get("nextFundingTimestamp")
                if isinstance(funding, dict)
                else None
            ),
            "timestamp": max(
                int(mark.get("timestamp") or 0) if isinstance(mark, dict) else 0,
                int(index_row.get("ts") or 0),
            ),
            "info": {
                "mark": mark.get("info") if isinstance(mark, dict) else None,
                "funding": funding.get("info")
                if isinstance(funding, dict)
                else None,
                "index": index_row,
            },
        }
        return _raw_messages(
            descriptor,
            [make_unified_payload("derivatives_summary", value)],
            "ccxt+rest://okx",
            headers=getattr(exchange, "last_response_headers", None),
        )


def _raw_messages(
    descriptor: StreamDescriptor,
    values: Any,
    endpoint: str,
    *,
    request_limit: int | None = None,
    headers: dict | None = None,
) -> list[RawMessage]:
    rows = values if isinstance(values, list) else [values]
    received = int(time.time() * 1000)
    return [
        RawMessage(
            payload=value,
            source=DataSource.HTTP,
            stream_type=descriptor.stream_type,
            received_at_ms=received,
            endpoint=endpoint,
            http_status=200,
            http_headers=dict(headers or {}),
            request_limit=request_limit,
        )
        for value in rows
    ]


def _okx_index_symbol(exchange: Any, contract_symbol: str) -> str:
    market = exchange.market(contract_symbol)
    base = str(market.get("base") or "")
    quote = str(market.get("quote") or "")
    candidates = [
        item
        for item in exchange.markets.values()
        if bool(item.get("spot"))
        and str(item.get("base") or "") == base
        and str(item.get("quote") or "") == quote
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"unable to resolve one OKX index symbol for {contract_symbol}",
        )
    return str(candidates[0]["symbol"])


def rate_limit_endpoint(venue, req: TransportRequest) -> str | None:
    """Return quota metadata without exposing a native transport route."""

    if venue not in {"binance", "okx"}:
        return None
    descriptor = req.descriptor
    if venue == "okx":
        if descriptor.stream_type == StreamType.KLINE:
            return "/api/v5/market/history-candles"
        return None
    futures = descriptor.market_type.strip().lower() == "futures"
    if descriptor.stream_type == StreamType.KLINE:
        return "/fapi/v1/klines" if futures else "/api/v3/klines"
    if descriptor.stream_type == StreamType.AGG_TRADE:
        return "/fapi/v1/aggTrades" if futures else "/api/v3/aggTrades"
    if descriptor.stream_type == StreamType.FULL_DEPTH:
        return "/fapi/v1/depth" if futures else "/api/v3/depth"
    if not futures:
        return None
    return {
        StreamType.MARK_PRICE: "/fapi/v1/premiumIndex",
        StreamType.INDEX_PRICE: "/fapi/v1/premiumIndex",
        StreamType.PREMIUM_INDEX: "/fapi/v1/premiumIndexKlines",
        StreamType.FUNDING_RATE: "/fapi/v1/fundingRate",
        StreamType.OPEN_INTEREST: (
            "/futures/data/openInterestHist"
            if req.history or req.start_ms is not None or req.end_ms is not None
            else "/fapi/v1/openInterest"
        ),
    }.get(descriptor.stream_type)

HISTORY_STRATEGIES = {
    ("binance", StreamType.KLINE): _fetch_binance_raw,
    ("binance", StreamType.AGG_TRADE): _fetch_binance_raw,
    ("binance", StreamType.FULL_DEPTH): _fetch_binance_raw,
    ("binance", StreamType.PREMIUM_INDEX): _fetch_binance_raw,
    ("binance", StreamType.FUNDING_RATE): _fetch_binance_raw,
    ("binance", StreamType.OPEN_INTEREST): _fetch_binance_raw,
    ("binance", StreamType.MARK_PRICE): _fetch_binance_summary,
    ("binance", StreamType.INDEX_PRICE): _fetch_binance_summary,
    ("okx", StreamType.KLINE): _fetch_okx_kline_raw,
    ("okx", StreamType.MARK_PRICE): _fetch_okx_summary,
    ("okx", StreamType.INDEX_PRICE): _fetch_okx_summary,
}
