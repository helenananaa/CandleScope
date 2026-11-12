"""
L3: Bar State Engine — maintains OHLCV accumulation state per time bucket.

Responsibilities:
  * Create new BarState when a new bucket is encountered
  * Apply incoming BarInput to the appropriate BarState using merge rules
  * Track active (FORMING) bars and recently closed bars in memory
  * Auto-evict old bars to prevent unbounded memory growth
  * Support user-customizable merge strategies (default: standard OHLCV)

The default OHLCV merge rule is:
  O = first Open,  H = max(High),  L = min(Low),  C = last Close,  V = sum(Volume)

Users can override this by providing a ``BarMergeStrategy`` implementation.

Usage::

    engine = BarStateEngine(config, time_bucket)
    state, change = engine.apply("BTCUSDT", "1m", bucket_start, bar_input)
"""
from __future__ import annotations

from app.data_engine.kline_quality import BYBIT_WS_CONFIRMED_SOURCE
from app.data_engine.readonly import ReadonlyFields
from app.data_engine.aggregation.adapters import (
    snapshot_aggregation_values, snapshot_coverage, snapshot_field_summary,
)
from app.data_engine.aggregation.semantics import sum_additive
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
from . import component_accumulator

from copy import deepcopy

import logging
import time
from collections import OrderedDict

from .config import BarAggregatorConfig
from .models import (
    BarInput,
    BarInputSource,
    BarFinality,
    BarState,
    BarStatus,
    BarStateChange,
    BarMergeStrategy,
    MergeMode,
)
from .time_bucket import TimeBucketEngine

logger = logging.getLogger("bar_aggregator.L3_BarState")


# ═══════════════════════════════════════════════════════════════
#  Default Merge Strategy
# ═══════════════════════════════════════════════════════════════


def has_complete_closed_component_coverage(state: BarState) -> bool:
    """Return whether component snapshots authoritatively cover the bucket."""
    accumulator = state._component_accumulator
    if accumulator is not None and accumulator.current(state.source_snapshots):
        return accumulator.result.coverage(state.bucket_start_ms, state.bucket_end_ms).closed
    ordered = sorted(
        state.source_snapshots.values(),
        key=lambda item: (int(item["open_time_ms"]), int(item["close_time_ms"])),
    )
    if state._history_prefix is not None:
        prefix = component_accumulator._Summary.history(state._history_prefix)
        tail = component_accumulator._Summary.batch(ordered) if ordered else None
        return component_accumulator._combine(prefix, tail).coverage(
            state.bucket_start_ms, state.bucket_end_ms).closed
    return snapshot_coverage(ordered, state.bucket_start_ms, state.bucket_end_ms).closed


class StandardOHLCVMerge:
    """Standard OHLCV merge: O=first, H=max, L=min, C=last, V=snapshot/sum.

    For kline sources each WS update is a **cumulative snapshot** (volume
    is the running total for the whole bar), so we *replace* additive
    fields instead of accumulating.

    For tick/trade sources each event is an incremental single trade, so
    we *sum* them as before.
    """

    def apply(self, state: BarState, bar_input: BarInput, is_new: bool) -> BarState:
        now_ms = int(time.time() * 1000)
        merge_mode = self._resolve_merge_mode(state, bar_input)

        if is_new:
            # First input for this bucket — initialize from input
            state.open = bar_input.open
            state.high = bar_input.high
            state.low = bar_input.low
            state.close = bar_input.close
            if merge_mode == MergeMode.PRICE_ONLY:
                # Price-only inputs refresh the forming target candle but
                # their additive fields are not target-interval totals.
                state.volume = 0.0
                state.quote_volume = 0.0
                state.trades = 0
                state.taker_buy_base = 0.0
                state.taker_buy_quote = 0.0
                state.enhanced_fields = frozenset()
            else:
                state.volume = round(bar_input.volume, 8)
                state.quote_volume = round(bar_input.quote_volume, 8)
                state.trades = bar_input.trades
                state.taker_buy_base = round(bar_input.taker_buy_base, 8)
                state.taker_buy_quote = round(bar_input.taker_buy_quote, 8)
                state.enhanced_fields = bar_input.enhanced_fields
            state.tick_count = 1
            state.first_input_at_ms = bar_input.open_time_ms
            state.last_input_at_ms = bar_input.open_time_ms
            state.created_at_ms = now_ms
        else:
            if merge_mode == MergeMode.SNAPSHOT:
                # A native snapshot supplies the target bucket's true opening
                # price, even when a shorter PRICE_ONLY stream created it first.
                state.open = bar_input.open
            # Subsequent input — merge into existing state
            state.high = max(state.high, bar_input.high)
            state.low = min(state.low, bar_input.low)
            state.close = bar_input.close

            if merge_mode == MergeMode.INCREMENTAL:
                # Trade ticks are incremental — accumulate
                state.volume = round(state.volume + bar_input.volume, 8)
                state.quote_volume = round(state.quote_volume + bar_input.quote_volume, 8)
                state.trades += bar_input.trades
                state.taker_buy_base = round(state.taker_buy_base + bar_input.taker_buy_base, 8)
                state.taker_buy_quote = round(state.taker_buy_quote + bar_input.taker_buy_quote, 8)
                state.enhanced_fields = (
                    state.enhanced_fields & bar_input.enhanced_fields
                )
            elif merge_mode == MergeMode.PRICE_ONLY:
                pass
            else:
                # Kline snapshots are cumulative — replace
                state.volume = round(bar_input.volume, 8)
                state.quote_volume = round(bar_input.quote_volume, 8)
                state.trades = bar_input.trades
                state.taker_buy_base = round(bar_input.taker_buy_base, 8)
                state.taker_buy_quote = round(bar_input.taker_buy_quote, 8)
                state.enhanced_fields = bar_input.enhanced_fields

            state.tick_count += 1
            state.last_input_at_ms = bar_input.open_time_ms

        if merge_mode == MergeMode.SNAPSHOT and (
            bar_input.extra.get("source_ref")
            or bar_input.extra.get("gate_close_source")
            or bar_input.extra.get("bybit_close_confirmed") is True
        ):
            # A confirmed native snapshot supplies its complete final extrema
            # and quantities, including any correction to a forming snapshot.
            for name in (
                "open", "high", "low", "close", "volume", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote",
            ):
                setattr(state, name, getattr(bar_input, name))

        # Track whether the last component bar is closed.
        # Only update from the native channel (source_interval matches
        # the target interval) or from tick data.  Cross-interval
        # routing (e.g. OKX 1m → 5m) must NOT set this flag, because
        # a 1m bar closing does not mean the 5m bar should close —
        # doing so would cause SourceCloseFinalizer to seal the bar
        # after only one component, freezing the chart.
        if merge_mode in (MergeMode.SNAPSHOT, MergeMode.INCREMENTAL):
            state.last_close_received = bar_input.is_closed
        state.updated_at_ms = now_ms

        return state

    @staticmethod
    def _resolve_merge_mode(state: BarState, bar_input: BarInput) -> MergeMode:
        """Return the effective merge mode for standard-interval bars.

        New router paths set ``merge_mode`` explicitly.  The fallback keeps
        direct public API calls compatible while older callers are migrated.
        """
        if bar_input.merge_mode is not None:
            return bar_input.merge_mode
        if bar_input.source_interval == "tick":
            return MergeMode.INCREMENTAL
        return MergeMode.SNAPSHOT


class ComponentSnapshotOHLCVMerge:
    """Component-aware merge for custom intervals.

    Custom targets may receive source bars out of chronological order:
      * a current forming bar is seeded from partial cache/storage first
      * missing earlier components may arrive later via backfill
      * the same source bar may be re-sent with fresher OHLCV

    Accepted snapshots remain the correction authority. Fixed grids update a
    compact prefix/tail index; earlier corrections rebuild from these inputs.
    """

    def __init__(self, *, incremental=True):
        self.incremental = incremental

    def adopt_history_prefix(self, state, prefix):
        """Synchronous owner operation, after durable and target fences pass.

        Confirmed history and live snapshots occupy disjoint half-open ranges.
        The caller is responsible for refreshing the prefix on source changes;
        an input inside the prefix is rejected here instead of double counted.
        """
        source = prefix.summary.target
        if ((source.exchange, source.market_type, source.symbol, source.identity)
                != (state.exchange, state.market_type, state.symbol, state.identity)
                or prefix.start_ms != state.bucket_start_ms
                or prefix.through_ms > state.bucket_end_ms):
            raise ValueError('history prefix does not belong to the target bucket')
        head = component_accumulator._Summary.history(prefix)
        if any(row['open_time_ms'] < prefix.through_ms < row['close_time_ms'] + 1
               for row in state.source_snapshots.values()):
            raise ValueError('live component crosses the history seam')
        snapshots = {key: row for key, row in state.source_snapshots.items()
                     if row['open_time_ms'] >= prefix.through_ms}
        if any(row['close_time_ms'] + 1 > state.bucket_end_ms
               or row['close_time_ms'] + 1 - row['open_time_ms'] != prefix.source_width_ms
               or row['open_time_ms'] % prefix.source_width_ms for row in snapshots.values()):
            raise ValueError('live overlay does not match the qualified source grid')
        ordered = sorted(snapshots.values(), key=lambda row: row['open_time_ms'])
        tail = component_accumulator._Summary.batch(ordered) if ordered else None
        result = component_accumulator._combine(head, tail)
        state.source_snapshots = snapshots
        state.source_refs = {key: value for key, value in state.source_refs.items() if key in snapshots}
        state._component_accumulator = None
        state._history_prefix = prefix
        return self._project(state, result, is_new=False)

    @staticmethod
    def _project(state, result, *, is_new):
        coverage = result.coverage(state.bucket_start_ms, state.bucket_end_ms)
        summary, raw_enhanced = result.values, result.raw_enhanced
        fields = summary.project(enhanced_complete=coverage.enhanced_complete)
        for name in ('open', 'high', 'low', 'close', 'volume'):
            setattr(state, name, fields[name])
        state.enhanced_fields = frozenset(name for name in component_accumulator.ENHANCED
                                         if fields[name] is not None)
        for name, raw_value in zip(component_accumulator.ENHANCED, raw_enhanced):
            value = getattr(summary, name)
            if value is None:
                value = raw_value
            if value is None:
                value = 0
            setattr(state, name, value if name == 'trades' else round(value, 8))
        state.tick_count = result.count
        state.first_input_at_ms, state.last_input_at_ms = result.first, result.last
        state.last_close_received = result.last_closed
        now_ms = int(time.time() * 1000)
        if is_new and state.created_at_ms == 0:
            state.created_at_ms = now_ms
        state.updated_at_ms = now_ms
        return state

    def _can_accumulate(self, state, bar_input):
        if not self.incremental or len(state.source_snapshots) > component_accumulator.MAX_COMPONENTS:
            return False
        specs = (parse_interval_spec(state.interval), parse_interval_spec(bar_input.source_interval))
        return all(spec is not None and spec.alignment is IntervalAlignment.FIXED_EPOCH for spec in specs)

    INPUT_FIELDS = ("open_time_ms", "close_time_ms", "open", "high", "low", "close",
                    "volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote",
                    "enhanced_fields", "is_closed", "sequence")

    @staticmethod
    def _snapshot_from_input(bar_input: BarInput) -> ReadonlyFields:
        snapshot = {name:getattr(bar_input,name) for name in ComponentSnapshotOHLCVMerge.INPUT_FIELDS}
        snapshot["is_closed"] = bool(snapshot["is_closed"])
        snapshot["source_ref"] = bar_input.extra.get("source_ref")
        if bar_input.extra.get("warm_start_seed"):
            snapshot["warm_start_seed"] = True
        snapshot["aggregation_values"] = snapshot_aggregation_values(snapshot)
        return ReadonlyFields(snapshot)

    @staticmethod
    def _is_monotonic_candidate(existing: dict, candidate: dict) -> bool:
        """Return whether ``candidate`` can safely supersede ``existing``.

        Kline component payloads are cumulative snapshots.  Even a payload
        with a newer transport timestamp must not make finality, extrema, or
        additive totals move backwards.  A deliberate correction that needs
        to reduce one of these fields must rebuild/expire the target bucket
        instead of being mistaken for an ordinary live update.
        """
        if int(candidate["close_time_ms"]) != int(existing["close_time_ms"]):
            return False
        if float(candidate["open"]) != float(existing["open"]):
            return False
        if bool(existing["is_closed"]) and not bool(candidate["is_closed"]):
            return False
        if float(candidate["high"]) < float(existing["high"]):
            return False
        if float(candidate["low"]) > float(existing["low"]):
            return False
        if float(candidate["volume"]) < float(existing["volume"]):
            return False

        existing_fields = frozenset(existing["enhanced_fields"])
        candidate_fields = frozenset(candidate["enhanced_fields"])
        if not existing_fields.issubset(candidate_fields):
            return False
        for field in existing_fields:
            if field == "trades":
                if int(candidate[field]) < int(existing[field]):
                    return False
            elif float(candidate[field]) < float(existing[field]):
                return False
        return True

    @staticmethod
    def _has_monotonic_progress(existing: dict, candidate: dict) -> bool:
        """Return whether cumulative/finality fields prove forward progress."""
        if not bool(existing["is_closed"]) and bool(candidate["is_closed"]):
            return True
        if float(candidate["high"]) > float(existing["high"]):
            return True
        if float(candidate["low"]) < float(existing["low"]):
            return True
        if float(candidate["volume"]) > float(existing["volume"]):
            return True
        existing_fields = frozenset(existing["enhanced_fields"])
        for field in existing_fields:
            if field == "trades":
                if int(candidate[field]) > int(existing[field]):
                    return True
            elif float(candidate[field]) > float(existing[field]):
                return True
        return False

    @classmethod
    def _should_replace(
        cls,
        existing: dict,
        candidate: dict,
        *,
        allow_authoritative_correction: bool = False,
        allow_confirmed_close: bool = False,
    ) -> bool:
        if candidate == existing:
            return False

        if (allow_confirmed_close and not existing["is_closed"] and candidate["is_closed"]
                and candidate["close_time_ms"] == existing["close_time_ms"]):
            # An explicit venue close replaces its own forming snapshot even
            # when an extremum or quantity decreases.
            return True

        source_ref = candidate.get("source_ref")
        previous_ref = existing.get("source_ref")
        if source_ref is not None:
            if previous_ref is not None and source_ref["revision"] <= previous_ref["revision"]:
                return False
            if allow_authoritative_correction:
                return True

        existing_sequence = existing.get("sequence")
        candidate_sequence = candidate.get("sequence")
        if (
            allow_authoritative_correction
            and int(candidate["close_time_ms"]) == int(existing["close_time_ms"])
            and existing_sequence is not None
            and candidate_sequence is not None
            and int(candidate_sequence) > int(existing_sequence)
        ):
            # A closed backfill snapshot with a strictly newer freshness
            # sequence is an authoritative correction. It may legitimately
            # reduce extrema, volume, or other cumulative fields that a bad
            # earlier snapshot overstated.
            return True

        if not cls._is_monotonic_candidate(existing, candidate):
            return False

        if existing_sequence is not None and candidate_sequence is not None:
            if int(candidate_sequence) < int(existing_sequence):
                return False
            if int(candidate_sequence) > int(existing_sequence):
                return True

        # Equal or unavailable sequences are not freshness evidence.  Accept
        # only when cumulative/finality fields themselves prove progress;
        # ambiguous close-only changes fail closed.
        return cls._has_monotonic_progress(existing, candidate)

    def apply(self, state: BarState, bar_input: BarInput, is_new: bool) -> BarState:
        now_ms = int(time.time() * 1000)
        snapshots = state.source_snapshots

        if state._history_prefix is not None and bar_input.open_time_ms < state._history_prefix.through_ms:
            raise ValueError('covered history input requires prefix revision refresh')

        if is_new and snapshots:
            # Closed custom bars may be amended by late backfill components.
            # Keep the existing component history and merge the new snapshot.
            pass

        input_key = bar_input.input_key
        prepare = getattr(self, "prepare_input", None)
        candidate = prepare(bar_input) if prepare is not None else None
        if candidate is None:
            candidate = self._snapshot_from_input(bar_input)
        existing = snapshots.get(input_key)
        if existing is not None and not self._should_replace(
            existing,
            candidate,
            allow_authoritative_correction=(
                bar_input.source in {BarInputSource.BACKFILL, BarInputSource.CORRECTION}
                and bar_input.is_closed
            ),
            allow_confirmed_close=bar_input.extra.get("bybit_close_confirmed") is True,
        ):
            logger.debug(
                "Ignored non-monotonic or stale component snapshot %s "
                "(existing_sequence=%r, candidate_sequence=%r)",
                input_key,
                existing.get("sequence"),
                candidate.get("sequence"),
            )
            return state

        snapshots[input_key] = candidate
        if self._can_accumulate(state, bar_input):
            accumulator = state._component_accumulator
            if accumulator is None:
                accumulator = component_accumulator.ComponentAccumulator()
            state._component_accumulator = None
            result = accumulator.update(snapshots, input_key, existing)
            if state._history_prefix is not None:
                result = component_accumulator._combine(
                    component_accumulator._Summary.history(state._history_prefix), result)
                accumulator.result = result
            state._component_accumulator = accumulator
            coverage = result.coverage(state.bucket_start_ms, state.bucket_end_ms)
            summary, raw_enhanced = result.values, result.raw_enhanced
            first_time, last_time, last_closed = result.first, result.last, result.last_closed
        else:
            state._component_accumulator = None
            ordered = sorted(
                snapshots.values(),
                key=lambda snap: (
                    int(snap["open_time_ms"]),
                    int(snap["close_time_ms"]),
                    int(snap["sequence"]) if snap.get("sequence") is not None else -1,
                ),
            )
            coverage = snapshot_coverage(ordered, state.bucket_start_ms, state.bucket_end_ms)
            summary = snapshot_field_summary(ordered)
            raw_enhanced = tuple(sum_additive((row[name] for row in ordered), integer=name == "trades")
                                 if getattr(summary, name) is None else getattr(summary, name)
                                 for name in component_accumulator.ENHANCED)
            first_time, last_time = int(ordered[0]["open_time_ms"]), int(ordered[-1]["open_time_ms"])
            last_closed = bool(ordered[-1]["is_closed"])
            if state._history_prefix is not None:
                result = component_accumulator._combine(
                    component_accumulator._Summary.history(state._history_prefix),
                    component_accumulator._Summary.batch(ordered))
                return self._project(state, result, is_new=is_new)
        fields = summary.project(
            enhanced_complete=coverage.enhanced_complete,
        )
        for name in ("open", "high", "low", "close", "volume"):
            setattr(state, name, fields[name])
        enhanced = ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
        state.enhanced_fields = frozenset(name for name in enhanced if fields[name] is not None)
        # Preserve legacy diagnostic counters behind the mask. They are not
        # eligible fields: K130 and published records retain None for unknown.
        for name, raw_value in zip(enhanced, raw_enhanced):
            value = getattr(summary, name)
            if value is None:
                value = raw_value
            # Missing raw enhancements are legal. Only the masked diagnostic
            # counter uses zero; published/storage fields remain explicitly
            # unknown via enhanced_fields. The batch path previously rounded
            # None here and failed before producing a result.
            if value is None:
                value = 0
            if name != "trades":
                value = round(value, 8)
            setattr(state, name, value)
        state.tick_count = len(snapshots) + (state._history_prefix.summary.coverage.count
                                           if state._history_prefix is not None else 0)
        state.first_input_at_ms = first_time
        state.last_input_at_ms = last_time
        state.last_close_received = last_closed
        if is_new and state.created_at_ms == 0:
            state.created_at_ms = now_ms
        state.updated_at_ms = now_ms
        return state


# ═══════════════════════════════════════════════════════════════
#  Bar State Engine
# ═══════════════════════════════════════════════════════════════


class BarStateEngine:
    """Maintains OHLCV state for all active time buckets.

    Manages a collection of ``BarState`` objects, one per active bucket
    per (symbol, interval) pair.  Applies incoming ``BarInput`` events
    using a configurable merge strategy.
    """

    def __init__(
        self,
        config: BarAggregatorConfig,
        time_bucket: TimeBucketEngine,
        interval: str,
    ) -> None:
        self._cfg = config
        self._time_bucket = time_bucket
        self._interval = interval

        # Input semantics, not the target interval's global spelling, choose
        # snapshot replacement versus component accumulation.
        self._merge_strategy: BarMergeStrategy = StandardOHLCVMerge()
        self._component_merge_strategy = ComponentSnapshotOHLCVMerge(incremental=config.incremental_components)
        self._merge_strategy_overridden = False

        # Active (FORMING) bars: {(exchange, market_type, symbol, bucket_start_ms) → BarState}
        # Using OrderedDict to maintain insertion order for eviction
        self._active: OrderedDict[tuple[str, str, str, int], BarState] = OrderedDict()

        # Recently closed bars: {(exchange, market_type, symbol, bucket_start_ms) → BarState}
        self._closed: OrderedDict[tuple[str, str, str, int], BarState] = OrderedDict()

        # Eviction buffers — populated by _enforce_*_limit(), consumed by caller.
        # The aggregator checks these after each apply()/close_bar() call
        # and emits the appropriate lifecycle events.
        self.evicted_closed: list[BarState] = []
        self.evicted_expired: list[BarState] = []

    # ── Public: Configuration ────────────────────────────────

    def set_merge_strategy(self, strategy: BarMergeStrategy) -> None:
        """Replace the OHLCV merge strategy.

        Example — Heikin-Ashi bars::

            class HeikinAshiMerge:
                def apply(self, state, bar_input, is_new):
                    # custom HA logic
                    return state
            engine.set_merge_strategy(HeikinAshiMerge())
        """
        self._merge_strategy = strategy
        self._merge_strategy_overridden = True
        logger.info("Merge strategy changed to: %s", type(strategy).__name__)

    @property
    def merge_strategy(self) -> BarMergeStrategy:
        """Current merge strategy."""
        return self._merge_strategy

    def _strategy_for(self, bar_input: BarInput) -> BarMergeStrategy:
        if self._merge_strategy_overridden:
            return self._merge_strategy
        if bar_input.merge_mode == MergeMode.COMPONENT:
            return self._component_merge_strategy
        return self._merge_strategy

    # ── Public: Core Operation ───────────────────────────────

    def adopt_history_prefix(self, prefix, *, refresh=False, replace_provisional=False) -> BarState:
        """Install a qualified prefix while retaining the current live overlay."""
        source = prefix.summary.target
        key = (source.exchange, source.market_type, source.symbol, prefix.start_ms)
        was_closed = key in self._closed
        state = self._active.get(key) or self._closed.get(key)
        replacing = (replace_provisional and was_closed and state.finality == BarFinality.PROVISIONAL
                     and prefix.complete and prefix.through_ms == state.bucket_end_ms)
        if (was_closed and not (refresh or replacing)) or self._merge_strategy_overridden:
            raise ValueError('history initialization requires a forming or recoverable target')
        if refresh and (state is None or state._history_prefix is None):
            raise ValueError('history refresh requires an existing compact prefix')
        if state is None:
            start, end = self._time_bucket.compute_bucket_range(prefix.start_ms)
            state = BarState(source.symbol, self._interval, start, end, 0, 0, 0, 0, 0,
                             exchange=source.exchange, market_type=source.market_type,
                             series_identity=source.identity)
        self._component_merge_strategy.adopt_history_prefix(state, prefix)
        if was_closed and not replacing and has_complete_closed_component_coverage(state):
            state.finality = BarFinality.AUTHORITATIVE
            state.close_reason = 'history_prefix_refresh'
            self._closed.move_to_end(key)
            return state
        if was_closed:
            # Deleting one historical component revokes the old close. A gap
            # cannot retain authoritative finality just because it was closed.
            self._closed.pop(key)
            state.status = BarStatus.FORMING
            state.finality = BarFinality.PROVISIONAL
            state.close_reason = 'history_prefix_gap'
        self._active[key] = state
        self._active.move_to_end(key)
        self._enforce_active_limit(source.exchange, source.market_type, source.symbol)
        return state

    def apply(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        bucket_start_ms: int,
        bar_input: BarInput,
    ) -> tuple[BarState, BarStateChange]:
        """Apply a BarInput to the appropriate bucket state.

        If the bucket doesn't exist yet, a new BarState is created.
        If it exists, the input is merged into it.

        Args:
            symbol:          Trading pair (e.g. "BTCUSDT")
            bucket_start_ms: The bucket this input belongs to
            bar_input:       The input data to merge

        Returns:
            Tuple of (updated BarState, what changed)
        """
        exchange = exchange.strip().lower()
        market_type = market_type.strip().lower()
        key = (exchange, market_type, symbol, bucket_start_ms)
        merge_strategy = self._strategy_for(bar_input)
        existing_state = self._active.get(key) or self._closed.get(key)
        source_ref = bar_input.extra.get("source_ref")
        if existing_state is not None and source_ref is not None:
            previous_ref = existing_state.source_refs.get(bar_input.input_key)
            if previous_ref is not None and source_ref["revision"] <= previous_ref["revision"]:
                return existing_state, BarStateChange.NO_CHANGE

        if key in self._active:
            # Existing active bar — merge
            state = self._active[key]
            previous_component = (
                state.source_snapshots.get(bar_input.input_key)
                if merge_strategy is self._component_merge_strategy
                else None
            )
            state = merge_strategy.apply(state, bar_input, is_new=False)
            self._mark_authoritative_close_policy(state, bar_input)
            self._active[key] = state
            if (
                merge_strategy is self._component_merge_strategy
                and previous_component is not None
                and state.source_snapshots.get(bar_input.input_key) is previous_component
            ):
                return state, BarStateChange.NO_CHANGE
            # Move to end (most recently updated)
            if source_ref is not None:
                state.source_refs[bar_input.input_key] = deepcopy(dict(source_ref))
            self._active.move_to_end(key)
            return state, BarStateChange.UPDATED

        # Check if this bucket was already closed
        if key in self._closed:
            # Already closed — this is an amendment (e.g. late data from backfill)
            old_state = self._closed[key]
            # For backfill data, we overwrite (is_new=True) instead of merge,
            # because backfill bars are complete final data and should replace
            # existing state rather than accumulate on top of it.
            if bar_input.source in {
                BarInputSource.BACKFILL,
                BarInputSource.CORRECTION,
            }:
                was_authoritative = old_state.finality == BarFinality.AUTHORITATIVE
                previous_component = (
                    old_state.source_snapshots.get(bar_input.input_key)
                    if merge_strategy is self._component_merge_strategy
                    else None
                )
                state = merge_strategy.apply(old_state, bar_input, is_new=True)
                state.status = BarStatus.CLOSED  # keep it closed
                if bar_input.merge_mode != MergeMode.COMPONENT:
                    state.finality = BarFinality.AUTHORITATIVE
                    state.close_reason = "backfill_amendment"
                elif has_complete_closed_component_coverage(state):
                    # Late component repair may promote a provisional close
                    # only after the state proves complete closed coverage.
                    state.finality = BarFinality.AUTHORITATIVE
                    state.close_reason = "backfill_amendment"
                self._closed[key] = state
                if (
                    merge_strategy is self._component_merge_strategy
                    and previous_component is not None
                    and state.source_snapshots.get(bar_input.input_key) is previous_component
                    and was_authoritative == (
                        state.finality == BarFinality.AUTHORITATIVE
                    )
                ):
                    return state, BarStateChange.NO_CHANGE
                if source_ref is not None:
                    state.source_refs[bar_input.input_key] = deepcopy(dict(source_ref))
                return state, BarStateChange.AMENDED
            # Realtime data for an already-closed bar — ignore
            return old_state, BarStateChange.NO_CHANGE

        # New bucket — create fresh BarState
        bucket_start, bucket_end = self._time_bucket.compute_bucket_range(bucket_start_ms)
        state = BarState(
            symbol=symbol,
            interval=self._interval,
            series_identity=bar_input.identity,
            bucket_start_ms=bucket_start,
            bucket_end_ms=bucket_end,
            exchange=exchange,
            market_type=market_type,
            open=0.0,
            high=0.0,
            low=0.0,
            close=0.0,
            volume=0.0,
        )
        state = merge_strategy.apply(state, bar_input, is_new=True)
        self._mark_authoritative_close_policy(state, bar_input)
        self._active[key] = state
        if source_ref is not None:
            state.source_refs[bar_input.input_key] = deepcopy(dict(source_ref))

        # Evict oldest active bars if limit exceeded
        self._enforce_active_limit(exchange, market_type, symbol)

        return state, BarStateChange.CREATED

    def _mark_authoritative_close_policy(
        self,
        state: BarState,
        bar_input: BarInput,
    ) -> None:
        """Mark native cumulative snapshots as requiring explicit finality."""
        merge_mode = bar_input.merge_mode
        if merge_mode is None:
            merge_mode = (
                MergeMode.INCREMENTAL
                if bar_input.source_interval == "tick"
                else MergeMode.SNAPSHOT
            )
        # Native/cumulative kline snapshots are only final when their source
        # explicitly confirms closure (for example Binance ``x=true``).
        # Incremental trade-built bars intentionally retain the legacy
        # next-bucket/timeout policy because they have no source-close flag.
        if merge_mode in (MergeMode.SNAPSHOT, MergeMode.PRICE_ONLY):
            state.requires_authoritative_close = True
        if merge_mode == MergeMode.SNAPSHOT:
            state.quality_source = ""
            if bar_input.extra.get("trade_coverage_verified") is True:
                state.quality_source = "trade_history_verified"
            elif bar_input.is_closed and bar_input.extra.get("bybit_close_confirmed") is True:
                state.quality_source = BYBIT_WS_CONFIRMED_SOURCE
            gate_source = bar_input.extra.get("gate_close_source")
            if bar_input.is_closed and gate_source:
                state.quality_source = gate_source

    # ── Public: State Queries ────────────────────────────────

    def get_active(
        self, exchange: str, market_type: str, symbol: str, bucket_start_ms: int,
    ) -> BarState | None:
        """Get a specific active (FORMING) bar state."""
        return self._active.get((exchange.strip().lower(), market_type.strip().lower(), symbol, bucket_start_ms))

    def get_closed(
        self, exchange: str, market_type: str, symbol: str, bucket_start_ms: int,
    ) -> BarState | None:
        """Get a specific closed bar state from recent memory."""
        return self._closed.get((exchange.strip().lower(), market_type.strip().lower(), symbol, bucket_start_ms))

    def get_state(
        self, exchange: str, market_type: str, symbol: str, bucket_start_ms: int,
    ) -> BarState | None:
        """Get bar state (active or closed)."""
        key = (exchange.strip().lower(), market_type.strip().lower(), symbol, bucket_start_ms)
        return self._active.get(key) or self._closed.get(key)

    def get_all_active(self, exchange: str, market_type: str, symbol: str) -> list[BarState]:
        """Get all active (FORMING) bars for a symbol, ordered by bucket_start."""
        exchange = exchange.strip().lower()
        market_type = market_type.strip().lower()
        return sorted(
            [
                s for (ex, mt, sym, _), s in self._active.items()
                if ex == exchange and mt == market_type and sym == symbol
            ],
            key=lambda s: s.bucket_start_ms,
        )

    def get_recent_closed(
        self, exchange: str, market_type: str, symbol: str, limit: int = 100,
    ) -> list[BarState]:
        """Get recently closed bars for a symbol, newest first."""
        exchange = exchange.strip().lower()
        market_type = market_type.strip().lower()
        bars = [
            s for (ex, mt, sym, _), s in self._closed.items()
            if ex == exchange and mt == market_type and sym == symbol
        ]
        bars.sort(key=lambda s: s.bucket_start_ms, reverse=True)
        return bars[:limit]

    def get_latest_bar(self, exchange: str, market_type: str, symbol: str) -> BarState | None:
        """Get the most recent bar (active preferred, then closed)."""
        active = self.get_all_active(exchange, market_type, symbol)
        if active:
            return active[-1]
        closed = self.get_recent_closed(exchange, market_type, symbol, limit=1)
        return closed[0] if closed else None

    # ── Public: Lifecycle Management ─────────────────────────

    def close_bar(
        self, exchange: str, market_type: str, symbol: str, bucket_start_ms: int,
    ) -> BarState | None:
        """Move a bar from active to closed.

        Called by the Finalizer when a bar should be sealed.

        Returns the closed BarState, or None if not found.
        """
        key = (exchange.strip().lower(), market_type.strip().lower(), symbol, bucket_start_ms)
        state = self._active.pop(key, None)
        if state is None:
            return None

        state.status = BarStatus.CLOSED
        state.updated_at_ms = int(time.time() * 1000)
        self._closed[key] = state

        # Enforce closed bars limit
        self._enforce_closed_limit(exchange, market_type, symbol)

        return state

    def expire_bar(
        self, exchange: str, market_type: str, symbol: str, bucket_start_ms: int,
    ) -> BarState | None:
        """Remove a bar from memory entirely.

        Returns the expired BarState, or None if not found.
        """
        key = (exchange.strip().lower(), market_type.strip().lower(), symbol, bucket_start_ms)
        state = self._active.pop(key, None) or self._closed.pop(key, None)
        if state is not None:
            state.status = BarStatus.EXPIRED
        return state

    def force_close_all_active(self, exchange: str, market_type: str, symbol: str) -> list[BarState]:
        """Force-close all active bars for a symbol.

        Used during shutdown or when switching intervals.

        Returns list of closed BarStates.
        """
        closed: list[BarState] = []
        keys_to_close = [
            (ex, mt, sym, bs) for (ex, mt, sym, bs) in self._active
            if ex == exchange.strip().lower() and mt == market_type.strip().lower() and sym == symbol
        ]
        for key in keys_to_close:
            state = self.close_bar(key[0], key[1], key[2], key[3])
            if state:
                closed.append(state)
        return closed

    def clear(
        self,
        symbol: str | None = None,
        exchange: str | None = None,
        market_type: str | None = None,
    ) -> None:
        """Clear all state.  If symbol is given, clear only that symbol."""
        if symbol is None:
            self._active.clear()
            self._closed.clear()
        else:
            normalized_exchange = exchange.strip().lower() if exchange else None
            normalized_market = market_type.strip().lower() if market_type else None
            self._active = OrderedDict(
                (k, v)
                for k, v in self._active.items()
                if k[2] != symbol
                or (normalized_exchange is not None and k[0] != normalized_exchange)
                or (normalized_market is not None and k[1] != normalized_market)
            )
            self._closed = OrderedDict(
                (k, v)
                for k, v in self._closed.items()
                if k[2] != symbol
                or (normalized_exchange is not None and k[0] != normalized_exchange)
                or (normalized_market is not None and k[1] != normalized_market)
            )

    # ── Public: Snapshot ─────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a JSON-serializable snapshot of engine state."""
        indices = [state._component_accumulator.snapshot()
                   for state in (*self._active.values(), *self._closed.values())
                   if state._component_accumulator is not None]
        return {
            "engine": "BarStateEngine",
            "interval": self._interval,
            "merge_strategy": type(self._merge_strategy).__name__,
            "active_bars": len(self._active),
            "closed_bars": len(self._closed),
            "max_active": self._cfg.max_active_bars,
            "max_closed": self._cfg.max_closed_bars_in_memory,
            "component_execution": {
                "enabled": self._component_merge_strategy.incremental,
                "indexed_states": len(indices),
                **{name: sum(item[name] for item in indices) for name in (
                    "appends", "tail_replacements", "rebuilds", "rebuilt_components",
                    "summary_nodes", "estimated_bytes")},
            },
        }

    # ── Internal: Eviction ───────────────────────────────────

    def _enforce_active_limit(self, exchange: str, market_type: str, symbol: str) -> None:
        """Evict oldest active bars if over the limit.

        Bars which require an explicit source-close confirmation are expired
        rather than promoted to CLOSED.  Other bars retain the legacy
        force-close behavior and are appended to ``self.evicted_closed``.
        """
        normalized_exchange = exchange.strip().lower()
        normalized_market = market_type.strip().lower()
        symbol_keys = [
            k for k in self._active
            if k[0] == normalized_exchange and k[1] == normalized_market and k[2] == symbol
        ]
        while len(symbol_keys) > self._cfg.max_active_bars:
            oldest_key = symbol_keys.pop(0)
            state = self._active.pop(oldest_key, None)
            if state:
                if (
                    state.requires_authoritative_close
                    and not state.last_close_received
                ):
                    state.close_reason = "active_capacity_unconfirmed"
                    state.finality = BarFinality.PROVISIONAL
                    logger.warning(
                        "Expiring unconfirmed active bar at capacity: "
                        "%s:%s:%s@%s bucket=%d",
                        normalized_exchange,
                        normalized_market,
                        symbol,
                        self._interval,
                        oldest_key[3],
                    )
                    state.status = BarStatus.EXPIRED
                    state.updated_at_ms = int(time.time() * 1000)
                    self.evicted_expired.append(state)
                    continue
                logger.warning(
                    "Force-closing oldest active bar: %s:%s:%s@%s bucket=%d",
                    normalized_exchange, normalized_market, symbol, self._interval, oldest_key[3],
                )
                state.status = BarStatus.CLOSED
                state.close_reason = "active_capacity_fallback"
                state.finality = BarFinality.PROVISIONAL
                state.updated_at_ms = int(time.time() * 1000)
                self._closed[oldest_key] = state
                self.evicted_closed.append(state)

    def _enforce_closed_limit(self, exchange: str, market_type: str, symbol: str) -> None:
        """Evict oldest closed bars if over the limit.

        Expired bars are appended to ``self.evicted_expired`` so the
        aggregator can emit EXPIRED events for them after processing.
        """
        normalized_exchange = exchange.strip().lower()
        normalized_market = market_type.strip().lower()
        symbol_keys = [
            k for k in self._closed
            if k[0] == normalized_exchange and k[1] == normalized_market and k[2] == symbol
        ]
        while len(symbol_keys) > self._cfg.max_closed_bars_in_memory:
            oldest_key = symbol_keys.pop(0)
            evicted = self._closed.pop(oldest_key, None)
            if evicted:
                evicted.status = BarStatus.EXPIRED
                self.evicted_expired.append(evicted)
