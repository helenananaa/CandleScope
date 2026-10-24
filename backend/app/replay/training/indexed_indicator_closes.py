"""Complete pre-tape close inputs from the same immutable minute authority.

Close-source builtins do not require constructing OHLCV display objects. The
range proof still covers every source minute, including those between selected
closes. Gaps, unusual values and the frozen warmup/tape seam use the chart path.
"""

from array import array
from bisect import bisect_right
from typing import NamedTuple

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


class _CloseInputs(NamedTuple):
    start_ms: int
    stop_ms: int
    first_ms: int
    ends: array
    closes: list[str]
    gaps: tuple


def _read_inputs(context, start, before, interval, width, cancelled, *, local_only):
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
    # The batch keeps primitive input columns, not tens of thousands of
    # tracked per-bar objects. Only consumed 500-bar pages become objects.
    ends = array("q")
    for _ in range((MAX_CONTEXT_MINUTES if local_only else 500) - len(gaps)):
        end = compute_bucket_end_ms(cursor, width, interval=interval)
        if end > limit:
            break
        ends.append(end)
        cursor = end
    if not ends:
        return _CloseInputs(start, first, first, ends, [], gaps) if gaps else None
    closes = select_indexed_closes(
        context, first, cursor, [end - 60000 for end in ends], cancelled,
        local_only=local_only,
    )
    if closes is None:
        if local_only:
            return None
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
            [(end - first) // 60000 - 1 for end in ends], cancelled
        )
    if cancelled.is_set():
        raise InterruptedError("indicator close preparation cancelled")
    if len(closes) != len(ends):
        raise ValueError("indicator close source changed its bounded row count")
    return _CloseInputs(start, cursor, first, ends, closes, gaps)


def _page(inputs, start, revealed_boundary_ms):
    index = bisect_right(inputs.ends, start)
    first = inputs.ends[index - 1] if index else inputs.first_ms
    gaps = inputs.gaps if start == inputs.start_ms else ()
    if start != first and not gaps:
        raise ValueError("buffered indicator prefix cursor is not a bucket boundary")
    stop_index = min(len(inputs.ends), index + 500 - len(gaps))
    bars = tuple(
        IndicatorCloseBar(
            inputs.ends[i - 1] if i else inputs.first_ms,
            inputs.ends[i] - 1, inputs.ends[i] - 60000, inputs.closes[i],
        )
        for i in range(index, stop_index)
    )
    stop = inputs.ends[stop_index - 1] if bars else gaps[-1][1] + 1
    chunk = IndicatorCloseChunk(start, stop, bars, gaps)
    validate_chunk(chunk, revealed_boundary_ms)
    return chunk


def read_indexed_closes(context, start, before, interval, width, cancelled):
    inputs = _read_inputs(context, start, before, interval, width, cancelled, local_only=False)
    return None if inputs is None else _page(inputs, start, context.revealed_boundary_ms)


class LocalIndicatorCloseBuffer:
    """One worker's bounded local inputs, exposed as ordinary 500-bar pages.

    Prefetch never prepares a missing day or builds the account range index.
    A miss disables prefetch for this worker; ordinary pages keep their lazy
    source preparation and fallback. The next worker revalidates disk inputs.
    """

    def __init__(self, context, interval, width, cancelled):
        self.context, self.interval, self.width = context, interval, width
        self.cancelled = cancelled
        self.inputs = None
        self.target = None
        self.enabled = True

    def read(self, start, before):
        if self.cancelled.is_set():
            raise InterruptedError("indicator close preparation cancelled")
        inputs = self.inputs
        if inputs is None or self.target != before or not inputs.start_ms <= start < inputs.stop_ms:
            inputs = None
            if self.enabled:
                inputs = _read_inputs(
                    self.context, start, before, self.interval, self.width,
                    self.cancelled, local_only=True,
                )
                self.enabled = inputs is not None
            self.inputs, self.target = inputs, before
        if inputs is None:
            return read_indexed_closes(
                self.context, start, before, self.interval, self.width, self.cancelled,
            )
        if self.cancelled.is_set():
            raise InterruptedError("indicator close preparation cancelled")
        return _page(inputs, start, self.context.revealed_boundary_ms)
