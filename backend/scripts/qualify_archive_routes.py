"""Bounded public ZIP qualification through production registry/cache/admission.

Uses four small, closed monthly BTCUSDT daily-candle objects. Exit probes are
separate from archive accounting. Results do not establish a throughput SLA.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def qualify(args):
    import aiohttp
    from app.core.proxy_pool import get_proxy_pool
    from app.data_engine.backfill.archive_cache import AiohttpArchiveHttpClient, HistoricalArchiveCache
    from app.data_engine.ingestion.config import IngestionConfig
    from app.data_engine.ingestion.transport import TransportLayer
    from app.exchanges import bootstrap_default_adapters
    from app.exchanges.archive import ArchiveGranularity, ArchiveRequestContext
    from app.exchanges.public_admission import get_public_admission

    routes = []
    # Measure addresses without recording addresses or proxy credentials.
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), trust_env=False) as session:
        for index, proxy in enumerate(args.proxy):
            async with session.get("https://api.ipify.org", proxy=proxy) as response:
                response.raise_for_status()
                address = (await response.text()).strip()
                import ipaddress
                ipaddress.ip_address(address)
                group = hashlib.sha256(address.encode()).hexdigest()
                routes.append({"id": f"route-{index}", "name": f"route-{index}", "url": proxy,
                               "enabled": True, "egress_group": group, "exchanges": ["binance"], "max_concurrency": 2})
    cfg = IngestionConfig(proxy_mode="pool", proxy_strategy="balanced", proxy_routes=routes)
    transport = TransportLayer(cfg)
    provider = bootstrap_default_adapters().get_plugin("binance").history_archive_provider()
    assert provider is not None
    cache = HistoricalArchiveCache(args.output / "cache", max_bytes=10 * 1024**2)
    start = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2024, 5, 1, tzinfo=timezone.utc).timestamp() * 1000) - 1
    refs = [ref for ref in provider.plan_objects(market_type="spot", symbol="BTCUSDT", interval="1d",
            start_ms=start, end_ms=end, now_ms=int(time.time() * 1000)) if ref.granularity == ArchiveGranularity.MONTHLY]
    assert len(refs) == 4
    report = {"schema": "candlescope.public-archive-routes/1", "independent_exits": len({r["egress_group"] for r in routes}),
              "provider": provider.id, "objects": [], "scope": "Four small public ZIPs; no throughput/SLA or mixed REST/WS claim."}
    pool = get_proxy_pool()
    started = time.monotonic()
    async def one(ref):
        http = AiohttpArchiveHttpClient(request_runner=transport.archive_http_request,
            timeout_seconds=45).for_exchange("binance", context=ArchiveRequestContext(provider.id, ref.object_key))
        async with cache.materialize(ref, provider, http) as cold:
            bars = provider.parse_bars(cold.path, ref)
            assert cold.provider_checksum == cold.content_sha256 and bars
            assert bars[0].open_time == ref.start_ms and bars[-1].close_time == ref.end_ms
            async with cache.materialize(ref, provider, http) as warm:
                assert warm.cache_hit and warm.content_sha256 == cold.content_sha256
            return {"period": ref.period, "rows": len(bars), "bytes": cold.size_bytes,
                    "sha256": cold.content_sha256, "provider_checksum": cold.provider_checksum,
                    "download_ms": cold.download_elapsed_ms, "verify_ms": cold.verify_elapsed_ms,
                    "cold_cache_hit": cold.cache_hit, "warm_cache_hit": warm.cache_hit}
    try:
        results = await asyncio.gather(*(one(ref) for ref in refs), return_exceptions=True)
        for ref, result in zip(refs, results):
            report["objects"].append(result if isinstance(result, dict) else {
                "period": ref.period, "error_type": type(result).__name__, "error": str(result)})
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["routes"] = [{"id": r["id"], "egress_group": r["egress_group"], **pool.archive_traffic(r["url"])} for r in routes]
        report["admission"] = get_public_admission().snapshot()
        report["passed"] = all(isinstance(r, dict) for r in results)
        assert not pool._archive_leases and not any(pool._active.values())
        assert report["admission"]["in_flight"] == 0
        if args.require_independent:
            report["passed"] &= report["independent_exits"] >= 2 and all(r["requests_total"] > 0 for r in report["routes"])
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "admission"}, indent=2))
        return 0 if report["passed"] else 1
    finally:
        await transport.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-independent", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["DATA_DIR"] = os.environ["CANDLE_DATA_DIR"] = str(args.output / "data")
    return asyncio.run(qualify(args))


if __name__ == "__main__":
    raise SystemExit(main())
