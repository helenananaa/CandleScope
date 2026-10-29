"""Third independent schema fixture; this does not qualify a live vendor.

The seven-column seconds/OHLCVT shape and sparse no-trade intervals follow
Kraken's downloadable historical OHLCVT documentation. Values are synthetic.
The fixture deliberately owns no CCXT adapter, Binance parser or URL resolver.
"""
import asyncio
import csv
import io
import zipfile

import pytest

from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.models import BackfillTask
from app.data_engine.backfill.source_router import HistoricalSourceRouter
from app.exchanges.archive import ArchiveBar, ArchiveCapabilities, ArchiveGranularity, ArchiveHttpResponse, ArchiveObjectRef
from app.exchanges.archive_sources import ArchiveSourceRegistry
from tests.test_history_archive_import_cleanup import START, import_object, storage_at


class OhlcvtFixture:
    id = "kraken-ohlcvt-fixture-v1"

    def capabilities(self, market_type):
        return ArchiveCapabilities(self.id, ("spot",), ("1m",), (ArchiveGranularity.BULK,), "UTC", 720,
                                   venue="kraken", timestamp_unit="s", volume_unit="base",
                                   format_version="seconds-ohlcvt-7", enhanced_fields=("trades",),
                                   gap_policy="absent interval means no trades; no synthetic candle",
                                   stability="fixture-only")

    def plan_objects(self, **kwargs):
        return [ArchiveObjectRef(self.id, "kraken", "spot", "XBTUSD", "1m", ArchiveGranularity.BULK,
                "fixture-range", START, START + 5 * 60_000 - 1, "XBTUSD_1.zip", "UTC",
                url="https://fixture.invalid/fixture.zip", allowed_hosts=("fixture.invalid",))]

    async def resolve_objects(self, objects, http):
        return objects

    def parse_checksum(self, payload, ref):
        raise AssertionError("Fixture has no published checksum")

    def parse_bars(self, path, ref):
        with zipfile.ZipFile(path) as archive:
            text = archive.read("XBTUSD_1.csv").decode()
        result = []
        for t, o, h, low, c, volume, trades in csv.reader(io.StringIO(text)):
            start = int(t) * 1000
            result.append(ArchiveBar(start, start + 59_999, float(o), float(h), float(low), float(c),
                                     float(volume), trades=int(trades), enhanced_fields=frozenset({"trades"})))
        return result


class FixtureHttp:
    async def download(self, url, destination, **kwargs):
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("XBTUSD_1.csv", "".join(
                f"{START // 1000 + minute * 60},100,110,90,105,2.5,7\n" for minute in [0, 1, 3, 4]))
        return ArchiveHttpResponse(200, {})


@pytest.mark.parametrize("enabled", [False, True])
def test_independent_source_registration_full_import_and_sparse_coverage(monkeypatch, tmp_path, enabled):
    async def run():
        storage_at(monkeypatch, tmp_path)
        sources = ArchiveSourceRegistry()
        sources.register(venue="kraken", source_id=OhlcvtFixture.id, factory=lambda cfg: OhlcvtFixture(), enabled=enabled)
        class NoVenuePlugin:
            def get_plugin(self, exchange):
                raise AssertionError("An independent source must not require a CCXT plugin")
        monkeypatch.setattr("app.data_engine.backfill.source_router.get_exchange_registry", lambda: NoVenuePlugin())
        router = HistoricalSourceRouter(BackfillConfig(history_archive_cache_dir=str(tmp_path / "cache")),
                                        sources=sources, http=FixtureHttp())
        task = BackfillTask("XBTUSD", "1m", START, START + 5 * 60_000 - 1, exchange="kraken")
        try:
            plan = await router.prepare([task])
            if not enabled:
                assert not plan.futures
                assert router.snapshot()["source_reasons"]["kraken"] == "source_not_enabled"
                return
            ref = plan.refs_for(task)[0]
            result = await plan.future_for(ref)
            assert [bar.open_time for bar in result.bars] == [START + i * 60_000 for i in [0, 1, 3, 4]]
            assert all(bar.trades == 7 and bar.volume == 2.5 for bar in result.bars)
            assert not result.provider_checksum  # Local digest is never relabelled provider-verified.
            assert import_object(result)["imported"]
            caps = router.snapshot()["source_capabilities"]["kraken"]
            assert caps["provider_id"] == OhlcvtFixture.id and caps["venue"] == "kraken"
            assert caps["stability"] == "fixture-only"
        finally:
            await router.close()
    asyncio.run(run())
