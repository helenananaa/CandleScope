"""Chart-only tape aggregation, allowing an explicitly incomplete warmup head.

Execution builders require a complete display prefix. A review window may start
mid-bucket, so this reducer retains that truthful partial bar without relaxing
execution validation. Empty minutes fold by display bucket, not one minute at a
time. It owns no broker, source cursor, account or execution checkpoint.
"""

from collections import OrderedDict
from copy import copy
from decimal import Decimal, localcontext

from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.replay.bars.builder import (
    AGG_TRADE_SYNTHETIC_SOURCE,
    ReplayDisplayBar,
    assess_bar_builder_capability,
)
from app.replay.bars.trade_builder import _decimal_string, _FormingBaseBar, _sum
from app.replay.dataset import ReplayBar


class _ChartForming:
    """Keep Decimal accumulators until a chart observation, using scalar order.

    This is disposable display state. Each addition still uses precision 60,
    exactly as _FormingBaseBar.accumulate; only repeated string formatting and
    immutable object construction are removed from the per-trade path.
    """

    def __init__(self, trade, at, base):
        self.open_time_ms, self.close_time_ms = at, at + base - 1
        self.open = self.close = trade.price
        self.high = self.low = Decimal(trade.price)
        self.volume = Decimal(trade.quantity)
        self.quote_volume = Decimal(trade.quote_quantity)
        self.trades = trade.raw_trade_count
        self.taker_buy_base = Decimal(0) if trade.is_buyer_maker else self.volume
        self.taker_buy_quote = Decimal(0) if trade.is_buyer_maker else self.quote_volume

    def accumulate(self, trade):
        price, quantity, quote = (
            Decimal(trade.price),
            Decimal(trade.quantity),
            Decimal(trade.quote_quantity),
        )
        self.high, self.low = max(self.high, price), min(self.low, price)
        self.close = trade.price
        self.volume += quantity
        self.quote_volume += quote
        self.trades += trade.raw_trade_count
        if not trade.is_buyer_maker:
            self.taker_buy_base += quantity
            self.taker_buy_quote += quote

    def to_replay_bar(self):
        values = {
            field: _decimal_string(getattr(self, field), field)
            for field in (
                "high",
                "low",
                "volume",
                "quote_volume",
                "taker_buy_base",
                "taker_buy_quote",
            )
        }
        return _FormingBaseBar(
            open_time_ms=self.open_time_ms,
            close_time_ms=self.close_time_ms,
            open=self.open,
            close=self.close,
            trades=self.trades,
            **values,
        ).to_replay_bar()


class TapeChartBuilder:
    def __init__(
        self,
        *,
        base_interval,
        display_interval,
        replay_start_ms,
        replay_end_time_ms,
        warmup_bars=(),
        max_closed_bars=501,
    ):
        if not assess_bar_builder_capability(base_interval, display_interval).enabled:
            raise ValueError(
                "tape display interval cannot be tiled by its base interval"
            )
        self.base = parse_interval_ms(base_interval)
        self.base_interval = base_interval
        self.interval = display_interval
        self.width = parse_interval_ms(display_interval)
        self.start = self.next_base = replay_start_ms
        self.terminal = replay_end_time_ms
        self.capacity = max_closed_bars
        self.buckets = OrderedDict()
        self.forming = None
        self.previous_close = None
        self.last_trade = None
        self.finalized = False
        self.history_last_close = None
        self.append_history(warmup_bars)

    def fork(self):
        """Detach mutable display state; immutable bars/trades can be shared.

        An advancing observer must not change an older cached observation.
        The Decimal values themselves are immutable, but their forming-bar
        accumulator and the bucket collection are owned by each fork.
        """
        result = copy(self)
        result.buckets = self.buckets.copy()
        result.forming = None if self.forming is None else copy(self.forming)
        return result

    def append_history(self, bars):
        """Feed only older public base bars, in order, before tape execution."""
        self.append_indexed_history((bar, bar.open_time_ms, 1) for bar in bars)

    def append_indexed_history(self, summaries):
        """Append verified contiguous context summaries on the same base grid."""
        if self.last_trade is not None or self.forming is not None or self.finalized:
            raise ValueError("chart context cannot follow tape execution")
        for bar, last_base, count in summaries:
            if bar.close_time_ms >= self.start or (
                self.history_last_close is not None
                and bar.open_time_ms <= self.history_last_close
            ):
                raise ValueError(
                    "chart context overlaps its frozen execution or previous context"
                )
            self._feed(bar, last_base, count)
            self.previous_close = bar.close
            self.history_last_close = bar.close_time_ms

    def _merge(self, bar, last_base, count, closed=True):
        start = compute_bucket_start_ms(
            bar.open_time_ms, self.width, interval=self.interval
        )
        end = compute_bucket_end_ms(start, self.width, interval=self.interval)
        previous = self.buckets.get(start)
        expected = (end - start) // self.base
        first = bar.open_time_ms if previous is None else previous.first_base_open_ms
        components = count if previous is None else previous.component_count + count

        def total(field):
            value = getattr(bar, field)
            if previous is None:
                return value
            prior = getattr(previous, field)
            return (
                None
                if prior is None or value is None
                else prior + value
                if field == "trades"
                else _sum(prior, value, field)
            )

        return ReplayDisplayBar(
            open_time_ms=start,
            close_time_ms=end - 1,
            open=bar.open if previous is None else previous.open,
            high=bar.high
            if previous is None or Decimal(bar.high) > Decimal(previous.high)
            else previous.high,
            low=bar.low
            if previous is None or Decimal(bar.low) < Decimal(previous.low)
            else previous.low,
            close=bar.close,
            volume=total("volume"),
            quote_volume=total("quote_volume"),
            trades=total("trades"),
            taker_buy_base=total("taker_buy_base"),
            taker_buy_quote=total("taker_buy_quote"),
            first_base_open_ms=first,
            last_base_open_ms=last_base,
            component_count=components,
            expected_components=expected,
            is_closed=closed
            and first == start
            and components == expected
            and last_base + self.base == end,
            synthetic=(
                bar.source == AGG_TRADE_SYNTHETIC_SOURCE
                or (previous is not None and previous.synthetic)
            ),
        )

    def _feed(self, bar, last_base, count):
        value = self._merge(bar, last_base, count)
        self.buckets[value.open_time_ms] = value
        while len(self.buckets) > self.capacity:
            self.buckets.popitem(last=False)

    def _finish_forming(self):
        bar = self.forming.to_replay_bar()
        self._feed(bar, bar.open_time_ms, 1)
        self.previous_close = bar.close
        self.next_base = bar.close_time_ms + 1
        self.forming = None

    def _empty_until(self, target):
        while self.next_base < target:
            if self.previous_close is None:
                raise ValueError("empty leading tape interval lacks a previous close")
            start = compute_bucket_start_ms(
                self.next_base, self.width, interval=self.interval
            )
            end = min(
                target, compute_bucket_end_ms(start, self.width, interval=self.interval)
            )
            count = (end - self.next_base) // self.base
            if count < 1 or (end - self.next_base) % self.base:
                raise ValueError("empty tape span is not base aligned")
            price = self.previous_close
            bar = ReplayBar(
                open_time_ms=self.next_base,
                close_time_ms=self.next_base + self.base - 1,
                open=price,
                high=price,
                low=price,
                close=price,
                volume="0",
                quote_volume="0",
                trades=0,
                taker_buy_base="0",
                taker_buy_quote="0",
                source=AGG_TRADE_SYNTHETIC_SOURCE,
            )
            self._feed(bar, end - self.base, count)
            self.next_base = end

    def apply_trades_final_state(self, trades):
        if self.finalized:
            raise ValueError("tape chart is finalized")
        with localcontext() as context:
            context.prec = 60
            self._apply(trades)

    def _apply(self, trades):
        for trade in trades:
            if not self.start <= trade.trade_time_ms <= self.terminal or (
                self.last_trade is not None
                and (
                    trade.trade_time_ms < self.last_trade.trade_time_ms
                    or trade.agg_trade_id != self.last_trade.agg_trade_id + 1
                )
            ):
                raise ValueError(
                    "tape chart source is unordered or outside its frozen range"
                )
            at = compute_bucket_start_ms(
                trade.trade_time_ms, self.base, interval=self.base_interval
            )
            if self.forming is not None and self.forming.open_time_ms != at:
                self._finish_forming()
            if self.forming is None:
                self._empty_until(at)
                self.forming = _ChartForming(trade, at, self.base)
            else:
                self.forming.accumulate(trade)
            self.last_trade = trade

    def finalize_bars(self, *, virtual_time_ms):
        if virtual_time_ms != self.terminal:
            raise ValueError("tape chart terminal changed")
        if not self.finalized:
            if self.forming is not None:
                self._finish_forming()
            self._empty_until(self.terminal + 1)
            self.finalized = True

    def replace_projection(self):
        values = dict(self.buckets)
        if self.forming is not None:
            bar = self.forming.to_replay_bar()
            value = self._merge(bar, bar.open_time_ms, 1, closed=False)
            values[value.open_time_ms] = value
        return {"bars": [row.to_dict() for row in values.values()][-self.capacity :]}
