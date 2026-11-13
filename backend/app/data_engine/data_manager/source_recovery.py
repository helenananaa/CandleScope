"""Finite source reconstruction using the original storage/budget owners."""
import asyncio
from contextlib import asynccontextmanager
from threading import Event

from app.core.executors import run_storage
from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.aggregation.source_window import SOURCE_SUMMARY_BYTES

# Raw JSON pages are byte bounded. Only scalar candle fields survive decode;
# include the encoded page, one temporary decoded tree and all summary work.
SOURCE_PAGE_WORK_BYTES = 4 * 1024 * 1024


class SourceRecoveryReader:
    def __init__(self, bridge):
        self.bridge = bridge

    @asynccontextmanager
    async def stage(self, incoming, start, end, *, is_current):
        bridge = self.bridge
        storage = bridge._storage_provider()
        budget = bridge.preview_memory_budget
        fold = getattr(storage, 'fold_source_window', None)
        validate = getattr(storage, 'validate_source_window', None)
        if not callable(fold) or not callable(validate) or budget is None:
            raise BlockUnavailable('bounded selected-source recovery is unavailable')
        cancel = Event()
        with budget.reserve('history-query', SOURCE_PAGE_WORK_BYTES + SOURCE_SUMMARY_BYTES * 2):
            try:
                # Original dispatcher only; do not read a half-committed native
                # source and mistake the expected transient mismatch for proof.
                async with asyncio.timeout(1.5):
                    await bridge.delivery.flush_pending()
                if not is_current() or bridge._storage_provider() is not storage:
                    raise BlockRevisionChanged('source recovery binding changed during drain')
                summary = await run_storage(fold, incoming.extra['source_ref']['series'],
                    start, end, incoming.close_time_ms + 1 - incoming.open_time_ms,
                    incoming, cancel)
                if not await run_storage(validate, summary.version):
                    raise BlockRevisionChanged('source reconstruction expired before adoption')
                if (not is_current() or bridge._storage_provider() is not storage
                        or bridge.preview_memory_budget is not budget):
                    raise BlockRevisionChanged('source recovery binding changed before adoption')
                yield summary
            finally:
                # run_storage retains ownership until a running thread has
                # physically drained even when the awaiting task is cancelled.
                cancel.set()
