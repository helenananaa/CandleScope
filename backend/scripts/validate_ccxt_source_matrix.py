"""Real public source acceptance: four market rails, channels, enrichment, restart.

Requires a NEW isolated CANDLE_DATA_DIR. --legacy-db opens the original read-only
and copies bounded native rows; it never writes the user's original database.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
from app.data_engine.data_manager.aggregator_bridge import AggregatorBridge
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.factory import ExchangeIngestionFactory
from app.data_engine.ingestion.normalize import NormalizeLayer
from app.data_engine.ingestion.models import (
    DataSource,
    StreamDescriptor,
    StreamType,
    TransportRequest,
)
from app.data_engine.storage import (
    klines_repo,
    kline_sources,
    market_sources,
    source_enrichment,
    source_retention,
)
from app.exchanges import bootstrap_default_adapters, get_exchange_registry
from app.exchanges.ccxt_ext.fork_kline import LOCK_PATH

RAILS = [
    ("binance", "spot", "BTCUSDT"),
    ("binance", "futures", "BTCUSDT"),
    ("okx", "spot", "BTC-USDT"),
    ("okx", "futures", "BTC-USDT-SWAP"),
]


class Harness:
    def __init__(self, desc, config):
        self.desc = desc
        self.config = config
        self.agg = BarAggregator(BarAggregatorConfig())
        self.agg.add_target(
            desc.symbol,
            desc.interval,
            exchange=desc.exchange,
            market_type=desc.market_type,
        )
        self.cache = BarCache()
        self.bus = DataEventBus()
        self.events = []
        self.bridge = AggregatorBridge(
            cache=self.cache,
            event_bus=self.bus,
            storage_provider=lambda: klines_repo.KlinesRepoAdapter(),
            mark_bar_received=lambda key: None,
            is_started=lambda: True,
        )
        self.agg.publisher.on_bar_event(self.bridge.on_bar_event)
        from app.data_engine.ingestion import StreamPipeline

        self.pipeline = StreamPipeline(config, None, desc)
        self.pipeline.delivery.on_market_event(self.agg.on_market_event)
        self.layer = self.pipeline.normalize

    async def deliver(self, msg):
        await self.layer.ingest(msg)
        await self.bridge.delivery.flush()

    async def close(self):
        await self.pipeline.recovery.stop()
        await self.bridge.delivery.stop()
        await self.bus.close()


async def candles(desc, config, plugin, output):
    harness = Harness(desc, config)
    factory = ExchangeIngestionFactory(config)
    frames = []
    forming = set()
    chosen = {}
    closed = asyncio.Event()

    async def receive(event):
        await harness.agg.on_market_event(event)
        if event.source == DataSource.WEBSOCKET:
            frames.append(event.data["source_candle"])
            opened = event.data["open_time"]
            if not event.data["is_closed"]:
                forming.add(opened)
            elif opened in forming and not chosen:
                chosen.update(opened=opened, payload=event.data["source_candle"])
                closed.set()

    try:
        initial = await plugin.fetch_history_with_config(
            TransportRequest(desc, limit=3), config
        )
        for msg in initial:
            await harness.deliver(msg)
        handle = await factory._start_descriptor(desc, receive)
        await asyncio.wait_for(closed.wait(), 110)
        await handle.stop()
        await harness.bridge.delivery.flush()
        opened = chosen["opened"]
        samples = []
        fields = ["open", "high", "low", "close", "volume", "quoteVolume"]
        for attempt in range(15):
            rest = await plugin.fetch_history_with_config(
                TransportRequest(desc, limit=1, start_ms=opened, end_ms=opened), config
            )
            assert len(rest) == 1 and rest[0].payload["timestamp"] == opened
            await harness.deliver(rest[0])
            samples.append(rest[0].payload)
            if (
                len(samples) >= 2
                and samples[-1]["raw"] == samples[-2]["raw"]
                and all(
                    Decimal(samples[-1][key]) == Decimal(chosen["payload"][key])
                    for key in fields
                )
            ):
                break
            await asyncio.sleep(2)
        else:
            raise AssertionError("REST/WS close did not converge")
        assert not kline_sources.pending(desc)
        rows = klines_repo.query_klines(
            desc.symbol,
            desc.interval,
            opened,
            opened,
            exchange=desc.exchange,
            market_type=desc.market_type,
        )
        assert len(rows) == 1
        for dst, src in [
            ("open", "open"),
            ("close", "close"),
            ("volume", "volume"),
            ("quote_volume", "quoteVolume"),
        ]:
            assert rows[0][dst] == float(samples[-1][src])
        if desc.exchange == "okx":
            assert rows[0]["trades"] is None
        previous = len(frames)
        handle = await factory._start_descriptor(desc, receive)
        for _ in range(40):
            if len(frames) > previous:
                break
            await asyncio.sleep(0.5)
        assert len(frames) > previous, "no message after WS restart"
        await handle.stop()
        await harness.bridge.delivery.flush()
        evidence = {
            "frames": frames,
            "rest": samples,
            "observations": kline_sources.observations(desc, opened),
            "row": rows[0],
        }
        output.write_text(json.dumps(evidence, indent=2) + "\n")
        return {
            "status": "passed",
            "ws_frames": len(frames),
            "rest_samples": len(samples),
            "closed_at": opened,
            "restart": True,
            "pending": len(kline_sources.pending(desc)),
        }
    finally:
        await factory.shutdown()
        await harness.close()


async def channel(desc, config, plugin):
    layer = NormalizeLayer(config, desc)
    events = []

    async def receive(event):
        events.append(event)

    layer.on_event(receive)
    result = {}
    try:
        values = await asyncio.wait_for(
            plugin.fetch_history_with_config(TransportRequest(desc, limit=10), config),
            40,
        )
        for msg in values:
            await layer.ingest(msg)
        rows = market_sources.observations(desc)
        assert any(row["transport"] == "rest" for row in rows), (
            "missing REST full response"
        )
        result["rest"] = {
            "status": "passed",
            "responses": sum(row["transport"] == "rest" for row in rows),
            "events": len(events),
        }
    except ValueError as exc:
        if "does not support" not in str(exc):
            raise
        result["rest"] = {"status": "unsupported", "reason": str(exc)}
    session = plugin.create_stream_session(config, desc)
    if session is None:
        result["ws"] = {"status": "unsupported"}
        return result
    session.on_message(layer.ingest)
    try:
        await session.start()
        deadline = time.monotonic() + (
            20 if desc.stream_type == StreamType.LIQUIDATION else 35
        )
        while time.monotonic() < deadline:
            rows = market_sources.observations(desc)
            ws_rows = [row for row in rows if row["transport"] == "ws"]
            channels = {
                json.loads(row["payload_json"]).get("arg", {}).get("channel")
                for row in ws_rows
            }
            complete_summary = (
                not (
                    desc.exchange == "okx"
                    and desc.stream_type
                    in {StreamType.MARK_PRICE, StreamType.INDEX_PRICE}
                )
                or (
                    {"mark-price"}
                    if desc.stream_type == StreamType.MARK_PRICE
                    else {"index-tickers"}
                )
                <= channels
            )
            if ws_rows and complete_summary:
                result["ws"] = {
                    "status": "passed",
                    "raw_frames": sum(row["transport"] == "ws" for row in rows),
                    "events": len(events),
                }
                break
            await asyncio.sleep(0.25)
        else:
            result["ws"] = {
                "status": "no_event_in_window"
                if desc.stream_type == StreamType.LIQUIDATION
                else "failed",
                "snapshot": session.snapshot(),
            }
    finally:
        await session.stop()
    return result


async def main_run(args):
    if not os.getenv("CANDLE_DATA_DIR") or klines_repo.KLINES_DB_PATH.exists():
        raise RuntimeError("new isolated CANDLE_DATA_DIR required")
    args.output.mkdir(parents=True, exist_ok=True)
    klines_repo.init_klines_storage()
    kline_sources.rest_watermark()
    bootstrap_default_adapters()
    registry = get_exchange_registry()
    config = IngestionConfig(
        ccxt_fork_kline_enabled=True,
        **(
            {"proxy_mode": "custom", "http_proxy": args.http_proxy}
            if args.http_proxy
            else {}
        ),
    )
    result = {
        "lock": json.loads(LOCK_PATH.read_text()),
        "desktop_tested": False,
        "rails": {},
        "channels": {},
        "legacy": [],
    }

    def save():
        (args.output / "report.json").write_text(
            json.dumps(result, indent=2, default=str) + "\n"
        )

    try:
        for venue, market, symbol in [
            rail for rail in RAILS if rail[0] in args.venues and rail[1] in args.markets
        ]:
            key = f"{venue}-{market}"
            desc = StreamDescriptor(
                symbol,
                StreamType.KLINE,
                interval="1m",
                exchange=venue,
                market_type=market,
            )
            plugin = registry.get_plugin(venue)
            if not args.channels_only:
                try:
                    result["rails"][key] = await candles(
                        desc, config, plugin, args.output / f"{key}-candles.json"
                    )
                except Exception as exc:
                    result["rails"][key] = {
                        "status": "failed",
                        "error": repr(exc),
                        "traceback": __import__("traceback").format_exc(),
                    }
            save()
            types = [StreamType.TRADE, StreamType.TICKER, StreamType.DEPTH]
            if venue == "binance":
                types += [
                    StreamType.AGG_TRADE,
                    StreamType.FULL_DEPTH,
                    StreamType.MINI_TICKER,
                ]
            if market == "futures":
                types += [
                    StreamType.MARK_PRICE,
                    StreamType.INDEX_PRICE,
                    StreamType.FUNDING_RATE,
                    StreamType.OPEN_INTEREST,
                ]
            if market == "futures" and venue == "binance":
                types += [StreamType.PREMIUM_INDEX, StreamType.LIQUIDATION]
            for stream in types:
                if args.streams and stream.value not in args.streams:
                    continue
                channel_desc = StreamDescriptor(
                    symbol, stream, exchange=venue, market_type=market, depth_levels=5
                )
                name = f"{key}-{stream.value}"
                try:
                    result["channels"][name] = await channel(
                        channel_desc, config, plugin
                    )
                except Exception as exc:
                    result["channels"][name] = {
                        "status": "failed",
                        "error": repr(exc),
                        "traceback": __import__("traceback").format_exc(),
                    }
                save()
        if args.legacy_db:
            with sqlite3.connect(
                f"file:{args.legacy_db.resolve()}?mode=ro", uri=True
            ) as original:
                original.row_factory = sqlite3.Row
                for venue, market, symbol in [
                    rail
                    for rail in RAILS
                    if rail[0] in args.venues and rail[1] in args.markets
                ]:
                    rows = [
                        dict(row)
                        for row in original.execute(
                            "SELECT * FROM klines WHERE exchange=? AND market_type=? AND symbol=? AND interval=? ORDER BY open_time DESC LIMIT 3",
                            (venue, market, symbol, "1m"),
                        )
                    ]
                    if not rows:
                        continue
                    klines_repo.upsert_klines(
                        symbol,
                        "1m",
                        rows,
                        source="legacy_acceptance_copy",
                        exchange=venue,
                        market_type=market,
                    )
                    desc = StreamDescriptor(
                        symbol,
                        StreamType.KLINE,
                        interval="1m",
                        exchange=venue,
                        market_type=market,
                    )
                    harness = Harness(desc, config)
                    try:
                        proof = await source_enrichment.enrich(
                            desc,
                            config,
                            registry.get_plugin(venue),
                            harness.deliver,
                            start_ms=min(row["open_time"] for row in rows),
                            end_ms=max(row["open_time"] for row in rows),
                            limit=3,
                        )
                        result["legacy"].append(
                            {
                                "rail": f"{venue}-{market}",
                                "original_db_read_only": str(args.legacy_db),
                                "result": proof,
                            }
                        )
                    finally:
                        await harness.close()
                    save()
        result["retention"] = source_retention.compact(
            now_ms=int(time.time() * 1000) + 31 * 86400000
        )
        # Every compressed observation is decoded and checksum-verified in a new process.
        code = "from app.data_engine.storage import klines_repo,source_retention; from contextlib import closing; import json\nwith closing(klines_repo._connect()) as c:\n n=0\n for table in ('market_source_observations','kline_source_observations'):\n  for row in c.execute('SELECT * FROM '+table): source_retention.restore_row(c,table,dict(row)); n+=1\n print(json.dumps({'restored':n,'pending':c.execute('SELECT COUNT(*) FROM kline_source_heads WHERE delivered_revision<revision').fetchone()[0]}))"
        result["restart_readback"] = json.loads(
            subprocess.check_output(
                [sys.executable, "-c", code],
                env=dict(
                    os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])
                ),
                text=True,
            )
        )
        save()
        return result
    finally:
        for venue in ("binance", "okx"):
            await registry.get_plugin(venue).close_history_transport(config)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-db", type=Path)
    parser.add_argument("--http-proxy")
    parser.add_argument("--channels-only", action="store_true")
    parser.add_argument("--streams", nargs="+")
    parser.add_argument(
        "--markets", nargs="+", choices=["spot", "futures"], default=["spot", "futures"]
    )
    parser.add_argument(
        "--venues", nargs="+", choices=["binance", "okx"], default=["binance", "okx"]
    )
    logging.basicConfig(level=logging.WARNING)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main_run(args)), indent=2, default=str))
