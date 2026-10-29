import asyncio

import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import StreamDescriptor, StreamType, TransportRequest
from app.exchanges.registry import bootstrap_default_adapters
from app.exchanges.ccxt_ext.provider import CcxtProvider


def test_registry_has_one_connector_and_keeps_dataset_vendor_and_external_plugin():
    registry = bootstrap_default_adapters()
    connector = registry.get_provider("ccxt")
    bindings = [registry.get_plugin(venue) for venue in ("binance", "okx", "bybit")]
    assert all(binding.provider is connector for binding in bindings)
    assert [binding.capabilities().exchange for binding in bindings] == ["binance", "okx", "bybit"]
    assert not getattr(registry.get_plugin("twelvedata"), "connector_id", None)
    catalog = registry.provider_catalog()
    assert len([row for row in catalog if row["connector_id"] == "ccxt"]) == 1
    assert len(next(row["venues"] for row in catalog if row["connector_id"] == "ccxt")) == 105
    assert next(row for row in catalog if row["connector_id"] == "twelvedata")["venues"] == ["twelvedata"]


def test_provider_rejects_cross_venue_route_before_client_creation():
    provider = CcxtProvider()
    req = TransportRequest(StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m", exchange="okx"))
    with pytest.raises(ValueError, match="substitute"):
        asyncio.run(provider.fetch_history_with_config("binance", req, IngestionConfig()))
    assert provider.diagnostics()["active_rest_pools"] == 0


def test_venue_close_does_not_close_another_venue_or_configuration(monkeypatch):
    created = []

    class Pool:
        def __init__(self, entry, config):
            self.closed = False
            created.append(self)

        async def close(self):
            self.closed = True

        def snapshot(self):
            return {"closed": self.closed}

    monkeypatch.setattr("app.exchanges.ccxt_ext.provider._RestExchangePool", Pool)

    async def run():
        provider = CcxtProvider()
        first, second = IngestionConfig(), IngestionConfig()
        a = provider._rest_pool("binance", first)
        b = provider._rest_pool("okx", first)
        c = provider._rest_pool("binance", second)
        assert provider._rest_pool("binance", first) is a
        await provider.close_history_transport("binance", first)
        assert a.closed and not b.closed and not c.closed
        await provider.close_history_transport("okx", first)
        await provider.close_history_transport("binance", second)
        assert provider.diagnostics()["active_rest_pools"] == 0

    asyncio.run(run())


def test_unknown_generic_fields_survive_ws_projection_without_claiming_support():
    from app.exchanges.ccxt_ext.unified import CcxtUnifiedProjector
    descriptor = StreamDescriptor("BTC/USDT", StreamType.KLINE, interval="5m", exchange="bybit")
    projector = CcxtUnifiedProjector(exchange_id="bybit", market_type="spot", descriptor=descriptor)
    row = [300000, 1, 2, 0.5, 1.5, 9, {"vendorField": "0.00000000000000001"}]
    event, = projector.project([row])
    assert event.payload["value"] == row
    changed = [*row[:6], {"vendorField": "0.00000000000000002"}]
    event, = projector.project([changed])
    assert event.payload["value"] == changed

