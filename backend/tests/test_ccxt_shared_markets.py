from __future__ import annotations

import asyncio
from typing import Any

import ccxt
import ccxt.async_support as ccxt_async
import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import StreamDescriptor, StreamType
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.generic import _create_exchange, _RestExchangePool
from app.exchanges.ccxt_ext.markets import (
    get_shared_ccxt_market_tables,
    market_rail_key,
)
from app.exchanges.ccxt_ext.profiles import (
    BinanceSpotCcxtProfile,
    BinanceUsdmCcxtProfile,
)
from app.exchanges.ccxt_ext.runtime import CcxtRuntimePool


def _spot(base: str, quote: str = "USDT") -> dict[str, Any]:
    return {
        "id": f"{base}{quote}",
        "symbol": f"{base}/{quote}",
        "base": base,
        "quote": quote,
        "baseId": base,
        "quoteId": quote,
        "type": "spot",
        "spot": True,
        "margin": False,
        "swap": False,
        "future": False,
        "option": False,
        "contract": False,
        "linear": None,
        "inverse": None,
        "active": True,
        "precision": {"amount": 0.00001, "price": 0.01},
        "limits": {},
        "info": {"symbol": f"{base}{quote}"},
    }


class _Catalog:
    """Stands in for Binance ``exchangeInfo`` on every real ccxt Binance class."""

    def __init__(self, monkeypatch: Any, *markets: dict[str, Any]) -> None:
        self.markets = list(markets)
        self.loaders: list[Any] = []
        self.failures: list[BaseException] = []
        self.gate: asyncio.Event | None = None
        catalog = self

        async def fetch_markets(exchange: Any, params: Any = None) -> list[Any]:
            del params
            catalog.loaders.append(exchange)
            if catalog.gate is not None:
                await catalog.gate.wait()
            if catalog.failures:
                raise catalog.failures.pop(0)
            return [dict(market, info=dict(market["info"])) for market in catalog.markets]

        async def fetch_currencies(exchange: Any, params: Any = None) -> None:
            del exchange, params

        monkeypatch.setattr(ccxt_async.binance, "fetch_markets", fetch_markets)
        monkeypatch.setattr(ccxt_async.binance, "fetch_currencies", fetch_currencies)

    @property
    def calls(self) -> int:
        return len(self.loaders)


async def _borrow(pool: _RestExchangePool, selection: str = "spot") -> Any:
    async with pool.request(selection) as exchange:
        return exchange


def _rails() -> list[dict[str, Any]]:
    return get_shared_ccxt_market_tables().snapshot()["rails"]


async def _until(condition: Any) -> None:
    for _attempt in range(200):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached")


def _descriptor(symbol: str) -> StreamDescriptor:
    return StreamDescriptor(
        symbol,
        StreamType.KLINE,
        interval="1m",
        exchange="binance",
        market_type="spot",
    )


def test_market_rails_follow_venue_class_and_market_family() -> None:
    binance = get_ccxt_catalog_entry("binance")
    okx = get_ccxt_catalog_entry("okx")
    config = IngestionConfig(proxy_mode="none")

    def rest(entry: Any, market_type: str, cfg: IngestionConfig = config) -> Any:
        return _create_exchange(entry, cfg, market_type=market_type, websocket=False)

    rest_spot = rest(binance, "spot")
    ws_spot = BinanceSpotCcxtProfile().create_exchange(
        config,
        raw_event_sink=None,
        lifecycle_sink=None,
    )
    proxied_spot = rest(
        binance,
        "spot",
        IngestionConfig(proxy_mode="custom", http_proxy="http://127.0.0.1:9"),
    )
    rest_usdm = rest(binance, "swap.linear")
    ws_usdm = BinanceUsdmCcxtProfile().create_exchange(
        config,
        raw_event_sink=None,
        lifecycle_sink=None,
    )
    okx_spot = rest(okx, "spot")
    okx_swap = rest(okx, "swap.linear")

    # REST and ccxt.pro clients of one venue rail build the same tables; the
    # proxy only changes the path to them.
    assert market_rail_key(rest_spot) == market_rail_key(ws_spot)
    assert market_rail_key(rest_spot) == market_rail_key(proxied_spot)
    assert market_rail_key(rest_usdm) == market_rail_key(ws_usdm)
    assert len(
        {market_rail_key(item) for item in (rest_spot, rest_usdm, okx_spot, okx_swap)}
    ) == 4
    # Test doubles and adapters keep loading their own markets.
    assert market_rail_key(object()) is None


def test_rest_pools_and_websocket_runtime_share_one_market_load(
    monkeypatch: Any,
) -> None:
    catalog = _Catalog(monkeypatch, _spot("BTC"), _spot("ETH"))
    entry = get_ccxt_catalog_entry("binance")

    async def run() -> None:
        catalog.gate = asyncio.Event()
        # Two transport configs own separate REST pools; the websocket
        # runtime pool owns a ccxt.pro client of the same rail.
        first = _RestExchangePool(entry, IngestionConfig(proxy_mode="none"))
        second = _RestExchangePool(entry, IngestionConfig(proxy_mode="none"))
        runtime_pool = CcxtRuntimePool()
        borrowers = asyncio.gather(
            _borrow(first),
            _borrow(second),
            runtime_pool.acquire(
                BinanceSpotCcxtProfile(),
                IngestionConfig(proxy_mode="none"),
            ),
        )
        await _until(
            lambda: catalog.calls == 1 and _rails()[0]["sharers"] == 3
        )
        catalog.gate.set()
        rest_a, rest_b, runtime = await borrowers

        assert catalog.calls == 1
        assert rest_a.markets is rest_b.markets is runtime.exchange.markets
        assert rest_a.markets_by_id is runtime.exchange.markets_by_id
        assert runtime.exchange.symbols == ["BTC/USDT", "ETH/USDT"]
        assert runtime.resolve_symbol(_descriptor("ETHUSDT")) == "ETH/USDT"
        (rail,) = _rails()
        assert rail["rail"] == "binance:spot"
        assert (rail["loads"], rail["adoptions"], rail["sharers"]) == (1, 2, 3)
        assert rail["markets"] == 2
        assert first.snapshot()["clients_created"] == 1

        # A client created later adopts the loaded table without a download.
        third = _RestExchangePool(entry, IngestionConfig(proxy_mode="system"))
        rest_c = await _borrow(third)
        assert catalog.calls == 1
        assert rest_c.markets is rest_a.markets

        for pool in (first, second, third):
            await pool.close()
        assert _rails()[0]["sharers"] == 1
        await runtime_pool.release(runtime)
        # The table goes with its last client; a new client loads afresh.
        assert _rails() == []
        fourth = _RestExchangePool(entry, IngestionConfig(proxy_mode="none"))
        await _borrow(fourth)
        assert catalog.calls == 2
        await fourth.close()

    asyncio.run(run())


def test_symbol_miss_reload_refreshes_every_sharer_once(monkeypatch: Any) -> None:
    catalog = _Catalog(monkeypatch, _spot("BTC"))
    entry = get_ccxt_catalog_entry("binance")
    tables = get_shared_ccxt_market_tables()

    async def run() -> None:
        first = _RestExchangePool(entry, IngestionConfig(proxy_mode="none"))
        second = _RestExchangePool(entry, IngestionConfig(proxy_mode="none"))
        runtime_pool = CcxtRuntimePool()
        runtime = await runtime_pool.acquire(
            BinanceSpotCcxtProfile(),
            IngestionConfig(proxy_mode="none"),
        )
        rest_a = await _borrow(first)
        rest_b = await _borrow(second)
        initial = rest_a.markets
        assert catalog.calls == 1

        # SOL lists after the catalog was loaded.  Both pools miss it at the
        # same time; one reload serves them and the websocket runtime.
        catalog.markets.append(_spot("SOL"))
        catalog.gate = asyncio.Event()
        miss_a = asyncio.create_task(
            first.resolve_symbol("spot", rest_a, _descriptor("SOLUSDT"), market_type="spot")
        )
        await _until(lambda: catalog.calls == 2)
        miss_b = asyncio.create_task(
            second.resolve_symbol("spot", rest_b, _descriptor("SOLUSDT"), market_type="spot")
        )
        await asyncio.sleep(0)
        catalog.gate.set()
        assert await asyncio.gather(miss_a, miss_b) == ["SOL/USDT", "SOL/USDT"]

        assert catalog.calls == 2
        assert catalog.loaders[1] is rest_a
        assert rest_a.markets is not initial
        assert rest_a.markets is rest_b.markets is runtime.exchange.markets
        assert runtime.resolve_symbol(_descriptor("SOLUSDT")) == "SOL/USDT"
        assert first.snapshot()["market_reloads"] == 1
        assert second.snapshot()["market_reloads"] == 1
        (rail,) = _rails()
        assert (rail["loads"], rail["reloads"], rail["markets"]) == (1, 1, 2)

        # A miss observed against the replaced table adopts the newer one
        # instead of downloading the catalog again.
        await tables.reload(rest_b, stale_markets=initial)
        assert catalog.calls == 2
        # A miss against the current table does reload.
        await tables.reload(rest_b, stale_markets=rest_b.markets)
        assert catalog.calls == 3
        assert rest_a.markets is rest_b.markets is runtime.exchange.markets

        await first.close()
        await second.close()
        await runtime_pool.release(runtime)

    asyncio.run(run())


def test_failed_load_retries_on_the_waiting_client(monkeypatch: Any) -> None:
    catalog = _Catalog(monkeypatch, _spot("BTC"))
    catalog.failures.append(ccxt.NetworkError("first transport path is down"))
    entry = get_ccxt_catalog_entry("binance")

    async def run() -> None:
        catalog.gate = asyncio.Event()
        first = _RestExchangePool(entry, IngestionConfig(proxy_mode="none"))
        second = _RestExchangePool(entry, IngestionConfig(proxy_mode="none"))
        failing = asyncio.create_task(_borrow(first))
        await _until(lambda: catalog.calls == 1)
        waiting = asyncio.create_task(_borrow(second))
        await _until(lambda: _rails()[0]["sharers"] == 2)
        catalog.gate.set()

        with pytest.raises(ccxt.NetworkError):
            await failing
        exchange = await waiting
        # The waiter did not inherit the other client's failure: it loaded
        # through its own client.
        assert catalog.calls == 2
        assert catalog.loaders[1] is exchange
        assert exchange.symbols == ["BTC/USDT"]
        assert first.snapshot()["market_load_failures"] == 1
        (rail,) = _rails()
        assert (rail["loads"], rail["load_failures"], rail["sharers"]) == (1, 1, 1)
        await first.close()
        await second.close()

    asyncio.run(run())


def test_closing_the_loading_client_hands_the_load_to_a_waiter(
    monkeypatch: Any,
) -> None:
    catalog = _Catalog(monkeypatch, _spot("BTC"))
    entry = get_ccxt_catalog_entry("binance")

    async def run() -> None:
        catalog.gate = asyncio.Event()
        closing = _RestExchangePool(entry, IngestionConfig(proxy_mode="none"))
        borrower = asyncio.create_task(_borrow(closing))
        await _until(lambda: catalog.calls == 1)
        runtime_pool = CcxtRuntimePool()
        acquiring = asyncio.create_task(
            runtime_pool.acquire(
                BinanceSpotCcxtProfile(),
                IngestionConfig(proxy_mode="none"),
            )
        )
        await _until(lambda: _rails()[0]["sharers"] == 2)

        # Transport shutdown closes the client whose load is in flight.
        await closing.close()
        await asyncio.gather(borrower, return_exceptions=True)
        assert borrower.cancelled()
        await _until(lambda: catalog.calls == 2)
        catalog.gate.set()
        runtime = await acquiring

        assert catalog.loaders[1] is runtime.exchange
        assert runtime.exchange.symbols == ["BTC/USDT"]
        (rail,) = _rails()
        assert (rail["loads"], rail["load_failures"], rail["sharers"]) == (1, 0, 1)
        await runtime_pool.release(runtime)
        assert _rails() == []

    asyncio.run(run())
