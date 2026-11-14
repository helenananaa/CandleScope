"""Finite source reconstruction using the original storage/budget owners."""

import asyncio
from contextlib import asynccontextmanager, nullcontext
from threading import Event
from dataclasses import replace

from app.core.executors import run_storage
from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.aggregation.source_window import (
    SOURCE_SUMMARY_BYTES,
    EmptySourceWindow,
)
from app.data_engine.market_data.kline_metrics import (
    kline_available_fields,
    KLINE_ENHANCED_FIELDS,
)
from app.data_engine.memory_budget import retained_size, MemoryBudgetExceeded

# Raw JSON pages are byte bounded. Only scalar candle fields survive decode;
# include the encoded page, one temporary decoded tree and all summary work.
SOURCE_PAGE_WORK_BYTES = 4 * 1024 * 1024


class SourceRecoveryReader:
    def __init__(self, bridge, aggregator):
        self.bridge = bridge
        self.aggregator = aggregator
        self.binding = object()

    def reset_binding(self):
        # One epoch of the existing storage owner, not a source revision ledger.
        self.binding = object()

    def available(self):
        storage = self.bridge._storage_provider()
        return (
            self.bridge.preview_memory_budget is not None
            and self.aggregator._source_component_reader
            == self.bridge.read_source_components
            and getattr(storage, "revision_store", None) is not None
            and self.bridge.delivery.journal is not None
        ) and all(
            callable(getattr(storage, name, None))
            for name in (
                "capture_source_window",
                "fold_source_window",
                "validate_source_window",
            )
        )

    @asynccontextmanager
    async def stage(
        self,
        incoming,
        start,
        end,
        *,
        target_interval,
        is_current,
        previous=None,
        force=False,
    ):
        bridge = self.bridge
        storage = bridge._storage_provider()
        budget = bridge.preview_memory_budget
        fold = getattr(storage, "fold_source_window", None)
        validate = getattr(storage, "validate_source_window", None)
        if not callable(fold) or not callable(validate) or budget is None:
            raise BlockUnavailable("bounded selected-source recovery is unavailable")
        cancel = Event()
        runtime = self.aggregator.history_prefix_runtime
        if runtime is None or runtime.closing:
            raise BlockUnavailable("original source recovery lifetime is unavailable")
        store, journal = storage.revision_store, bridge.delivery.journal
        epoch = self.binding

        def capabilities():
            return frozenset(
                kline_available_fields(
                    incoming.exchange, incoming.market_type
                ).intersection(KLINE_ENHANCED_FIELDS)
            )

        capability = capabilities()

        def owner_bound():
            return (
                bridge._storage_provider() is storage
                and storage.revision_store is store
                and bridge.delivery.journal is journal
                and self.aggregator.history_prefix_runtime is runtime
                and not runtime.closing
                and bridge.preview_memory_budget is budget
                and self.binding is epoch
                and capabilities() == capability
            )

        def bound():
            return is_current() and owner_bound()

        # Reuse the existing handoff task capacity/lifetime. A registered H127
        # target already entered it through hold(); do not reenter that owner.
        lifetime = (
            nullcontext()
            if asyncio.current_task() in runtime.tasks
            else runtime._task()
        )
        # The caller already reserves the held graph plus 16 KiB for this
        # metadata-only read. Decode/summary staging is needed only on refold.
        async with lifetime:
            try:
                if (previous is not None and not force and previous.binding is epoch
                        and previous.capabilities == capability):
                    preview = getattr(storage, 'validate_source_preview', None)
                    if callable(preview) and not incoming.is_closed:
                        valid, watermark = await run_storage(preview, previous.version,
                            previous.observation_watermark, target_interval=target_interval)
                    else:
                        valid = await run_storage(validate, previous.version, target_interval=target_interval)
                        watermark = None
                    if valid:
                        if not bound():
                            raise BlockRevisionChanged('source recovery binding changed during preview validation')
                        yield None, owner_bound, watermark
                        return
                with budget.reserve("history-query", SOURCE_SUMMARY_BYTES * 2 + 16384):
                    # The worker receives a private scalar input/reference,
                    # never the producer's mutable extra mapping.
                    incoming = replace(
                        incoming,
                        extra={"source_ref": dict(incoming.extra["source_ref"])},
                    )
                    try:
                        version = await run_storage(
                            storage.capture_source_window,
                            incoming.extra["source_ref"]["series"],
                            start,
                            end,
                            incoming.close_time_ms + 1 - incoming.open_time_ms,
                        )
                    except EmptySourceWindow:
                        if previous is not None or incoming.is_closed or not bound():
                            raise
                        yield None, owner_bound, None
                        return
                    if (
                        previous is None
                        and version.closed_count == 1
                        and incoming.is_closed
                    ):
                        # No siblings means ordinary live admission. In
                        # particular, do not wait for this input's native write
                        # while the original dispatcher is intentionally busy.
                        if (
                            not await run_storage(
                                validate, version, target_interval=target_interval
                            )
                            or not bound()
                        ):
                            raise BlockRevisionChanged(
                                "single-source admission view expired"
                            )
                        yield None, owner_bound, None
                        return
                    # Original dispatcher only; do not read a half-committed native
                    # source and mistake the expected transient mismatch for proof.
                    async with asyncio.timeout(1.5):
                        await bridge.delivery.flush_pending()
                    if not bound():
                        raise BlockRevisionChanged(
                            "source recovery binding changed during drain"
                        )
                    with budget.reserve("history-query", SOURCE_PAGE_WORK_BYTES):
                        summary = await run_storage(
                            fold,
                            incoming.extra["source_ref"]["series"],
                            start,
                            end,
                            incoming.close_time_ms + 1 - incoming.open_time_ms,
                            incoming,
                            cancel,
                        )
                    if not await run_storage(
                        validate, summary.version, target_interval=target_interval
                    ):
                        raise BlockRevisionChanged(
                            "source reconstruction expired before adoption"
                        )
                    if not bound():
                        raise BlockRevisionChanged(
                            "source recovery binding changed before adoption"
                        )
                    summary = replace(
                        summary,
                        binding=epoch,
                        capabilities=capability,
                        estimated_bytes=0,
                    )
                    size = retained_size((summary,))[0] + 64
                    if size > SOURCE_SUMMARY_BYTES:
                        raise MemoryBudgetExceeded(
                            "bound source summary exceeds staging allowance"
                        )
                    yield replace(summary, estimated_bytes=size), owner_bound, None
            finally:
                # run_storage retains ownership until a running thread has
                # physically drained even when the awaiting task is cancelled.
                cancel.set()
