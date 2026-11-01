"""H127: bounded, revision-fenced reads of canonical closed history.

One context owns one page, using B130 leases rather than a second cache. A
receipt (and continuation) becomes available only after successful context
exit. Consumers may stage a prefix inside the context, but must not publish it
before that fence passes. This interface does not download or materialize.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import threading
import time

from app.data_engine.aggregation.blocks import BlockKey, BlockRevisionChanged, BlockUnavailable
from app.data_engine.aggregation.core import InputRevision, AcceptedComponent, summarize
from app.data_engine.history import AlwaysOpenCalendar
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
from app.data_engine.interval_resolution import IntervalPurpose, IntervalRouteKind
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size
from .models import SeriesKey


MAX_PAGE_ROWS = 256
BLOCK_ROWS = 16
FIELDS = frozenset(("open", "high", "low", "close", "volume", "quote_volume",
                    "trades", "taker_buy_base", "taker_buy_quote"))
CORE_FIELDS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class HistoryBlockCursor:
    source: SeriesKey
    start_ms: int
    end_ms: int
    position_ms: int
    direction: str
    revisions: tuple[InputRevision, ...]
    required_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoryBlockReceipt:
    source: SeriesKey
    requested_range: tuple[int, int]
    page_range: tuple[int, int]
    revisions: tuple[InputRevision, ...]
    unavailable_ranges: tuple[tuple[int, int], ...]
    missing_fields: tuple[str, ...]
    complete: bool
    continuation: HistoryBlockCursor | None
    blocks: int
    storage_rows: int
    cache_hits: int


class HistoryBlockPage:
    """Lease-scoped values; an accepted immutable receipt survives release."""
    def __init__(self, leases):
        self._leases = leases
        self._active = True
        self._receipt = None

    @property
    def blocks(self):
        if not self._active:
            raise BlockRevisionChanged("history page leases have been released")
        return tuple(lease.block for lease in self._leases)

    @property
    def receipt(self) -> HistoryBlockReceipt:
        if self._receipt is None:
            raise BlockRevisionChanged("history page has not passed its publication fence")
        return self._receipt


class HistoryBlockReader:
    def __init__(self, engine):
        self.engine = engine
        self._lock = threading.Lock()
        self._metrics = dict(reads=0, accepted_pages=0, partial_pages=0, failures=0,
                             cancellations=0, storage_reads=0, storage_rows=0, cache_hits=0, accepted_blocks=0)

    def snapshot(self):
        with self._lock:
            return {**self._metrics, "max_page_rows": MAX_PAGE_ROWS, "block_rows": BLOCK_ROWS}

    def _count(self, **values):
        with self._lock:
            for key, value in values.items():
                self._metrics[key] += value

    @staticmethod
    def _cancelled(cancel):
        if cancel is not None and cancel.is_set():
            raise CancelledError()

    def _qualify(self, source):
        # v1 deliberately qualifies canonical crypto grids, not arbitrary
        # calendar/provider semantics. No implicit replacement with 1m data.
        if (not isinstance(source, SeriesKey) or source.exchange not in ("binance", "okx")
                or not source.identity.is_legacy_default_for(source.exchange)):
            raise ValueError("H127 requires a qualified default Binance/OKX source identity")
        route = self.engine._interval_resolver.resolve(exchange=source.exchange,
            market_type=source.market_type, interval=source.interval, purpose=IntervalPurpose.HISTORY)
        spec = parse_interval_spec(source.interval)
        if (route.kind is not IntervalRouteKind.NATIVE or route.canonical_interval != source.interval
                or spec is None or spec.alignment is not IntervalAlignment.FIXED_EPOCH
                or spec.phase_ms != 0 or not 60_000 <= spec.nominal_ms <= 86_400_000):
            raise ValueError("H127 v1 requires a canonical native fixed grid between 1m and 1d")
        policy = self.engine.history_policy
        if policy is not None:
            try:
                calendar = policy.calendar_for(self.engine._history_series_key(source))
            except Exception as exc:
                raise BlockUnavailable("cannot qualify the history calendar") from exc
            if not isinstance(calendar, AlwaysOpenCalendar):
                raise ValueError("H127 v1 does not qualify session or unknown calendars")
        return spec.nominal_ms, policy

    @contextmanager
    def read(self, source: SeriesKey, start_ms: int, end_ms: int, *,
             max_rows: int = MAX_PAGE_ROWS, direction: str = "asc",
             cursor: HistoryBlockCursor | None = None,
             required_fields=CORE_FIELDS, cancel=None):
        """Read a page of a half-open range, on a storage worker (never the event loop).

        Page size limits expected source slots, not returned rows. Empty or
        untrusted slots are unavailable coverage, not proof of source exhaustion
        or an instruction to repair. Budget/source errors abort without receipt.
        """
        self._count(reads=1)
        page = None
        try:
            self._cancelled(cancel)
            width, policy = self._qualify(source)
            if (type(start_ms) is not int or type(end_ms) is not int
                    or not 0 <= start_ms < end_ms <= (1 << 63) - 1
                    or start_ms % width or end_ms % width
                    or end_ms > int(time.time() * 1000) // width * width):
                raise ValueError("aligned, elapsed half-open source range required")
            if type(max_rows) is not int or not 1 <= max_rows <= MAX_PAGE_ROWS:
                raise ValueError("history page row budget must be between 1 and 256")
            if direction not in ("asc", "desc"):
                raise ValueError("history direction must be asc or desc")
            # Reject unbounded/unsupported field containers before materializing.
            if not isinstance(required_fields, (tuple, list, set, frozenset)) or len(required_fields) > len(FIELDS):
                raise ValueError("bounded required-field set required")
            fields = tuple(sorted(set(required_fields)))
            if not fields or not set(fields) <= FIELDS:
                raise ValueError("unsupported required history fields")
            position = start_ms if direction == "asc" else end_ms
            if cursor is not None:
                if (not isinstance(cursor, HistoryBlockCursor)
                        or (cursor.source, cursor.start_ms, cursor.end_ms, cursor.direction, cursor.required_fields)
                        != (source, start_ms, end_ms, direction, fields)
                        or type(cursor.position_ms) is not int or cursor.position_ms % width
                        or not start_ms < cursor.position_ms < end_ms):
                    raise ValueError("history continuation does not match the request")
                position = cursor.position_ms
            lo, hi = ((position, min(end_ms, position + max_rows * width)) if direction == "asc"
                      else (max(start_ms, position - max_rows * width), position))
            manager = getattr(self.engine, "shared_blocks", None)
            storage = self.engine.storage
            adapter = getattr(manager, "source", None)
            store = getattr(storage, "revision_store", None)
            if (manager is None or storage is None or adapter is None or store is None
                    or getattr(adapter, "store", None) is not store):
                raise BlockUnavailable("versioned canonical history storage is unavailable")

            def check_binding():
                if (self.engine.storage is not storage or manager.source is not adapter
                        or self.engine.history_policy is not policy):
                    raise BlockRevisionChanged("history source binding changed during the read")

            with manager.view((source,)) as view:
                check_binding()
                if cursor is not None and cursor.revisions != view.revisions:
                    raise BlockRevisionChanged("history continuation source revision expired")
                # Raw rows, decoded bars and page output metadata share the
                # existing D126 history-query allowance. B130 charges its own
                # retained summaries and per-build work separately.
                work_bytes = (hi - lo) // width * 4096 + 4096
                with self.engine.memory_budget.reserve("history-query", 32 * 1024), ExitStack() as held:
                    ranges = []
                    at = lo
                    while at < hi:
                        stop = min(hi, (at // (BLOCK_ROWS * width) + 1) * BLOCK_ROWS * width)
                        ranges.append((at, stop))
                        at = stop
                    leases = {}
                    for bounds in ranges:
                        self._cancelled(cancel)
                        lease = manager.acquire(BlockKey(source, *bounds, input_fingerprint="h127-canonical-v1"), view, cancel=cancel)
                        if lease is not None:
                            held.callback(lease.close)
                            leases[bounds] = lease
                    hits = len(leases)
                    self._count(cache_hits=hits)
                    rows_read = 0
                    if hits != len(ranges):
                        with self.engine.memory_budget.reserve("history-query", work_bytes):
                            self._cancelled(cancel)
                            leaves, build = [], None
                            self._count(storage_reads=1)
                            rows = self.engine._read_canonical_history_rows(storage, source, lo, hi,
                                                                          (hi - lo) // width + 1)
                            rows_read = len(rows)
                            self._count(storage_rows=rows_read)
                            self._cancelled(cancel)
                            check_binding()
                            if retained_size((rows,))[0] > work_bytes // 2:
                                raise MemoryBudgetExceeded("canonical history page exceeds its decoding allowance")
                            times = [row["open_time"] for row in rows]
                            if (len(times) > (hi - lo) // width or len(set(times)) != len(times)
                                    or any(type(t) is not int or not lo <= t < hi or t % width for t in times)):
                                raise BlockUnavailable("canonical history page violates its grid or row bound")
                            valid = [row for row in rows if row.get("close_time") == row["open_time"] + width - 1]
                            bars = self.engine._storage_rows_to_bars(source, valid)
                            accepted = {bar.time_ms: bar for bar in bars if bar.is_closed and bar.trusted_final}
                            for bounds in ranges:
                                self._cancelled(cancel)
                                if bounds in leases:
                                    continue
                                leaves = [accepted[t] for t in range(*bounds, width) if t in accepted]
                                if not leaves:
                                    continue
                                def build(leaves=leaves):
                                    return summarize((AcceptedComponent(source, bar, bar.time_ms + width,
                                                      view.revisions[0]) for bar in leaves), target=source)
                                lease = manager.acquire(BlockKey(source, *bounds, input_fingerprint="h127-canonical-v1"), view, build,
                                                        work_bytes=64 * 1024, cancel=cancel)
                                held.callback(lease.close)
                                leases[bounds] = lease
                            # Do not retain decoded input pages across caller work.
                            del rows, valid, bars, accepted, times, leaves, build
                    page = HistoryBlockPage(tuple(leases[b] for b in ranges if b in leases))
                    blocks = page.blocks
                    if any(not block.summary.all_authoritative for block in blocks):
                        raise BlockUnavailable("unqualified cached history summary")
                    coverage = sorted(part for block in blocks for part in block.summary.coverage.ranges)
                    missing, at = [], lo
                    for start, stop in coverage:
                        if start > at:
                            missing.append((at, start))
                        at = max(at, stop)
                    if at < hi:
                        missing.append((at, hi))
                    missing_fields = tuple(f for f in fields if any(
                        getattr(block.summary.values, f) is None for block in blocks))
                    next_position = hi if direction == "asc" else lo
                    continuation = (HistoryBlockCursor(source, start_ms, end_ms, next_position,
                        direction, view.revisions, fields) if start_ms < next_position < end_ms else None)
                    receipt = HistoryBlockReceipt(source, (start_ms, end_ms), (lo, hi), view.revisions,
                        tuple(missing), missing_fields, not missing and not missing_fields,
                        continuation, len(blocks), rows_read, hits)
                    try:
                        yield page
                        self._cancelled(cancel)
                        check_binding()
                    finally:
                        page._active = False
                        page._leases = ()
            check_binding()
            page._receipt = receipt
            self._count(accepted_pages=1, partial_pages=int(not receipt.complete),
                        accepted_blocks=receipt.blocks)
        except CancelledError:
            self._count(cancellations=1)
            raise
        except BaseException:
            self._count(failures=1)
            raise
