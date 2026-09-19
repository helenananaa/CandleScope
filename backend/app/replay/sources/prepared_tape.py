"""Command-local validated tape blocks sharing immutable reader pages only."""

from bisect import bisect_right
from dataclasses import dataclass

from .trade_source import TradeReplaySource


@dataclass(frozen=True)
class PreparedTapeSlice:
    trades: tuple
    start: TradeReplaySource
    end: TradeReplaySource
    revision: int
    target: int

    def validate(self, actor, target):
        source = actor._source
        if (type(source) is not TradeReplaySource
                or source._reader is not self.start._reader
                or source._blind_mode != self.start._blind_mode
                or source._time_offset_ms != self.start._time_offset_ms
                or source.snapshot_ref() != self.start.snapshot_ref()
                or source.cursor() != self.start.cursor()
                or actor._revision != self.revision or target != self.target):
            raise ValueError("prepared tape basis changed")


@dataclass(frozen=True)
class PreparedTapeBlock:
    trades: tuple
    offsets: tuple
    sources: tuple
    next_time: int | None

    def position(self, count):
        if not 0 <= count <= len(self.trades):
            raise ValueError("prepared tape position outside block")
        index = bisect_right(self.offsets, count) - 1
        source = self.sources[index].fork()
        delta = count - self.offsets[index]
        if delta:
            source._page_index += delta
            actual = source._page[source._page_index - 1]
            public = self.trades[count - 1]
            source._source_sequence += delta
            source._last_actual = actual.cursor
            source._last_public_time_ms = public.trade_time_ms
            source._last_public_agg_trade_id = public.agg_trade_id
            source._peeked_public = None
        return source

    def slice(self, first, last, revision, target):
        if not 0 <= first <= last <= len(self.trades):
            raise ValueError("prepared tape slice outside block")
        next_time = (self.trades[last].trade_time_ms
                     if last < len(self.trades) else self.next_time)
        if ((last and self.trades[last - 1].trade_time_ms > target)
                or next_time is None or next_time <= target):
            raise ValueError("prepared tape slice must end at a complete nonterminal cohort")
        return PreparedTapeSlice(
            self.trades[first:last], self.position(first), self.position(last),
            revision, target,
        )


def plan(actor, target, maximum):
    if type(actor._source) is not TradeReplaySource:
        return None
    source = actor._source.fork()
    maximum = min(maximum, 8192)
    trades, offsets, sources = [], [], []
    while len(trades) < maximum and (event := source.peek()) is not None:
        if event.trade_time_ms > target:
            break
        # Save one independent cursor per immutable page, after public identity
        # initialization. Any prefix position can then be derived without reads.
        if not sources or sources[-1]._page is not source._page:
            offsets.append(len(trades))
            sources.append(source.fork())
        if source.next() != event:
            raise ValueError("source changed during tape preparation")
        trades.append(event)
    following = source.peek()
    block = None
    if trades:
        block = PreparedTapeBlock(
            tuple(trades), tuple(offsets), tuple(sources),
            None if following is None else following.trade_time_ms,
        )
    return dict(
        revision=actor._revision, cursor=actor._cursor_dict(),
        event_count=len(trades),
        last_event_time_ms=trades[-1].trade_time_ms if trades else None,
        event_times_ms=tuple(e.trade_time_ms for e in trades),
        event_prices=tuple(e.price for e in trades),
        has_more_before_target=following is not None and following.trade_time_ms <= target,
        max_events=maximum, prepared_tape=block,
    )
