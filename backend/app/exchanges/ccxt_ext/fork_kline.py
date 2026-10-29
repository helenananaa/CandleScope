"""Strict boundary for the opt-in, source-pinned CandleScope CCXT fork.

Source evidence is retained in the source journal before downstream delivery.
"""

from __future__ import annotations

import copy
import importlib.resources
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.data_engine.ingestion.models import (
    DataSource,
    MarketEvent,
    RawMessage,
    StreamDescriptor,
    StreamType,
)

SCHEMA = "candlescope.binance.usdm.kline.v1"
LOCK_PATH = Path(__file__).resolve().parents[3] / "ccxt-fork.lock.json"


def require_fork(exchange: Any) -> None:
    """Reject vanilla CCXT, an incompatible schema, or an unpinned fork build."""
    from .binance_usdm import CcxtCompatibilityError

    required = (
        "candlescope_kline_contract",
        "fetch_candlescope_klines",
        "parse_candlescope_ws_kline",
    )
    if not all(callable(getattr(exchange, name, None)) for name in required):
        raise CcxtCompatibilityError(
            "CCXT fork required: run backend/scripts/install_ccxt_fork.py in an isolated venv"
        )
    lock = json.loads(LOCK_PATH.read_text())
    try:
        build = json.loads(
            importlib.resources.files("ccxt")
            .joinpath("candlescope_build.json")
            .read_text()
        )
    except (FileNotFoundError, ValueError) as exc:
        raise CcxtCompatibilityError("CCXT fork build provenance is missing") from exc
    if exchange.candlescope_kline_contract() != {
        "upstream": lock["upstream_version"],
        "schema": SCHEMA,
    }:
        raise CcxtCompatibilityError(
            "CCXT fork contract differs from the qualified schema"
        )
    if (
        build.get("source_commit") != lock["source_commit"]
        or build.get("schema") != SCHEMA
    ):
        raise CcxtCompatibilityError(
            "CCXT fork source commit differs from ccxt-fork.lock.json"
        )


def _integer(payload: dict, key: str) -> int:
    value = payload.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid fork kline integer: {key}")
    return value


def normalize_fork_kline(
    message: RawMessage, descriptor: StreamDescriptor
) -> MarketEvent | None:
    payload = message.payload
    expected = {
        "schema": SCHEMA,
        "exchange": "binance",
        "marketType": "swap.linear",
        "marketId": descriptor.symbol.upper(),
        "timeframe": descriptor.interval,
        "volumeUnit": "base",
        "quoteVolumeUnit": "quote",
    }
    if (
        descriptor.exchange != "binance"
        or descriptor.market_type != "futures"
        or descriptor.stream_type != StreamType.KLINE
        or message.stream_type != StreamType.KLINE
        or not isinstance(payload, dict)
        or any(payload.get(k) != v for k, v in expected.items())
    ):
        raise ValueError("fork kline identity/schema/units do not match the stream")
    opened = _integer(payload, "timestamp")
    closed_at = _integer(payload, "closeTime")
    trades = _integer(payload, "trades")
    if closed_at < opened:
        raise ValueError("fork kline close time precedes open time")
    fields = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "quote_volume": "quoteVolume",
        "taker_buy_base": "takerBuyBaseVolume",
        "taker_buy_quote": "takerBuyQuoteVolume",
    }
    exact: dict[str, Decimal] = {}
    for target, source in fields.items():
        value = payload.get(source)
        try:
            if not isinstance(value, str):
                raise ValueError(f"fork kline {source} must retain its decimal string")
            parsed = Decimal(value)
            if not parsed.is_finite() or parsed < 0 or not math.isfinite(float(parsed)):
                raise ValueError(f"invalid fork kline decimal: {source}")
        except InvalidOperation as exc:
            raise ValueError(f"invalid fork kline decimal: {source}") from exc
        exact[target] = parsed
    if (
        exact["low"] > min(exact["open"], exact["close"])
        or exact["high"] < max(exact["open"], exact["close"])
        or exact["taker_buy_base"] > exact["volume"]
        or exact["taker_buy_quote"] > exact["quote_volume"]
    ):
        raise ValueError("inconsistent fork kline price/volume bounds")
    if message.source == DataSource.WEBSOCKET:
        if (
            payload.get("closeEvidence") != "ws_x"
            or type(payload.get("closed")) is not bool
        ):
            raise ValueError("fork WS kline requires explicit boolean close evidence")
        is_closed = payload["closed"]
        evidence = "ws_x"
        event_time = _integer(payload, "eventTime")
    elif message.source in {DataSource.HTTP, DataSource.HTTP_BACKFILL}:
        if (
            payload.get("closeEvidence") != "rest_close_time"
            or payload.get("closed") is not None
        ):
            raise ValueError("fork REST kline cannot claim explicit WS finality")
        server_time = payload.get("_source_rest_server_time_ms")
        if server_time is not None:
            if type(server_time) is not int or server_time <= 0:
                raise ValueError("invalid REST exchange time evidence")
            is_closed = closed_at < server_time
            evidence = (
                "rest_server_time_elapsed" if is_closed else "rest_server_time_pending"
            )
        else:
            # Parsing old/offline envelopes remains possible; durable REST
            # acquisition always supplies an exchange-clock observation.
            is_closed = closed_at < message.received_at_ms
            evidence = (
                "rest_close_time_elapsed" if is_closed else "rest_close_time_pending"
            )
        event_time = opened
    else:
        raise ValueError("unsupported source for fork kline")
    raw = payload.get("raw")
    if not isinstance(raw, str):
        raise ValueError("fork kline source evidence is missing")
    try:
        source_payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError("fork kline source evidence is malformed") from exc
    names = (
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "closeTime",
        "quoteVolume",
        "trades",
        "takerBuyBaseVolume",
        "takerBuyQuoteVolume",
    )
    if message.source == DataSource.WEBSOCKET:
        if not isinstance(source_payload, dict) or not isinstance(
            source_payload.get("k"), dict
        ):
            raise ValueError("fork WS source evidence is not a candle")
        kline = source_payload["k"]
        source_values = [
            kline.get(key)
            for key in ("t", "o", "h", "l", "c", "v", "T", "q", "n", "V", "Q")
        ]
        if (
            source_payload.get("e") != "kline"
            or source_payload.get("s") != payload["marketId"]
            or kline.get("s") != payload["marketId"]
            or kline.get("i") != payload["timeframe"]
            or type(kline.get("x")) is not bool
            or kline["x"] != is_closed
            or type(source_payload.get("E")) is not int
            or source_payload["E"] != event_time
        ):
            raise ValueError("fork WS metadata differs from source evidence")
    else:
        if not isinstance(source_payload, list) or len(source_payload) < 11:
            raise ValueError("fork REST source evidence is not a complete candle")
        source_values = source_payload[:11]
    for key, value in zip(names, source_values, strict=True):
        if type(value) is not type(payload[key]) or value != payload[key]:
            raise ValueError(f"fork kline {key} differs from source evidence")
    data = {key: float(value) for key, value in exact.items()}
    data.update(
        interval=descriptor.interval,
        open_time=opened,
        close_time=closed_at,
        trades=trades,
        is_closed=is_closed,
        close_evidence=evidence,
        source_candle=copy.deepcopy(payload),
    )
    receipt = payload.get("_source_receipt")
    if receipt is not None:
        if receipt["status"] != "selected":
            return None
        data["source_ref"] = dict(receipt["ref"])
        data["is_correction"] = is_closed
    return MarketEvent(
        event_type=StreamType.KLINE,
        symbol=descriptor.symbol,
        exchange=descriptor.exchange,
        event_time_ms=event_time,
        received_at_ms=message.received_at_ms,
        source=message.source,
        data=data,
        stream_key=descriptor.key,
        sequence=opened,
        market_type=descriptor.market_type,
    )


async def prepare_source_messages(messages, descriptor, *, watermark=None):
    from app.core.executors import run_storage
    from app.data_engine.storage import kline_sources

    unrecorded = [
        message for message in messages if "_source_receipt" not in message.payload
    ]
    if not unrecorded:
        return
    build = json.loads(LOCK_PATH.read_text())
    for message in unrecorded:
        message.payload = dict(
            message.payload,
            _source_build={
                key: build[key]
                for key in ("source_commit", "upstream_version", "schema")
            },
        )
    events = [normalize_fork_kline(message, descriptor) for message in unrecorded]
    if (
        any(event.source != DataSource.WEBSOCKET for event in events)
        and watermark is None
    ):
        raise ValueError(
            "REST source persistence requires a pre-request database watermark"
        )
    receipts = await run_storage(
        kline_sources.record_batch, events, descriptor, watermark
    )
    for message, receipt in zip(unrecorded, receipts, strict=True):
        message.payload = dict(message.payload, _source_receipt=receipt)
