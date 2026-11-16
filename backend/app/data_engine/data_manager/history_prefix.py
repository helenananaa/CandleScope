"""R129's bounded H127 consumer; no new cache, revision log or writer.

The prepared value contains closed canonical components, never a completed target bar.
Initial staging requires complete coverage; explicit partial refresh preserves gaps.
Its reservation belongs to the caller until adoption/discard. The realtime
owner must still fence its target generation and live overlay before adoption.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import threading

from app.core.executors import run_storage
from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.aggregation.core import combine
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size


from app.data_engine.aggregation.history_prefix import (
    EmptyHistoryPrefix, HistoryPrefix, MAX_PREFIX_ROWS, PREFIX_BYTES,
)


class HistoryPrefixReader:
    """Stage one compact prefix using existing bounded storage workers.

    Complete pages are folded immediately; no list of input bars, page results
    or block handles survives to the next page. H127 cursors pin the revision
    across pages. A final fresh D126 version read catches changes after the last page.
    """

    def __init__(self, engine):
        self.engine = engine

    @property
    def memory_budget(self):
        return self.engine.memory_budget

    def qualify(self, source):
        return self.engine.history_blocks._qualify(source)

    def scoped_version_reader(self):
        store = getattr(self.engine.storage, "revision_store", None)
        create = getattr(store, "scoped_version_reader", None)
        return create() if callable(create) else None

    def validate_bound(self, prefix, *, read_scope=None):
        engine = self.engine
        return self.validate(prefix, storage=engine.storage, manager=engine.shared_blocks,
                             policy=engine.history_policy, read_scope=read_scope)

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

    def validate(self, prefix, *, storage, manager, policy, read_scope=None):
        """Worker-side durable fence, also reusable immediately before adoption."""
        engine = self.engine
        adapter = manager.source
        if (engine.storage is not storage or engine.shared_blocks is not manager
                or engine.history_policy is not policy
                or prefix.binding != (id(storage), id(manager), id(policy))):
            raise BlockRevisionChanged("history prefix source binding changed")
        validator = getattr(adapter, 'validate_detached', None)
        if (not callable(validator) or getattr(adapter, 'store', None) is not getattr(storage, 'revision_store', None)
                or manager.snapshot()['closed']):
            raise BlockRevisionChanged('history prefix source is unavailable')
        options = {"read_scope": read_scope} if read_scope is not None else {}
        validator(prefix.summary.revisions, acquisition_revision=prefix.acquisition_revision, **options)
        if (engine.storage is not storage or engine.shared_blocks is not manager
                or engine.history_policy is not policy or manager.source is not adapter
                or manager.snapshot()['closed']):
            raise BlockRevisionChanged("history prefix source binding changed")

    def matches_closed_overlay(self, source, prefix, components):
        """Fence and compare a bounded seam before dropping accepted leaves.

        Aggregate equality alone can hide opposite corrections to two leaves.
        Use the existing canonical reader and normalizer, without another cache
        or a write path. The new prefix covers this range on both read fences.
        """
        if not components or len(components) > 128:
            raise ValueError("bounded closed overlay required")
        lo, hi = components[0]['open_time_ms'], components[-1]['close_time_ms'] + 1
        if source != prefix.summary.target or not prefix.start_ms <= lo < hi <= prefix.through_ms:
            raise ValueError("overlay is outside the staged prefix")
        engine = self.engine
        self.validate_bound(prefix)
        with self.memory_budget.reserve('history-query', len(components) * 4096 + 4096):
            rows = engine._read_canonical_history_rows(engine.storage, source, lo, hi, len(components) + 1)
            if retained_size((rows,))[0] > len(components) * 2048 + 2048:
                raise MemoryBudgetExceeded('overlay comparison exceeds its decoding allowance')
            bars = engine._storage_rows_to_bars(source, rows)
            valid = len(rows) == len(bars) == len(components)
            for row, bar, held in zip(rows, bars, components):
                fields = ('open', 'high', 'low', 'close', 'volume', *held['enhanced_fields'])
                if (row.get('open_time') != held['open_time_ms']
                        or row.get('close_time') != held['close_time_ms']
                        or not bar.is_closed or not bar.trusted_final or not held['is_closed']
                        or bar.enhanced_fields != held['enhanced_fields']
                        or any(getattr(bar, name) != held[name] for name in fields)):
                    valid = False
                    break
        self.validate_bound(prefix)
        return valid

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
        store = getattr(storage, 'revision_store', None)
        if store is None:
            raise BlockUnavailable('history prefix requires durable acquisition fencing')
        # Capture before the first page, never relabel old inputs with a head
        # obtained after staging. This is D126's existing global delete floor.
        acquisition_revision = await run_storage(store.head)
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
                if summary is None:
                    raise EmptyHistoryPrefix('history prefix has no canonical components')
                if require_complete and not summary.is_authoritative(start_ms, through_ms):
                    raise BlockUnavailable("history prefix cannot prove closed coverage")
                prefix = HistoryPrefix(summary, start_ms, through_ms, spec.nominal_ms,
                                       pages, storage_rows, cache_hits, acquisition_revision,
                                       (id(storage), id(manager), id(policy)))
                await run_storage(self.validate, prefix, storage=storage,
                                  manager=manager, policy=policy)
                yield prefix
            finally:
                cancel.set()
