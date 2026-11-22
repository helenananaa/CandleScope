"""INGESTION_MARKET_SOURCE_CAPTURE_ENABLED turns the raw REST/WS envelope log off."""

import asyncio

import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import (
    DataSource,
    RawMessage,
    StreamDescriptor,
    StreamType,
    TransportRequest,
)
from app.data_engine.ingestion.normalize import NormalizeLayer
from app.data_engine.storage import klines_repo, market_sources
from app.exchanges.ccxt_ext import venue_history
from app.exchanges.ccxt_ext.provider import CcxtProvider
from app.exchanges.ccxt_ext.source_capture import RAW_ONLY, REST_CAPTURE


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "klines.sqlite")
    klines_repo.init_klines_storage()
    # The build record ships with the pinned CCXT fork; these tests do not need it.
    monkeypatch.setattr(market_sources, "_provenance", lambda: '{"capture_schema": "test"}')


def test_capture_defaults_on_and_follows_the_environment(monkeypatch):
    monkeypatch.delenv("INGESTION_MARKET_SOURCE_CAPTURE_ENABLED", raising=False)
    assert IngestionConfig().market_source_capture_enabled is True
    monkeypatch.setenv("INGESTION_MARKET_SOURCE_CAPTURE_ENABLED", "0")
    assert IngestionConfig().market_source_capture_enabled is False


@pytest.mark.parametrize("enabled", [True, False])
def test_raw_websocket_frames_are_kept_only_with_capture(database, enabled):
    desc = StreamDescriptor("BTC-USDT-SWAP", StreamType.DEPTH, exchange="okx", market_type="futures")
    forwarded = []

    async def forward(event):
        forwarded.append(event)

    layer = NormalizeLayer(
        IngestionConfig(ccxt_fork_kline_enabled=True, market_source_capture_enabled=enabled), desc
    )
    layer.on_event(forward)
    frame = {"arg": {"channel": "books", "instId": desc.symbol}, "data": [{"seqId": 1}]}
    asyncio.run(layer.ingest(RawMessage({RAW_ONLY: True, "raw": frame}, DataSource.WEBSOCKET, StreamType.DEPTH, 100)))
    assert len(market_sources.observations(desc)) == (1 if enabled else 0)
    # A capture-only frame is never parsed, whether or not it was kept.
    assert forwarded == []


@pytest.mark.parametrize("enabled", [True, False])
def test_rest_history_envelopes_are_kept_only_with_capture(database, monkeypatch, enabled):
    desc = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m", exchange="binance")

    async def strategy(req, config, pool):
        sink = REST_CAPTURE.get()
        if sink is not None:
            sink.append({"endpoint": "https://public.test/klines", "received_at": 1, "payload": [[1, "2"]]})
        return []

    monkeypatch.setitem(venue_history.HISTORY_STRATEGIES, ("binance", StreamType.KLINE), strategy)
    provider = CcxtProvider()
    config = IngestionConfig(ccxt_fork_kline_enabled=True, market_source_capture_enabled=enabled)

    async def run():
        try:
            return await provider.fetch_history_with_config("binance", TransportRequest(desc), config)
        finally:
            await provider.close_history_transport("binance", config)

    assert asyncio.run(run()) == []
    assert len(market_sources.observations(desc)) == (1 if enabled else 0)
