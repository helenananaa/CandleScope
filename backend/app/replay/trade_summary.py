"""Bounded immutable trade blocks: candles and ordered price extrema, no account state."""

from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal, localcontext
import asyncio

from app.data_engine.interval_policy import compute_bucket_start_ms
from .bars.trade_builder import _FormingBaseBar
from .broker.risk import mark_position
from .broker.models import decimal_to_string
from .sources.trade_reader import ReplayTrade

_CACHE = OrderedDict()
CACHE_BLOCKS = 8


def eligible(broker, trades):
    """Conservative exact-decimal domain; unusual precision uses the old reducer.

    Inputs occupy at most 25 decimal places across the decimal point. Products,
    subtraction and a bounded (8192 trade) sum therefore fit precision 60.
    """
    values = [
        broker._position.quantity,
        broker._position.entry_price or "0",
        broker._account.cash_balance,
        broker._equity_peak,
        broker._max_drawdown,
    ]
    for trade in trades:
        values.extend((trade.price, trade.quantity, trade.quote_quantity))
    forming = broker._bar_builder._forming
    if forming is not None:
        values.extend(
            (
                forming.volume,
                forming.quote_volume,
                forming.taker_buy_base,
                forming.taker_buy_quote,
            )
        )
    if len(trades) > 8192:
        return False
    for value in values:
        number = Decimal(value)
        if (not number.is_finite() or number.adjusted() > 12
                or number.as_tuple().exponent < -12):
            return False
    return True


@dataclass(frozen=True)
class TradeSummary:
    blocks: tuple
    low: Decimal
    high: Decimal
    fall: Decimal
    rise: Decimal


def prepare(trades, builder):
    key = (builder._base_interval, tuple(trades))
    found = _CACHE.get(key)
    if found is not None:
        _CACHE.move_to_end(key)
        return found
    blocks = []
    with localcontext() as ctx:
        ctx.prec = 60
        low = high = Decimal(trades[0].price)
        fall = rise = Decimal(0)
        prior = None
        current = None
        values = None
        for trade in trades:
            if not isinstance(trade, ReplayTrade):
                raise ValueError("trade summary requires validated trades")
            if prior is not None and (
                trade.agg_trade_id != prior.agg_trade_id + 1
                or trade.trade_time_ms < prior.trade_time_ms
                or (trade.exchange, trade.market_type, trade.symbol)
                != (prior.exchange, prior.market_type, prior.symbol)
            ):
                raise ValueError("trade summary source is not contiguous")
            price = Decimal(trade.price)
            high, low = max(high, price), min(low, price)
            fall, rise = max(fall, high - price), max(rise, price - low)
            at = builder._base_open(trade.trade_time_ms)
            if current != at:
                if values is not None:
                    blocks.append(tuple(values))
                current = at
                values = [
                    at,
                    trade,
                    trade,
                    1,
                    price,
                    price,
                    Decimal(trade.quantity),
                    Decimal(trade.quote_quantity),
                    trade.raw_trade_count,
                    Decimal(0),
                    Decimal(0),
                ]
            else:
                values[2] = trade
                values[3] += 1
                values[4], values[5] = max(values[4], price), min(values[5], price)
                values[6] += Decimal(trade.quantity)
                values[7] += Decimal(trade.quote_quantity)
                values[8] += trade.raw_trade_count
            if not trade.is_buyer_maker:
                values[9] += Decimal(trade.quantity)
                values[10] += Decimal(trade.quote_quantity)
            prior = trade
        blocks.append(tuple(values))
    found = TradeSummary(tuple(blocks), low, high, fall, rise)
    _CACHE[key] = found
    while len(_CACHE) > CACHE_BLOCKS:
        _CACHE.popitem(last=False)
    return found


def apply_candles(builder, summary):
    with localcontext() as ctx:
        ctx.prec = 60
        for (
            at,
            first,
            last,
            count,
            high,
            low,
            volume,
            quote,
            raw_count,
            taker,
            taker_quote,
        ) in summary.blocks:
            builder._validate_trade(first)
            if last.trade_time_ms > builder._replay_end_time_ms:
                raise ValueError("summary escaped replay end")
            forming = builder._forming
            next_sequence = builder._replay_events_applied + 1
            if forming is not None and at != forming.open_time_ms:
                if at < forming.open_time_ms:
                    raise ValueError("summary moved backwards")
                builder._append_finalized(
                    forming.to_replay_bar(),
                    [],
                    source_sequence=next_sequence,
                    project=False,
                )
                forming = None
            if forming is None:
                builder._append_empty_until(
                    at, [], source_sequence=next_sequence, project=False
                )
                opening = first.price
            else:
                opening = forming.open
                high, low = (
                    max(high, Decimal(forming.high)),
                    min(low, Decimal(forming.low)),
                )
                volume += Decimal(forming.volume)
                quote += Decimal(forming.quote_volume)
                raw_count += forming.trades
                taker += Decimal(forming.taker_buy_base)
                taker_quote += Decimal(forming.taker_buy_quote)

            def number(v):
                return decimal_to_string(v, field_name="trade summary")

            builder._forming = _FormingBaseBar(
                at,
                builder._base_end(at) - 1,
                opening,
                number(high),
                number(low),
                last.price,
                number(volume),
                number(quote),
                raw_count,
                number(taker),
                number(taker_quote),
            )
            builder._replay_events_applied += count
            builder._last_trade_time_ms = last.trade_time_ms
            builder._last_agg_trade_id = last.agg_trade_id
        builder._last_projected_open_ms = compute_bucket_start_ms(
            at, builder._display_interval_ms, interval=builder._display_interval
        )


def apply(broker, trades):
    if broker.open_orders or broker._ended or not hasattr(broker._position, "quantity"):
        raise ValueError(
            "trade summary requires an active ONE_WAY broker without orders"
        )
    if len(trades) < 4 or not eligible(broker, trades):
        broker.apply_source_events_final_state(trades)
        return False
    summary = prepare(trades, broker._bar_builder)
    with localcontext() as ctx:
        ctx.prec = 60
        quantity = Decimal(broker._position.quantity)
        cash = Decimal(broker._account.cash_balance)
        entry = Decimal(broker._position.entry_price or "0")
        low, high = sorted(
            cash + (p - entry) * quantity for p in (summary.low, summary.high)
        )
        drawdown = abs(quantity) * (summary.fall if quantity >= 0 else summary.rise)
        broker._max_drawdown = decimal_to_string(
            max(
                Decimal(broker._max_drawdown),
                drawdown,
                Decimal(broker._equity_peak) - low,
            ),
            field_name="max drawdown",
        )
        broker._equity_peak = decimal_to_string(
            max(Decimal(broker._equity_peak), high), field_name="equity peak"
        )
        apply_candles(broker._bar_builder, summary)
        broker._position = mark_position(broker._position, trades[-1].price)
        broker._account = broker._account_from(broker._ledger, broker._position)
        broker._assert_invariants()
    return True


async def advance(actor, target, count, *, prepared=None):
    trades = []
    start_sequence = actor._source.cursor().source_sequence
    for i in range(count):
        event = actor._source.next() if prepared is None else prepared.trades[i]
        if not isinstance(event, ReplayTrade) or event.trade_time_ms > target:
            raise ValueError("trade summary lost source basis")
        trades.append(event)
        actor._event_chain_hash = actor._next_chain_hash(
            actor._event_chain_hash, event,
            (actor._source.cursor().source_sequence if prepared is None
             else start_sequence + i + 1),
        )
        if i % 64 == 63:
            await asyncio.sleep(0)
    if prepared is not None:
        actor._source = prepared.end.fork()
    if trades:
        actor._invalidate_component_state()
        if actor._source.exhausted():
            raise ValueError("trade summary must retain an exact terminal tail")
        summarized = apply(actor._reducer, trades)
    else:
        summarized = False
    actor._clock.advance_to(target)
    actor._metrics["events_processed"] += count
    actor._metrics["tape_summary_events"] = actor._metrics.get(
        "tape_summary_events", 0
    ) + (count if summarized else 0)
    return count
