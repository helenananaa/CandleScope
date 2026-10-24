"""Canonical closed indicator prefixes from the same source as tape charts."""

from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.replay.bars.builder import ReplayDisplayBar

from .indicator_history import (
    IndicatorHistoryChunk,
    IndicatorHistoryPreparing,
    validate_chunk,
)
from .tape_projection import tape_history_epoch


class TapeIndicatorHistory:
    def __init__(
        self,
        *,
        context_history,
        projection,
        binding,
        persisted,
        archive,
        data_epoch,
        display_interval,
        source_sequence,
        revealed_boundary_ms,
        cancelled,
    ):
        self.interval = display_interval
        self.interval_ms = parse_interval_ms(display_interval)
        if not self.interval_ms:
            raise ValueError("invalid tape indicator interval")
        self.origin_ms = compute_bucket_start_ms(
            context_history.origin_ms, self.interval_ms, interval=self.interval
        )
        self.revealed_boundary_ms = revealed_boundary_ms
        self.history_epoch = tape_history_epoch(
            data_epoch, str(binding["base_interval"]), display_interval, context_history
        )
        self.identity = {
            **context_history.identity,
            "contract": "replay.indicator-tape-origin.v1",
            "history_epoch": self.history_epoch,
            "origin_ms": self.origin_ms,
            "identity": {
                **context_history.identity["identity"],
                "display_interval": display_interval,
            },
        }
        self.projection = projection
        self.arguments = {
            "binding": binding,
            "persisted": persisted,
            "archive": archive,
            "data_epoch": data_epoch,
            "display_interval": display_interval,
            "source_sequence": source_sequence,
            "revealed_boundary_ms": revealed_boundary_ms,
            "context_history": context_history,
            "history_epoch": self.history_epoch,
            "cancelled": cancelled,
            # Builtin mathematics consume OHLCV only. The shared chart reducer
            # keeps the same boundaries and gap rules, but need not aggregate
            # quote/trade/taker columns over the complete historical prefix.
            "indicator_input": True,
        }
        # Empty origin page validates the selected source/time even if there is
        # no mathematical prefix. It is bounded and reused by sibling indicators.
        selected = projection.compute(
            **self.arguments,
            before_ms=self.origin_ms,
            limit=1,
            include_selection_boundary=True,
        )
        self.closed_before_ms = selected["selected_closed_before_ms"]
        from .indexed_indicator_closes import LocalIndicatorCloseBuffer

        self.close_buffer = LocalIndicatorCloseBuffer(
            context_history, self.interval, self.interval_ms, cancelled,
        )

    def read_closes(self, start_ms, stop_before_ms):
        if (
            start_ms < self.origin_ms
            or not start_ms < stop_before_ms <= self.closed_before_ms
        ):
            return None
        return self.close_buffer.read(start_ms, stop_before_ms)

    def read(self, start_ms, stop_before_ms):
        if (
            start_ms < self.origin_ms
            or not start_ms < stop_before_ms <= self.revealed_boundary_ms + 1
        ):
            raise ValueError("tape indicator prefix is outside its revealed source")
        stop, count = start_ms, 0
        while stop < stop_before_ms and count < 500:
            stop = compute_bucket_end_ms(stop, self.interval_ms, interval=self.interval)
            count += 1
        stop = min(stop, stop_before_ms)
        result = self.projection.compute(**self.arguments, before_ms=stop, limit=count)
        if result["status"] != "ready":
            context = (
                result["context_prepared_before_ms"]
                < result["context_target_before_ms"]
            )
            raise IndicatorHistoryPreparing(
                {
                    "window_start_ms": start_ms,
                    "window_stop_ms": stop,
                    "phase": "context" if context else "trades",
                    "prepared": result["context_prepared_before_ms"]
                    if context
                    else result["prepared_sequence"],
                    "target": result["context_target_before_ms"]
                    if context
                    else result["target_sequence"],
                    "source_sequence": result["source_sequence"],
                }
            )
        if (
            result["history_epoch"] != self.history_epoch
            or result["history_boundary_ms"] != self.origin_ms
        ):
            raise ValueError("tape indicator history source changed")
        bars, gap_buckets = [], set(result["incomplete_context_buckets"])
        for raw in result["bars"]:
            bar = ReplayDisplayBar.from_dict(raw)
            if not start_ms <= bar.open_time_ms < stop:
                raise ValueError("tape indicator source returned another window")
            if bar.is_closed:
                bars.append(bar)
            elif bar.open_time_ms == self.origin_ms or bar.open_time_ms in gap_buckets:
                # A partial oldest bucket and declared holes never seed RSI as
                # complete bars. They reset the state just like explicit gaps.
                gap_buckets.add(bar.open_time_ms)
            else:
                raise ValueError("tape indicator prefix contains an unrevealed bucket")
        gaps = tuple(
            (
                at,
                min(
                    stop,
                    compute_bucket_end_ms(at, self.interval_ms, interval=self.interval),
                )
                - 1,
            )
            for at in sorted(gap_buckets)
            if start_ms <= at < stop
        )
        chunk = IndicatorHistoryChunk(start_ms, stop, tuple(bars), gaps)
        validate_chunk(chunk, self.revealed_boundary_ms)
        return chunk
