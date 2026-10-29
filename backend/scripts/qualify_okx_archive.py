"""Compare one live, probe-selected OKX daily ZIP with the same public REST range.

Uses the default registry/provider and production archive admission. No user DB
is read or changed. This qualifies a spot sample, not every archive product.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def qualify(args):
    from app.data_engine.backfill.config import BackfillConfig
    from app.data_engine.backfill.source_router import HistoricalSourceRouter
    from app.data_engine.ingestion.config import IngestionConfig
    from app.data_engine.ingestion.models import StreamDescriptor, StreamType, TransportRequest
    from app.data_engine.ingestion.normalize import NormalizeLayer
    from app.data_engine.ingestion.transport import TransportLayer
    from app.exchanges import bootstrap_default_adapters
    from app.exchanges.public_admission import get_public_admission

    config = IngestionConfig(proxy_mode="custom", http_proxy=args.proxy)
    transport = TransportLayer(config)
    plugin = bootstrap_default_adapters().get_plugin("okx")
    router = HistoricalSourceRouter(BackfillConfig(history_archive_enabled=True,
        history_archive_okx_enabled=True, history_archive_cache_dir=str(args.output / "cache"),
        fetch_timeout=45), request_runner=transport.archive_http_request)
    report = {"schema": "candlescope.okx-archive-rest-parity/1", "passed": False,
              "scope": "One probe-selected spot daily ZIP; local SHA-256, no vendor checksum."}
    try:
        report["probe"] = await router.probe_enabled_capabilities()
        assert report["probe"]["okx"]["enabled"], report["probe"]
        provider = plugin.history_archive_provider()
        now = int(time.time() * 1000)
        candidates = provider.plan_objects(market_type="spot", symbol="BTC-USDT", interval="1m",
            start_ms=now - 7 * 86_400_000, end_ms=now - 4 * 86_400_000, now_ms=now)
        resolved = await provider.resolve_objects(candidates, router._http_for("okx"))
        result = await router._load_object(provider, max(resolved, key=lambda ref: ref.start_ms))
        report["archive"] = result.receipt()
        desc = StreamDescriptor(result.ref.symbol, StreamType.KLINE, interval="1m",
                                exchange="okx", market_type="spot")
        layer = NormalizeLayer(config, desc)
        rest = {}
        cursor = result.ref.end_ms
        pages = 0
        while cursor >= result.ref.start_ms:
            messages = await plugin.fetch_history_with_config(TransportRequest(desc, limit=300,
                start_ms=result.ref.start_ms, end_ms=cursor), config)
            events = [event for msg in messages for event in layer.parse_all(msg)]
            assert events, "REST stopped before covering the archive range"
            batch = {event.data["open_time"]: event.data for event in events
                     if result.ref.start_ms <= event.data["open_time"] <= cursor}
            assert batch, "REST pagination did not advance"
            rest.update(batch)
            cursor = min(batch) - 1
            pages += 1
            assert pages <= 10, "Unexpected daily sample page count"
        archive = {bar.open_time: bar for bar in result.bars}
        differences = []
        for timestamp in sorted(archive.keys() | rest.keys()):
            if timestamp not in archive or timestamp not in rest:
                differences.append({"timestamp": timestamp, "field": "missing_row"})
                continue
            bar, row = archive[timestamp], rest[timestamp]
            for field in ("open", "high", "low", "close", "volume", "quote_volume", "close_time"):
                if not math.isclose(float(getattr(bar, field)), float(row[field]), rel_tol=1e-12, abs_tol=1e-9):
                    differences.append({"timestamp": timestamp, "field": field,
                                        "archive": getattr(bar, field), "rest": row[field]})
            if not row["is_closed"]:
                differences.append({"timestamp": timestamp, "field": "not_closed"})
        warm = await router._load_object(plugin.history_archive_provider(), result.ref)
        assert warm.content_sha256 == result.content_sha256
        report.update(rest_rows=len(rest), archive_rows=len(archive), rest_pages=pages,
            difference_count=len(differences), differences=differences[:30],
            timeline_sha256=hashlib.sha256(json.dumps(sorted(archive)).encode()).hexdigest(),
            reread_same_digest=True, passed=not differences)
    finally:
        await plugin.close_history_transport(config)
        await router.close()
        await transport.stop()
        report["admission"] = get_public_admission().snapshot()
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert report["admission"]["in_flight"] == 0
    print(json.dumps({k: v for k, v in report.items() if k != "admission"}, indent=2))
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["DATA_DIR"] = os.environ["CANDLE_DATA_DIR"] = str(args.output / "data")
    return asyncio.run(asyncio.wait_for(qualify(args), timeout=180))


if __name__ == "__main__":
    raise SystemExit(main())
