from __future__ import annotations

import asyncio

from app.data_engine.data_manager import DataManager
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType, TransportRequest
from app.data_engine.interval_resolution import IntervalResolver
from app.data_engine.kline_quality import GATE_LEGACY_VOLUME_SOURCE, GATE_WS_CONFIRMED_SOURCE, source_is_trusted_final
from app.data_engine.storage import klines_repo
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.gate_candles import fetch_linear_candles
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


def test_gate_linear_ws_only_finalizes_confirmed_native_snapshot(tmp_path, monkeypatch):
    async def exercise():
        resolver = IntervalResolver()
        for purpose in ("history", "realtime"):
            assert resolver.resolve(exchange="gate", market_type=MARKET, interval="5m", purpose=purpose).is_native

        monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
        klines_repo.init_klines_storage()
        manager = DataManager()
        manager.set_storage(klines_repo.KlinesRepoAdapter())
        manager._started = True
        manager.bar_aggregator.add_target(SYMBOL, "5m", exchange="gate", market_type=MARKET)
        profile = CcxtUnifiedProfile(get_ccxt_catalog_entry("gate"), MARKET)
        exchange = profile.create_exchange(IngestionConfig(proxy_mode="none"), raw_event_sink=None, lifecycle_sink=None)
        monkeypatch.setattr(exchange, "market", lambda _symbol: CONTRACT)
        projector = CcxtUnifiedProjector(exchange_id="gate", market_type=MARKET, descriptor=DESCRIPTOR)
        normalizer = CcxtUnifiedNormalizer(DESCRIPTOR)

        def stored():
            return klines_repo.query_klines(SYMBOL, "5m", exchange="gate", market_type=MARKET)

        async def project(candle):
            async def watch(_symbol, _interval):
                return [exchange.parse_ohlcv({**candle, "n": "5m_BTC_USDT"})]
            monkeypatch.setattr(exchange, "watch_ohlcv", watch)
            rows = await profile.watch(exchange, DESCRIPTOR, SYMBOL)
            events = []
            for raw in projector.project(rows):
                event = normalizer.parse(RawMessage(raw.payload, DataSource.WEBSOCKET, StreamType.KLINE, OPENED + WIDTH))
                await manager.bar_aggregator.on_market_event(event)
                events.append(event)
            return events

        try:
            preview = {**VENUE_BAR, "h": "74190", "v": "3683965.5", "w": "true"}
            [forming] = await project(preview)
            assert not forming.data["is_closed"]
            assert forming.data["volume"] == 368.39655
            [successor] = await project({**VENUE_BAR, "t": (OPENED + WIDTH) // 1000})
            assert not successor.data["is_closed"]
            assert stored() == []

            [final] = await project({**VENUE_BAR, "w": True})
            assert final.data["is_closed"]
            await manager.aggregator_bridge.delivery.stop()
            [saved] = stored()
            assert saved["source"] == GATE_WS_CONFIRMED_SOURCE
            assert (saved["high"], saved["volume"]) == (74188.0, 368.3966)
            assert await project(preview) == []
            assert await project({**VENUE_BAR, "w": True}) == []
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
            [payload] = await fetch_linear_candles(exchange, SYMBOL, req, limit=1, now_ms=OPENED + WIDTH)
            assert calls == [{"contract": "BTC_USDT", "settle": "usdt", "interval": "5m",
                              "from": OPENED // 1000, "to": OPENED // 1000 + 1}]
            assert payload["value"] == [OPENED, 74161.1, 74188, 73948.4, 73985.1, 368.3966]
            assert payload["gate_rest_close_verified"] is True
            [forming] = await fetch_linear_candles(exchange, SYMBOL, req, limit=1, now_ms=OPENED + WIDTH - 1)
            assert forming["is_closed"] is False
            assert await fetch_linear_candles(exchange, SYMBOL, req, limit=1, now_ms=OPENED) == []
            assert len(calls) == 2
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
