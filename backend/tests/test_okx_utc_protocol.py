"""Exercise the pinned CCXT methods, without opening a network connection."""
import asyncio

import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import StreamDescriptor, StreamType
from app.exchanges.ccxt_ext.profiles import OkxSpotCcxtProfile, OkxSwapCcxtProfile
from app.exchanges.ccxt_ext.models import CcxtRawMarketEvent
from app.exchanges.okx_intervals import okx_utc_interval


class Captured(Exception):
    def __init__(self, request):
        self.request = request


@pytest.mark.parametrize("market_type", ["spot", "swap.linear"])
@pytest.mark.parametrize("interval", ["6h", "12h", "1d", "2d", "3d", "1w", "1M", "3M"])
def test_owned_rest_pool_uses_qualified_utc_grid_for_source_history(market_type, interval):
    from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
    from app.exchanges.ccxt_ext.generic import _create_exchange

    async def run():
        exchange = _create_exchange(get_ccxt_catalog_entry("okx"), IngestionConfig(proxy_mode="none"),
                                    market_type=market_type, websocket=False)
        spot = market_type == "spot"
        symbol = "BTC/USDT" if spot else "BTC/USDT:USDT"
        exchange.set_markets([{
            "id": "BTC-USDT" if spot else "BTC-USDT-SWAP", "symbol": symbol,
            "base": "BTC", "quote": "USDT", "type": "spot" if spot else "swap",
            "spot": spot, "swap": not spot, "future": False, "option": False,
            "contract": not spot, "linear": not spot, "inverse": False,
            "settle": None if spot else "USDT",
        }])
        async def load(*args, **kwargs):
            return exchange.markets
        async def rest(request, *args):
            raise Captured(request)
        exchange.load_markets = load
        exchange.publicGetMarketHistoryCandles = rest
        try:
            with pytest.raises(Captured) as got:
                await exchange.fetch_candlescope_klines(symbol, interval, 1772323200000, 1,
                                                       {"until": 1772323200000})
            assert got.value.request["bar"] == okx_utc_interval(interval)
            assert got.value.request["before"] == 1772323199999
            assert got.value.request["after"] == 1772323200001
        finally:
            await exchange.close()
    asyncio.run(run())


@pytest.mark.parametrize("profile_type", [OkxSpotCcxtProfile, OkxSwapCcxtProfile])
@pytest.mark.parametrize("interval", ["1m", "6h", "12h", "1d", "3d", "1w", "1M"])
def test_utc_subscribe_cache_reverse_unsubscribe_and_rest(profile_type, interval):
    async def run():
        profile = profile_type()
        exchange = profile.create_exchange(IngestionConfig(proxy_mode="none"), raw_event_sink=None, lifecycle_sink=None)
        spot = profile.market_type == "spot"
        symbol = "BTC/USDT" if spot else "BTC/USDT:USDT"
        native = "BTC-USDT" if spot else "BTC-USDT-SWAP"
        exchange.set_markets([{
            "id": native, "symbol": symbol, "base": "BTC", "quote": "USDT",
            "baseId": "BTC", "quoteId": "USDT", "type": "spot" if spot else "swap",
            "spot": spot, "swap": not spot, "future": False, "option": False,
            "contract": not spot, "linear": not spot, "inverse": False,
            "settle": None if spot else "USDT", "settleId": None if spot else "USDT",
        }])
        async def load(*args, **kwargs):
            return exchange.markets
        async def subscribe(access, message_hash, channel, *args):
            raise Captured(channel)
        async def multiple(url, hashes, request, *args):
            raise Captured(request)
        async def rest(request, *args):
            raise Captured(request)
        exchange.load_markets = load
        exchange.subscribe = subscribe
        exchange.watch_multiple = multiple
        exchange.publicGetMarketCandles = rest
        descriptor = StreamDescriptor(native, StreamType.KLINE, interval=interval, exchange="okx", market_type=profile.market_type)
        expected = "candle" + okx_utc_interval(interval)
        try:
            with pytest.raises(Captured) as got:
                await profile.watch(exchange, descriptor, symbol)
            assert got.value.request == expected
            assert profile.matches(CcxtRawMarketEvent(expected, native, {}, 0, "okx", profile.market_type), descriptor)
            assert exchange.find_timeframe(expected[6:]) == interval
            resolved = []
            client = type("Client", (), {"resolve": lambda self, value, key: resolved.append(key)})()
            exchange.handle_ohlcv(client, {"arg": {"channel": expected, "instId": native}, "data": [["1793059200000", "1", "3", "0.5", "2", "10", "1", "20", "1"]]})
            assert set(exchange.ohlcvs[symbol]) == {interval}
            assert resolved == [f"{expected}:{native}", f"multi:{expected}:{symbol}"]
            with pytest.raises(Captured) as got:
                await exchange.watch_ohlcv_for_symbols([[symbol, "1m"], [symbol, interval]])
            assert got.value.request["args"][-1]["channel"] == expected
            with pytest.raises(Captured) as got:
                await exchange.un_watch_ohlcv(symbol, interval)
            assert got.value.request["op"] == "unsubscribe"
            assert got.value.request["args"][0]["channel"] == expected
            with pytest.raises(Captured) as got:
                await exchange.fetch_ohlcv(symbol, interval)
            assert got.value.request["bar"] == okx_utc_interval(interval)
        finally:
            await exchange.close()
    asyncio.run(run())


@pytest.mark.parametrize("channel,accepted", [("candle1Dutc", True), ("candle1D", False), ("candleunknown", False), ("candle6Hutc", False)])
def test_normalizer_never_relabels_a_different_grid(channel, accepted):
    from app.data_engine.ingestion.models import DataSource, RawMessage
    from app.exchanges.plugins.okx.normalizer import OkxNormalizer
    descriptor = StreamDescriptor("BTC-USDT", StreamType.KLINE, interval="1d", exchange="okx", market_type="spot")
    normalizer = OkxNormalizer(IngestionConfig(), descriptor)
    message = RawMessage(payload={"arg": {"channel": channel}, "data": [["1793059200000", "1", "3", "0.5", "2", "10", "1", "20", "1"]]},
        source=DataSource.WEBSOCKET, stream_type=StreamType.KLINE, received_at_ms=1793059260000)
    parsed = normalizer.parse(message)
    assert (parsed is not None) is accepted
    if parsed:
        assert parsed.data["interval"] == "1d"
        assert parsed.data["is_closed"] is True
        assert parsed.data["close_time"] == 1793145599999
