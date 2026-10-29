"""Public Binance REST/WS acceptance through the real backend pipeline.

Run with a NEW, isolated CANDLE_DATA_DIR. No API keys or desktop app are used.
The exchange need not revise a closed candle during this bounded observation;
controlled correction/failure regressions are intentionally separate evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
from app.data_engine.data_manager.aggregator_bridge import AggregatorBridge
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.factory import ExchangeIngestionFactory
from app.data_engine.ingestion.models import (
    DataSource,
    StreamDescriptor,
    StreamType,
    TransportRequest,
)
from app.data_engine.storage import klines_repo, kline_sources
from app.exchanges import bootstrap_default_adapters, get_exchange_registry
from app.exchanges.ccxt_ext.fork_kline import LOCK_PATH


async def validate(output: Path, timeout: float) -> dict:
    if not os.environ.get("CANDLE_DATA_DIR"):
        raise RuntimeError("CANDLE_DATA_DIR must identify a new isolated directory")
    if klines_repo.KLINES_DB_PATH.exists():
        raise RuntimeError(
            "Acceptance requires a new database; existing data is preserved"
        )
    output.mkdir(parents=True, exist_ok=True)
    klines_repo.init_klines_storage()
    bootstrap_default_adapters()
    plugin = get_exchange_registry().get_plugin("binance")
    config = IngestionConfig(ccxt_fork_kline_enabled=True)
    descriptor = StreamDescriptor(
        "BTCUSDT", StreamType.KLINE, interval="1m", market_type="futures"
    )
    factory = ExchangeIngestionFactory(config)
    aggregator = BarAggregator(BarAggregatorConfig())
    aggregator.add_target("BTCUSDT", "1m", market_type="futures")
    cache, bus = BarCache(), DataEventBus()
    bridge = AggregatorBridge(
        cache=cache,
        event_bus=bus,
        storage_provider=lambda: klines_repo.KlinesRepoAdapter(),
        mark_bar_received=lambda key: None,
        is_started=lambda: True,
    )
    aggregator.publisher.on_bar_event(bridge.on_bar_event)
    events, frames, health = [], [], []
    closed = asyncio.Event()
    reconnected = asyncio.Event()
    reconnect_after = None
    forming = set()
    chosen = {}

    async def receive(event):
        await aggregator.on_market_event(event)
        if event.source == DataSource.WEBSOCKET:
            envelope = event.data["source_candle"]
            frames.append(envelope)
            if reconnect_after is not None and len(frames) >= reconnect_after + 2:
                reconnected.set()
            opened = event.data["open_time"]
            if not event.data["is_closed"]:
                forming.add(opened)
            elif opened in forming and not closed.is_set():
                chosen.update(open_time=opened, ws=envelope)
                closed.set()

    async def observe(event):
        events.append(event.to_dict())

    async def observe_health(state, reason):
        health.append({"state": state.value, "reason": reason})

    bus.subscribe(observe)
    started = time.time()
    try:
        initial = await asyncio.wait_for(
            plugin.fetch_history_with_config(
                TransportRequest(descriptor, limit=3), config
            ),
            45,
        )
        # REST persistence precedes startup. Factory must wire the real consumer
        # before replaying these pending snapshots and then opening the WS.
        handle = await factory._start_descriptor(
            descriptor, receive, on_health=observe_health
        )
        pipeline = factory._ingress.get_pipeline(descriptor.key)
        await asyncio.wait_for(closed.wait(), timeout)
        snapshot = pipeline.snapshot()
        await handle.stop()
        await bridge.delivery.flush()
        opened = chosen["open_time"]
        before = kline_sources.latest(descriptor, opened)
        rest_samples = []
        rest_attempts = 0
        # Binance REST and WS can disagree immediately at the close boundary.
        # Record each observation. Repeated REST values alone can be a cached
        # pre-close snapshot: also require elapsed exchange time and convergence
        # to the explicit WS close. Persistent disagreement fails this gate.
        comparison_fields = (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quoteVolume",
            "trades",
            "takerBuyBaseVolume",
            "takerBuyQuoteVolume",
        )
        for attempt in range(15):
            rest_attempts += 1
            try:
                rest = await asyncio.wait_for(
                    plugin.fetch_history_with_config(
                        TransportRequest(
                            descriptor, limit=1, start_ms=opened, end_ms=opened
                        ),
                        config,
                    ),
                    45,
                )
            except RuntimeError as exc:
                if "source_read_conflict" not in str(exc):
                    raise
                await asyncio.sleep(2)
                continue
            if len(rest) != 1 or rest[0].payload["timestamp"] != opened:
                raise AssertionError("REST did not return the exact WS-closed candle")
            for message in rest:
                await pipeline.normalize.ingest(message)
            await bridge.delivery.flush()
            rest_samples.append(rest[0].payload)
            if (
                len(rest_samples) >= 2
                and rest_samples[-1]["raw"] == rest_samples[-2]["raw"]
                and rest_samples[-1]["_source_rest_server_time_ms"]
                >= chosen["ws"]["closeTime"] + 15000
                and all(
                    Decimal(str(chosen["ws"][name]))
                    == Decimal(str(rest_samples[-1][name]))
                    for name in comparison_fields
                )
            ):
                break
            await asyncio.sleep(2)
        else:
            raise AssertionError(
                "REST/WS did not converge within fifteen bounded confirmation attempts"
            )
        latest = kline_sources.latest(descriptor, opened)
        row = klines_repo.query_klines(
            "BTCUSDT", "1m", opened, opened, market_type="futures"
        )[0]
        cached = cache.get_bar_at(
            SeriesKey("BTCUSDT", "1m", market_type="futures"), opened // 1000
        )
        fields = {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "quote_volume": "quoteVolume",
            "trades": "trades",
            "taker_buy_base": "takerBuyBaseVolume",
            "taker_buy_quote": "takerBuyQuoteVolume",
        }
        rest_payload = rest[0].payload
        for target, source in fields.items():
            expected = float(rest_payload[source])
            assert row[target] == expected, (target, row[target], expected)
            assert getattr(cached, target) == expected, target
        assert latest["envelope"]["raw"] == rest_payload["raw"]
        assert not kline_sources.pending(descriptor)
        assert any(event["event_type"] == "bar.closed" for event in events)
        ws_rest_equal = all(
            Decimal(str(chosen["ws"][name])) == Decimal(str(rest_payload[name]))
            for name in fields.values()
        )
        reconnect_after = len(frames)
        restarted_handle = await factory._start_descriptor(
            descriptor, receive, on_health=observe_health
        )
        await asyncio.wait_for(reconnected.wait(), 30)
        reconnect_snapshot = factory._ingress.get_pipeline(descriptor.key).snapshot()
        await restarted_handle.stop()
        await bridge.delivery.flush()
        assert not kline_sources.pending(descriptor)
        # Fresh interpreter reads the same durable source and canonical rows.
        code = """import json,sys
from app.data_engine.storage import kline_sources,klines_repo
from app.data_engine.ingestion.models import StreamDescriptor,StreamType
d=StreamDescriptor('BTCUSDT',StreamType.KLINE,interval='1m',market_type='futures')
t=int(sys.argv[1]); h=kline_sources.latest(d,t)
print(json.dumps({'head':h,'rows':klines_repo.query_klines('BTCUSDT','1m',t,t,market_type='futures'),'pending':len(kline_sources.pending(d))}))
"""
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        recovered = json.loads(
            await asyncio.to_thread(
                subprocess.check_output,
                [sys.executable, "-c", code, str(opened)],
                text=True,
                env=env,
            )
        )
        assert (
            recovered["head"] == latest
            and recovered["rows"] == [row]
            and recovered["pending"] == 0
        )
        (output / "source-observations.json").write_text(
            json.dumps(kline_sources.observations(descriptor, opened), indent=2) + "\n"
        )
        (output / "ws-delivered.json").write_text(json.dumps(frames, indent=2) + "\n")
        (output / "rest-samples.json").write_text(
            json.dumps(rest_samples, indent=2) + "\n"
        )
        (output / "events.json").write_text(json.dumps(events, indent=2) + "\n")
        (output / "restart-readback.json").write_text(
            json.dumps(recovered, indent=2) + "\n"
        )
        return dict(
            status="passed",
            started_at_ms=int(started * 1000),
            elapsed_seconds=round(time.time() - started, 3),
            lock=json.loads(LOCK_PATH.read_text()),
            database=str(klines_repo.KLINES_DB_PATH),
            initial_rest_rows=len(initial),
            ws_delivered=len(frames),
            forming_then_closed=True,
            rest_attempts=rest_attempts,
            stable_rest_samples=len(rest_samples),
            closed_open_time=opened,
            ws_rest_values_equal=ws_rest_equal,
            revision_before_rest=before["revision"],
            revision_after_rest=latest["revision"],
            live_closed_revision_observed=latest["revision"] != before["revision"],
            full_source_roundtrip=True,
            websocket_restart_verified=True,
            reconnect_pipeline=reconnect_snapshot,
            separate_process_readback=True,
            pending_sources=0,
            source_raw_sha256=hashlib.sha256(
                latest["envelope"]["raw"].encode()
            ).hexdigest(),
            health=health,
            pipeline=snapshot,
            delivery=bridge.delivery.snapshot(),
            desktop_tested=False,
        )
    finally:
        await factory.shutdown()
        await plugin.close_history_transport(config)
        await bridge.delivery.stop()
        await bus.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=100)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        result = asyncio.run(validate(args.output.resolve(), args.timeout))
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "result.json").write_text(
            json.dumps({"status": "failed", "error": repr(exc)}, indent=2) + "\n"
        )
        raise
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"pipeline", "reconnect_pipeline", "lock", "health"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
