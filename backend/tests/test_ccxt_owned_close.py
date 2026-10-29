import asyncio

import ccxt
import ccxt.async_support as ccxt_async
import pytest

from app.exchanges.ccxt_ext.generic import _owned_exchange_class
from app.exchanges.ccxt_ext.runtime import close_ccxt_exchange


@pytest.mark.parametrize("windows", [False, True])
def test_delayed_catalog_sibling_cannot_reopen_a_closed_owned_session(windows):
    async def run():
        exchange = _owned_exchange_class(ccxt_async.okx, windows=windows)({})
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


def test_public_capture_wrapper_closes_owned_rest_session():
    from app.exchanges.ccxt_ext.hooks import build_hooked_exchange_class
    from app.exchanges.ccxt_ext.binance_usdm import SUPPORTED_CCXT_VERSION

    async def run():
        cls = build_hooked_exchange_class(
            _owned_exchange_class(ccxt_async.binance, windows=False),
            exchange_id="binance",
            market_type="spot",
            supported_ccxt_version=SUPPORTED_CCXT_VERSION,
        )
        exchange = cls({})
        exchange.open()
        session = exchange.session
        await close_ccxt_exchange(exchange)
        assert session.closed and exchange.session is None

    asyncio.run(run())
