"""Fixed-horizon BAR cursor backed by continuously published immutable segments."""
from types import MappingProxyType

from ..errors import ReplayDomainError, ReplayErrorCode
from .bar_source import PagedBarReplaySource, BAR_TERMINAL_REQUESTED_HORIZON


class ProgressiveBarReplaySource(PagedBarReplaySource):
    def __init__(self, snapshot, *, history, feed_id, page_rows=256, actual_snapshot=None):
        if type(page_rows) is not int or not 1 <= page_rows <= 4096:
            raise ValueError("progressive page size must contain 1-4096 bars")
        feed = history.status(feed_id)
        actual = actual_snapshot or snapshot
        offset = snapshot.replay_start_ms - actual.replay_start_ms
        identity = snapshot.identity
        if (feed["identity"] != {"exchange": identity.exchange, "market_type": identity.market_type, "symbol": identity.symbol}
                or snapshot.interval != "1m" or feed["start_ms"] != actual.replay_start_ms
                or actual.replay_end_open_ms + 60_000 > feed["end_ms"]):
            raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Initial BAR snapshot does not match the progressive horizon")
        initial = tuple(row.with_time_offset(offset) for row in history.read(feed_id, actual.replay_start_ms, actual.replay_end_open_ms + 60_000))
        if initial != snapshot.replay_rows:
            raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Initial BAR snapshot differs from its published segment")

        def load_page(start, end, count):
            return tuple(row.with_time_offset(offset) for row in history.read(feed_id, start - offset, end - offset + 60_000))

        super().__init__(snapshot, terminal_open_ms=feed["end_ms"] - 60_000 + offset,
            terminal_kind=BAR_TERMINAL_REQUESTED_HORIZON, source_revision=feed_id,
            source_fingerprint=feed_id, page_rows=page_rows, page_loader=load_page)
        # Distinct from single-revision paged archives: restoration must rebind
        # this durable feed rather than resolve the latest mutable market data.
        self._snapshot_ref = MappingProxyType({**self._snapshot_ref,
            "schema_version": "replay-progressive-bar-source.v1", "feed_id": feed_id})

    def ready(self):
        """Availability is independent from cursor exhaustion and never advances."""
        try:
            self.peek()
        except ReplayDomainError as exc:
            if exc.code is ReplayErrorCode.DATASET_PENDING:
                return False
            raise
        return True
