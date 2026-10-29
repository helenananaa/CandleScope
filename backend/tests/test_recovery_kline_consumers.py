"""Compare K-line consumer semantics with real SQLite and durable bar delivery.

The controlled history input enters Reconciler; storage readback then uses the
same DataManager completion hook as BackfillCoordinator. The scheduler/network
and external alert delivery are deliberately excluded from this fixture.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.alerts.facade import AlertFacade
from app.alerts.runtime import AlertRuntimeEngine
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.models import BackfillPlan, BackfillTask, FetchResult, FetchedBar
from app.data_engine.backfill.reconciler import Reconciler
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import BarData, DataEventType, SeriesKey
from app.data_engine.ingestion import StreamPipeline
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import RawMessage, DataSource, StreamDescriptor, StreamType
from app.data_engine.storage import klines_repo
from tests.test_alerts_runtime import _rule_payload
from tests.test_recovery_delivery_integration import _until

T = 1_700_000_040_000
IDENTITY = dict(symbol="BTCUSDT", interval="1m", exchange="binance", market_type="futures")


def _history_row(timestamp, price):
    return [timestamp, str(price), str(price), str(price), str(price), "10",
            timestamp + 59_999, "20", 4, "6", "12", "0"]


class _Factory:
    def __init__(self, bypass=False):
        self.bypass = bypass
        self.requests = []
        self.pipeline = None

    async def http_fetch(self, request):
        self.requests.append(request)
        return [RawMessage(payload=_history_row(t, 150), source=DataSource.HTTP,
                           stream_type=StreamType.KLINE, received_at_ms=T + 180_000)
                for t in range(request.start_ms, request.end_ms + 1, 60_000)]

    async def start(self, symbol, interval, on_market_event, exchange="binance",
                    market_type="spot", on_gap=None):
        config = IngestionConfig(proxy_mode="none", http_proxy=None, proxy_routes=[],
                                 ccxt_unified_stream_enabled=True)
        descriptor = StreamDescriptor(symbol, StreamType.KLINE, interval=interval,
                                      exchange=exchange, market_type=market_type)
        self.pipeline = StreamPipeline(config, self, descriptor)
        p = self.pipeline
        if self.bypass:
            p.continuity.on_event(p.delivery.deliver_event)
            p.continuity.on_gap(p.delivery.deliver_gap)
        p.delivery.on_market_event(on_market_event)
        p.delivery.on_gap(on_gap)
        return p

    async def emit(self, timestamp, price, *, closed=True):
        payload = dict(e="kline", E=timestamp + 59_999, k=dict(
            t=timestamp, T=timestamp + 59_999, i="1m", o=str(price), h=str(price),
            l=str(price), c=str(price), v="10", q="20", n=4, V="6", Q="12", x=closed,
        ))
        await self.pipeline.normalize.ingest(RawMessage(
            payload=payload, source=DataSource.WEBSOCKET, stream_type=StreamType.KLINE,
            received_at_ms=timestamp + 59_999,
        ))


async def _history_repair(dm, store, timestamp, price):
    task = BackfillTask(start_ms=timestamp, end_ms=timestamp, **IDENTITY)
    bar = FetchedBar(open_time=timestamp, close_time=timestamp + 59_999,
                     open=price, high=price, low=price, close=price, volume=10, **IDENTITY)
    reconciler = Reconciler(BackfillConfig(), klines_repo.AsyncKlinesRepoAdapter())
    result = await reconciler.reconcile([FetchResult(task=task, bars=[bar])], BackfillPlan(gaps=[]))
    assert result.bars_written == 1 and not result.errors
    rows = store.query_bars(start_ms=timestamp, end_ms=timestamp, **IDENTITY)
    assert len(rows) == 1
    await dm.on_bars_backfilled(
        bars=[BarData.from_storage_row(row, exchange="binance", market_type="futures") for row in rows],
        event_detail={"reason": "tail_gap", "requester": "ingestion_gap"}, **IDENTITY,
    )


_REOPEN = """
import json,sys
from pathlib import Path
from app.data_engine.storage import klines_repo
klines_repo.KLINES_DB_PATH=Path(sys.argv[1])
store=klines_repo.KlinesRepoAdapter()
print(json.dumps(store.query_bars(symbol='BTCUSDT',interval='1m',exchange='binance',market_type='futures',order='ASC')))
"""


def _reopen(root):
    result = subprocess.run(
        [sys.executable, "-c", _REOPEN, str(root / "bars.sqlite")],
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])),
        check=True, capture_output=True, text=True, timeout=30,
    )
    rows = json.loads(result.stdout)
    (root / "reopened.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


async def _manager(root, monkeypatch, *, bypass=False):
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", root / "bars.sqlite")
    klines_repo.init_klines_storage()
    store = klines_repo.KlinesRepoAdapter()
    dm = DataManager()
    dm.set_storage(store)
    # Activate publication without runtime prewarm, timers, servers or real feeds.
    dm._started = True
    factory = _Factory(bypass)
    dm.set_ingestion_factory(factory)
    gaps, events, recoveries = [], [], []
    dm.set_backfill_trigger(lambda *args, **kwargs: gaps.append((args, kwargs)))
    async def observe(event):
        events.append(dict(type=event.event_type.value, time=event.bar.time if event.bar else None,
                           close=event.bar.close if event.bar else None))
    async def recover(error):
        recoveries.append(error.to_dict())
    dm.subscribe(callback=observe, on_recovery=recover, continuity="gap_aware", **IDENTITY)
    await dm.ensure_stream(**IDENTITY)
    return dm, store, factory, gaps, events, recoveries


async def _close(dm, factory):
    await factory.pipeline.stop()
    await dm.aggregator_bridge.delivery.flush()
    await dm.aggregator_bridge.delivery.stop()
    await dm.event_bus.close()


@pytest.mark.anyio
async def test_same_final_ohlcv_does_not_imply_same_alert_history(tmp_path, monkeypatch):
    results = []
    for bypass in (False, True):
        root = tmp_path / ("downstream" if bypass else "inline")
        dm, store, factory, gaps, events, recoveries = await _manager(root, monkeypatch, bypass=bypass)
        facade = AlertFacade(store_path=root / "alerts.json")
        rule = facade.save_rule(_rule_payload(target={
            "exchange": "binance", "marketType": "futures", "symbol": "BTCUSDT", "interval": "1m",
        }))
        alerts = AlertRuntimeEngine(facade=facade, data_manager=dm)
        triggers = []
        async def capture(payload, **kwargs):
            triggers.append(payload)
            return payload
        monkeypatch.setattr(facade, "emit_triggered", capture)
        async def evaluate(event):
            await alerts.evaluate_event(rule["id"], event)
        dm.subscribe(callback=evaluate, event_types={DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED},
                     continuity="gap_aware", **IDENTITY)
        try:
            await factory.emit(T, 99)
            await factory.emit(T + 120_000, 99)
            if not bypass:
                await factory.pipeline.recovery.wait_idle()
            await _until(lambda: sum(e["type"] == "bar.closed" for e in events) == (2 if bypass else 3))
            if bypass:
                assert any(kwargs.get("requester") == "ingestion_gap" for _, kwargs in gaps)
                await _history_repair(dm, store, T + 60_000, 150)
                await _until(lambda: any(e["type"] == "backfill.completed" for e in events))
        finally:
            await _close(dm, factory)
        cache = dm.cache.get_latest(SeriesKey(**IDENTITY), 10)
        rows = _reopen(root)
        assert [bar.close for bar in cache] == [99, 150, 99]
        assert [row["close"] for row in rows] == [99, 150, 99]
        assert len(triggers) == (0 if bypass else 1)
        assert recoveries == []
        (root / "consumers.json").write_text(json.dumps(dict(
            events=events, alert_crossings=len(triggers), recovery_callbacks=recoveries,
            source_gap_requests=[kwargs for _, kwargs in gaps],
        ), indent=2), encoding="utf-8")
        results.append([{k: row[k] for k in ("open_time", "open", "high", "low", "close", "volume")}
                        for row in rows])
    assert results[0] == results[1]


@pytest.mark.anyio
async def test_missing_close_is_repaired_before_late_replay(tmp_path, monkeypatch):
    dm, store, factory, gaps, events, recoveries = await _manager(tmp_path, monkeypatch)
    try:
        await factory.emit(T, 99, closed=False)
        await factory.emit(T + 60_000, 101)
        await factory.pipeline.recovery.wait_idle()
        await _until(lambda: sum(e["type"] == "bar.closed" for e in events) == 2)
        assert len(factory.requests) == 1
        assert factory.requests[0].start_ms == T
        assert [(row["open_time"], row["close"]) for row in store.query_bars(order="ASC", **IDENTITY)] == [(T, 150), (T + 60_000, 101)]
        await factory.emit(T, 150)  # late replay must not deliver the recovered close twice
    finally:
        await _close(dm, factory)
    rows = _reopen(tmp_path)
    assert [(row["open_time"], row["close"]) for row in rows] == [(T, 150), (T + 60_000, 101)]
    assert [e["time"] for e in events if e["type"] == "bar.closed"] == [T // 1000, (T + 60_000) // 1000]
    assert recoveries == []
    (tmp_path / "consumers.json").write_text(json.dumps(dict(events=events, recovery_callbacks=recoveries),
                                                       indent=2), encoding="utf-8")
