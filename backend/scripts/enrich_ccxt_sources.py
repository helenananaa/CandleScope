"""Backfill source evidence in an offline profile, preserving every original row.

The backend using this profile must be stopped. This CLI never starts a desktop
app. Use --apply to deliver re-fetched snapshots; otherwise list the bounded
candidate range. Existing rows are backed up in source_enrichment_audit.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from app.data_engine.ingestion.config import IngestionConfig
    from app.data_engine.ingestion.models import StreamDescriptor, StreamType
    from app.data_engine.ingestion.normalize import NormalizeLayer
    from app.data_engine.ingestion.delivery import DeliveryLayer
    from app.data_engine.storage import klines_repo, source_enrichment
    from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
    from app.data_engine.data_manager.aggregator_bridge import AggregatorBridge
    from app.data_engine.data_manager.cache import BarCache
    from app.data_engine.data_manager.event_bus import DataEventBus
    from app.exchanges import bootstrap_default_adapters, get_exchange_registry

    desc = StreamDescriptor(
        args.symbol,
        StreamType.KLINE,
        interval=args.interval,
        exchange=args.exchange,
        market_type=args.market,
    )
    if not args.apply:
        rows = klines_repo.query_klines(
            args.symbol,
            args.interval,
            args.start,
            args.end,
            limit=args.limit,
            exchange=args.exchange,
            market_type=args.market,
        )
        return {
            "mode": "dry-run",
            "rows": len(rows),
            "data_dir": str(args.data_dir),
            "first": rows[0]["open_time"] if rows else None,
            "last": rows[-1]["open_time"] if rows else None,
        }
    bootstrap_default_adapters()
    registry = get_exchange_registry()
    cfg = IngestionConfig(ccxt_fork_kline_enabled=True)
    agg = BarAggregator(BarAggregatorConfig())
    agg.add_target(
        args.symbol, args.interval, exchange=args.exchange, market_type=args.market
    )
    cache, bus = BarCache(), DataEventBus()
    bridge = AggregatorBridge(
        cache=cache,
        event_bus=bus,
        storage_provider=lambda: klines_repo.KlinesRepoAdapter(),
        mark_bar_received=lambda key: None,
        is_started=lambda: True,
    )
    agg.publisher.on_bar_event(bridge.on_bar_event)
    layer = NormalizeLayer(cfg, desc)
    delivery = DeliveryLayer(cfg, desc)
    delivery.on_market_event(agg.on_market_event)
    # This is a bounded selection of historical rows, not a continuous live
    # feed. Retain durable delivery/acknowledgement without starting live gap
    # recovery between independent selected ranges.
    layer.on_event(delivery.deliver_event)

    async def deliver(message):
        await layer.ingest(message)
        await bridge.delivery.flush()

    try:
        return await source_enrichment.enrich(
            desc,
            cfg,
            registry.get_plugin(args.exchange),
            deliver,
            start_ms=args.start,
            end_ms=args.end,
            limit=args.limit,
        )
    finally:
        await delivery.close_all_subscribers()
        await bridge.delivery.stop()
        await bus.close()
        for venue in ("binance", "okx"):
            plugin = registry.get_plugin(venue)
            await plugin.close_history_transport(cfg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--exchange", choices=["binance", "okx"], required=True)
    parser.add_argument("--market", choices=["spot", "futures"], required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.data_dir.is_dir():
        parser.error("existing offline profile directory required")
    os.environ["CANDLE_DATA_DIR"] = str(args.data_dir.resolve())
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
