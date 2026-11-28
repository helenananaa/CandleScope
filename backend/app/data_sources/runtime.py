"""Start and stop the data-source key store with the app."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .credentials import DataSourceCredentials, activate

logger = logging.getLogger("candlescope.data_sources")
# Saved keys are read before charts open. A Keychain prompt can hold the read;
# startup goes on after this long and the keys arrive when the read finishes.
LOAD_WAIT_SECONDS = 5.0


async def start_data_source_credentials(app, root: Path, *, factory=DataSourceCredentials,
                                        wait_seconds: float = LOAD_WAIT_SECONDS) -> None:
    owner = factory(root)
    app.state.data_source_credentials = owner
    activate(owner)
    load = asyncio.ensure_future(asyncio.to_thread(owner.load))
    try:
        await asyncio.wait_for(asyncio.shield(load), timeout=wait_seconds)
    except asyncio.TimeoutError:
        logger.warning("Saved data-source keys are still loading; startup continues")
    except Exception as exc:
        # Charts must still open; the settings page shows the failure.
        logger.warning("Saved data-source keys unavailable: %s", type(exc).__name__)


def stop_data_source_credentials(app) -> None:
    activate(None)
    app.state.data_source_credentials = None
