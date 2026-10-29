"""Exchange-neutral continuity contracts across the real service boundaries."""
from __future__ import annotations

import asyncio
import pytest

from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.continuity_policy import ContinuityPolicy, ContinuityUnsupported
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import BarData
from app.data_engine.ingestion import StreamPipeline
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamDescriptor, StreamType
from app.data_engine.market_data.events import MarketStateEvent
from app.data_engine.market_data.hub import MarketEventHub
from app.data_engine.market_data.models import MarketChannel, MarketStreamKey
from app.data_engine.storage import klines_repo
from tests.test_subscription_continuity import capture, closed
from tests.test_recovery_kline_consumers import T
from tests.test_recovery_delivery_integration import _until
from tests import test_trade_flow_service as trade
from tests import test_full_order_book_service as book


IDENTITIES = [
    ("binance", "spot", "ETHUSDT"), ("binance", "futures", "BTCUSDT"),
    ("okx", "spot", "BTC-USDT"), ("okx", "swap", "ETH-USDT-SWAP"),
    ("bybit", "spot", "SOL/USDT"), ("bybit", "swap.linear", "BTC/USDT:USDT"),
    ("twelvedata", "stock", "AAPL"), ("twelvedata", "forex", "EUR/USD"),
]


class KlineFactory:
    async def start(self, symbol, interval, on_market_event, exchange, market_type,
                    on_gap=None, *, gap_repair_owner="inline"):
        self.pipeline = StreamPipeline(IngestionConfig(ccxt_unified_stream_enabled=False), self,
            StreamDescriptor(symbol, StreamType.KLINE, interval=interval,
                             exchange=exchange, market_type=market_type),
            gap_repair_owner=gap_repair_owner)
        self.pipeline.delivery.on_market_event(on_market_event)
        self.pipeline.delivery.on_gap(on_gap)
        return self.pipeline

    async def emit(self, opened, *, is_closed=True):
        d = self.pipeline.descriptor
        from app.data_engine.interval_policy import parse_interval_ms
        closed_at = opened + parse_interval_ms(d.interval) - 1
        await self.pipeline.continuity.ingest(MarketEvent(
            StreamType.KLINE, d.symbol, d.exchange, closed_at, closed_at,
            DataSource.WEBSOCKET,
            data={"open_time": opened, "close_time": closed_at, "interval": d.interval,
                  "is_closed": is_closed, "open": 100, "high": 100, "low": 100, "close": 100,
                  "volume": 1}, market_type=d.market_type,
        ))


@pytest.mark.anyio
async def test_kline_repair_includes_preview_whose_final_update_was_lost(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    dm = DataManager()
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    dm._started = True
    factory, requests = KlineFactory(), []
    dm.set_ingestion_factory(factory)
    dm.set_backfill_trigger(lambda *args, **kwargs: requests.append((args, kwargs)))
    identity = dict(exchange="okx", market_type="futures", symbol="BTC-USDT-SWAP", interval="1m")
    try:
        await dm.ensure_stream(**identity)
        strict, errors, _ = capture(dm, identity=identity)
        live, _, _ = capture(dm, identity=identity, policy="gap_aware")
        await factory.emit(T)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(T + 60_000, is_closed=False)
        await factory.emit(T + 180_000)
        await _until(lambda: len(closed(live)) == 2)
        assert requests[0][0][2:4] == (T + 60_000, T + 120_000)
        assert closed(strict) == [T // 1000]
        await dm.on_bars_backfilled(**identity, bars=[BarData(
            (T + offset) // 1000, 100, 100, 100, 100, 1, source="backfill_rest_verified",
        ) for offset in (60_000, 120_000)])
        await _until(lambda: len(closed(strict)) == 4)
        assert closed(strict) == [(T + offset) // 1000 for offset in (0, 60_000, 120_000, 180_000)]
        assert errors == []
    finally:
        await dm.coordinator.stop_all()
        await dm.aggregator_bridge.delivery.stop()
        await dm.event_bus.close()


@pytest.mark.anyio
@pytest.mark.parametrize("exchange,market,symbol", IDENTITIES)
async def test_kline_policy_has_no_exchange_or_symbol_allowlist(tmp_path, monkeypatch, exchange, market, symbol):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    dm = DataManager()
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    dm._started = True
    factory, requests = KlineFactory(), []
    dm.set_ingestion_factory(factory)
    dm.set_backfill_trigger(lambda *args, **kwargs: requests.append((args, kwargs)))
    # Exercise each route within its declared BarBasis qualification. The
    # Bybit evidence currently qualifies 5m, not every catalog timeframe.
    interval, width = ("5m", 300_000) if exchange == "bybit" else ("1m", 60_000)
    first = T // width * width
    identity = dict(exchange=exchange, market_type=market, symbol=symbol, interval=interval)
    try:
        if exchange == "twelvedata":
            from app.data_engine.interval_resolution import IntervalResolutionError
            with pytest.raises(IntervalResolutionError, match="realtime is unavailable"):
                await dm.ensure_stream(**identity)
            contract = dm.continuity_contract(MarketStreamKey.build(exchange, market, symbol, MarketChannel.KLINE))
            assert contract["available"] is False and contract["policies"] == []
            return
        await dm.ensure_stream(**identity)
        strict, errors, _ = capture(dm, identity=identity)
        live, _, _ = capture(dm, identity=identity, policy="gap_aware")
        await factory.emit(first)
        await _until(lambda: len(closed(strict)) == 1)
        await factory.emit(first + 2 * width)
        await _until(lambda: len(closed(live)) == 2)
        assert len(closed(strict)) == 1
        assert requests[0][0][:2] == (symbol, interval)
        assert requests[0][0][4:] == (exchange, market)
        await dm.on_bars_backfilled(**identity, bars=[BarData(
            (first + width) // 1000, 100, 100, 100, 100, 1, source="backfill_rest_verified")])
        await _until(lambda: len(closed(strict)) == 3)
        assert errors == []
        assert factory.pipeline.recovery.snapshot()["ordered_filter_enabled"] is True
    finally:
        await dm.coordinator.stop_all()
        await dm.aggregator_bridge.delivery.stop()
        await dm.event_bus.close()


@pytest.mark.anyio
@pytest.mark.parametrize("exchange,market,symbol", IDENTITIES)
async def test_ordered_filter_is_independent_of_binance_inline_recovery(exchange, market, symbol):
    pipeline = StreamPipeline(IngestionConfig(ccxt_unified_stream_enabled=False), object(),
        StreamDescriptor(symbol, StreamType.KLINE, interval="1m", exchange=exchange, market_type=market),
        gap_repair_owner="data_manager")
    delivered = []
    async def receive(event):
        delivered.append(event)
    pipeline.recovery.on_event(receive)
    def event(opened, *, correction=False):
        return MarketEvent(StreamType.KLINE, symbol, exchange, opened, opened,
                           DataSource.PLUGIN if correction else DataSource.WEBSOCKET,
                           data={"open_time": opened, "is_closed": True, "is_correction": correction},
                           market_type=market)
    await pipeline.recovery.ingest_event(event(T + 60_000))
    await pipeline.recovery.ingest_event(event(T))
    await pipeline.recovery.ingest_event(event(T, correction=True))
    assert [item.data["open_time"] for item in delivered] == [T + 60_000, T]
    assert delivered[-1].data["is_correction"] is True
    await pipeline.stop()


@pytest.mark.anyio
async def test_trade_consumers_share_repair_and_gap_aware_gets_corrections(tmp_path):
    class Factory(trade._Factory):
        def __init__(self):
            super().__init__()
            self.gate = asyncio.Event()
        async def fetch_market(self, descriptor, **kwargs):
            await self.gate.wait()
            return await super().fetch_market(descriptor, **kwargs)
    factory = Factory()
    factory.repair_rows[2] = trade._event(2, source=DataSource.HTTP_BACKFILL)
    service = trade._service(factory, tmp_path)
    try:
        await service.ensure_stream(trade._key(), consumer_id="test")
        await factory.emit(trade._event(1))
        await _until(lambda: service.diagnostics()["commands_processed"] == 1)
        strict = service.attach(trade._key(), continuity="strict").subscription
        live = service.attach(trade._key(), continuity="gap_aware").subscription
        await factory.emit(trade._event(3))
        await _until(lambda: service.diagnostics()["commands_processed"] == 2)
        service.hub.flush_all()
        waiting = asyncio.create_task(strict.receive())
        immediate = await asyncio.wait_for(live.receive(), 1)
        assert [row.agg_trade_id for row in immediate.records] == [3]
        assert immediate.detail["source_continuity"]["state"] == "gapped"
        assert not waiting.done()
        factory.gate.set()
        repaired = await asyncio.wait_for(waiting, 1)
        assert [row.agg_trade_id for row in repaired.records] == [2, 3]
        assert repaired.continuity and repaired.detail["continuity_replayed"]
        notice = await asyncio.wait_for(live.receive(), 1)
        assert notice.detail["source_continuity"]["state"] == "resolved"
        assert [row.agg_trade_id for row in notice.corrections] == [2]
        assert len(factory.fetch_calls) == 1
        await strict.close()
        await live.close()
    finally:
        factory.gate.set()
        await service.shutdown()


@pytest.mark.anyio
async def test_trade_timeout_does_not_cancel_another_consumer_or_shared_repair(tmp_path):
    class Factory(trade._Factory):
        def __init__(self):
            super().__init__()
            self.gate = asyncio.Event()
        async def fetch_market(self, descriptor, **kwargs):
            await self.gate.wait()
            return await super().fetch_market(descriptor, **kwargs)
    factory = Factory()
    factory.repair_rows[2] = trade._event(2, source=DataSource.HTTP_BACKFILL)
    service = trade._service(factory, tmp_path)
    try:
        await service.ensure_stream(trade._key(), consumer_id="test")
        await factory.emit(trade._event(1))
        await _until(lambda: bool(service.engine.raw_tail(("binance", "futures", "BTCUSDT"), 1)))
        quick = service.attach(trade._key(), continuity=ContinuityPolicy(max_wait_seconds=.01)).subscription
        patient = service.attach(trade._key(), continuity="strict").subscription
        await factory.emit(trade._event(3))
        await _until(lambda: service.diagnostics()["commands_processed"] == 2)
        service.hub.flush_all()
        with pytest.raises(ConsumerRecoveryRequired, match="source_gap_timeout"):
            await quick.receive()
        waiting = asyncio.create_task(patient.receive())
        factory.gate.set()
        assert [row.agg_trade_id for row in (await asyncio.wait_for(waiting, 1)).records] == [2, 3]
        await patient.close()
    finally:
        factory.gate.set()
        await service.shutdown()


@pytest.mark.anyio
async def test_full_book_strict_waits_for_verified_snapshot_while_live_sees_gap():
    factory = book._Factory()
    factory.prestart_events = [book._delta(100, 101, 99)]
    factory.plans.extend([book._FetchPlan([book._rest_snapshot(100)]), book._FetchPlan([book._rest_snapshot(200)])])
    service = book._service(factory)
    key = book._key()
    try:
        await service.ensure_stream(key, consumer_id="test")
        await service.wait_for_live(key, timeout_seconds=1)
        strict = service.attach(key, continuity="strict").subscription
        live = service.attach(key, continuity="gap_aware").subscription
        await strict.receive()
        await live.receive()
        await factory.gap()
        pending = asyncio.create_task(strict.receive())
        notice = await asyncio.wait_for(live.receive(), 1)
        assert notice.event.data["source_continuity"]["state"] == "gapped"
        assert not pending.done()
        await _until(lambda: factory.fetch_calls == 2)
        await factory.emit(book._delta(200, 201, 199))
        recovered = await asyncio.wait_for(pending, 1)
        assert recovered.event.data["last_update_id"] == 201
        assert recovered.event.data["source_continuity"]["historical_transitions_replayed"] is False
        await strict.close()
        await live.close()
    finally:
        await service.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("channel", [MarketChannel.DEPTH, MarketChannel.TICKER, MarketChannel.MARK_PRICE,
                                      MarketChannel.OPEN_INTEREST, MarketChannel.FUNDING_RATE])
async def test_state_gap_notice_survives_fast_latest_state_coalescing(channel):
    hub = MarketEventHub()
    key = MarketStreamKey.build("bybit", "swap", "ETH/USDT:USDT", channel)
    strict = hub.subscribe([key], continuity="strict")
    live = hub.subscribe([key], continuity="gap_aware")
    hub.mark_source_gap([key], reason="ingestion_reconnecting")
    hub.publish(MarketStateEvent(key, 100, 100, "plugin", {"value": 10}))
    try:
        notice = await live.receive()
        assert notice.event.data["source_continuity"]["state"] == "gapped"
        current = await live.receive()
        assert current.event.data["source_continuity"]["state"] == "restored"
        assert (await strict.receive()).event.data["value"] == 10
    finally:
        await hub.close()


@pytest.mark.anyio
async def test_state_strict_wait_has_deadline_and_close_wakes_it():
    hub = MarketEventHub()
    key = MarketStreamKey.build("okx", "spot", "BTC-USDT", MarketChannel.DEPTH)
    quick = hub.subscribe([key], continuity=ContinuityPolicy(max_wait_seconds=.01))
    patient = hub.subscribe([key], continuity="strict")
    hub.mark_source_gap([key], reason="disconnect")
    with pytest.raises(ConsumerRecoveryRequired, match="source_gap_timeout"):
        await quick.receive()
    waiting = asyncio.create_task(patient.receive())
    await hub.close()
    with pytest.raises(ConsumerRecoveryRequired, match="source_stream_closed"):
        await waiting


@pytest.mark.anyio
async def test_observational_trade_exposes_quality_and_rejects_false_strict_claim(monkeypatch):
    from tests import test_trade_tape_service as tape
    service = tape.TradeTapeService(tape._Factory())
    monkeypatch.setattr(service, "_validate_key", lambda key: (key.exchange, key.market_type, key.symbol))
    try:
        with pytest.raises(ContinuityUnsupported, match="cannot be proven"):
            service.attach(tape._key(), continuity="strict")
        attachment = service.attach(tape._key(), continuity="gap_aware")
        service.engine.activate_stream(("sample", "spot", "BTC/USDT"))
        row = service.engine.ingest(tape._event("opaque-id"))
        service.hub.append(row)
        service.hub.flush_all()
        batch = await attachment.subscription.receive()
        assert batch.detail["source_continuity"]["source_exhaustive"] is False
        await attachment.subscription.close()
    finally:
        await service.shutdown()


@pytest.mark.anyio
async def test_sampled_liquidation_rejects_strict_without_allocating_subscriber(tmp_path):
    from tests import test_liquidation_service as liquidation
    service = liquidation._service(liquidation._Factory(), tmp_path / "liq.sqlite")
    try:
        with pytest.raises(ContinuityUnsupported):
            service.attach(liquidation._key(), continuity="strict")
        assert service.hub.diagnostics()["active_subscribers"] == 0
        attachment = service.attach(liquidation._key(), continuity="gap_aware")
        assert attachment.subscription._source_quality == "sampled_liquidations"
        await attachment.subscription.close()
    finally:
        await service.shutdown()


@pytest.mark.parametrize("exchange,market,symbol,channel,strict", [
    ("okx", "spot", "ETH-USDT", MarketChannel.KLINE, True),
    ("okx", "swap", "ETH-USDT-SWAP", MarketChannel.KLINE, True),
    ("bybit", "spot", "SOL/USDT", MarketChannel.TRADE, False),
    ("binance", "futures", "BTCUSDT", MarketChannel.LIQUIDATION, False),
    ("binance", "futures", "ETHUSDT", MarketChannel.AGG_TRADE, True),
])
def test_capability_report_states_guarantee_instead_of_exchange_whitelist(exchange, market, symbol, channel, strict):
    key = MarketStreamKey.build(exchange, market, symbol, channel)
    contract = DataManager().continuity_contract(key)
    assert contract["available"]
    assert ("strict" in contract["policies"]) is strict
    assert "gap_aware" in contract["policies"]


def test_provider_declared_swap_is_resolved_before_legacy_futures_alias():
    from dataclasses import replace
    from tests.test_interval_resolution import _capabilities, _StubRegistry, IntervalResolver
    capabilities = _capabilities()
    capabilities.channels = [replace(capabilities.channels[0], market_types=("swap",))]
    from app.exchanges.models import ExchangeMarket
    capabilities.markets = [ExchangeMarket("swap", "perpetual", "Swap")]
    capabilities.native_bar_specs = [replace(spec, market_type="swap") for spec in capabilities.native_bar_specs]
    route = IntervalResolver(_StubRegistry(capabilities)).resolve(
        exchange="fixture", market_type="swap", interval="1m", purpose="realtime")
    assert route.market_type == "swap" and route.native_interval == "1m"


@pytest.mark.anyio
async def test_observational_connection_gap_is_immediate_scoped_and_bounded():
    from app.data_engine.market_data.append_hub import AppendBatchHub
    from app.data_engine.market_data.continuity import health_callback
    hub = AppendBatchHub()
    identity = ("okx", "futures", "ETH-USDT-SWAP")
    first = hub.subscribe(source_quality="sampled_liquidations")
    first.stream_identities = {identity}
    other = hub.subscribe(source_quality="sampled_liquidations")
    other.stream_identities = {("bybit", "swap.linear", "BTC/USDT:USDT")}
    callback = health_callback(hub, lambda: (identity,))
    try:
        for _ in range(100):
            await callback("reconnecting", "network")
        control = await first.receive()
        assert control.records == () and control.resync_required
        assert control.detail["source_continuity"]["state"] == "unrecoverable"
        assert other._source_control is None and first.pending_batch_count == 0
        pending = asyncio.create_task(first.receive())
        await hub.close()
        assert await pending is None
    finally:
        await hub.close()


@pytest.mark.anyio
async def test_invalid_state_policy_does_not_leak_a_hub_subscription():
    hub = MarketEventHub()
    key = MarketStreamKey.build("okx", "spot", "BTC-USDT", MarketChannel.TICKER)
    with pytest.raises(ValueError):
        hub.subscribe([key], continuity="typo")
    assert hub.diagnostics()["active_subscribers"] == 0
    await hub.close()


@pytest.mark.anyio
async def test_non_binance_id_capable_plugin_uses_same_trade_repair(tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    import app.exchanges as exchanges
    original = exchanges.bootstrap_default_adapters().get_plugin("binance").capabilities()
    registry = SimpleNamespace(get_plugin=lambda name: SimpleNamespace(capabilities=lambda: original))
    monkeypatch.setattr(exchanges, "get_exchange_registry", lambda: registry)
    factory = trade._Factory()
    service = trade._service(factory, tmp_path)
    key = MarketStreamKey.build("fixturevenue", "futures", "GOLDUSD", MarketChannel.AGG_TRADE)
    def event(sequence):
        return replace(trade._event(sequence), exchange=key.exchange, symbol=key.symbol)
    factory.repair_rows[2] = event(2)
    try:
        await service.ensure_stream(key, consumer_id="test")
        await factory.emit(event(1))
        await _until(lambda: service.diagnostics()["commands_processed"] == 1)
        subscription = service.attach(key, continuity="strict").subscription
        await factory.emit(event(3))
        await _until(lambda: service.diagnostics()["commands_processed"] >= 2)
        service.hub.flush_all()
        batch = await asyncio.wait_for(subscription.receive(), 1)
        assert [row.agg_trade_id for row in batch.records] == [2, 3]
        assert all(row.exchange == key.exchange and row.symbol == key.symbol for row in batch.records)
        await subscription.close()
    finally:
        await service.shutdown()


@pytest.mark.anyio
async def test_trade_factory_delegates_repair_before_pipeline_start(monkeypatch):
    from app.data_engine.ingestion import MarketDataIngress
    from app.data_engine.ingestion.factory import ExchangeIngestionFactory
    owners = []
    async def started(pipeline):
        owners.append(pipeline.recovery.gap_repair_owner)
    monkeypatch.setattr(StreamPipeline, "start", started)
    factory = ExchangeIngestionFactory()
    factory._ingress = MarketDataIngress(factory.config)
    factory._ingress._started = True
    async def receive(event):
        pass
    try:
        await factory.start_market(StreamDescriptor("ETHUSDT", StreamType.AGG_TRADE,
                                   exchange="binance", market_type="spot"), receive,
                                   gap_repair_owner="trade_flow")
        assert owners == ["trade_flow"]
    finally:
        await factory.shutdown()
