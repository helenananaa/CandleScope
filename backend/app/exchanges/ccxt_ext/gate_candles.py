"""Gate perpetual 5m candles on the pinned CCXT REST and Pro clients."""

from decimal import Decimal, InvalidOperation
import math

from app.data_engine.ingestion.models import TransportRequest
from app.data_engine.bar_basis import GATE_INVERSE_CONTRACTS

from .unified import make_unified_payload


_FIVE_MINUTES_MS = 300_000


class GateKlineProtocolMixin:
    def parse_ohlcv(self, candle, market=None):
        row = super().parse_ohlcv(candle, market)
        name = candle.get("n") if isinstance(candle, dict) else None
        if (self.options.get("defaultType") == "swap" and self.options.get("defaultSubType") in {"linear", "inverse"}
                and isinstance(name, str) and name.startswith("5m_")):
            # Gate Pro handles WS and REST candles with the same parser. The
            # subscription label is present on the Pro frame only.
            return [*row[:5], candle.get("v"), candle.get("w") is True]
        return row


def linear_contract_size(market: dict) -> Decimal:
    try:
        size = Decimal(str(market.get("contractSize")))
    except InvalidOperation as exc:
        raise ValueError("Invalid Gate linear contract size") from exc
    if market.get("swap") is not True or market.get("linear") is not True or not size.is_finite() or size <= 0:
        raise ValueError("Invalid Gate linear contract size")
    return size


def perpetual_volume_scale(market: dict, descriptor) -> Decimal:
    if descriptor.market_type != "swap.inverse":
        return linear_contract_size(market)
    if descriptor.series_identity != GATE_INVERSE_CONTRACTS:
        raise ValueError("Gate inverse 5m candles require volume_semantics=contract_count")
    if market.get("swap") is not True or market.get("inverse") is not True or market.get("settleId") != "btc":
        raise ValueError("Invalid Gate BTC-settled perpetual")
    return Decimal(1)


def candle_row(row, contracts, scale: Decimal) -> list:
    try:
        count = Decimal(str(contracts))
        volume = float(count * scale)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid Gate candle contract volume") from exc
    if not math.isfinite(volume) or count < 0:
        raise ValueError("Invalid Gate candle contract volume")
    return [*row[:5], volume]


async def fetch_perpetual_candles(exchange, symbol: str, req: TransportRequest, *, limit: int, now_ms: int) -> list[dict]:
    inverse = req.descriptor.market_type == "swap.inverse"
    if inverse and req.descriptor.series_identity != GATE_INVERSE_CONTRACTS:
        raise ValueError("Gate inverse 5m candles require volume_semantics=contract_count")
    width = _FIVE_MINUTES_MS
    end = min(req.end_ms if req.end_ms is not None else now_ms, now_ms) // width * width
    if req.start_ms is None:
        start = max(0, end - (limit - 1) * width)
    else:
        start = (req.start_ms + width - 1) // width * width
        end = min(end, start + (limit - 1) * width)
    if start > end:
        return []
    # The Gate futures endpoint returns an empty page for from=to. Extend
    # inside the final requested bucket and filter the returned opens locally.
    to_seconds = min(end // 1000 + 1, now_ms // 1000)
    if start // 1000 == to_seconds:
        return []

    market = exchange.market(symbol)
    scale = perpetual_volume_scale(market, req.descriptor)
    rows = await exchange.publicFuturesGetSettleCandlesticks({
        "contract": market["id"], "settle": market["settleId"], "interval": "5m",
        "from": start // 1000, "to": to_seconds,
    })
    candles = {}
    for raw in rows:
        row = exchange.parse_ohlcv(raw, market)
        opened = row[0]
        if type(opened) is not int or opened % width:
            raise ValueError("Invalid Gate perpetual candle boundary")
        if start <= opened <= end:
            if opened in candles:
                raise ValueError("Duplicate Gate perpetual candle")
            closed = opened + width <= now_ms
            candles[opened] = make_unified_payload(
                "kline", candle_row(row, raw.get("v"), scale),
                is_closed=closed, gate_rest_close_verified=closed,
            )
    return [candles[opened] for opened in sorted(candles)]
