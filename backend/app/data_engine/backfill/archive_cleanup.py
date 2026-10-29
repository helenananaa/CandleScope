"""Recoverable, bounded ZIP cleanup driven by atomic storage import proofs."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .archive_cache import HistoricalArchiveCache
from .config import BackfillConfig

ImportProofLookup = Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]]
logger = logging.getLogger("backfill.ArchiveCleanup")


class ArchiveImportCleanup:
    """One worker per router; cache roots belong to one application profile.

    No in-memory acknowledgement authorizes deletion. Scanning indexed objects
    against durable proofs recovers the commit-before-notification crash window.
    A failed unlink retains the cache index and retry state. Old receipts, pins,
    unknown storage implementations and another object's revision fail closed.
    """

    def __init__(
        self,
        config: BackfillConfig,
        cache: HistoricalArchiveCache,
        lookup: ImportProofLookup,
        *,
        interval_seconds: float = 30.0,
    ) -> None:
        self._config, self._cache, self._lookup = config, cache, lookup
        self._interval = interval_seconds
        self._cursor = ""
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self.last_error: str | None = None

    def request(self) -> None:
        if self._closed:
            return
        self._wake.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="history-archive-cleanup")

    async def sweep_page(self) -> bool:
        """Process at most 128 objects; return whether another page may remain."""
        # Deferred LRU/invalidated blobs are independent of import policy and
        # must make progress even when non-imported cache entries remain.
        await asyncio.to_thread(self._cache._drain_blob_cleanup)
        if self._config.history_archive_cleanup_policy != "delete_after_import":
            self._cursor = ""
            return False
        candidates = await self._cache.cleanup_candidates(self._cursor)
        if not candidates:
            self._cursor = ""
            self.last_error = None
            return False
        proofs = await self._lookup(candidates)
        # Configuration may have changed while storage was busy.
        if self._config.history_archive_cleanup_policy == "delete_after_import":
            await self._cache.cleanup_imported(proofs)
        self._cursor = str(candidates[-1]["object_key"])
        more = len(candidates) == 128
        if not more:
            self._cursor = ""
        self.last_error = None
        return more

    async def _run(self) -> None:
        while not self._closed:
            self._wake.clear()
            try:
                more = await self.sweep_page()
            except Exception as exc:
                self.last_error = str(exc)[:500]
                logger.warning("Archive cleanup deferred: %s", exc)
                more = False
            if self._closed:
                break
            if more:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    async def close(self) -> None:
        self._closed = True
        self._wake.set()
        if self._task is not None:
            # Drain a physical filesystem operation rather than cancelling
            # its asyncio wrapper while its worker still owns the cache lock.
            await asyncio.shield(self._task)

    def snapshot(self) -> dict[str, Any]:
        return {
            "policy": self._config.history_archive_cleanup_policy,
            "running": self._task is not None and not self._task.done(),
            "last_error": self.last_error,
        }
