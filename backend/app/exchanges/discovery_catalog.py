"""Background discovery of public catalogs, using the host's durable snapshot.

Query-only providers are deliberately excluded: they require a user query and
may charge per request. New registry entries are picked up on the next sweep.
"""
from __future__ import annotations

import asyncio
import logging

from app.exchanges import symbol_catalog as catalog

logger = logging.getLogger(__name__)


async def refresh_discovery_catalogs() -> None:
    catalog.bootstrap_default_adapters()
    adapters = sorted(catalog.get_exchange_registry().list(),
                      key=lambda item: (not getattr(item, "eager_catalog_refresh", True), item.id))
    for adapter in adapters:
        if callable(getattr(adapter, "search_symbols", None)):
            continue
        for market in adapter.capabilities().markets:
            # Yield to chart/history work. This sweep is optional background I/O.
            while catalog.foreground_is_busy():
                await asyncio.sleep(1)
            try:
                await catalog.refresh_market_catalog(adapter, market.market_type, force=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Discovery refresh failed for %s", adapter.id, exc_info=True)
            await asyncio.sleep(0.1)


async def run_discovery_catalogs() -> None:
    await asyncio.sleep(max(1, catalog.SYMBOL_CATALOG_FOREGROUND_DWELL_SECONDS))
    while True:
        try:
            await refresh_discovery_catalogs()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Discovery catalog sweep deferred", exc_info=True)
        await asyncio.sleep(300)
