"""Training-local view over shared immutable market ranges.

No future per-minute account snapshots or chained builder states are prepared.
Range references are explicitly versioned by the internal shared command.
"""

from collections.abc import Sequence
from copy import copy
from decimal import Decimal, localcontext

from ..canonical import canonical_sha256
from ..dataset import ReplayBar
from .models import LedgerAccount, decimal_to_string
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


account_sample_visits = 0


def account_sample(basis, close):
    global account_sample_visits
    account_sample_visits += 1
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


def prefetch_account_samples(basis, offsets):
    """Evaluate selected offsets with chunked market reads."""

    market = basis.get("market_view")
    if market is None:
        return
    unique = sorted({int(offset) for offset in offsets})
    closes = market.closes_at(unique)
    cache = basis.setdefault("_sample_cache", {})
    for offset, close in zip(unique, closes):
        if offset not in cache:
            cache[offset] = account_sample(basis["account"], close)


class AccountRanges:
    def __init__(self, index, basis):
        self.index, self.basis = index, basis

    def query(self, start, end):
        if start == end:
            return None
        if not any(Decimal(q) for q, _ in self.basis["legs"]):
            cash = Decimal(self.basis["cash"])
            return cash, cash, Decimal(0)
        summary = self.index.market.summary(start, end, prices_only=True)
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
        exact = 2 * (adjusted - scale + 1) + 4 <= 60
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
        value = self.market.summary(start, end, prices_only=True)
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
        a, b = self.market.bound(start), self.market.bound(end)
        value = self.market.summary(a, b)
        return None if value is None else value[0]


class SharedPreparedInterval(PreparedBarInterval):
    shared = True

    def end_for_time(self, target):
        end = self.market.bound(target, right=True)
        # The latest opened candle may still be forming. Inspect its actual
        # close, preserving calendar intervals rather than assuming fixed ms.
        if end and self.market.row(end-1)[1] > target:
            end -= 1
        return max(0, min(end, self.market.count-int(self.terminal)))

    def __init__(self, source, broker, chain_hash):
        builder = broker._bar_builder
        if builder._base_interval != builder._display_interval:
            raise ValueError("shared preparation requires a base-bar adapter")
        result = source.shared_market_range()
        if result is None:
            raise ValueError("shared market range is unavailable")
        self.market, self.terminal = result
        self.source_archive = getattr(source, "_archive", None)
        self.source_reference = source.snapshot_ref()
        self.market.prepare_nodes()
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
        # The source's positional cursor can start at the replay boundary.
        # Include immutable history before that boundary for small UI tails;
        # otherwise the first daily/weekly acknowledgement falls back to a
        # large raw-bar reconstruction despite a prepared market index.
        display_first = max(0, min(display_first, self.market.row(0)[0] - 20_160 * self.market.base_ms))
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

    def rebased(self, source, broker, chain_hash):
        """Rebind the command seed/origin, reusing only immutable market data.

        A terminal-covering suffix has exactly the same range reference as a
        cold factory query. Limited non-terminal windows must prepare normally.
        """
        offset = source.cursor().source_sequence-self.start
        current_key = self.configuration(broker._bar_builder)
        if (not self.terminal or not 0 <= offset < self.market.count
                or self.source_archive is None or getattr(source, "_archive", None) is not self.source_archive
                or source.snapshot_ref() != self.source_reference
                or self.builder_key[:2]+self.builder_key[3:] != current_key[:2]+current_key[3:]
                or self.chains[offset] != chain_hash):
            return None
        result = copy(self)
        result.market = self.market.slice(offset, self.market.count)
        result.start = source.cursor().source_sequence
        result.builder_key = current_key
        result.origin = freeze_builder(broker._bar_builder)
        result._transport_origins = {}
        result.seed = chain_hash
        result.reference = result.market.reference()
        result.bars = LazySequence(result.market.count, result._bar)
        result.times = LazySequence(result.market.count, lambda i: result.market.row(i)[1])
        result.chains = LazySequence(result.market.count+1, result._chain)
        result.interactions = InteractionRanges(result.market)
        result.closes = CloseRanges(result.market)
        result.valuation = None
        result.prepare_valuation(broker)
        return result

    def prepare_valuation(self, broker):
        position = broker._position.to_dict()
        legs = (
            [position[side] for side in ("long", "short")]
            if "long" in position
            else [position]
        )
        basis = {
            "legs": [[leg["quantity"], leg["entry_price"] or "0"] for leg in legs],
            "cash": broker._ledger.account_total(LedgerAccount.CASH),
        }
        key = canonical_sha256(
            {
                "schema": "shared-valuation.v2",
                "basis": basis,
                "model": broker._model_version,
                "config": broker._config_hash,
                "ledger_tail": broker._ledger.tail_hash,
            }
        )
        if self.valuation is not None and self.valuation["key"] == key:
            return self.valuation
        self.valuation = {
            "key": key,
            "basis": basis,
            "ranges": AccountRanges(self, basis),
            "ledger_hash": broker._ledger.tail_hash,
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

    def prepare_transport_tail(self, tail_limit=16):
        """Cache only a compact copy of already revealed market bars."""
        origins = getattr(self, "_transport_origins", None)
        if origins is None:
            origins = self._transport_origins = {}
        if tail_limit not in origins:
            origins[tail_limit] = self.builder_at(0, tail_limit=tail_limit)

    def builder_at(self, end, *, tail_limit=None):
        origin = getattr(self, "_transport_origins", {}).get(tail_limit, self.origin)
        builder = freeze_builder(origin)
        retained = builder._max_closed_bars if tail_limit is None else min(builder._max_closed_bars, tail_limit)
        if tail_limit is not None:
            # Persist the explicit transport-tail capacity so v1 restore checks
            # remain strict. Historical queries use the immutable source anchor.
            builder._max_closed_bars = retained
        skipped = max(0, end - retained)
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
        elif len(builder._closed_bars) > retained:
            # A short first interval may start with a much larger warmup tail.
            # Trim that already-closed prefix before append's one-row eviction;
            # otherwise the declared compact capacity and checkpoint disagree.
            remove = len(builder._closed_bars) - retained
            for bar in builder._closed_bars[:remove]:
                ordinal = builder._closed_prefix_count + 1
                builder._closed_prefix_hash = builder._next_closed_chain_hash(
                    builder._closed_prefix_hash, ordinal, bar)
                builder._closed_prefix_count = ordinal
            builder._closed_bars = builder._closed_bars[remove:]
            builder._closed_encoding_cache = {}
        builder.apply_bars_final_state(self.bars[skipped:end])
        return builder


def restore_legacy_curve(basis):
    from types import SimpleNamespace
    from ..source_chain import next_source_chain_hash
    from .prepared_interval import _PreparedChains
    bars = [ReplayBar(**row) for row in basis["bars"]]
    if basis["chain_mode"] not in {"legacy", "range"}:
        raise ValueError("unknown legacy curve chain mode")
    owner = SimpleNamespace(bars=bars, start=basis["start"], _chain_seed=basis["seed"],
                            _next_hash=next_source_chain_hash if basis["chain_mode"] == "legacy" else None)
    return {**basis, "samples": LazySequence(len(bars), lambda i: account_sample(basis["account"], bars[i].close)),
            "times": [bar.close_time_ms for bar in bars], "chains": _PreparedChains(owner)}


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

    cache = {}

    def sample_at(index):
        cached = cache.get(index)
        if cached is not None:
            return cached
        value = account_sample(basis["account"], market.row(index)[5])
        cache[index] = value
        return value

    restored = {
        **basis,
        "market_view": market,
        "_sample_cache": cache,
        "samples": LazySequence(market.count, sample_at),
        "times": LazySequence(market.count, lambda i: market.row(i)[1]),
        "chains": LazySequence(market.count + 1, chain),
    }
    return restored
