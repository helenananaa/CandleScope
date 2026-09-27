from __future__ import annotations

import asyncio
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import replace
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.bounded_executor import ExecutorBusyError
from app.data_engine.bar_aggregator import BarEvent, BarEventType, BarFinality, BarState
from app.data_engine.bar_aggregator.config import BarAggregatorConfig
from app.data_engine.bar_aggregator.publisher import BarAggregatorPublisher
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.data_manager.aggregator_bridge import AggregatorBridge
from app.data_engine.data_manager.bar_delivery import source_recovery_handler
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.data_manager.models import DataEventType, SeriesKey
from app.data_engine.storage import klines_repo
from app.data_engine.series_identity import KlineSeriesIdentity
from tests.test_bar_delivery_journal import payload


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def bridge(storage, bus=None):
    bus = bus or DataEventBus()
    instance = AggregatorBridge(cache=BarCache(), event_bus=bus, storage_provider=lambda: storage,
                                mark_bar_received=lambda key: None, is_started=lambda: True)
    instance.delivery.retry_delay = 0
    return instance, bus


def closed(close=2):
    start = int(time.time() * 1000) // 60_000 * 60_000 - 60_000
    return BarEvent(BarEventType.CLOSED, BarState(symbol="BTCUSDT", interval="1m",
        bucket_start_ms=start, bucket_end_ms=start + 60_000, open=1, high=4, low=1,
        close=close, volume=10, finality=BarFinality.AUTHORITATIVE, close_reason="source_close"))


async def wait_for(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(wait(), 3)


@async_test
@pytest.mark.parametrize("error", [OSError("disk failure"), sqlite3.OperationalError("database is locked"), ExecutorBusyError("storage")])
async def test_failed_canonical_write_stays_durable_and_retries_without_exposing_uncommitted_bar(storage, monkeypatch, error):
    instance, bus = bridge(storage)
    delivered = []
    async def receive(event):
        delivered.append(event)
    bus.subscribe(receive)
    original = storage.bar_delivery._write
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(storage.bar_delivery, "_write", fail)
    event = closed()
    try:
        assert await instance.on_bar_event(event) == "accepted"
        assert storage.bar_delivery.pending()[0]["phase"] == "pending"
        assert not instance._cache.get_latest(SeriesKey("BTCUSDT", "1m"), 1)
        assert not delivered
        assert instance.delivery.snapshot()["degraded"]
        monkeypatch.setattr(storage.bar_delivery, "_write", original)
        await instance.delivery.flush()
        await wait_for(lambda: len(delivered) == 1)
        assert delivered[0].bar.close == 2
        assert delivered[0].event_type == DataEventType.BAR_CLOSED
        assert delivered[0].detail["delivery_id"] == event.delivery_id
        assert not storage.bar_delivery.pending()
        assert not instance.delivery.snapshot()["degraded"]
        # Re-entering the callback with the same source event must preserve
        # both identity and payload timestamp, even in a later clock tick.
        await asyncio.sleep(0.01)
        assert await instance.on_bar_event(event) == "published"
        assert len(delivered) == 1
    finally:
        await bus.close()


@async_test
async def test_ack_failure_retries_publication_without_duplicate_subscriber_delivery(storage, monkeypatch):
    instance, bus = bridge(storage)
    delivered = []
    async def receive(event):
        delivered.append(event)
    bus.subscribe(receive)
    acknowledge = storage.bar_delivery.acknowledge
    monkeypatch.setattr(storage.bar_delivery, "acknowledge", lambda *args: (_ for _ in ()).throw(OSError("ack failed")))
    try:
        await instance.on_bar_event(closed())
        await wait_for(lambda: len(delivered) == 1)
        assert storage.bar_delivery.pending()[0]["phase"] == "committed"
        monkeypatch.setattr(storage.bar_delivery, "acknowledge", acknowledge)
        await instance.delivery.flush()
        await asyncio.sleep(0.02)
        assert len(delivered) == 1
        assert not storage.bar_delivery.pending()
    finally:
        await bus.close()


@async_test
@pytest.mark.parametrize("commit_before_exit", [False, True])
async def test_process_exit_is_recovered_without_another_ingestion_event(storage, commit_before_exit):
    path = str(klines_repo.KLINES_DB_PATH)
    script = "\n".join([
        "import os", "from app.data_engine.storage import klines_repo as repo",
        "repo.KLINES_DB_PATH = " + repr(path),
        "journal = repo.KlinesRepoAdapter().bar_delivery",
        "journal.enqueue('crash-event', " + repr(payload()) + ")",
        "journal.commit('crash-event')" if commit_before_exit else "pass", "os._exit(17)",
    ])
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-B", "-c", script],
                                     cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
    assert result.returncode == 17, result.stderr.decode(errors="replace")
    instance, bus = bridge(storage)
    delivered = []
    async def receive(event):
        delivered.append(event)
    bus.subscribe(receive)
    await instance.delivery.start()
    try:
        await wait_for(lambda: len(delivered) == 1 and instance.delivery.snapshot()["published"] == 1)
        assert delivered[0].detail["delivery_id"] == "crash-event"
        assert delivered[0].bar.close == 2
        assert not storage.bar_delivery.pending()
    finally:
        await instance.delivery.stop()
        await bus.close()


@async_test
async def test_receipt_failure_propagates_and_protected_range_survives_until_verified_repair(storage, monkeypatch):
    instance, bus = bridge(storage)
    event = closed()
    key = SeriesKey("BTCUSDT", "1m")
    await instance.delivery.prepare_series(key)
    enqueue = storage.bar_delivery.enqueue
    monkeypatch.setattr(storage.bar_delivery, "enqueue", lambda *args: (_ for _ in ()).throw(OSError("no receipt")))
    publisher = BarAggregatorPublisher(BarAggregatorConfig())
    publisher.on_bar_event(instance.on_bar_event)
    observed = []
    async def incomplete(watch):
        observed.append(watch)
        return False
    instance.delivery.recover_source = incomplete
    try:
        with pytest.raises(BarDeliveryUnavailable):
            await publisher.emit(event)
        assert instance.delivery.snapshot()["unconfirmed_receipt"]
        monkeypatch.setattr(storage.bar_delivery, "enqueue", enqueue)
        await instance.delivery.recover_once()
        assert observed[0]["from_ms"] <= event.bar.bucket_start_ms < observed[0]["through_ms"]
        assert storage.bar_delivery.recovery_watches(instance.delivery.owner, int(time.time() * 1000))
        assert instance.delivery.snapshot()["degraded"]
        async def complete(watch):
            return True
        instance.delivery.recover_source = complete
        await instance.delivery.recover_once()
        assert not storage.bar_delivery.recovery_watches(instance.delivery.owner, int(time.time() * 1000))
    finally:
        await instance.delivery.stop()
        await bus.close()


@async_test
@pytest.mark.parametrize("failure", ["incomplete", "source_error", "ack_error"])
async def test_failed_recovery_does_not_block_other_series(storage, monkeypatch, failure):
    instance, bus = bridge(storage)
    delivery, journal = instance.delivery, storage.bar_delivery
    journal.watch("previous-owner", {"symbol": "UNAVAILABLEUSDT", "interval": "1m"}, 60_000)
    journal.watch("previous-owner", {"symbol": "ETHUSDT", "interval": "1m"}, 120_000)
    attempts = []
    resolved = False
    finish_recovery = journal.finish_recovery

    async def recover(watch):
        symbol = watch["series"]["symbol"]
        attempts.append(symbol)
        if symbol == "UNAVAILABLEUSDT" and not resolved:
            if failure == "source_error":
                raise OSError("source unavailable")
            return failure == "ack_error"
        return True

    def acknowledge(watch_id):
        if "UNAVAILABLEUSDT" in watch_id and not resolved and failure == "ack_error":
            raise OSError("recovery acknowledgement failed")
        finish_recovery(watch_id)

    delivery.recover_source = recover
    monkeypatch.setattr(journal, "finish_recovery", acknowledge)
    try:
        await delivery.recover_once()
        assert attempts == ["UNAVAILABLEUSDT", "ETHUSDT"]
        remaining = journal.recovery_watches(delivery.owner, int(time.time() * 1000))
        assert [watch["series"]["symbol"] for watch in remaining] == ["UNAVAILABLEUSDT"]
        assert delivery.snapshot()["recovery_pending"] == 1
        assert delivery.snapshot()["degraded"]
        assert "UNAVAILABLEUSDT" in delivery.snapshot()["recovery_error"]

        resolved = True
        await delivery.recover_once()
        assert attempts == ["UNAVAILABLEUSDT", "ETHUSDT", "UNAVAILABLEUSDT"]
        assert not journal.recovery_watches(delivery.owner, int(time.time() * 1000))
        assert delivery.snapshot()["recovery_pending"] == 0
        assert delivery.snapshot()["recovery_error"] is None
    finally:
        await delivery.stop()
        await bus.close()


@async_test
@pytest.mark.parametrize("same_start", [False, True])
async def test_recovery_advances_past_a_full_failed_batch_and_retries_it(storage, same_start):
    instance, bus = bridge(storage)
    delivery, journal = instance.delivery, storage.bar_delivery
    blocked = [f"A{index:03}USDT" for index in range(32)]
    healthy = ["Z000USDT", "Z001USDT"]
    for index, symbol in enumerate(blocked + healthy):
        journal.watch("previous-owner", {"symbol": symbol, "interval": "1m"},
                      60_000 if same_start else (index + 1) * 60_000)
    # Active streams owned by this delivery instance are not recovery work.
    journal.watch(delivery.owner, {"symbol": "ACTIVEUSDT", "interval": "1m"}, 0)
    attempts = []
    resolved = False

    async def recover(watch):
        symbol = watch["series"]["symbol"]
        attempts.append(symbol)
        return resolved or symbol in healthy

    delivery.recover_source = recover
    try:
        await delivery.recover_once()
        assert attempts == blocked
        assert delivery.snapshot()["recovery_pending"] == 34
        assert delivery.snapshot()["degraded"]
        await delivery.recover_once()
        assert attempts == blocked + healthy
        assert delivery.snapshot()["recovery_pending"] == 32
        assert delivery.snapshot()["degraded"]
        assert delivery.snapshot()["recovery_error"]

        resolved = True
        await delivery.recover_once()
        assert attempts == blocked + healthy + blocked
        assert not journal.recovery_watches(delivery.owner, int(time.time() * 1000))
        assert delivery.snapshot()["recovery_pending"] == 0
        assert delivery.snapshot()["recovery_error"] is None
        assert not delivery.snapshot()["degraded"]
    finally:
        await delivery.stop()
        await bus.close()


@async_test
async def test_recovery_cancellation_preserves_unfinished_watches(storage):
    instance, bus = bridge(storage)
    delivery, journal = instance.delivery, storage.bar_delivery
    symbols = ["BTCUSDT", "ETHUSDT"]
    for index, symbol in enumerate(symbols):
        journal.watch("previous-owner", {"symbol": symbol, "interval": "1m"}, (index + 1) * 60_000)
    attempts = []
    cancel = True

    async def recover(watch):
        attempts.append(watch["series"]["symbol"])
        if cancel:
            raise asyncio.CancelledError
        return True

    delivery.recover_source = recover
    try:
        with pytest.raises(asyncio.CancelledError):
            await delivery.recover_once()
        assert attempts == ["BTCUSDT"]
        assert len(journal.recovery_watches(delivery.owner, int(time.time() * 1000))) == 2
        cancel = False
        await delivery.recover_once()
        assert attempts == ["BTCUSDT"] + symbols
        assert not journal.recovery_watches(delivery.owner, int(time.time() * 1000))
    finally:
        await delivery.stop()
        await bus.close()


@async_test
async def test_source_recovery_preserves_identity_and_requires_verified_completion():
    requests = []
    verified = False
    class Coordinator:
        async def request_and_wait(self, request):
            requests.append(request)
            return SimpleNamespace(status="completed", verified_contiguous=verified, error=None)
    handler = source_recovery_handler(Coordinator())
    watch = {"watch_id": "interrupted-stream", "from_ms": 60_000, "through_ms": 180_001,
             "series": {"symbol": "BTCUSDT", "interval": "1m", "exchange": "binance", "market_type": "futures",
                        "provider_id": "custom", "venue": "binance"}}
    assert not await handler(watch)
    verified = True
    assert await handler(watch)
    assert requests[0].start_ms == 60_000 and requests[0].end_ms == 120_000
    assert requests[0].metadata["requires_trusted_finality"] is True
    assert requests[0].metadata["series_identity"]["provider_id"] == "custom"
    assert requests[0].market_type == "futures"


@async_test
async def test_recovery_never_overwrites_newer_authoritative_canonical_bar(storage):
    journal = storage.bar_delivery
    journal.enqueue("old-event", payload())
    journal.commit("old-event")
    row = {**payload()["storage_row"], "close": 4}
    klines_repo.upsert_klines("BTCUSDT", "1m", [row], source="repair_binance_rest_verified")
    instance, bus = bridge(storage)
    delivered = []
    async def receive(event):
        delivered.append(event)
    bus.subscribe(receive)
    try:
        await instance.delivery.flush()
        await wait_for(lambda: len(delivered) == 1)
        assert delivered[0].bar.close == 4
        assert delivered[0].detail["canonical_reconciled"] is True
        assert instance._cache.get_latest(SeriesKey("BTCUSDT", "1m"), 1)[0].close == 4
    finally:
        await bus.close()


@async_test
async def test_shutdown_drains_inflight_transaction_even_if_shutdown_is_cancelled(storage, monkeypatch):
    instance, bus = bridge(storage)
    entered, release = threading.Event(), threading.Event()
    write = storage.bar_delivery._write
    def gated_write(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test did not release physical transaction"
        return write(*args, **kwargs)
    monkeypatch.setattr(storage.bar_delivery, "_write", gated_write)
    event = closed()
    submission = asyncio.create_task(instance.on_bar_event(event))
    stopping = None
    try:
        await wait_for(entered.is_set)
        stopping = asyncio.create_task(instance.delivery.stop())
        await asyncio.sleep(0.02)
        stopping.cancel()
        await asyncio.sleep(0)
        stopping.cancel()
        await asyncio.sleep(0.02)
        assert not stopping.done() and not submission.done()
        assert instance.delivery.snapshot()["active_submissions"] == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        with pytest.raises(asyncio.CancelledError):
            await submission
        assert instance.delivery.snapshot()["active_submissions"] == 0
        assert storage.bar_delivery.pending()[0]["phase"] == "committed"
        assert not instance._cache.get_latest(SeriesKey("BTCUSDT", "1m"), 1)
        recovered, _ = bridge(storage, bus)
        await recovered.delivery.flush()
        assert recovered._cache.get_latest(SeriesKey("BTCUSDT", "1m"), 1)[0].close == 2
        assert not storage.bar_delivery.pending()
    finally:
        release.set()
        await asyncio.gather(submission, *([stopping] if stopping else []), return_exceptions=True)
        await bus.close()


@async_test
async def test_receipt_admission_is_bounded_and_snapshots_mutable_bar(storage, monkeypatch):
    instance, bus = bridge(storage)
    instance.delivery.max_submissions = 1
    entered, release = threading.Event(), threading.Event()
    enqueue = storage.bar_delivery.enqueue
    def gated_enqueue(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test did not release receipt"
        return enqueue(*args, **kwargs)
    monkeypatch.setattr(storage.bar_delivery, "enqueue", gated_enqueue)
    event = closed()
    submission = asyncio.create_task(instance.on_bar_event(event))
    try:
        await wait_for(entered.is_set)
        event.bar.close = 99
        with pytest.raises(BarDeliveryUnavailable, match="capacity"):
            await instance.on_bar_event(closed(3))
        assert instance.delivery.snapshot()["active_submissions"] == 1
        assert instance.delivery.snapshot()["admission_rejected"] == 1
        assert instance.delivery.snapshot()["unconfirmed_receipt"]
        release.set()
        await submission
        assert klines_repo.query_klines("BTCUSDT", "1m")[0]["close"] == 2
    finally:
        release.set()
        await asyncio.gather(submission, return_exceptions=True)
        await instance.delivery.stop()
        await bus.close()


@async_test
async def test_stream_does_not_start_without_durable_recovery_watch(storage, monkeypatch):
    from unittest.mock import AsyncMock
    from app.data_engine.data_manager.coordinator import StreamCoordinator
    from app.data_engine.data_manager.models import StreamStatus
    instance, bus = bridge(storage)
    monkeypatch.setattr(storage.bar_delivery, "watch", lambda *args: (_ for _ in ()).throw(OSError("watch unavailable")))
    factory = SimpleNamespace(start=AsyncMock())
    coordinator = StreamCoordinator()
    coordinator.set_ingestion_factory(factory)
    coordinator.set_bar_aggregator(object())
    coordinator.set_before_stream_start(instance.delivery.prepare_series)
    try:
        info = await coordinator.ensure_stream("BTCUSDT", "1m")
        assert info.status == StreamStatus.ERROR
        assert "watch unavailable" in info.error
        factory.start.assert_not_awaited()
    finally:
        await coordinator.shutdown()
        await instance.delivery.stop()
        await bus.close()


@async_test
async def test_ingestion_propagates_required_delivery_failure_before_observer_queues():
    from app.data_engine.ingestion.config import IngestionConfig
    from app.data_engine.ingestion.delivery import DeliveryLayer
    from tests.test_ingestion_delivery import _descriptor, _market_event
    delivery = DeliveryLayer(IngestionConfig(), _descriptor())
    subscriber = delivery.create_queue_subscriber()
    async def required(event):
        raise BarDeliveryUnavailable("no durable receipt")
    delivery.on_market_event(required)
    try:
        with pytest.raises(BarDeliveryUnavailable):
            await delivery.deliver_event(_market_event())
        assert subscriber.queue_size == 0
    finally:
        await subscriber.close()


@async_test
async def test_historical_amendment_extends_recovery_watch_before_receipt(storage, monkeypatch):
    instance, bus = bridge(storage)
    key = SeriesKey("BTCUSDT", "1m")
    await instance.delivery.prepare_series(key)
    seen = []
    def fail_receipt(*args):
        watches = storage.bar_delivery.recovery_watches("test-next-owner", 180_000)
        seen.extend(watches)
        raise OSError("historical receipt unavailable")
    monkeypatch.setattr(storage.bar_delivery, "enqueue", fail_receipt)
    try:
        with pytest.raises(BarDeliveryUnavailable):
            await instance.delivery.submit("historical-amend", payload(event_type="bar.amended"), key)
        assert seen and seen[0]["from_ms"] == 60_000
    finally:
        await instance.delivery.stop()
        await bus.close()


@async_test
async def test_close_and_amend_preserve_order_metrics_and_semantic_identity(storage):
    instance, bus = bridge(storage)
    delivered = []
    async def receive(event):
        delivered.append(event)
    bus.subscribe(receive)
    identity = KlineSeriesIdentity.for_exchange("binance", provider_id="custom-provider")
    first = closed()
    first.bar = replace(first.bar, series_identity=identity, quote_volume=123.4567890123,
                        trades=7, taker_buy_base=2.5, taker_buy_quote=30.123456789,
                        enhanced_fields=frozenset({"quote_volume", "trades", "taker_buy_base", "taker_buy_quote"}))
    amended = BarEvent(BarEventType.AMENDED, replace(first.bar, close=3), previous_bar=replace(first.bar))
    other = closed(4)
    try:
        await instance.on_bar_event(first)
        await instance.on_bar_event(amended)
        await instance.on_bar_event(other)
        await wait_for(lambda: len(delivered) == 3)
        assert [event.event_type for event in delivered] == [
            DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED, DataEventType.BAR_CLOSED]
        sequences = [event.detail["delivery_sequence"] for event in delivered]
        assert sequences == sorted(set(sequences))
        assert delivered[1].previous_bar.close == 2
        assert delivered[1].bar.quote_volume == 123.4567890123
        assert delivered[1].bar.trades == 7
        assert delivered[1].bar.taker_buy_quote == 30.123456789
        assert delivered[1].key.identity == identity
        assert klines_repo.query_klines("BTCUSDT", "1m", series_identity=identity)[0]["close"] == 3
        assert klines_repo.query_klines("BTCUSDT", "1m")[0]["close"] == 4
    finally:
        await instance.delivery.stop()
        await bus.close()
