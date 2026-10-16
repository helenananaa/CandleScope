"""Canonical builtin evaluation over a fixed replay prefix, with bounded IO."""

from __future__ import annotations

import math
from threading import Event
from time import monotonic
from typing import NamedTuple

from app.data_engine.interval_policy import (
    compute_bucket_start_ms,
    is_monthly_interval,
    parse_interval_ms,
)
from app.indicator.serialization import serialize_indicator_result
from app.indicator.types import IndicatorKey
from app.replay.bars.builder import ReplayDisplayBar

from .history import MAX_HISTORY_PAGE_BARS
from .indicator_checkpoint import (
    IndicatorCheckpointStore,
    checkpoint_key,
    discard_prefix_graphics,
    dump_state,
    new_indicator,
    normalized_parameters,
    restore_state,
)
from .indicator_history import (
    IndicatorHistoryPreparing,
    PinnedIndicatorHistory,
    validate_chunk,
)


class CanonicalIndicatorBar(NamedTuple):
    """Validated, immutable input for builtin math; no live-stream metadata."""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


class CloseIndicatorBar(NamedTuple):
    time: int
    close: float


def indicator_bar(bar: ReplayDisplayBar) -> CanonicalIndicatorBar:
    prices = {
        key: float(getattr(bar, key))
        for key in ("open", "high", "low", "close", "volume")
    }
    if (
        not all(math.isfinite(value) for value in prices.values())
        or prices["volume"] < 0
        or prices["high"] < max(prices["open"], prices["close"], prices["low"])
        or prices["low"] > min(prices["open"], prices["close"], prices["high"])
    ):
        raise ValueError("indicator bar has invalid OHLCV values")
    return CanonicalIndicatorBar(
        time=bar.open_time_ms // 1000,
        **prices,
        is_closed=bar.is_closed,
    )


def prefix_start(history, name: str, params: dict, before: int) -> int:
    """Finite windows need only their preceding inputs; recursive seeds do not.

    Keep the fixed source identity, gap handling and selected-source boundary.
    Calendar windows walk actual month/year buckets, not 30-day estimates.
    """
    if name == "VOL":
        return before
    if name not in {"MA", "BOLL"}:
        return history.origin_ms
    count = params["period"] - 1
    interval = history.identity["identity"]["display_interval"]
    width = parse_interval_ms(interval)
    if not width:
        raise ValueError("invalid finite indicator interval")
    cursor = before
    if is_monthly_interval(interval):
        for _ in range(count):
            if cursor <= history.origin_ms:
                break
            cursor = compute_bucket_start_ms(cursor - 1, width, interval=interval)
    else:
        cursor -= count * width
    return max(history.origin_ms, cursor)


class CanonicalReplayIndicators:
    def __init__(
        self,
        checkpoints: IndicatorCheckpointStore,
        *,
        checkpoint_rows: int = 4096,
        max_prefix_pages: int = 64,
        max_prefix_seconds: float = 0.5,
    ):
        self.checkpoints = checkpoints
        self.checkpoint_rows = max(1, checkpoint_rows)
        self.max_prefix_pages = max(1, max_prefix_pages)
        if not math.isfinite(max_prefix_seconds) or max_prefix_seconds <= 0:
            raise ValueError("indicator preparation time budget must be positive and finite")
        self.max_prefix_seconds = max_prefix_seconds

    def compute(
        self,
        *,
        history: PinnedIndicatorHistory,
        name: str,
        params: dict,
        rows: tuple[ReplayDisplayBar, ...],
        cancelled: Event | None = None,
    ):
        deadline = monotonic() + self.max_prefix_seconds
        params = normalized_parameters(name, params)
        if not rows or len(rows) > 10_000:
            raise ValueError("indicator render window must contain 1..10000 bars")
        before = rows[0].open_time_ms
        if before < history.origin_ms:
            raise ValueError("indicator window precedes its canonical origin")
        if before > getattr(history, "closed_before_ms", history.revealed_boundary_ms):
            # A later public clock does not prove an unconsumed tape bucket
            # closed. Recheck before loading a checkpoint from a later review.
            raise ValueError("indicator prefix is ahead of the selected source sequence")
        # Validate the entire render request before publishing even a prefix
        # checkpoint. The last unclosed row is evaluated on a disposable state.
        previous = before - 1
        render_bars = []
        for index, row in enumerate(rows):
            if (
                row.open_time_ms <= previous
                or row.open_time_ms > history.revealed_boundary_ms
                or row.close_time_ms < row.open_time_ms
                or not row.open_time_ms
                <= row.first_base_open_ms
                <= row.last_base_open_ms
                <= row.close_time_ms
                or row.last_base_open_ms > history.revealed_boundary_ms
                or (row.is_closed and row.close_time_ms > history.revealed_boundary_ms)
                or (
                    not row.is_closed
                    and (
                        index != len(rows) - 1
                        or row.close_time_ms < history.revealed_boundary_ms
                    )
                )
            ):
                raise ValueError(
                    "indicator render window crossed its revealed boundary"
                )
            render_bars.append(indicator_bar(row))
            previous = row.close_time_ms
        identity = checkpoint_key(history.identity, name, params)
        start = prefix_start(history, name, params, before)
        saved = self.checkpoints.load(identity, before, start)
        cursor, last_close = start, None
        instance = new_indicator(name, params)
        if saved is not None:
            try:
                instance = restore_state(name, params, saved["state"])
                cursor, last_close = saved["before_ms"], saved["last_close_ms"]
            except (TypeError, ValueError, OverflowError):
                self.checkpoints.discard(identity, saved["before_ms"])
                saved = None
        read_rows = 0
        since_checkpoint = 0
        pages = 0
        close_reader = (
            getattr(history, "read_closes", None)
            if name in {"MA", "EMA", "RSI", "MACD", "BOLL"}
            and params.get("source", "close") == "close"
            else None
        )
        while cursor < before:
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError("indicator preparation cancelled")
            try:
                close_chunk = None if close_reader is None else close_reader(cursor, before)
                chunk = history.read(cursor, before) if close_chunk is None else close_chunk
            except IndicatorHistoryPreparing as pending:
                # Retain only fully consumed mathematics. A source continuation
                # can progress inside one display bucket without moving cursor.
                self.checkpoints.save(identity, cursor, last_close, dump_state(instance))
                return {"status": "preparing", "seed": history.identity,
                    "prepared_before_ms": cursor, "target_before_ms": before,
                    "prefix_rows_read": read_rows, "source_preparation": pending.progress}
            if (
                chunk.start_ms != cursor
                or chunk.stop_ms > before
                or len(chunk.bars) > MAX_HISTORY_PAGE_BARS
            ):
                raise ValueError("indicator reader changed its prefix cursor")
            validate_chunk(chunk, history.revealed_boundary_ms)
            for bar in chunk.bars:
                if last_close is not None and bar.open_time_ms != last_close + 1:
                    instance = new_indicator(name, params)
                if close_chunk is None:
                    value = indicator_bar(bar)
                else:
                    close = float(bar.close)
                    if not math.isfinite(close):
                        raise ValueError("indicator close input is not finite")
                    value = CloseIndicatorBar(bar.open_time_ms // 1000, close)
                instance.update_closed(value)
                last_close = bar.close_time_ms
            if any(end == chunk.stop_ms - 1 for _, end in chunk.gaps):
                instance = new_indicator(name, params)
                last_close = None
            discard_prefix_graphics(instance)
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError("indicator preparation cancelled")
            cursor = chunk.stop_ms
            read_rows += len(chunk.bars)
            since_checkpoint += len(chunk.bars)
            pages += 1
            if since_checkpoint >= self.checkpoint_rows:
                self.checkpoints.save(
                    identity, cursor, last_close, dump_state(instance)
                )
                since_checkpoint = 0
            # A page's IO is already bounded and cancellable. Yield between
            # complete pages, retaining only consumed mathematics: inexpensive
            # local reads need fewer HTTP round trips, while slow reads release
            # the shared worker lane without waiting for a fixed page count.
            if cursor < before and (
                pages >= self.max_prefix_pages or monotonic() >= deadline
            ):
                self.checkpoints.save(
                    identity, cursor, last_close, dump_state(instance)
                )
                return {
                    "status": "preparing",
                    "seed": history.identity,
                    "prepared_before_ms": cursor,
                    "target_before_ms": before,
                    "prefix_rows_read": read_rows,
                }
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError("indicator preparation cancelled")
        # Exact requested boundaries make differing chart left edges and a
        # process restart cheap without storing any chart's mutable window.
        self.checkpoints.save(identity, before, last_close, dump_state(instance))
        instance = restore_state(name, params, dump_state(instance))
        if last_close is not None and before != last_close + 1:
            instance = new_indicator(name, params)
        math_seed = {
            "schema": "replay.builtin-seed.v1", "name": name, "params": params,
            "before_ms": before, "state": dump_state(instance),
        }
        instance.retain_outputs(len(rows))
        for row, bar in zip(rows, render_bars, strict=True):
            if last_close is not None and row.open_time_ms != last_close + 1:
                instance = new_indicator(name, params)
                instance.retain_outputs(len(rows))
            # This state is not retained: repeated ticks, including an
            # incomplete equal-ms trade cohort, cannot advance a checkpoint.
            instance.update_closed(bar)
            last_close = row.close_time_ms
        market = history.identity["identity"]
        key = IndicatorKey(
            market["symbol"],
            market["display_interval"],
            name,
            params,
            exchange=market["exchange"],
            market_type=market["market_type"],
        )
        return {
            "status": "ready",
            "payload": serialize_indicator_result(instance.build_result(key)),
            "seed": history.identity,
            "math_seed": math_seed,
            "prefix_rows_read": read_rows,
            "checkpoint_before_ms": saved["before_ms"] if saved else None,
        }
