"""Controlled SQLite/factory/writer comparison; never contacts an exchange."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.data_engine.ingestion.factory import ExchangeIngestionFactory
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamType, StreamDescriptor
from app.data_engine.market_data.models import MarketChannel, MarketStreamKey
from app.data_engine.market_data.service import MarketDataService
from app.data_engine.market_data.storage_writer import MarketMetricStorageWriter
from app.data_engine.storage.market_metrics_repo import MarketMetricsRepository

BASELINE = "1988a9b8ecefac1d325447f570c3a1dd0435a028"


async def measure(service_class, directory):
    repository = MarketMetricsRepository(directory / "metrics.sqlite")
    writer = MarketMetricStorageWriter(repository)
    factory = ExchangeIngestionFactory()
    calls = []
    step = 300_000
    start = (int(time.time() * 1000) // step - 5 * 24 * 12) * step
    stamps = list(range(start, start + 100 * step, step))
    async def fetch(request):
        calls.append(request)
        return [RawMessage(
            payload={"symbol": "BTCUSDT", "sumOpenInterest": str(100 + i),
                     "sumOpenInterestValue": str(1000 + i), "timestamp": stamp},
            source=DataSource.HTTP, stream_type=StreamType.OPEN_INTEREST,
            received_at_ms=int(time.time() * 1000),
        ) for i, stamp in enumerate(stamps)
          if request.start_ms <= stamp <= request.end_ms]
    factory._ingress = SimpleNamespace(transport=SimpleNamespace(http_fetch=fetch))
    service = service_class(factory, metrics_repository=repository, metrics_writer=writer)
    key = MarketStreamKey.build("binance", "futures", "BTCUSDT", MarketChannel.OPEN_INTEREST)
    # Warm shared plugin imports/registry and the normalizer for both variants.
    # This preparation is outside the measured service queries and counters.
    await factory.fetch_market(StreamDescriptor(
        symbol="BTCUSDT", exchange="binance", market_type="futures",
        stream_type=StreamType.OPEN_INTEREST, interval="5m",
    ), history=True, start_ms=start, end_ms=stamps[-1] + step - 1)
    calls.clear()
    elapsed = []
    signatures = []
    cpu_start = time.process_time()
    for _ in range(51):
        began = time.perf_counter()
        page = await service.history_page(key, period="5m", start_ms=start,
                                          end_ms=stamps[-1] + step - 1, limit=500)
        elapsed.append((time.perf_counter() - began) * 1000)
        signatures.append([(e.event_time_ms, e.data["open_interest"], e.data["open_interest_value"])
                           for e in page.events])
    cpu_ms = (time.process_time() - cpu_start) * 1000
    assert all(s == signatures[0] for s in signatures)
    hot = sorted(elapsed[1:])
    result = {"requests": len(calls), "cold_ms": elapsed[0], "hot_p50_ms": hot[24],
              "hot_p95_ms": hot[47], "hot_p99_ms": hot[49], "cpu_ms": cpu_ms,
              "rows_written": writer.diagnostics()["rows_written"], "rows": len(signatures[0])}
    await service.shutdown()
    return result, signatures[0]


async def main():
    with tempfile.TemporaryDirectory(prefix="candlescope-149-benchmark-") as temporary:
        root = Path(temporary)
        baseline_file = root / "baseline.py"
        baseline_file.write_bytes(subprocess.check_output(
            ["git", "show", f"{BASELINE}:backend/app/data_engine/market_data/service.py"], cwd=ROOT))
        spec = importlib.util.spec_from_file_location("app.data_engine.market_data._baseline149", baseline_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        before, reference = await measure(module.MarketDataService, root / "before")
        after, actual = await measure(MarketDataService, root / "after")
        assert actual == reference
        print(json.dumps({"baseline": BASELINE, "scope": "Controlled 100 aligned final samples; real factory, native normalizer, SQLite and durable writer; zero external network. 1 cold + 50 hot reads. Latency is local fixture evidence, not exchange/native performance.",
                          "equal_data": True, "before": before, "after": after}, indent=2))


asyncio.run(main())
