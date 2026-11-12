"""H127 mixed fixed-grid read adapter, consuming D126/K130/B130.

Callers supply composition-qualified source grids. This interface neither
qualifies new venues nor enables a theoretical route in the chart picker.
The one-target result is readable only after the whole multi-source view
passes its fence. There is no second cache, downloader or materialization owner.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass, replace

from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.aggregation.core import AggregateSummary, InputRevision, combine
from app.data_engine.history.cover_plan import (
    CoverBudgetExceeded, CoverUnavailable, plan_fixed_range, plan_fixed_target,
)
from app.data_engine.interval_policy import parse_interval_spec
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size
from .models import SeriesKey

_SUMMARY_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class MixedHistoryReceipt:
    target: SeriesKey
    requested_range: tuple[int, int]
    revisions: tuple[InputRevision, ...]
    qualifications: tuple[tuple[SeriesKey, str], ...]
    planned_rows: int
    estimated_cost: float
    explored_positions: int
    accepted_rows: int
    fallbacks: int
    pages: int
    storage_rows: int
    cache_hits: int
    acquisition_revision: int


class MixedHistoryRead:
    def __init__(self):
        self._summary = self._receipt = None

    @property
    def summary(self) -> AggregateSummary:
        if self._summary is None:
            raise BlockRevisionChanged("mixed history has not passed its publication fence")
        return self._summary

    @property
    def receipt(self) -> MixedHistoryReceipt:
        if self._receipt is None:
            raise BlockRevisionChanged("mixed history has not passed its publication fence")
        return self._receipt


class MixedHistoryReader:
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def read(self, target, start_ms, end_ms, sources, *, max_positions=32_768,
             page_rows=256, required_fields=frozenset({"open", "high", "low", "close", "volume"}),
             cancel=None):
        """Prepare one closed target; publish only after successful context exit.

        Runs on the caller's storage worker, using the synchronous H127 reader;
        it never submits nested work to the storage pool. One page is reduced
        and released before reading the next. Missing rows/fields stay explicit.
        """
        engine = self.engine
        history = engine.history_blocks
        history._cancelled(cancel)
        if type(max_positions) is not int or not 1 <= max_positions <= 131_072:
            raise ValueError("bounded planning position budget required")
        if type(page_rows) is not int or not 1 <= page_rows <= 256:
            raise ValueError("bounded H127 page row budget required")
        # Covers the DFS path, iterators and dead-position set, not just its
        # compact output spans. The pure planner itself owns no shared state.
        plan_bytes = max_positions * 512 + 64 * 1024
        with engine.memory_budget.reserve("history-query", plan_bytes + 4 * _SUMMARY_BYTES):
            plan = plan_fixed_target(target, start_ms, end_ms, sources,
                                     required_fields=required_fields, max_positions=max_positions)
            eligible = tuple(source for source in sources
                             if replace(source.series, interval=target.interval) == target
                             and required_fields <= source.fields)
            selected = tuple(dict.fromkeys(source.series for source in eligible))
            for source in eligible:
                width, _ = history._qualify(source.series)
                spec = parse_interval_spec(source.series.interval)
                if width != source.width_ms or spec.phase_ms != source.phase_ms:
                    raise BlockUnavailable("mixed source grid differs from its qualified H127 boundary")
            storage, manager, policy = engine.storage, engine.shared_blocks, engine.history_policy
            store = getattr(storage, "revision_store", None)
            if store is None or manager is None:
                raise BlockUnavailable("mixed history requires versioned canonical storage")
            floor = store.head()
            summary = None
            pages = storage_rows = cache_hits = 0
            accepted_rows = fallbacks = 0
            explored = plan.explored_positions
            used = {}

            def check_binding():
                if (engine.storage is not storage or engine.shared_blocks is not manager
                        or engine.history_policy is not policy):
                    raise BlockRevisionChanged("mixed history binding changed during the read")

            result = MixedHistoryRead()
            with manager.view(selected, acquired_at=floor) as view:
                check_binding()
                revisions = {revision.series: revision for revision in view.revisions}
                pending = deque(plan.spans)
                while pending:
                    span = pending.popleft()
                    cursor = None
                    span_summary = None
                    unavailable = False
                    while True:
                        history._cancelled(cancel)
                        with history.read(span.source.series, span.start_ms, span.end_ms,
                                          max_rows=page_rows, cursor=cursor,
                                          required_fields=required_fields, cancel=cancel) as page:
                            for block in page.blocks:
                                if block.summary.revisions != (revisions[span.source.series],):
                                    raise BlockRevisionChanged("mixed history source changed between spans")
                                # H127 has already proved source identity and
                                # actual bounds. Rebind the immutable summary
                                # to this target; K130 still owns all arithmetic.
                                part = replace(block.summary, target=target)
                                span_summary = combine((span_summary, part)) if span_summary is not None else part
                                if retained_size((span_summary,))[0] > _SUMMARY_BYTES:
                                    raise MemoryBudgetExceeded("mixed history summary exceeds its work allowance")
                        receipt = page.receipt
                        pages += 1
                        storage_rows += receipt.storage_rows
                        cache_hits += receipt.cache_hits
                        if not receipt.complete:
                            unavailable = True
                            break
                        cursor = receipt.continuation
                        if cursor is None:
                            break
                    if unavailable:
                        # Discard the entire tentative span, including earlier
                        # pages. Finer replacement covers this exact range once;
                        # prior successful spans remain in the output prefix.
                        finer = tuple(source for source in eligible if source.width_ms < span.source.width_ms)
                        if not finer:
                            raise BlockUnavailable("mixed history source has unavailable coverage or fields")
                        remaining = max_positions - explored
                        if remaining <= 0:
                            raise CoverBudgetExceeded("mixed history refinement position budget exhausted")
                        try:
                            replacement = plan_fixed_range(target, span.start_ms, span.end_ms, finer,
                                required_fields=required_fields, max_positions=remaining)
                        except CoverBudgetExceeded:
                            raise
                        except CoverUnavailable as error:
                            raise BlockUnavailable("finer sources cannot exactly replace the unavailable span") from error
                        explored += replacement.explored_positions
                        pending.extendleft(reversed(replacement.spans))
                        fallbacks += 1
                        continue
                    if span_summary is None:
                        raise BlockUnavailable("mixed history span contains no accepted components")
                    summary = combine((summary, span_summary)) if summary is not None else span_summary
                    if retained_size((summary,))[0] > _SUMMARY_BYTES:
                        raise MemoryBudgetExceeded("mixed history summary exceeds its work allowance")
                    accepted_rows += span.rows
                    used[(span.source.series, span.source.qualification)] = None
                if summary is None or not summary.is_authoritative(start_ms, end_ms):
                    raise BlockUnavailable("mixed history cannot prove complete authoritative coverage")
                check_binding()
                # Even a fully read result remains unpublished until the
                # caller exits and the encompassing B130 view is revalidated.
                yield result
                history._cancelled(cancel)
                check_binding()
            check_binding()
            result._receipt = MixedHistoryReceipt(target, (start_ms, end_ms), summary.revisions,
                tuple(used), plan.planned_rows, plan.estimated_cost, explored,
                accepted_rows, fallbacks, pages, storage_rows, cache_hits, floor)
            result._summary = summary
