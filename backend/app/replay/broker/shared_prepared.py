"""Training-local view over shared immutable market ranges.

No future per-minute account snapshots or chained builder states are prepared.
Range references are explicitly versioned by the internal shared command.
"""

from bisect import bisect_left
from collections.abc import Sequence
from decimal import Decimal, localcontext

from ..canonical import canonical_sha256
from ..dataset import ReplayBar
from .models import decimal_to_string
from .prepared_interval import PreparedBarInterval, freeze_builder
from .prepared_display import PreparedDisplay


class LazySequence(Sequence):
    def __init__(self, count, getter):
        self.count, self.getter = count, getter

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self.getter(i) for i in range(*index.indices(self.count))]
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError(index)
        return self.getter(index)


def account_sample(basis, close):
    with localcontext() as context:
        context.prec = 60
        price = Decimal(close)
        pnls = [
            (price - Decimal(entry)) * Decimal(quantity)
            if Decimal(quantity)
            else Decimal(0)
            for quantity, entry in basis["legs"]
        ]
        pnl = sum(pnls, Decimal(0))
        cash = Decimal(basis["cash"])
        return tuple(
            decimal_to_string(value, field_name="equity")
            for value in (cash + pnl, cash, pnl)
        )


class AccountRanges:
    def __init__(self, index, basis):
        self.index, self.basis = index, basis

    def query(self, start, end):
        if start == end:
            return None
        if not any(Decimal(q) for q, _ in self.basis["legs"]):
            cash = Decimal(self.basis["cash"])
            return cash, cash, Decimal(0)
        summary = self.index.market.summary(start, end)
        if summary is None:
            return None
        basis = self.basis
        quantities = [Decimal(q) for q, _ in basis["legs"]]
        with localcontext() as context:
            context.prec = 1000
            quantity = sum(quantities, Decimal(0))
        # When all intermediate affine calculations fit within the original
        # 60-digit context, price extrema and ordered up/down pairs are exact
        # account extrema. Unusual precision uses the original scalar formula.
        operands = [Decimal(basis["cash"])] + [
            Decimal(v) for leg in basis["legs"] for v in leg
        ]
        scale = min([summary[5]] + [v.as_tuple().exponent for v in operands])
        adjusted = max([summary[6]] + [v.adjusted() for v in operands])
        exact = (
            2 * (adjusted - scale + 1) + 4 <= 60
            and sum(bool(q) for q in quantities) <= 1
        )
        if not exact:
            from .prepared_interval import EquityRanges

            values = [
                Decimal(account_sample(basis, self.index.market.row(i)[5])[0])
                for i in range(start, end)
            ]
            return EquityRanges(values).query(0, len(values))
        low = Decimal(account_sample(basis, str(summary[1]))[0])
        high = Decimal(account_sample(basis, str(summary[2]))[0])
        pair = summary[3] if quantity >= 0 else summary[4]
        a, b = (Decimal(account_sample(basis, str(price))[0]) for price in pair)
        with localcontext() as context:
            context.prec = 60
            return max(low, high), min(low, high), max(Decimal(0), a - b)


class CloseRanges:
    def __init__(self, market):
        self.market = market

    def range_bounds(self, *, start, end):
        value = self.market.summary(start, end)
        return None if value is None else (value[1], value[2])


class InteractionRanges:
    def __init__(self, market):
        self.market = market

    def first_touch(self, price, *, below, start, end):
        return self.market.first_touch(price, below, start, end)


class SharedDisplay(PreparedDisplay):
    def __init__(self, market, revision):
        self.market, self.revision, self.base_ms = market, revision, market.base_ms
        self.opens = LazySequence(market.count, lambda i: market.row(i)[0])

    def range(self, start, end):
        a, b = bisect_left(self.opens, start), bisect_left(self.opens, end)
        value = self.market.summary(a, b)
        return None if value is None else value[0]


class SharedPreparedInterval(PreparedBarInterval):
    shared = True

    def __init__(self, source, broker, chain_hash):
        builder = broker._bar_builder
        if builder._base_interval != builder._display_interval:
            raise ValueError("shared preparation requires a base-bar adapter")
        result = source.shared_market_range()
        if result is None:
            raise ValueError("shared market range is unavailable")
        self.market, self.terminal = result
        self.start = source.cursor().source_sequence
        self.builder_key = self.configuration(builder)
        self.origin = freeze_builder(builder)
        self.seed = chain_hash
        self.reference = self.market.reference()
        self.bars = LazySequence(self.market.count, self._bar)
        self.times = LazySequence(self.market.count, lambda i: self.market.row(i)[1])
        self.chains = LazySequence(self.market.count + 1, self._chain)
        self.interactions = InteractionRanges(self.market)
        self.closes = CloseRanges(self.market)
        self.valuation = None
        revision = source.snapshot_ref().get("source_revision")
        # Include revealed history in the display view without preparing it.
        factory = getattr(source._archive, "shared_factory", None)
        first = max(0, source._index - 20_160)
        display_first = source._archive.open_at_index(first)
        if builder._closed_bars:
            display_first = min(display_first, builder._closed_bars[0].open_time_ms)
        display_market = factory(
            display_first, self.market.row(self.market.count - 1)[1] + 1
        )
        self.display = SharedDisplay(display_market or self.market, revision)
        self.prepare_valuation(broker)

    def _bar(self, index):
        bar = ReplayBar(*self.market.row(index))
        object.__setattr__(bar, "_normalized_values_validated", True)
        return bar

    def _chain(self, end):
        if end == 0:
            return self.seed
        return canonical_sha256(
            {
                "schema": "shared-source-range.v1",
                "previous": self.seed,
                "market": self.reference,
                "start_sequence": self.start,
                "end": end,
            }
        )

    def compatible(self, source, builder, chain_hash):
        return (
            source.cursor().source_sequence == self.start
            and self.seed == chain_hash
            and self.configuration(builder) == self.builder_key
        )

    def prepare_valuation(self, broker):
        position = broker._position.to_dict()
        legs = (
            [position[side] for side in ("long", "short")]
            if "long" in position
            else [position]
        )
        account = broker._account_from(broker._ledger, broker._position)
        basis = {
            "legs": [[leg["quantity"], leg["entry_price"] or "0"] for leg in legs],
            "cash": account.cash_balance,
        }
        key = canonical_sha256(
            {
                "schema": "shared-valuation.v1",
                "basis": basis,
                "model": broker._model_version,
                "config": broker._config_hash,
                "ledger": broker._ledger.snapshot(),
            }
        )
        if self.valuation is not None and self.valuation["key"] == key:
            return self.valuation
        self.valuation = {
            "key": key,
            "basis": basis,
            "ranges": AccountRanges(self, basis),
            "ledger_hash": broker._ledger.snapshot()["tail_hash"],
        }
        return self.valuation

    def curve_basis(self):
        return {
            "schema": "shared-curve.v1",
            "market": self.market.descriptor(),
            "reference": self.reference,
            "start": self.start,
            "seed": self.seed,
            "account": self.valuation["basis"],
            "ledger_hash": self.valuation["ledger_hash"],
        }

    def builder_at(self, end):
        builder = freeze_builder(self.origin)
        skipped = max(0, end - builder._max_closed_bars)
        if skipped:
            prefix = canonical_sha256(
                {
                    "schema": "shared-builder-prefix.v1",
                    "previous": builder._closed_chain_hash,
                    "market": self.reference,
                    "end": skipped,
                }
            )
            builder._closed_count += skipped
            builder._closed_prefix_count = builder._closed_count
            builder._closed_prefix_hash = builder._closed_chain_hash = prefix
            builder._closed_bars = []
            builder._closed_encoding_cache = {}
            builder._active_bar = None
            builder._replay_events_applied += skipped
            builder._last_base_open_ms = self.market.row(skipped - 1)[0]
        builder.apply_bars_final_state(self.bars[skipped:end])
        return builder


def restore_curve(basis):
    from ..shared_market_index import MarketRange

    market = MarketRange.restore(basis["market"])

    def chain(end):
        return canonical_sha256(
            {
                "schema": "shared-source-range.v1",
                "previous": basis["seed"],
                "market": basis["reference"],
                "start_sequence": basis["start"],
                "end": end,
            }
        )

    return {
        **basis,
        "samples": LazySequence(
            market.count, lambda i: account_sample(basis["account"], market.row(i)[5])
        ),
        "times": LazySequence(market.count, lambda i: market.row(i)[1]),
        "chains": LazySequence(market.count + 1, chain),
    }
