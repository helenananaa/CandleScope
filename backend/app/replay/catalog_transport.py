"""Cancellable listing I/O behind the existing synchronous S3 validators."""
from __future__ import annotations

import asyncio
import io

import aiohttp

from .trade_import import ReplayTradeImportError, _MAX_LISTING_PAGE_BYTES


class CatalogRefreshStopped(ReplayTradeImportError):
    """The catalog owner stopped discovery, without completing a generation."""


class CatalogListingTransport:
    """Own actual HTTP tasks/sockets; cancelling an awaiter alone is insufficient.

    The parser threads only receive bounded bytes. Session state and request
    registration live on one loop, including requests queued during close.
    """

    def __init__(self):
        self._loop = asyncio.get_running_loop()
        self._session = aiohttp.ClientSession(trust_env=True)
        self._requests: set[asyncio.Task] = set()
        self._closed = False

    def open(self, url, *, timeout):
        """urllib-compatible opener, called only by catalog worker threads."""
        result = asyncio.run_coroutine_threadsafe(self._read(url, timeout), self._loop)
        return io.BytesIO(result.result())

    async def _read(self, url, timeout):
        if self._closed:
            raise CatalogRefreshStopped("official catalog discovery stopped")
        task = asyncio.current_task()
        self._requests.add(task)
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                response.raise_for_status()
                payload = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    payload.extend(chunk)
                    if len(payload) > _MAX_LISTING_PAGE_BYTES:
                        raise ReplayTradeImportError("official listing exceeds its byte limit")
                return bytes(payload)
        except asyncio.CancelledError:
            raise CatalogRefreshStopped("official catalog discovery stopped") from None
        finally:
            self._requests.remove(task)

    async def close(self):
        # Queued _read coroutines check _closed before touching the session.
        self._closed = True
        requests = tuple(self._requests)
        for task in requests:
            task.cancel()
        await asyncio.gather(*requests, return_exceptions=True)
        await self._session.close()
