"""Complete pre-tape close inputs from the same immutable minute authority.

Close-source builtins do not require constructing OHLCV display objects. The
range proof still covers every source minute, including those between selected
closes. Gaps, unusual values and the frozen warmup/tape seam use the chart path.
"""

from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
)

from .indexed_tape_context import (
    MAX_CONTEXT_MINUTES,
    select_indexed_closes,
    select_indexed_context,
)
from .indicator_history import IndicatorCloseBar, IndicatorCloseChunk, validate_chunk


def read_indexed_closes(context, start, before, interval, width, cancelled):
    snapshot = getattr(context, "snapshot", None)
    if snapshot is None or context.config.base_interval != "1m":
        return None
    if start != compute_bucket_start_ms(start, width, interval=interval):
        return None
    frozen = (
        snapshot.warmup_rows[0].open_time_ms
        if snapshot.warmup_rows
        else snapshot.replay_start_ms
    )
    if start >= frozen or start < compute_bucket_start_ms(
        context.origin_ms, width, interval=interval
    ):
        return None
    if cancelled.is_set():
        raise InterruptedError("indicator close preparation cancelled")
    # A partial first display bucket has never been a valid recursive seed.
    # Its known incomplete span resets the math just as in TapeIndicatorHistory.
    cursor, gaps = start, ()
    if start < context.origin_ms:
        cursor = compute_bucket_end_ms(start, width, interval=interval)
        if cursor > before:
            return None
        gaps = ((start, cursor - 1),)
    first = cursor
    limit = min(before, frozen, first + MAX_CONTEXT_MINUTES * 60000)
    spans = []
    for _ in range(500 - len(gaps)):
        end = compute_bucket_end_ms(cursor, width, interval=interval)
        if end > limit:
            break
        spans.append((cursor, end))
        cursor = end
    if not spans:
        return IndicatorCloseChunk(start, first, (), gaps) if gaps else None
    closes = select_indexed_closes(
        context, first, cursor, [end - 60000 for _, end in spans], cancelled,
    )
    stop = cursor
    if closes is None:
        selected = select_indexed_context(context, first, cursor, cancelled)
        if selected is None:
            return None
        stop, market = selected
        if stop != cursor:
            raise ValueError("indicator close source changed its bounded range")
        # The ordinary indexed fallback retains its broader Decimal domain.
        coverage = market.display_summary(0, market.count, include_auxiliary=False)
        if any(
            value.adjusted() > 18 or value.as_tuple().exponent < -18
            for value in coverage[:5]
        ):
            return None
        closes = market.indicator_closes_at(
            [(end - first) // 60000 - 1 for _, end in spans], cancelled
        )
    if cancelled.is_set():
        raise InterruptedError("indicator close preparation cancelled")
    chunk = IndicatorCloseChunk(
        start,
        stop,
        tuple(
            IndicatorCloseBar(at, end - 1, end - 60000, close)
            for (at, end), close in zip(spans, closes, strict=True)
        ),
        gaps,
    )
    validate_chunk(chunk, context.revealed_boundary_ms)
    return chunk
