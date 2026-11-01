"""R129's bounded H127 consumer; no new cache, revision log or writer.

The prepared value contains closed canonical components, never a completed target bar.
Initial staging requires complete coverage; explicit partial refresh preserves gaps.
Its reservation belongs to the caller until adoption/discard. The realtime
owner must still fence its target generation and live overlay before adoption.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import threading

from app.core.executors import run_storage
from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.aggregation.core import AggregateSummary, combine
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size


MAX_PREFIX_ROWS = 65_536
PREFIX_BYTES = 32 * 1024


@dataclass(frozen=True, slots=True)
class HistoryPrefix:
    summary: AggregateSummary
    start_ms: int
    through_ms: int
    source_width_ms: int
    pages: int
    storage_rows: int
    cache_hits: int

    @property
    def complete(self):
        return self.summary.is_authoritative(self.start_ms, self.through_ms)


class HistoryPrefixReader:
    """Stage one compact prefix using existing bounded storage workers.

    Complete pages are folded immediately; no list of input bars, page results
    or block handles survives to the next page. H127 cursors pin the revision
    across pages. A final fresh B130 view catches changes after the last page.
    """

    def __init__(self, engine):
        self.engine = engine

    def _read_page(self, source, start, end, prefix, cursor, page_rows, cancel, require_complete):
        with self.engine.history_blocks.read(source, start, end, max_rows=page_rows,
                                             cursor=cursor, cancel=cancel) as page:
            parts = [block.summary for block in page.blocks]
            parts = ([prefix] if prefix is not None else []) + parts
            summary = combine(parts) if parts else None
            if summary is not None and retained_size((summary,))[0] > PREFIX_BYTES:
                raise MemoryBudgetExceeded("history prefix exceeds its staging allowance")
        receipt = page.receipt
        if require_complete and not receipt.complete:
            raise BlockUnavailable("history prefix has unavailable coverage or fields")
        return summary, receipt

    def validate(self, prefix, *, storage, manager, policy):
        """Worker-side durable fence, also reusable immediately before adoption."""
        engine = self.engine
        if (engine.storage is not storage or engine.shared_blocks is not manager
                or engine.history_policy is not policy):
            raise BlockRevisionChanged("history prefix source binding changed")
        with manager.view((prefix.summary.target,)) as view:
            if view.revisions != prefix.summary.revisions:
                raise BlockRevisionChanged("history prefix revision expired")
        if (engine.storage is not storage or engine.shared_blocks is not manager
                or engine.history_policy is not policy):
            raise BlockRevisionChanged("history prefix source binding changed")

    @asynccontextmanager
    async def stage(self, source, start_ms, through_ms, *, page_rows=256, require_complete=True):
        from app.data_engine.interval_policy import parse_interval_spec

        spec = parse_interval_spec(source.interval)
        if (spec is None or type(start_ms) is not int or type(through_ms) is not int
                or not 0 <= start_ms < through_ms
                or (through_ms - start_ms) // spec.nominal_ms > MAX_PREFIX_ROWS):
            raise ValueError("bounded nonempty history prefix required")
        engine = self.engine
        storage, manager, policy = engine.storage, engine.shared_blocks, engine.history_policy
        cancel = threading.Event()
        # Covers retained summary and intermediate folding metadata; H127
        # independently reserves its page/decode work and B130 its shared cache.
        with engine.memory_budget.reserve("history-query", PREFIX_BYTES * 2):
            try:
                cursor = summary = None
                pages = storage_rows = cache_hits = 0
                while True:
                    summary, receipt = await run_storage(self._read_page, source,
                        start_ms, through_ms, summary, cursor, page_rows, cancel, require_complete)
                    pages += 1
                    storage_rows += receipt.storage_rows
                    cache_hits += receipt.cache_hits
                    cursor = receipt.continuation
                    if cursor is None:
                        break
                if summary is None or (require_complete and not summary.is_authoritative(start_ms, through_ms)):
                    raise BlockUnavailable("history prefix cannot prove closed coverage")
                prefix = HistoryPrefix(summary, start_ms, through_ms, spec.nominal_ms,
                                       pages, storage_rows, cache_hits)
                await run_storage(self.validate, prefix, storage=storage,
                                  manager=manager, policy=policy)
                yield prefix
            finally:
                cancel.set()
