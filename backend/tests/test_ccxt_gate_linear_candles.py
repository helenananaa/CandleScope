from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.data_engine.bar_basis import GATE_INVERSE_CONTRACTS
from app.data_engine.data_manager import DataManager
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType, TransportRequest
from app.data_engine.interval_resolution import IntervalResolutionError, IntervalResolver
from app.data_engine.kline_quality import (
    GATE_INVERSE_WS_CONFIRMED_SOURCE, GATE_LEGACY_VOLUME_SOURCE, GATE_WS_CONFIRMED_SOURCE, source_is_trusted_final,
)
from app.data_engine.storage import klines_repo
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.gate_candles import fetch_perpetual_candles
from app.exchanges.ccxt_ext.generic import CcxtUnifiedProfile
from app.exchanges.ccxt_ext.unified import CcxtUnifiedNormalizer, CcxtUnifiedProjector
from tests.test_bar_delivery_journal import payload


OPENED = 1794210000000
WIDTH = 300_000
MARKET = "swap.linear"
SYMBOL = "BTC/USDT:USDT"
DESCRIPTOR = StreamDescriptor(SYMBOL, StreamType.KLINE, interval="5m", exchange="gate", market_type=MARKET)
CONTRACT = {"id": "BTC_USDT", "settleId": "usdt", "swap": True, "linear": True, "contractSize": 0.0001}
VENUE_BAR = {"t": OPENED // 1000, "o": "74161.1", "h": "74188", "l": "73948.4", "c": "73985.1", "v": 3683966}


@pytest.mark.parametrize("inverse", [False, True])
def test_gate_ws_only_finalizes_confirmed_native_snapshot(tmp_path, monkeypatch, inverse):
    identity = GATE_INVERSE_CONTRACTS if inverse else None
    market = "swap.inverse" if inverse else MARKET
    symbol = "BTC/USD:BTC" if inverse else SYMBOL
    contract = ({"id": "BTC_USD", "settleId": "btc", "swap": True, "inverse": True, "contractSize": 1}
                if inverse else CONTRACT)
    descriptor = replace(DESCRIPTOR, market_type=market, symbol=symbol, series_identity=identity)
    kwargs = {"series_identity": identity} if inverse else {}
    volume = 8250 if inverse else VENUE_BAR["v"]
    venue_bar = {**VENUE_BAR, "v": volume}
    scale = 1 if inverse else 0.0001
    async def exercise():
        resolver = IntervalResolver()
        for purpose in ("history", "realtime"):
            assert resolver.resolve(exchange="gate", market_type=market, interval="5m", purpose=purpose).is_native

        monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
        klines_repo.init_klines_storage()
        manager = DataManager()
        manager.set_storage(klines_repo.KlinesRepoAdapter())
        manager._started = True
        manager.bar_aggregator.add_target(symbol, "5m", exchange="gate", market_type=market, **kwargs)
        profile = CcxtUnifiedProfile(get_ccxt_catalog_entry("gate"), market)
        exchange = profile.create_exchange(IngestionConfig(proxy_mode="none"), raw_event_sink=None, lifecycle_sink=None)
        monkeypatch.setattr(exchange, "market", lambda _symbol: contract)
        projector = CcxtUnifiedProjector(exchange_id="gate", market_type=market, descriptor=descriptor)
        normalizer = CcxtUnifiedNormalizer(descriptor)

        def stored():
            return klines_repo.query_klines(symbol, "5m", exchange="gate", market_type=market, **kwargs)

        async def project(candle):
            async def watch(_symbol, _interval):
                return [exchange.parse_ohlcv({**candle, "n": "5m_" + contract["id"]})]
            monkeypatch.setattr(exchange, "watch_ohlcv", watch)
            rows = await profile.watch(exchange, descriptor, symbol)
            events = []
            for raw in projector.project(rows):
                event = normalizer.parse(RawMessage(raw.payload, DataSource.WEBSOCKET, StreamType.KLINE, OPENED + WIDTH))
                await manager.bar_aggregator.on_market_event(event)
                events.append(event)
            return events

        try:
            preview = {**venue_bar, "h": "74190", "v": str(volume - 0.5), "w": "true"}
            [forming] = await project(preview)
            assert not forming.data["is_closed"]
            assert forming.data["volume"] == pytest.approx((volume - 0.5) * scale)
            [successor] = await project({**venue_bar, "t": (OPENED + WIDTH) // 1000})
            assert not successor.data["is_closed"]
            assert stored() == []

            [final] = await project({**venue_bar, "w": True})
            assert final.data["is_closed"]
            await manager.aggregator_bridge.delivery.stop()
            [saved] = stored()
            assert saved["source"] == (GATE_INVERSE_WS_CONFIRMED_SOURCE if inverse else GATE_WS_CONFIRMED_SOURCE)
            assert (saved["high"], saved["volume"]) == pytest.approx((74188.0, volume * scale))
            if inverse:
                assert not klines_repo.query_klines(symbol, "5m", exchange="gate", market_type=market)
            assert await project(preview) == []
            assert await project({**venue_bar, "w": True}) == []
        finally:
            await manager.aggregator_bridge.delivery.stop()
            await manager.event_bus.close()
            await exchange.close()

    asyncio.run(exercise())


def test_gate_linear_single_bucket_rest_filters_outside_rows_and_freezes_finality(monkeypatch):
    from ccxt.async_support import gate

    async def exercise():
        exchange = gate()
        monkeypatch.setattr(exchange, "market", lambda _symbol: CONTRACT)
        calls = []

        async def fetch(params):
            calls.append(params)
            return [{**VENUE_BAR, "t": (OPENED + WIDTH) // 1000}, VENUE_BAR]

        monkeypatch.setattr(exchange, "publicFuturesGetSettleCandlesticks", fetch)
        req = TransportRequest(DESCRIPTOR, limit=1, start_ms=OPENED, end_ms=OPENED, history=True)
        try:
            [payload] = await fetch_perpetual_candles(exchange, SYMBOL, req, limit=1, now_ms=OPENED + WIDTH)
            assert calls == [{"contract": "BTC_USDT", "settle": "usdt", "interval": "5m",
                              "from": OPENED // 1000, "to": OPENED // 1000 + 1}]
            assert payload["value"] == [OPENED, 74161.1, 74188, 73948.4, 73985.1, 368.3966]
            assert payload["gate_rest_close_verified"] is True
            [forming] = await fetch_perpetual_candles(exchange, SYMBOL, req, limit=1, now_ms=OPENED + WIDTH - 1)
            assert forming["is_closed"] is False
            assert await fetch_perpetual_candles(exchange, SYMBOL, req, limit=1, now_ms=OPENED) == []
            assert len(calls) == 2
        finally:
            await exchange.close()

    asyncio.run(exercise())


def test_gate_inverse_history_requires_explicit_contract_volume(monkeypatch):
    from ccxt.async_support import gate
    from app.data_engine.series_identity import KlineSeriesIdentity
    from app.exchanges.history_identity import supports_history_identity

    route_params = dict(exchange="gate", market_type="swap.inverse", interval="5m")
    resolver = IntervalResolver()
    route = resolver.resolve(**route_params, purpose="history")
    route.require_series_identity(GATE_INVERSE_CONTRACTS)
    base_asset = KlineSeriesIdentity.for_exchange("gate")
    with pytest.raises(IntervalResolutionError, match="contract_count"):
        route.require_series_identity(base_asset)
    with pytest.raises(IntervalResolutionError):
        resolver.resolve(**(route_params | {"interval": "10m"}), purpose="history")
    assert not supports_history_identity(**route_params, identity=base_asset)

    async def exercise():
        exchange = gate()
        monkeypatch.setattr(exchange, "market", lambda _symbol: {
            "id": "BTC_USD", "settleId": "btc", "swap": True, "inverse": True,
            "contractSize": 1, "info": {"quanto_multiplier": "0"},
        })
        calls = []

        async def fetch(params):
            calls.append(params)
            return [{**VENUE_BAR, "v": 8250}]

        monkeypatch.setattr(exchange, "publicFuturesGetSettleCandlesticks", fetch)
        descriptor = replace(DESCRIPTOR, market_type="swap.inverse", symbol="BTC/USD:BTC")
        request = TransportRequest(descriptor, limit=1, start_ms=OPENED, end_ms=OPENED, history=True)
        try:
            with pytest.raises(ValueError, match="contract_count"):
                await fetch_perpetual_candles(exchange, descriptor.symbol, request, limit=1, now_ms=OPENED + WIDTH)
            assert not calls
            descriptor.series_identity = GATE_INVERSE_CONTRACTS
            [payload] = await fetch_perpetual_candles(
                exchange, descriptor.symbol, request, limit=1, now_ms=OPENED + WIDTH,
            )
            event = CcxtUnifiedNormalizer(descriptor).parse(RawMessage(
                payload=payload, source=DataSource.HTTP_BACKFILL, stream_type=StreamType.KLINE,
                received_at_ms=OPENED + WIDTH,
            ))
            assert calls[0]["settle"] == "btc" and calls[0]["contract"] == "BTC_USD"
            assert event.data["volume"] == 8250 and event.data["is_closed"]
            assert event.data["series_identity"] == GATE_INVERSE_CONTRACTS.to_dict()
        finally:
            await exchange.close()

    asyncio.run(exercise())


def test_gate_linear_upgrade_revokes_legacy_volume_and_pending_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    old_row = {**payload()["storage_row"], "open_time": OPENED, "close_time": OPENED + WIDTH - 1,
               "volume": VENUE_BAR["v"]}
    klines_repo.upsert_klines(SYMBOL, "5m", [old_row], exchange="gate", market_type=MARKET, source="backfill")
    klines_repo.upsert_klines(SYMBOL, "10m", [{**old_row, "close_time": OPENED + 2 * WIDTH - 1}],
                             exchange="gate", market_type=MARKET, source="backfill_aggregated")
    klines_repo.upsert_klines("BTC_USDT", "1m", [old_row], exchange="gate", market_type="spot", source="backfill")
    journal = klines_repo.KlinesRepoAdapter().bar_delivery
    journal.enqueue("legacy-gate", {**payload(), "exchange": "gate", "market_type": MARKET})
    with klines_repo._connect() as conn:
        conn.execute("DELETE FROM kline_quality_migrations WHERE name='gate_linear_base_volume_v1'")
        prior_revision = klines_repo.current_revision(conn)

    klines_repo.init_klines_storage()
    with klines_repo._connect() as conn:
        assert klines_repo.current_revision(conn) == prior_revision + 2
    for interval in ("5m", "10m"):
        [row] = klines_repo.query_klines(SYMBOL, interval, exchange="gate", market_type=MARKET)
        assert row["volume"] == VENUE_BAR["v"]
        assert row["source"] == GATE_LEGACY_VOLUME_SOURCE
        assert not source_is_trusted_final(row["source"])
    assert klines_repo.query_klines("BTC_USDT", "1m", exchange="gate", market_type="spot")[0]["source"] == "backfill"
    [pending] = journal.pending()
    assert pending["phase"] == "rejected" and pending["recovery_required"]

    klines_repo.upsert_klines(SYMBOL, "5m", [{**old_row, "volume": 368.3966}], exchange="gate",
                             market_type=MARKET, source="backfill")
    klines_repo.init_klines_storage()
    [fresh] = klines_repo.query_klines(SYMBOL, "5m", exchange="gate", market_type=MARKET)
    assert fresh["volume"] == 368.3966 and fresh["source"] == "backfill"
