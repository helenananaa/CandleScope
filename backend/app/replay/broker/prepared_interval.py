"""Prepared immutable BAR states and associative account range summaries.

Preparation indexes market summaries once and defers account samples. Legacy
builder/hash reconstruction retains exact per-event semantics; its first large
jump may scan the span. Native shared indexes use the separate bounded path.
"""

from bisect import bisect_right
from copy import copy
from decimal import Decimal, localcontext

from ..canonical import canonical_sha256
from ..errors import ReplayDomainError
from .execution import mark_position
from .interval_index import BarInteractionIndex, PriceRangeIndex
from .models import LedgerAccount, OrderType, OrderSide, decimal_to_string
from .prepared_display import PreparedDisplay
from ..dataset import ReplayBar

STRIDE = 128


class _BarListMarket:
    def __init__(self, bars, base_ms):
        self.bars = bars
        self.base_ms = base_ms
        self.count = len(bars)
        from ..shared_market_index import summarize, merge
        self.block_size = 256
        blocks = (self.count + self.block_size - 1) // self.block_size
        self.tree_size = 1 << max(0, (blocks - 1).bit_length())
        self.tree = [None] * (2 * self.tree_size)
        for block in range(blocks):
            start = block * self.block_size
            self.tree[self.tree_size + block] = summarize(
                [self.row(i) for i in range(start, min(start + self.block_size, self.count))], base_ms
            )
        for i in range(self.tree_size - 1, 0, -1):
            self.tree[i] = merge(self.tree[2 * i], self.tree[2 * i + 1], base_ms)

    def row(self, index):
        bar = self.bars[index]
        return (
            bar.open_time_ms,
            bar.close_time_ms,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.quote_volume,
            bar.trades,
            bar.taker_buy_base,
            bar.taker_buy_quote,
            getattr(bar, "source", "prepared"),
        )

    def summary(self, start, end):
        from ..shared_market_index import summarize, merge
        if not 0 <= start <= end <= self.count:
            raise IndexError("market summary bounds")
        if start == end:
            return None
        width = self.block_size
        left_end = min(end, ((start + width - 1) // width) * width)
        result = summarize([self.row(i) for i in range(start, left_end)], self.base_ms) if left_end > start else None
        right_start = max(left_end, (end // width) * width)
        left, right = left_end // width + self.tree_size, right_start // width + self.tree_size
        lhs, rhs = None, None
        while left < right:
            if left & 1:
                lhs = merge(lhs, self.tree[left], self.base_ms)
                left += 1
            if right & 1:
                right -= 1
                rhs = merge(self.tree[right], rhs, self.base_ms)
            left //= 2
            right //= 2
        result = merge(result, merge(lhs, rhs, self.base_ms), self.base_ms)
        tail = summarize([self.row(i) for i in range(right_start, end)], self.base_ms) if right_start < end else None
        return merge(result, tail, self.base_ms)


class _PreparedChains:
    def __init__(self, interval):
        self.interval = interval
        self._cache = {0: interval._chain_seed}

    def __len__(self):
        return len(self.interval.bars) + 1

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[item] for item in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if index in self._cache:
            return self._cache[index]
        hasher = self.interval._next_hash
        if hasher is None:
            seed = self.interval._chain_seed
            value = canonical_sha256(
                {
                    "schema": "prepared-source-range.v1",
                    "previous": seed,
                    "start_sequence": self.interval.start,
                    "end": index,
                }
            )
            self._cache[index] = value
            return value
        last = len(self._cache) - 1
        value = self._cache[last]
        for step in range(last + 1, index + 1):
            value = hasher(
                value, self.interval.bars[step - 1], self.interval.start + step
            )
            self._cache[step] = value
        return value

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]


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
        self.bars = []
        self._chain_seed = chain_hash
        self._next_hash = next_hash
        stopped_on_error = False
        while len(self.bars) < limit:
            try:
                event = source.next()
                if event is None:
                    break
            except (ReplayDomainError, ValueError, OSError):
                # An invalid future row must not prevent advancing a valid
                # earlier prefix. Its ordinary execution path reports it when
                # the cursor actually reaches that boundary.
                stopped_on_error = True
                break
            self.bars.append(event)
        # The terminal event stays on the ordinary execution path.
        self.terminal = not stopped_on_error and source.exhausted()
        self.times = tuple(bar.close_time_ms for bar in self.bars)
        self.chains = _PreparedChains(self)
        self.market = _BarListMarket(self.bars, builder._base_interval_ms)
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
        from .shared_prepared import AccountRanges, LazySequence, account_sample

        position = broker._position.to_dict()
        for leg in (position, position.get("long", {}), position.get("short", {})):
            for field in ("mark_price", "notional", "unrealized_pnl"):
                leg.pop(field, None)
        legs = (
            [position[side] for side in ("long", "short")]
            if "long" in position
            else [position]
        )
        basis = {
            "legs": [[leg["quantity"], leg.get("entry_price") or "0"] for leg in legs],
            "cash": broker._ledger.account_total(LedgerAccount.CASH),
        }
        key = canonical_sha256(
            {
                "algorithm": "prepared-valuation.v2",
                "execution_model": broker._model_version,
                "basis": basis,
                "ledger_tail": broker._ledger.tail_hash,
                "config": broker._config_hash,
            }
        )
        if self.valuation is not None and self.valuation["key"] == key:
            return self.valuation
        bars = self.bars
        self.valuation = {
            "key": key,
            "basis": basis,
            "ranges": AccountRanges(self, basis),
            "ledger_hash": broker._ledger.tail_hash,
            "samples": LazySequence(
                len(bars), lambda index: account_sample(basis, bars[index].close)
            ),
        }
        return self.valuation

    def curve_market_key(self):
        cached = getattr(self, "_curve_market_key", None)
        if cached is None:
            from ..source_chain import source_event_payload
            self._curve_bars = [source_event_payload(bar) for bar in self.bars]
            self._curve_market_key = canonical_sha256({"bars": self._curve_bars, "seed": self._chain_seed, "start": self.start})
        return self._curve_market_key

    def curve_basis(self):
        self.curve_market_key()
        return {"schema": "prepared-curve.v2", "start": self.start,
                "bars": self._curve_bars, "seed": self._chain_seed,
                "chain_mode": "legacy" if self._next_hash is not None else "range",
                "account": self.valuation["basis"], "ledger_hash": self.valuation["ledger_hash"]}

    def materialize_legacy_chains(self):
        """Compatibility path for archives that must explain old per-event hashes."""

        hasher = self._next_hash
        if hasher is None:
            raise ValueError("legacy chain materialization requires the original hasher")
        chains = [self._chain_seed]
        for index, event in enumerate(self.bars, start=1):
            chains.append(hasher(chains[-1], event, self.start + index))
        self.chains = chains
        return chains

    def builder_at(self, end):
        checkpoint = max((offset for offset in self.builders if offset <= end), default=0)
        builder = freeze_builder(self.builders[checkpoint])
        aligned = end // STRIDE * STRIDE
        if aligned > checkpoint:
            builder.apply_bars_final_state(self.bars[checkpoint:aligned])
            self.builders[aligned] = freeze_builder(builder)
            checkpoint = aligned
            builder = freeze_builder(self.builders[aligned])
        if end > checkpoint:
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
