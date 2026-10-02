from __future__ import annotations

import asyncio

import pytest

from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamType
from app.data_engine.market_data.models import MarketChannel, MarketStreamKey
from app.data_engine.market_data.trade_tape import TradeTapeEngine
from app.data_engine.market_data.trade_tape_service import TradeTapeService


class _Handle:
    def __init__(self) -> None:
        self.stops = 0

    async def stop(self) -> bool:
        self.stops += 1
        return True


class _Factory:
    def __init__(self) -> None:
        self.callback = None
        self.handle = _Handle()

    async def start_market(self, descriptor, callback, *, on_gap=None):
        assert descriptor.stream_type is StreamType.TRADE
        assert on_gap is None
        self.callback = callback
        return self.handle


def _key() -> MarketStreamKey:
    return MarketStreamKey.build(
        "sample",
        "spot",
        "BTC/USDT",
        MarketChannel.TRADE,
    )


def _event(trade_id: str, *, side: str = "buy") -> MarketEvent:
    return MarketEvent(
        event_type=StreamType.TRADE,
        symbol="BTC/USDT",
        exchange="sample",
        market_type="spot",
        event_time_ms=1_700_000_000_000,
        received_at_ms=1_700_000_000_010,
        source=DataSource.PLUGIN,
        data={
            "trade_id": trade_id,
            "exchange_trade_id": trade_id,
            "price": 60_000.0,
            "quantity": 0.1,
            "trade_time_ms": 1_700_000_000_000,
            "side": side,
            "is_buyer_maker": side == "sell",
        },
    )


def test_trade_tape_engine_deduplicates_without_claiming_exchange_continuity() -> None:
    engine = TradeTapeEngine(raw_ring_size=4, max_streams=1)
    identity = ("sample", "spot", "BTC/USDT")
    assert engine.activate_stream(identity) is True

    first = engine.ingest(_event("opaque-a"))
    duplicate = engine.ingest(_event("opaque-a"))
    second = engine.ingest(_event("opaque-z", side="sell"))

    assert first is not None and first.observation_sequence == 0
    assert duplicate is None
    assert second is not None and second.observation_sequence == 1
    assert second.to_dict()["continuity_mode"] == "observational"
    assert second.to_dict()["is_buyer_maker"] is True
    assert engine.diagnostics()["continuity"] is False


@pytest.mark.anyio
async def test_trade_tape_service_keeps_atomic_recent_to_live_handoff(monkeypatch) -> None:
    factory = _Factory()
    service = TradeTapeService(
        factory,
        engine=TradeTapeEngine(raw_ring_size=8, max_streams=2),
        flush_interval_seconds=1,
        max_streams=2,
    )
    monkeypatch.setattr(
        TradeTapeService,
        "_validate_key",
        staticmethod(lambda key: (key.exchange, key.market_type, key.symbol)),
    )
    key = _key()

    assert await service.ensure_stream(key, consumer_id="browser") is True
    assert factory.callback is not None
    await factory.callback(_event("one"))
    attachment = service.attach(key, recent_limit=10, max_pending_records=8)
    assert [item.trade_id for item in attachment.recent[("sample", "spot", "BTC/USDT")]] == [
        "one",
    ]

    await factory.callback(_event("two", side="sell"))
    service.hub.flush_all()
    batch = await asyncio.wait_for(attachment.subscription.receive(), timeout=1)
    assert batch is not None
    assert [item.trade_id for item in batch.records] == ["two"]
    assert batch.continuity is True

    await attachment.subscription.close()
    assert await service.release_stream(key, consumer_id="browser") is True
    assert factory.handle.stops == 1
    await service.shutdown()


def _allow_test_identity(monkeypatch) -> None:
    monkeypatch.setattr(TradeTapeService, "_validate_key", staticmethod(
        lambda key: (key.exchange, key.market_type, key.symbol),
    ))


@pytest.mark.anyio
async def test_resubscribe_waits_for_old_physical_stop(monkeypatch) -> None:
    _allow_test_identity(monkeypatch)
    entered, resume = asyncio.Event(), asyncio.Event()

    class SlowHandle(_Handle):
        async def stop(self):
            self.stops += 1
            entered.set()
            await resume.wait()
            return True

    factory = _Factory()
    old = factory.handle = SlowHandle()
    service = TradeTapeService(factory)
    await service.ensure_stream(_key(), consumer_id="old")
    release = asyncio.create_task(service.release_stream(_key(), consumer_id="old"))
    await entered.wait()
    factory.handle = _Handle()
    subscribe = asyncio.create_task(service.ensure_stream(_key(), consumer_id="new"))
    await asyncio.sleep(0)
    assert not subscribe.done()
    resume.set()
    assert await release
    assert await subscribe
    assert service.diagnostics()["logical_leases"] == 1
    assert old.stops == 1
    await factory.callback(_event("after-restart"))
    assert service.recent(_key())[0].trade_id == "after-restart"
    await service.shutdown()


@pytest.mark.anyio
async def test_start_failure_does_not_falsely_accept_waiting_subscriber(monkeypatch) -> None:
    _allow_test_identity(monkeypatch)
    entered, resume = asyncio.Event(), asyncio.Event()

    class Factory(_Factory):
        starts = 0

        async def start_market(self, descriptor, callback, **kwargs):
            self.starts += 1
            if self.starts == 1:
                entered.set()
                await resume.wait()
                raise RuntimeError("start failed")
            return await super().start_market(descriptor, callback, **kwargs)

    factory = Factory()
    service = TradeTapeService(factory)
    first = asyncio.create_task(service.ensure_stream(_key(), consumer_id="first"))
    await entered.wait()
    second = asyncio.create_task(service.ensure_stream(_key(), consumer_id="second"))
    await asyncio.sleep(0)
    assert not second.done()
    resume.set()
    with pytest.raises(RuntimeError, match="start failed"):
        await first
    assert await second
    assert factory.starts == 2
    assert service.diagnostics()["logical_leases"] == 1
    await service.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("timeout", [False, True])
async def test_cancelled_or_timed_out_stop_finishes_before_reuse(monkeypatch, timeout) -> None:
    _allow_test_identity(monkeypatch)
    entered, resume = asyncio.Event(), asyncio.Event()

    class Handle(_Handle):
        async def stop(self):
            self.stops += 1
            entered.set()
            await resume.wait()
            return True

    factory = _Factory()
    old = factory.handle = Handle()
    service = TradeTapeService(factory, physical_stop_timeout_seconds=.02 if timeout else 3)
    await service.ensure_stream(_key(), consumer_id="old")
    release = asyncio.create_task(service.release_stream(_key(), consumer_id="old"))
    await entered.wait()
    if not timeout:
        release.cancel()
    with pytest.raises(TimeoutError if timeout else asyncio.CancelledError):
        await release
    assert service.diagnostics()["physical_streams"] == 1
    factory.handle = _Handle()
    subscribe = asyncio.create_task(service.ensure_stream(_key(), consumer_id="new"))
    await asyncio.sleep(0)
    assert not subscribe.done()
    resume.set()
    assert await subscribe
    assert old.stops == 1
    assert service.diagnostics()["logical_leases"] == 1
    await service.shutdown()


@pytest.mark.anyio
async def test_cancelled_start_releases_reservation_and_identity_lock(monkeypatch) -> None:
    _allow_test_identity(monkeypatch)
    entered = asyncio.Event()

    class Factory(_Factory):
        async def start_market(self, descriptor, callback, **kwargs):
            entered.set()
            await asyncio.Event().wait()

    service = TradeTapeService(Factory())
    task = asyncio.create_task(service.ensure_stream(_key(), consumer_id="first"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service.diagnostics()["physical_streams"] == 0
    assert service._identity_locks.active_keys == 0
    service._factory = _Factory()
    assert await service.ensure_stream(_key(), consumer_id="next")
    await service.shutdown()


@pytest.mark.anyio
async def test_shutdown_during_start_stops_returned_handle(monkeypatch) -> None:
    _allow_test_identity(monkeypatch)
    entered, resume = asyncio.Event(), asyncio.Event()

    class Factory(_Factory):
        async def start_market(self, descriptor, callback, **kwargs):
            entered.set()
            await resume.wait()
            return self.handle

    factory = Factory()
    service = TradeTapeService(factory)
    task = asyncio.create_task(service.ensure_stream(_key(), consumer_id="first"))
    await entered.wait()
    shutdown = asyncio.create_task(service.shutdown())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    resume.set()
    with pytest.raises(RuntimeError, match="closed"):
        await task
    await shutdown
    assert factory.handle.stops == 1
    assert service.diagnostics()["physical_streams"] == 0
