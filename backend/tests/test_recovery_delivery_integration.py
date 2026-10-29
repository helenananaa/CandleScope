"""Issue #112 evidence: real reducers/writers, controlled source transport.

Only the inline Recovery wiring is bypassed in the comparison lane. No global
CCXT switch is changed. All durable files live under pytest's temporary root.
Shutdown coverage includes Recovery's stop-time flush, bounded queue pressure,
and both successful and exhausted downstream repair before durable closure.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.data_engine.ingestion import StreamPipeline
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamType
from app.data_engine.market_data.trade_flow import TradeFlowEngine
from app.data_engine.market_data.trade_flow_service import TradeFlowService
from app.data_engine.storage.raw_trade_archive import (
    ParquetRawAggTradeArchive, RawAggTradeArchiveWriter,
)
from app.data_engine.storage.trade_flow_store import SQLiteTradeFlowRollupStore
from app.data_engine.storage.trade_flow_writer import TradeFlowRollupWriter
from tests.test_trade_flow_service import _event, _key, IDENTITY


def _raw(sequence: int, *, source=DataSource.WEBSOCKET) -> RawMessage:
    event = _event(sequence)
    data = event.data
    return RawMessage(
        payload={
            "e": "aggTrade", "E": event.event_time_ms,
            "a": sequence, "p": str(data["price"]), "q": str(data["quantity"]),
            "f": data["first_trade_id"], "l": data["last_trade_id"],
            "T": data["trade_time_ms"], "m": data["is_buyer_maker"],
        },
        source=source, stream_type=StreamType.AGG_TRADE,
        received_at_ms=event.received_at_ms,
    )


async def _until(predicate) -> None:
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


class _Source:
    def __init__(self, *, failures=0, unavailable=False):
        self.failures = failures
        self.unavailable = unavailable
        self.gate = asyncio.Event()
        self.gate.set()
        self.attempted = asyncio.Event()
        self.requests = []

    async def http_fetch(self, request):
        self.requests.append(request)
        self.attempted.set()
        await self.gate.wait()
        if self.unavailable or self.failures:
            self.failures = max(0, self.failures - 1)
            raise TimeoutError("injected REST outage")
        return [_raw(i, source=DataSource.HTTP)
                for i in range(request.from_id, request.from_id + request.limit)]


class _Factory:
    def __init__(self, *, bypass=False, source=None, **overrides):
        self.bypass = bypass
        self.source = source or _Source()
        self.config = IngestionConfig(
            proxy_mode="none", http_proxy=None, proxy_routes=[],
            ccxt_unified_stream_enabled=True,
            ccxt_recovery_timeout_seconds=0.1,
            ccxt_recovery_retry_initial_seconds=0.001,
            ccxt_recovery_retry_max_seconds=0.002,
            ccxt_recovery_retry_deadline_seconds=0.02,
            **overrides,
        )
        self.pipeline = None
        self.downstream_fetches = []

    async def start_market(self, descriptor, callback, *, on_gap=None):
        self.pipeline = StreamPipeline(self.config, self.source, descriptor)
        pipeline = self.pipeline
        if self.bypass:
            pipeline.continuity.on_event(pipeline.delivery.deliver_event)
            pipeline.continuity.on_gap(pipeline.delivery.deliver_gap)
        pipeline.delivery.on_market_event(callback)
        if on_gap is not None:
            pipeline.delivery.on_gap(on_gap)
        # Physical input is controlled by emit(); use the real pipeline stop.
        return pipeline

    async def emit(self, sequence):
        await self.pipeline.normalize.ingest(_raw(sequence))

    async def fetch_market(self, descriptor, **kwargs):
        self.downstream_fetches.append(kwargs)
        if self.source.unavailable:
            raise TimeoutError("injected REST outage")
        return [_event(i, source=DataSource.HTTP_BACKFILL)
                for i in range(kwargs["from_id"], kwargs["from_id"] + kwargs["limit"])]


def _service(factory, root, *, initial_complete=True, command_queue_size=8192):
    root.mkdir(parents=True, exist_ok=True)
    archive = ParquetRawAggTradeArchive(root / "archive", max_rows_per_file=2)
    store = SQLiteTradeFlowRollupStore(root / "rollups.sqlite")
    return TradeFlowService(
        factory, engine=TradeFlowEngine(initial_bucket_complete=initial_complete),
        rollup_writer=TradeFlowRollupWriter(store, flush_interval_seconds=0.001),
        raw_archive=archive,
        archive_writer=RawAggTradeArchiveWriter(archive, flush_interval_seconds=0),
        flush_interval_seconds=60, physical_idle_grace_seconds=0,
        max_repair_attempts=2, repair_retry_backoff_seconds=0.001,
        command_queue_size=command_queue_size,
    )


_REOPEN = """
import asyncio, dataclasses, json, sys
from pathlib import Path
from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive
from app.data_engine.storage.trade_flow_store import SQLiteTradeFlowRollupStore
root=Path(sys.argv[1]); last=int(sys.argv[2])
identity=dict(exchange='binance',market_type='futures',symbol='BTCUSDT')
archive=ParquetRawAggTradeArchive(root/'archive')
rows=archive.scan_range(**identity)
coverage=archive.coverage(**identity,expected_start_agg_trade_id=1,expected_end_agg_trade_id=last)
rollups=asyncio.run(SQLiteTradeFlowRollupStore(root/'rollups.sqlite').query_rollups(**identity))
print(json.dumps(dict(rows=rows,coverage=dataclasses.asdict(coverage),rollups=rollups)))
"""


def _reopen(root, last):
    # A fresh interpreter cannot reuse engine/ring/writer state from this test.
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run(
        [sys.executable, "-c", _REOPEN, str(root), str(last)],
        env=env, capture_output=True, text=True, check=True, timeout=30,
    )
    data = json.loads(result.stdout)
    (root / "reopened.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _trade_values(rows):
    # Source/timestamps/revisions legitimately differ; compare economic records.
    fields = ("agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
              "trade_time_ms", "is_buyer_maker")
    return [{key: row[key] for key in fields} for row in rows]


@pytest.mark.anyio
async def test_inline_and_downstream_repair_preserve_archive_after_process_reopen(tmp_path):
    results = []
    for bypass in (False, True):
        root = tmp_path / ("downstream" if bypass else "inline")
        factory = _Factory(bypass=bypass)
        service = _service(factory, root)
        await service.ensure_stream(_key(), consumer_id="verification")
        attachment = service.attach(_key(), recent_limit=0)
        try:
            await factory.emit(1)
            await factory.emit(4)
            await _until(lambda: len(service.engine.raw_snapshot(IDENTITY)) == 4)
            await service._command_queue.join()
            service.hub.flush_all()
            batches = []
            while attachment.subscription.pending_batch_count:
                batches.append(await attachment.subscription.receive())
            delivered = [trade.agg_trade_id for batch in batches for trade in batch.records]
            resync = any(batch.resync_required for batch in batches)
            assert delivered == ([1, 4] if bypass else [1, 2, 3, 4])
            assert resync is bypass
            assert len(factory.downstream_fetches) == int(bypass)
        finally:
            await attachment.subscription.close()
            await service.shutdown()
        recovered = _reopen(root, 4)
        assert recovered["coverage"]["complete"] is True
        assert [row["agg_trade_id"] for row in recovered["rows"]] == [1, 2, 3, 4]
        assert recovered["rollups"][0]["agg_trade_count"] == 4
        assert recovered["rollups"][0]["base_volume_delta"] == 4.0
        assert recovered["rollups"][0]["is_complete"] == 1
        (root / "delivery.json").write_text(json.dumps(dict(
            hub_ids=delivered, resync_required=resync,
            inline_requests=len(factory.source.requests),
            downstream_requests=len(factory.downstream_fetches),
        )), encoding="utf-8")
        results.append(recovered)
    assert _trade_values(results[0]["rows"]) == _trade_values(results[1]["rows"])


@pytest.mark.anyio
async def test_transient_inline_failure_repairs_before_archive_and_without_resync(tmp_path):
    factory = _Factory(source=_Source(failures=1))
    service = _service(factory, tmp_path)
    await service.ensure_stream(_key(), consumer_id="verification")
    try:
        await factory.emit(1)
        await factory.emit(4)
        await _until(lambda: len(service.engine.raw_snapshot(IDENTITY)) == 4)
        assert len(factory.source.requests) == 2
        assert factory.downstream_fetches == []
    finally:
        await service.shutdown()
    assert _reopen(tmp_path, 4)["coverage"]["complete"] is True


@pytest.mark.anyio
async def test_exhausted_repair_retains_gap_after_process_reopen(tmp_path):
    factory = _Factory(source=_Source(unavailable=True))
    service = _service(factory, tmp_path)
    await service.ensure_stream(_key(), consumer_id="verification")
    try:
        await factory.emit(1)
        await factory.emit(4)
        await _until(lambda: service.diagnostics()["repairs_exhausted"] == 1)
        assert [trade.agg_trade_id for trade in service.engine.raw_snapshot(IDENTITY)] == [1, 4]
    finally:
        await service.shutdown()
    reopened = _reopen(tmp_path, 4)
    assert reopened["coverage"]["complete"] is False
    assert reopened["coverage"]["gaps"]
    assert reopened["rollups"][0]["is_complete"] == 0


@pytest.mark.anyio
async def test_large_reconnect_replay_does_not_change_durable_trade_totals(tmp_path):
    factory = _Factory(continuity_buffer_size=3)
    service = _service(factory, tmp_path)
    await service.ensure_stream(_key(), consumer_id="verification")
    try:
        for sequence in (1, 10):
            await factory.emit(sequence)
        await _until(lambda: len(service.engine.raw_snapshot(IDENTITY)) == 10)
        for sequence in range(1, 11):
            await factory.emit(sequence)
        await service._command_queue.join()
    finally:
        await service.shutdown()
    reopened = _reopen(tmp_path, 10)
    assert [row["agg_trade_id"] for row in reopened["rows"]] == list(range(1, 11))
    assert reopened["rollups"][0]["agg_trade_count"] == 10
    assert reopened["coverage"]["complete"] is True


@pytest.mark.anyio
async def test_buffer_overflow_hands_off_to_downstream_repair(tmp_path):
    source = _Source()
    source.gate.clear()
    factory = _Factory(source=source, ccxt_recovery_buffer_max_events=1)
    service = _service(factory, tmp_path)
    await service.ensure_stream(_key(), consumer_id="verification")
    try:
        await factory.emit(1)
        await factory.emit(4)
        await source.attempted.wait()
        await factory.emit(5)
        await _until(lambda: len(service.engine.raw_snapshot(IDENTITY)) == 5)
        # Engine admission precedes the repair worker's completion accounting.
        await _until(lambda: service.diagnostics()["repairs_succeeded"] == 1)
        assert factory.pipeline.recovery.snapshot()["terminal_failures"] == 1
        assert service.diagnostics()["repairs_succeeded"] == 1
    finally:
        await service.shutdown()
    reopened = _reopen(tmp_path, 5)
    assert reopened["coverage"]["complete"] is True
    assert reopened["rollups"][0]["agg_trade_count"] == 5


@pytest.mark.anyio
async def test_complete_observed_id_range_does_not_claim_initial_minute_complete(tmp_path):
    factory = _Factory()
    service = _service(factory, tmp_path, initial_complete=False)
    await service.ensure_stream(_key(), consumer_id="verification")
    try:
        await factory.emit(1)
        await factory.emit(4)
        await _until(lambda: len(service.engine.raw_snapshot(IDENTITY)) == 4)
    finally:
        await service.shutdown()
    reopened = _reopen(tmp_path, 4)
    assert reopened["coverage"]["complete"] is True  # exactly the requested IDs only
    assert reopened["rollups"][0]["is_complete"] == 0  # unknown minute prefix


@pytest.mark.anyio
@pytest.mark.parametrize("rest_unavailable", [False, True])
async def test_shutdown_preserves_tail_already_buffered_by_ingestion(tmp_path, rest_unavailable):
    source = _Source(unavailable=rest_unavailable)
    source.gate.clear()
    factory = _Factory(source=source)
    service = _service(factory, tmp_path, command_queue_size=1)
    await service.ensure_stream(_key(), consumer_id="verification")
    await factory.emit(1)
    await _until(lambda: service.diagnostics()["commands_processed"] == 1)
    await factory.emit(4)
    await asyncio.wait_for(source.attempted.wait(), timeout=3)
    await factory.emit(5)
    await factory.emit(6)
    assert factory.pipeline.recovery.snapshot()["buffered_events"] == 3
    await asyncio.wait_for(service.shutdown(), timeout=3)
    reopened = _reopen(tmp_path, 6)
    diagnostics = service.diagnostics()
    (tmp_path / "stop.json").write_text(json.dumps(dict(
        events_after_stop=diagnostics["events_after_stop"],
        inline=factory.pipeline.recovery.snapshot(),
        downstream_requests=len(factory.downstream_fetches),
    ), indent=2), encoding="utf-8")
    expected_ids = [1, 4, 5, 6] if rest_unavailable else list(range(1, 7))
    assert [row["agg_trade_id"] for row in reopened["rows"]] == expected_ids
    assert reopened["coverage"]["complete"] is (not rest_unavailable)
    assert reopened["rollups"][0]["agg_trade_count"] == len(expected_ids)
    assert bool(reopened["rollups"][0]["is_complete"]) is (not rest_unavailable)
    assert diagnostics["events_after_stop"] == 0
    assert diagnostics["state"] == "closed"
