"""Prepared immutable BAR states and associative account range summaries.

Preparation scans once. A jump evaluates a logarithmic range query and replays
at most STRIDE-1 builder bars, never the account reducer for the skipped span.
"""

from bisect import bisect_right
from copy import copy
from decimal import Decimal, localcontext

from ..canonical import canonical_sha256
from ..errors import ReplayDomainError
from .execution import mark_position
from .interval_index import BarInteractionIndex, PriceRangeIndex
from .models import OrderType, OrderSide, decimal_to_string
from .prepared_display import PreparedDisplay
from ..dataset import ReplayBar

STRIDE = 128


def freeze_builder(builder):
    result = copy(builder)
    result._closed_bars = list(builder._closed_bars)
    result._prepared_closed_hashes = None
    return result


class EquityRanges:
    def __init__(self, values):
        self.size = 1
        while self.size < len(values):
            self.size *= 2
        self.nodes = [None] * (self.size * 2)
        for i, value in enumerate(values):
            self.nodes[self.size + i] = (value, value, Decimal(0))
        with localcontext() as context:
            context.prec = 60
            for i in range(self.size - 1, 0, -1):
                self.nodes[i] = self.merge(self.nodes[2 * i], self.nodes[2 * i + 1])

    @staticmethod
    def merge(left, right):
        if left is None:
            return right
        if right is None:
            return left
        return (
            max(left[0], right[0]),
            min(left[1], right[1]),
            max(left[2], right[2], left[0] - right[1]),
        )

    def query(self, start, end):
        left, right = start + self.size, end + self.size
        before = after = None
        with localcontext() as context:
            context.prec = 60
            while left < right:
                if left & 1:
                    before = self.merge(before, self.nodes[left])
                    left += 1
                if right & 1:
                    right -= 1
                    after = self.merge(self.nodes[right], after)
                left //= 2
                right //= 2
            return self.merge(before, after)


class PreparedBarInterval:
    def __init__(self, source, builder, chain_hash, next_hash, *, limit=100_000):
        self.start = source.cursor().source_sequence
        reference = (
            source.snapshot_ref()
            if callable(getattr(source, "snapshot_ref", None))
            else {}
        )
        reference = reference.to_dict() if hasattr(reference, "to_dict") else reference
        revision = reference.get("source_revision") or getattr(
            getattr(getattr(source, "_snapshot", None), "provenance", None),
            "source_revision",
            None,
        )
        prefix = {}
        if builder._display_interval == builder._base_interval:
            for value in builder._closed_bars:
                if value.component_count == 1 and not value.synthetic:
                    prefix[value.open_time_ms] = ReplayBar(
                        open_time_ms=value.open_time_ms,
                        close_time_ms=value.close_time_ms,
                        **{
                            key: getattr(value, key)
                            for key in (
                                "open",
                                "high",
                                "low",
                                "close",
                                "volume",
                                "quote_volume",
                                "trades",
                                "taker_buy_base",
                                "taker_buy_quote",
                            )
                        },
                        source="prepared-snapshot",
                    )
        prefix_factory = getattr(source, "prefix_for_index", None)
        if callable(prefix_factory):
            earlier = prefix_factory(20_160)
            try:
                while earlier.cursor().source_sequence < self.start:
                    event = earlier.next()
                    if event is None:
                        break
                    prefix[event.open_time_ms] = event
            except (ReplayDomainError, ValueError, OSError):
                pass
        self.builder_key = self.configuration(builder)
        self.builders = {0: freeze_builder(builder)}
        current = freeze_builder(builder)
        current._prepared_closed_hashes = {}
        self.bars = []
        self.chains = [chain_hash]
        stopped_on_error = False
        while len(self.bars) < limit:
            try:
                event = source.next()
                if event is None:
                    break
                current.apply_bars_final_state((event,))
            except (ReplayDomainError, ValueError, OSError):
                # An invalid future row must not prevent advancing a valid
                # earlier prefix. Its ordinary execution path reports it when
                # the cursor actually reaches that boundary.
                stopped_on_error = True
                break
            self.bars.append(event)
            self.chains.append(
                next_hash(self.chains[-1], event, self.start + len(self.bars))
            )
            if len(self.bars) % STRIDE == 0:
                self.builders[len(self.bars)] = freeze_builder(current)
        # The terminal event stays on the ordinary execution path.
        self.terminal = not stopped_on_error and source.exhausted()
        self.times = tuple(bar.close_time_ms for bar in self.bars)
        self.interactions = BarInteractionIndex(self.bars)
        self.closes = PriceRangeIndex(
            [(Decimal(bar.close), Decimal(bar.close)) for bar in self.bars]
        )
        self.display_prefix = [prefix[time] for time in sorted(prefix)]
        display_bars = self.display_prefix + self.bars
        self.display = PreparedDisplay(
            display_bars, builder._base_interval_ms, revision
        )
        self.valuation = None

    @staticmethod
    def configuration(builder):
        return (
            builder._base_interval,
            builder._display_interval,
            builder._max_closed_bars,
            builder._warmup_fingerprint,
            builder._gap_policy,
            builder._synthetic_policy,
        )

    def compatible(self, source, builder, chain_hash):
        offset = source.cursor().source_sequence - self.start
        return (
            self.configuration(builder) == self.builder_key
            and 0 <= offset <= len(self.bars)
            and (offset < len(self.bars) or self.terminal)
            and self.chains[offset] == chain_hash
        )

    def end_for_time(self, target):
        return max(
            0,
            min(bisect_right(self.times, target), len(self.bars) - int(self.terminal)),
        )

    def safe_end(self, broker, start, end):
        for order in broker.open_orders:
            eligible = max(start, order.accepted_source_sequence - self.start)
            if eligible >= end:
                continue
            if order.order_type is OrderType.MARKET:
                end = eligible
                continue
            price = (
                order.limit_price
                if order.order_type is OrderType.LIMIT
                else order.stop_price
            )
            below = (
                order.side is OrderSide.SELL
                if order.order_type is OrderType.STOP_MARKET
                else order.side is OrderSide.BUY
            )
            end = min(
                end,
                self.interactions.first_touch(
                    Decimal(price), below=below, start=eligible, end=end
                ),
            )
        return end

    def prepare_valuation(self, broker):
        position = broker._position.to_dict()
        for leg in (position, position.get("long", {}), position.get("short", {})):
            for field in ("mark_price", "notional", "unrealized_pnl"):
                leg.pop(field, None)
        key = canonical_sha256(
            {
                "algorithm": "prepared-valuation.v1",
                "execution_model": broker._model_version,
                "position": position,
                "ledger": broker._ledger.snapshot(),
                "config": broker._config_hash,
            }
        )
        if self.valuation is not None and self.valuation["key"] == key:
            return self.valuation
        flat = (
            all(Decimal(position[side]["quantity"]) == 0 for side in ("long", "short"))
            if position.get("position_mode") == "HEDGE"
            else Decimal(position["quantity"]) == 0
        )
        if flat:
            account = broker._account_from(broker._ledger, broker._position)
            samples = [
                (account.equity, account.cash_balance, account.unrealized_pnl)
            ] * len(self.bars)
        else:
            samples = []
            for bar in self.bars:
                account = broker._account_from(
                    broker._ledger, mark_position(broker._position, bar.close)
                )
                samples.append(
                    (account.equity, account.cash_balance, account.unrealized_pnl)
                )
        self.valuation = {
            "key": key,
            "samples": samples,
            "ranges": EquityRanges([Decimal(row[0]) for row in samples]),
            "ledger_hash": broker._ledger.snapshot()["tail_hash"],
        }
        return self.valuation

    def builder_at(self, end):
        checkpoint = end // STRIDE * STRIDE
        builder = freeze_builder(self.builders[checkpoint])
        builder.apply_bars_final_state(self.bars[checkpoint:end])
        return builder

    def apply(self, broker, start, end):
        valuation = self.prepare_valuation(broker)
        peak, trough, drawdown = valuation["ranges"].query(start, end)
        with localcontext() as context:
            context.prec = 60
            broker._max_drawdown = decimal_to_string(
                max(
                    Decimal(broker._max_drawdown),
                    drawdown,
                    Decimal(broker._equity_peak) - trough,
                ),
                field_name="max drawdown",
            )
            broker._equity_peak = decimal_to_string(
                max(Decimal(broker._equity_peak), peak), field_name="equity peak"
            )
        broker._bar_builder = self.builder_at(end)
        broker._position = mark_position(broker._position, self.bars[end - 1].close)
        broker._account = broker._account_from(broker._ledger, broker._position)
        broker._assert_invariants()
