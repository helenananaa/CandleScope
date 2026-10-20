"""Disposable, sequence-bound chart windows from the frozen trade source."""

from __future__ import annotations

import json
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, Lock
from time import monotonic

from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.data_engine.storage.raw_trade_archive import RawAggTradeDatasetRef
from app.replay.canonical import canonical_sha256
from app.replay.dataset import ReplayBar
from app.replay.models import ReplaySessionConfig, SourceKind
from app.replay.sources.trade_reader import PagedReplayTradeReader, ReplayTrade

from .errors import TrainingRunError
from .history import _decode_bar_snapshot
from .indicator_history import validate_chunk
from .tape_chart_builder import TapeChartBuilder


def fail(message, *, code="TAPE_PROJECTION_INVALID", status=422):
    return TrainingRunError(code, message, status_code=status)


def tape_history_epoch(data_epoch, base_interval, display_interval, context_history):
    return canonical_sha256(
        {
            "contract": "replay.public-tape-history.v1",
            "data_epoch": data_epoch,
            "base_interval": base_interval,
            "display_interval": display_interval,
            "scope": "CONTEXT_AND_FROZEN_TAPE"
            if context_history is not None
            else "FROZEN_WARMUP_AND_TAPE",
            "context_epoch": None
            if context_history is None
            else context_history.history_epoch,
        }
    )


@dataclass
class _Window:
    reader: PagedReplayTradeReader
    builder: TapeChartBuilder
    next_sequence: int
    start_ms: int
    offset_ms: int
    target_sequence: int
    close_at_ms: int | None
    origin_ms: int
    context_cursor: int
    context_stop: int
    warmup: tuple[ReplayBar, ...]
    incomplete_context_buckets: set[int]
    selected_closed_before_ms: int
    end_ms: int
    last_progress_at: float = 0.0


class TapeDisplayProjection:
    """Bounded derived-market cache; never contains accounts or actor cursors.

    The service serializes each immutable request identity. Cancellation retains
    complete pages. A later compatible window forks prepared market state; it
    never mutates a cached earlier selection or shares any account state.
    """

    def __init__(
        self,
        *,
        page_rows=8192,
        pages_per_call=4,
        capacity=8,
        pending_retention_seconds=120,
        clock=monotonic,
    ):
        self.page_rows = page_rows
        self.pages_per_call = pages_per_call
        self.capacity = capacity
        self.pending_retention_seconds = pending_retention_seconds
        self._clock = clock
        self._cache = OrderedDict()
        self._selections = OrderedDict()
        self._lock = Lock()
        self._owners = {}

    @contextmanager
    def _own(self, key, cancelled):
        # Chart and indicator workers can prepare the same immutable window.
        # Only that window is serialized; an unrelated slow download must not
        # lock every market. Waiting and computation remain cancellable.
        with self._lock:
            entry = self._owners.setdefault(key, [Lock(), 0])
            entry[1] += 1
        acquired = False
        try:
            while not cancelled.is_set():
                acquired = entry[0].acquire(timeout=0.05)
                if acquired:
                    yield
                    return
            raise InterruptedError("tape projection cancelled")
        finally:
            if acquired:
                entry[0].release()
            with self._lock:
                entry[1] -= 1
                if not entry[1]:
                    del self._owners[key]

    def compute(self, **kwargs):
        binding, context = kwargs["binding"], kwargs.get("context_history")
        key = (
            binding["session_id"],
            binding["track_id"],
            *(
                kwargs[name]
                for name in (
                    "data_epoch",
                    "display_interval",
                    "source_sequence",
                    "revealed_boundary_ms",
                    "limit",
                )
            ),
            kwargs.get("before_ms"),
            None if context is None else context.history_epoch,
            kwargs.get("indicator_input", False),
        )
        with self._own(key, kwargs["cancelled"]):
            return self._compute(**kwargs)

    def _compute(
        self,
        *,
        binding,
        persisted,
        archive,
        display_interval,
        source_sequence,
        revealed_boundary_ms,
        data_epoch,
        limit,
        cancelled: Event,
        before_ms=None,
        context_history=None,
        history_epoch=None,
        include_selection_boundary=False,
        indicator_input=False,
    ):
        if (
            any(
                type(value) is not int or value < 0
                for value in (source_sequence, revealed_boundary_ms, limit)
            )
            or not 1 <= limit <= 500
        ):
            raise fail("tape projection bounds are invalid")
        if binding.get("degraded_reason") is not None:
            raise fail(
                "frozen tape is unavailable",
                code="HISTORY_SNAPSHOT_UNAVAILABLE",
                status=503,
            )
        epochs = {
            str(binding[key]) for key in ("track_dataset_epoch", "session_data_epoch")
        }
        epochs.add(str(persisted.get("data_epoch")))
        if binding["session_id"] == binding["primary_adapter_session_id"]:
            epochs.add(str(binding["run_dataset_epoch"]))
        if epochs != {data_epoch}:
            raise fail(
                "tape projection data epoch changed",
                code="HISTORY_DATA_EPOCH_MISMATCH",
                status=409,
            )
        if source_sequence > int(
            binding["source_sequence"]
        ) or revealed_boundary_ms > int(binding["virtual_time_ms"]):
            raise fail(
                "tape projection is ahead of the durable cursor",
                code="HISTORY_BOUNDARY_AHEAD",
                status=409,
            )
        config = ReplaySessionConfig.from_dict(binding["config"])
        if config.source_kind is not SourceKind.AGG_TRADE:
            raise fail("tape projection requires an aggregate-trade source")
        width = parse_interval_ms(display_interval)
        if not width:
            raise fail("tape display interval is invalid")
        if before_ms is not None and (
            type(before_ms) is not int
            or before_ms < 0
            or before_ms > revealed_boundary_ms + 1
            or compute_bucket_start_ms(before_ms, width, interval=display_interval)
            != before_ms
        ):
            raise fail("tape history cursor must be a revealed display bucket boundary")
        history_scope = (
            "CONTEXT_AND_FROZEN_TAPE"
            if context_history is not None
            else "FROZEN_WARMUP_AND_TAPE"
        )
        actual_history_epoch = tape_history_epoch(
            data_epoch, config.base_interval, display_interval, context_history
        )
        if history_epoch is not None and history_epoch != actual_history_epoch:
            raise fail(
                "tape history generation changed; reload the chart",
                code="HISTORY_EPOCH_MISMATCH",
                status=409,
            )
        key = (
            binding["session_id"],
            binding["track_id"],
            data_epoch,
            display_interval,
            source_sequence,
            revealed_boundary_ms,
            limit,
            config.base_interval,
            persisted.get("synthetic_origin_ms"),
            before_ms,
            actual_history_epoch,
            indicator_input,
        )
        with self._lock:
            selection = self._selections.get(key)
            window = None if selection is None else self._cache.get(selection[0])
        if cancelled.is_set():
            raise InterruptedError("tape projection cancelled")
        if window is None:
            window = self._start(
                binding,
                persisted,
                archive,
                config,
                display_interval,
                width,
                source_sequence,
                revealed_boundary_ms,
                limit,
                before_ms,
                context_history,
            )
            # Closed pages contain the same immutable context/trades even when
            # playback advances. Keep their bounded preparation progress across
            # observer requests, but never cache the request's revealed boundary
            # as evidence for a different selected source sequence.
            content_key = (
                "indicator-content" if indicator_input else "content",
                binding["session_id"],
                binding["track_id"],
                data_epoch,
                display_interval,
                config.base_interval,
                actual_history_epoch,
                window.start_ms,
                window.end_ms,
                window.origin_ms,
                window.offset_ms,
                window.context_stop,
                window.target_sequence,
                window.close_at_ms,
                limit,
            )
            selection = (content_key, window.selected_closed_before_ms)
            with self._lock:
                self._selections[key] = selection
                self._selections.move_to_end(key)
                while len(self._selections) > self.capacity * 4:
                    self._selections.popitem(last=False)
        with self._own(selection[0], cancelled):
            with self._lock:
                cached = self._cache.get(selection[0])
            window = cached or self._extend_prefix(selection[0], window, cancelled)
            return self._advance_window(
                window=window,
                key=selection[0],
                selected_closed_before_ms=selection[1],
                cancelled=cancelled,
                context_history=context_history,
                revealed_boundary_ms=revealed_boundary_ms,
                display_interval=display_interval,
                width=width,
                limit=limit,
                before_ms=before_ms,
                binding=binding,
                config=config,
                actual_history_epoch=actual_history_epoch,
                history_scope=history_scope,
                data_epoch=data_epoch,
                source_sequence=source_sequence,
                include_selection_boundary=include_selection_boundary,
                indicator_input=indicator_input,
            )

    @staticmethod
    def _can_extend(previous, target):
        return (
            previous.close_at_ms is None
            and not previous.builder.finalized
            and previous.target_sequence <= target.target_sequence
            and target.next_sequence <= previous.next_sequence <= target.target_sequence
            and previous.origin_ms == target.origin_ms
            and previous.offset_ms == target.offset_ms
            and previous.context_stop == target.context_stop
            and previous.context_cursor >= target.context_cursor
            and previous.start_ms <= target.start_ms <= previous.end_ms
            and previous.end_ms <= target.end_ms
            # A prestart-only page can omit part of the frozen warmup. It is
            # not a complete seed for the subsequent execution window.
            and previous.end_ms >= previous.builder.start
            and previous.builder.capacity == target.builder.capacity
        )

    def _extend_prefix(self, key, target, cancelled):
        with self._lock:
            candidates = [
                (previous_key, previous.next_sequence, previous.context_cursor)
                for previous_key, previous in self._cache.items()
                if previous_key != key
                and previous_key[:7] == key[:7]
                and self._can_extend(previous, target)
            ]
        # At most capacity candidates. Acquire the predecessor's ownership
        # before copying because another worker may still be preparing it.
        # Target sequence/end never move backwards and finalized predecessors
        # are excluded, so nested ownership cannot form a dependency cycle.
        for previous_key, _, _ in sorted(
            candidates, key=lambda item: item[1:], reverse=True
        ):
            with self._own(previous_key, cancelled):
                with self._lock:
                    previous = self._cache.get(previous_key)
                if previous is None or not self._can_extend(previous, target):
                    continue
                builder = previous.builder.fork()
                builder.terminal = target.builder.terminal
                target.builder = builder
                target.next_sequence = previous.next_sequence
                target.context_cursor = previous.context_cursor
                target.warmup = previous.warmup
                target.incomplete_context_buckets = {
                    at
                    for at in previous.incomplete_context_buckets
                    if target.start_ms <= at < target.end_ms
                }
                return target
        return target

    def _advance_window(
        self,
        *,
        window,
        key,
        selected_closed_before_ms,
        cancelled,
        context_history,
        revealed_boundary_ms,
        display_interval,
        width,
        limit,
        before_ms,
        binding,
        config,
        actual_history_epoch,
        history_scope,
        data_epoch,
        source_sequence,
        include_selection_boundary,
        indicator_input,
    ):
        for _ in range(self.pages_per_call):
            if cancelled.is_set():
                raise InterruptedError("tape projection cancelled")
            if window.context_cursor < window.context_stop:
                indexed_reader = getattr(context_history, "read_indexed", None)
                indexed = (
                    None
                    if indexed_reader is None
                    else indexed_reader(
                        window.context_cursor,
                        window.context_stop,
                        display_interval,
                        cancelled,
                        **({"include_auxiliary": False} if indicator_input else {}),
                    )
                )
                if indexed is not None:
                    if cancelled.is_set():
                        raise InterruptedError("tape context cancelled")
                    stop, summaries = indexed
                    try:
                        window.builder.append_indexed_history(summaries)
                        window.context_cursor = stop
                    except Exception:
                        with self._lock:
                            self._cache.pop(key, None)
                        raise
                    self._remember(key, window)
                    continue
                chunk = context_history.read(window.context_cursor, window.context_stop)
                if cancelled.is_set():
                    raise InterruptedError("tape context cancelled")
                validate_chunk(chunk, revealed_boundary_ms)
                if (
                    chunk.start_ms != window.context_cursor
                    or chunk.stop_ms > window.context_stop
                ):
                    raise fail("tape context changed its page cursor")
                try:
                    window.builder.append_history(
                        tuple(
                            ReplayBar(
                                open_time_ms=bar.open_time_ms,
                                close_time_ms=bar.close_time_ms,
                                open=bar.open,
                                high=bar.high,
                                low=bar.low,
                                close=bar.close,
                                volume=bar.volume,
                                quote_volume=bar.quote_volume,
                                trades=bar.trades,
                                taker_buy_base=bar.taker_buy_base,
                                taker_buy_quote=bar.taker_buy_quote,
                                source="agg_trade_synthetic"
                                if bar.synthetic
                                else "replay_context",
                            )
                            for bar in chunk.bars
                        )
                    )
                    for gap_start, gap_end in chunk.gaps:
                        bucket = compute_bucket_start_ms(
                            gap_start, width, interval=display_interval
                        )
                        while bucket <= gap_end:
                            window.incomplete_context_buckets.add(bucket)
                            bucket = compute_bucket_end_ms(
                                bucket, width, interval=display_interval
                            )
                    window.context_cursor = chunk.stop_ms
                except Exception:
                    with self._lock:
                        self._cache.pop(key, None)
                    raise
                self._remember(key, window)
                continue
            if window.warmup:
                self._append_warmup(key, window)
            if window.next_sequence == window.target_sequence:
                break
            page = window.reader.read_sequence_page(
                after_sequence=window.next_sequence,
                revealed_sequence=window.target_sequence,
                limit=self.page_rows,
            )
            if cancelled.is_set():
                raise InterruptedError("tape projection cancelled")
            trades = tuple(
                trade.with_time_offset(window.offset_ms) for trade in page.trades
            )
            try:
                window.builder.apply_trades_final_state(trades)
            except Exception:
                with self._lock:
                    self._cache.pop(key, None)
                raise
            window.next_sequence = page.next_sequence
            self._remember(key, window)
        if window.context_cursor == window.context_stop and window.warmup:
            self._append_warmup(key, window)
        ready = (
            window.context_cursor == window.context_stop
            and window.next_sequence == window.target_sequence
        )
        if ready and window.close_at_ms is not None:
            window.builder.finalize_bars(virtual_time_ms=window.close_at_ms)
        bars = (
            []
            if not ready
            else [
                bar
                for bar in window.builder.replace_projection()["bars"]
                if bar["open_time_ms"] >= window.start_ms
                and (before_ms is None or bar["open_time_ms"] < before_ms)
            ][-limit:]
        )
        if ready:
            self._remember(key, window)
        cursor = (
            None
            if not ready
            else bars[0]["open_time_ms"]
            if bars
            else max(window.origin_ms, window.start_ms)
        )
        if cursor is not None and before_ms is not None:
            cursor = min(cursor, before_ms)
        return {
            "protocol": "replay.v3",
            "schema_version": "replay.tape-projection.v1",
            "run_id": str(binding["run_id"]),
            "identity": {
                "exchange": config.exchange,
                "market_type": config.market_type,
                "symbol": config.symbol,
                "source_kind": "AGG_TRADE",
                "base_interval": config.base_interval,
                "display_interval": display_interval,
            },
            "history_policy": {
                key: binding["history_policy"][key]
                for key in (
                    "schema_version",
                    "indicator_warmup_bars",
                    "visible_history_lookback",
                    "visible_history_rows",
                    "effective_warmup_bars",
                    "forward_cache_ms",
                    "interval_ms",
                    "policy_hash",
                )
            },
            "history_scope": history_scope,
            "history_epoch": actual_history_epoch,
            "context_prepared_before_ms": window.context_cursor,
            "context_target_before_ms": window.context_stop,
            "incomplete_context_buckets": sorted(window.incomplete_context_buckets)
            if ready
            else [],
            "session_id": binding["session_id"],
            "track_id": binding["track_id"],
            "data_epoch": data_epoch,
            "display_interval": display_interval,
            "revealed_boundary_ms": revealed_boundary_ms,
            "source_sequence": source_sequence,
            "target_sequence": window.target_sequence,
            "before_ms": before_ms,
            "history_boundary_ms": window.origin_ms,
            "next_before_ms": cursor,
            "has_more": None if cursor is None else cursor > window.origin_ms,
            "status": "ready" if ready else "preparing",
            "prepared_sequence": window.next_sequence,
            "bars": bars,
            **(
                {"selected_closed_before_ms": selected_closed_before_ms}
                if include_selection_boundary
                else {}
            ),
        }

    def _append_warmup(self, key, window):
        try:
            window.builder.append_history(window.warmup)
        except Exception:
            with self._lock:
                self._cache.pop(key, None)
            raise
        window.warmup = ()

    def _remember(self, key, window):
        with self._lock:
            now = self._clock()
            window.last_progress_at = now
            self._cache[key] = window
            self._cache.move_to_end(key)
            while len(self._cache) > self.capacity:
                # Origin probes and completed indicator pages must not evict
                # a cold chart that is still accumulating minute history.
                # Retention is bounded in both count and time: closed tabs or
                # failed observers cannot pin unfinished windows indefinitely.
                victim = next(
                    (
                        candidate
                        for candidate, prepared in self._cache.items()
                        if now - prepared.last_progress_at
                        >= self.pending_retention_seconds
                        or (
                            prepared.context_cursor == prepared.context_stop
                            and prepared.next_sequence == prepared.target_sequence
                            and not prepared.warmup
                        )
                    ),
                    next(iter(self._cache)),
                )
                del self._cache[victim]

    def _reader(self, archive, reference):
        # A reader has no mutable cursor. Reuse one already validated for this
        # exact immutable manifest and archive, with the same cache lifetime as
        # its prepared windows. Cold imports/changed references still validate
        # the whole source; every bounded read still checks epoch/ID continuity.
        if archive.enabled:
            with self._lock:
                for window in reversed(self._cache.values()):
                    reader = window.reader
                    if (
                        reader.archive is archive
                        and reader.dataset_ref == reference
                        and reader.page_rows == self.page_rows
                    ):
                        return reader
        return PagedReplayTradeReader(archive, reference, page_rows=self.page_rows)

    def _start(
        self,
        binding,
        persisted,
        archive,
        config,
        interval,
        width,
        sequence,
        boundary,
        limit,
        before_ms,
        context_history,
    ):
        snapshot = _decode_bar_snapshot(persisted, config=config)
        raw = json.loads(bytes(persisted["snapshot_blob"]))
        reference = RawAggTradeDatasetRef.from_dict(raw["trade_dataset_ref"])
        if (
            reference.data_epoch != persisted["data_epoch"]
            or sequence > reference.row_count
        ):
            raise fail(
                "frozen tape sequence or epoch changed",
                code="HISTORY_DATA_EPOCH_MISMATCH",
                status=409,
            )
        if (reference.exchange, reference.market_type, reference.symbol) != (
            config.exchange,
            config.market_type,
            config.symbol,
        ):
            raise fail("frozen tape belongs to another market")
        offset = snapshot.replay_start_ms - reference.start_time_ms
        terminal = reference.end_time_ms + offset
        if boundary > terminal or boundary < snapshot.replay_start_ms - 1:
            raise fail("tape projection time is outside the frozen range")
        reader = self._reader(archive, reference)
        last = (
            None
            if sequence == 0
            else reader.read_sequence_page(
                after_sequence=sequence - 1, revealed_sequence=sequence, limit=1
            ).trades[0]
        )
        if last is not None and last.trade_time_ms + offset > boundary:
            raise fail(
                "selected trade sequence is ahead of the revealed time",
                code="HISTORY_BOUNDARY_AHEAD",
                status=409,
            )
        observed = (
            terminal
            if boundary == terminal and sequence == reference.row_count
            else last.trade_time_ms + offset
            if last is not None
            else snapshot.replay_start_ms - 1
        )
        observed_start = compute_bucket_start_ms(observed, width, interval=interval)
        selected_closed_before = compute_bucket_start_ms(
            observed + (boundary == terminal and sequence == reference.row_count),
            width,
            interval=interval,
        )
        end = compute_bucket_end_ms(observed_start, width, interval=interval)
        if last is not None and boundary >= end:
            # A clock-only advance can complete the last selected bucket even
            # before this market trades again. A historical request may pair
            # an older sequence with that newer clock, so time alone is not a
            # completeness proof: an unselected trade in the same bucket must
            # keep it forming (including a partial equal-ms cohort).
            next_trade = (
                None
                if sequence == reference.row_count
                else reader.read_sequence_page(
                    after_sequence=sequence,
                    revealed_sequence=sequence + 1,
                    limit=1,
                ).trades[0]
            )
            if next_trade is None or next_trade.trade_time_ms + offset >= end:
                selected_closed_before = end
        if before_ms is not None:
            end = min(end, before_ms)
        start = compute_bucket_start_ms(max(0, end - 1), width, interval=interval)
        for _ in range(limit - 1):
            if start == 0:
                break
            start = compute_bucket_start_ms(start - 1, width, interval=interval)
        frozen_start = (
            snapshot.warmup_rows[0].open_time_ms
            if snapshot.warmup_rows
            else snapshot.replay_start_ms
        )
        history_start = (
            frozen_start if context_history is None else context_history.origin_ms
        )
        origin = compute_bucket_start_ms(
            history_start,
            width,
            interval=interval,
        )
        start = max(start, origin)
        target = sequence
        close_at = None
        if end <= snapshot.replay_start_ms:
            target, last = 0, None
        elif last is not None and end <= last.trade_time_ms + offset:
            # A later revealed trade proves the older page is complete, but
            # must not itself enter the page or its OHLC/volume.
            first_after = archive.scan_page(
                exchange=reference.exchange,
                market_type=reference.market_type,
                symbol=reference.symbol,
                start_time_ms=end - offset,
                end_time_ms=last.trade_time_ms,
                start_agg_trade_id=reference.expected_first_agg_trade_id,
                end_agg_trade_id=reference.expected_first_agg_trade_id + sequence - 1,
                limit=1,
                dataset_ref=reference,
            )
            if first_after.data_epoch != reference.data_epoch or not first_after.rows:
                raise fail(
                    "frozen tape page boundary is incomplete",
                    code="HISTORY_SOURCE_INCOMPLETE",
                    status=503,
                )
            next_trade = ReplayTrade.from_archive_row(first_after.rows[0])
            target = next_trade.agg_trade_id - reference.expected_first_agg_trade_id
            if not 0 <= target < sequence or next_trade.trade_time_ms + offset < end:
                raise fail("frozen tape page boundary is invalid")
            last = (
                None
                if target == 0
                else reader.read_sequence_page(
                    after_sequence=target - 1,
                    revealed_sequence=target,
                    limit=1,
                ).trades[0]
            )
            if last is not None and last.trade_time_ms + offset >= end:
                raise fail(
                    "frozen tape page omitted an earlier trade",
                    code="HISTORY_SOURCE_INCOMPLETE",
                    status=503,
                )
            close_at = end - 1
        elif boundary == terminal and sequence == reference.row_count:
            close_at = terminal
        elif end <= selected_closed_before:
            close_at = end - 1
        execution_start = max(start, snapshot.replay_start_ms)
        after = 0
        warmup = tuple(
            bar
            for bar in snapshot.warmup_rows
            if max(start, history_start) <= bar.open_time_ms < end
        )
        if execution_start > snapshot.replay_start_ms:
            after = target
            previous = last
            if last is not None and execution_start - offset <= last.trade_time_ms:
                first = archive.scan_page(
                    exchange=reference.exchange,
                    market_type=reference.market_type,
                    symbol=reference.symbol,
                    start_time_ms=execution_start - offset,
                    end_time_ms=last.trade_time_ms,
                    start_agg_trade_id=reference.expected_first_agg_trade_id,
                    end_agg_trade_id=reference.expected_first_agg_trade_id + target - 1,
                    limit=1,
                    dataset_ref=reference,
                )
                if first.data_epoch != reference.data_epoch or not first.rows:
                    raise fail(
                        "frozen tape window is incomplete",
                        code="HISTORY_SOURCE_INCOMPLETE",
                        status=503,
                    )
                trade = ReplayTrade.from_archive_row(first.rows[0])
                after = trade.agg_trade_id - reference.expected_first_agg_trade_id
                if (
                    not 0 <= after < target
                    or trade.trade_time_ms < execution_start - offset
                ):
                    raise fail("frozen tape window cursor is invalid")
                previous = (
                    None
                    if after == 0
                    else reader.read_sequence_page(
                        after_sequence=after - 1, revealed_sequence=after, limit=1
                    ).trades[0]
                )
                if (
                    previous is not None
                    and previous.trade_time_ms + offset >= execution_start
                ):
                    raise fail(
                        "frozen tape window omitted an earlier trade",
                        code="HISTORY_SOURCE_INCOMPLETE",
                        status=503,
                    )
            close = (
                previous.price
                if previous is not None
                else snapshot.warmup_rows[-1].close
                if snapshot.warmup_rows
                else None
            )
            base_ms = parse_interval_ms(config.base_interval)
            warmup = (
                ()
                if close is None
                else (
                    ReplayBar(
                        open_time_ms=execution_start - base_ms,
                        close_time_ms=execution_start - 1,
                        open=close,
                        high=close,
                        low=close,
                        close=close,
                        volume="0",
                        quote_volume="0",
                        trades=0,
                        taker_buy_base="0",
                        taker_buy_quote="0",
                        source="agg_trade_synthetic",
                    ),
                )
            )
        context_stop = min(frozen_start, end) if context_history is not None else 0
        context_cursor = (
            min(max(start, history_start), context_stop)
            if context_history is not None
            else 0
        )
        builder = TapeChartBuilder(
            base_interval=config.base_interval,
            display_interval=interval,
            replay_start_ms=execution_start,
            replay_end_time_ms=terminal if close_at is None else close_at,
            max_closed_bars=limit + 1,
        )
        # This price seeds empty execution minutes only. A prestart-only page
        # never finalizes execution, so it cannot publish this later warmup price.
        builder.previous_close = (
            snapshot.warmup_rows[-1].close if snapshot.warmup_rows else None
        )
        return _Window(
            reader,
            builder,
            after,
            start,
            offset,
            target,
            close_at,
            origin,
            context_cursor,
            context_stop,
            warmup,
            set(),
            selected_closed_before,
            end,
        )
