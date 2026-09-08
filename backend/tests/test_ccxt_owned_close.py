import asyncio

import ccxt
import ccxt.async_support as ccxt_async
import pytest

from app.exchanges.ccxt_ext.generic import _owned_exchange_class
from app.exchanges.ccxt_ext.runtime import close_ccxt_exchange


def test_delayed_catalog_sibling_cannot_reopen_a_closed_owned_session():
    async def run():
        exchange = _owned_exchange_class(ccxt_async.okx, windows=True)({})
        release = asyncio.Event()

        async def delayed_sibling():
            await release.wait()
            exchange.open()

        task = asyncio.create_task(delayed_sibling())
        exchange.open()
        session = exchange.session
        await close_ccxt_exchange(exchange)
        assert session.closed
        release.set()
        with pytest.raises(ccxt.ExchangeNotAvailable, match="exchange is closed"):
            await task
        assert exchange.session is None
        await close_ccxt_exchange(exchange)

    asyncio.run(run())
