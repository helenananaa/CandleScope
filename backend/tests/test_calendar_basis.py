from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path

import pytest

from app.data_engine.calendar_basis import RULES, wall_ms_to_utc
from app.data_engine.interval_policy import parse_interval_spec, interval_tiles
from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
from app.data_engine.bar_aggregator.models import BarFinality
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.data_manager.custom_query import CustomIntervalQueryService
from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamType


def ms(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


@pytest.mark.parametrize("interval,start,end", [
    ("1d~c1~America/New_York", "2024-03-10T05:00Z", "2024-03-11T04:00Z"),
    ("1d~c1~America/New_York", "2024-11-03T04:00Z", "2024-11-04T05:00Z"),
    ("1d~c1~Asia/Shanghai", "2024-02-28T16:00Z", "2024-02-29T16:00Z"),
    ("1w~c1~America/New_York", "2024-03-04T05:00Z", "2024-03-11T04:00Z"),
    ("1M~c1~UTC", "2024-02-01T00:00Z", "2024-03-01T00:00Z"),
    ("12M~c1~America/New_York", "2024-01-01T05:00Z", "2025-01-01T05:00Z"),
    ("1M~c1~America/New_York", "2024-03-01T05:00Z", "2024-04-01T04:00Z"),
])
def test_calendar_boundaries(interval, start, end):
    spec = parse_interval_spec(interval)
    assert spec.floor_ms(ms(start)) == ms(start)
    assert spec.floor_ms(ms(end) - 1) == ms(start)
    assert spec.next_ms(ms(start)) == ms(end)
    assert spec.previous_ms(ms(end)) == ms(start)


@pytest.mark.parametrize("wall", ["2024-03-10T02:30Z", "2024-11-03T01:30Z"])
def test_ambiguous_and_missing_local_times_are_rejected(wall):
    with pytest.raises(ValueError, match="ambiguous_or_nonexistent"):
        wall_ms_to_utc(ms(wall), "America/New_York")


@pytest.mark.parametrize("value", ["24h~c1~UTC", "1d~c2~UTC", "1d~c1~Europe/London", "0d~c1~UTC", "13M~c1~UTC"])
def test_unsupported_calendar_contract_is_rejected(value):
    assert parse_interval_spec(value) is None


def test_identity_and_exact_sources():
    target = parse_interval_spec("1d~c1~America/New_York")
    assert interval_tiles(parse_interval_spec("1h"), target)
    assert not interval_tiles(parse_interval_spec("2h"), target)
    assert not interval_tiles(parse_interval_spec("1d"), target)
    assert not interval_tiles(parse_interval_spec("1h~a1~60000"), target)
    assert len({SeriesKey("BTC-USDT", interval) for interval in ["1d", "1d~c1~UTC", "1d~c1~Asia/Shanghai", target.canonical]}) == 4
    root = Path(__file__).resolve().parents[2]
    assert json.loads((root / "frontend/data/calendar-v1.json").read_text()) == RULES


def test_basis_definition_roundtrip_and_unknown_provider():
    from app.data_engine.bar_basis import BarBasis, native_bar_spec
    from app.data_engine.interval_resolution import IntervalResolver, IntervalResolutionError
    basis = BarBasis.parse("1d~c1~America/New_York")
    assert BarBasis.restore(basis.to_dict()) == basis
    with pytest.raises(ValueError, match="definition_mismatch"):
        BarBasis.restore({**basis.to_dict(), "tzdb_version": "future"})
    contract = native_bar_spec("bybit", "spot", "5m", "realtime")
    contract.validate(1672324800000, 1672325099999)
    with pytest.raises(ValueError, match="boundary_mismatch"):
        contract.validate(1672324801000, 1672325100999)
    with pytest.raises(IntervalResolutionError) as error:
        IntervalResolver().resolve(exchange="kraken", market_type="spot", interval="7m", purpose="history")
    assert error.value.code.value == "native_bar_basis_unknown"


def test_local_calendar_resampling_keeps_actual_day_end_and_missing_hour(tmp_path):
    from app.local_data import LocalDatasetService, LocalImportOptions
    service = LocalDatasetService(tmp_path / "local")
    start = ms("2024-03-09T05:00Z")
    path = tmp_path / "hours.csv"
    # 24h, 23h and 24h days; omit one hour from the first day.
    path.write_text("time,open,high,low,close,volume\n" + "\n".join(
        f"{start+i*3600000},{100+i},{102+i},{99+i},{101+i},1" for i in range(71) if i != 3))
    manifest = service.import_csv(path, LocalImportOptions(name="DST", symbol="BTC-USDT", interval="1h", timestamp_unit="ms"))
    data = service.query(manifest["dataset_id"], interval="1d~c1~America/New_York", limit=10)["data"]
    assert [r["time"]*1000 for r in data] == [ms("2024-03-10T05:00Z"), ms("2024-03-11T04:00Z")]
    assert [r["volume"] for r in data] == [23, 24]
    assert data[0]["open"] == 124 and data[0]["close"] == 147
    older = service.query(manifest["dataset_id"], interval="1d~c1~America/New_York", limit=1,
                          before_ms=ms("2024-03-11T04:00Z"))["data"]
    assert older == data[:1]
    reopened = LocalDatasetService(tmp_path / "local")
    assert reopened.query(manifest["dataset_id"], interval="1d~c1~America/New_York", limit=10)["data"] == data


@pytest.mark.parametrize("start,hours", [("2024-03-10T05:00Z", 23), ("2024-11-03T04:00Z", 25)])
def test_calendar_history_stream_duplicates_and_late_repair(monkeypatch, start, hours):
    target = "1d~c1~America/New_York"
    begin = ms(start)
    rows = [dict(open_time=begin+i*3600000, close_time=begin+(i+1)*3600000-1,
                 open=100+i, high=102+i, low=99+i, close=101+i, volume=1,
                 quote_volume=10, trades=0, taker_buy_base=0, taker_buy_quote=0, is_closed=True)
            for i in range(hours+1)]
    def event(i):
        return MarketEvent(event_type=StreamType.KLINE, symbol="BTC-USDT", exchange="okx", market_type="spot",
            source=DataSource.WEBSOCKET, event_time_ms=rows[i]["close_time"], received_at_ms=rows[i]["close_time"],
            stream_key="fixture", sequence=rows[i]["close_time"], data={**rows[i], "interval": "1h"})
    async def run():
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target("BTC-USDT", target, exchange="okx")
        for i in range(hours+1):
            if i == 2:
                continue
            monkeypatch.setattr("app.data_engine.bar_aggregator.aggregator.time.time", lambda: rows[i]["close_time"] / 1000)
            await agg.on_market_event(event(i))
            await agg.on_market_event(event(i))
        state = next(b for b in agg.get_recent_bars("BTC-USDT", target, exchange="okx") if b.bucket_start_ms == begin)
        assert state.volume == hours - 1
        assert state.finality is BarFinality.PROVISIONAL
        await agg.on_market_event(replace(event(2), source=DataSource.HTTP_BACKFILL))
        await agg.on_market_event(replace(event(2), source=DataSource.HTTP_BACKFILL))
        assert state.volume == hours
        assert state.bucket_end_ms == begin + hours * 3600000
        assert state.finality is BarFinality.AUTHORITATIVE
        history = CustomIntervalQueryService._aggregate_read_only([BarData.from_storage_row(r) for r in rows], target, 86400, source_interval="1h")
        historical = next(b for b in history if b.time * 1000 == begin)
        assert (state.open, state.high, state.low, state.close, state.volume) == (historical.open, historical.high, historical.low, historical.close, historical.volume)
    asyncio.run(run())


def test_local_frozen_basis_definition_is_checked_on_reopen_and_export(tmp_path):
    from app.local_data import LocalDatasetService, LocalImportOptions
    service = LocalDatasetService(tmp_path / "local")
    csv = tmp_path / "bars.csv"
    csv.write_text("time,open,high,low,close,volume\n1704067200000,1,2,1,2,1")
    manifest = service.import_csv(csv, LocalImportOptions(name="basis", symbol="BTC", interval="1m", timestamp_unit="ms"))
    revision = service._revision_dir(manifest["dataset_id"])
    assert manifest["bar_basis"]["interval"] == "1m"
    service._validate_packaged_revision(revision, manifest["dataset_id"])
    path = revision / "manifest.json"
    manifest["bar_basis"]["phase_ms"] = 60000
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="boundary definition"):
        service.get_manifest(manifest["dataset_id"])
    with pytest.raises(ValueError, match="boundary definition"):
        service._validate_packaged_revision(revision, manifest["dataset_id"])


def test_calendar_warm_snapshot_keeps_dst_window(monkeypatch):
    from app.data_engine.bar_aggregator.models import BarInput, BarInputSource
    async def run():
        begin, end = ms("2024-11-03T04:00Z"), ms("2024-11-04T05:00Z")
        monkeypatch.setattr("app.data_engine.bar_aggregator.aggregator.time.time", lambda: begin / 1000)
        agg = BarAggregator(BarAggregatorConfig())
        interval = "1d~c1~America/New_York"
        agg.add_target("BTC-USDT", interval, exchange="okx")
        events = []
        async def capture(event):
            events.append(event)
        agg.publisher.on_bar_event(capture)
        state = await agg.seed_active_bar("BTC-USDT", interval,
            BarInput(symbol="BTC-USDT", source_interval=interval, exchange="okx", market_type="spot",
                     open_time_ms=begin, close_time_ms=end-1, open=1, high=2, low=1, close=2,
                     volume=25, source=BarInputSource.MANUAL, is_closed=False), exchange="okx")
        assert state.bucket_start_ms == begin and state.bucket_end_ms == end
        assert state.volume == 25 and events == []
    asyncio.run(run())


def test_generic_bybit_rest_fixture_through_normalization_boundary():
    from app.data_engine.ingestion.normalize import NormalizeLayer
    from app.data_engine.ingestion.config import IngestionConfig
    from app.data_engine.ingestion.models import RawMessage, StreamDescriptor
    from app.exchanges.ccxt_ext.unified import CcxtUnifiedNormalizer, CCXT_UNIFIED_MARKER
    from app.exchanges import bootstrap_default_adapters
    bootstrap_default_adapters()
    fixture = json.loads((Path(__file__).parent / "fixtures/bar_basis/bybit-5m-rest.json").read_text())["body"]
    descriptor = StreamDescriptor("BTC-USDT", StreamType.KLINE, interval="5m", exchange="bybit")
    layer = NormalizeLayer(IngestionConfig(), descriptor)
    layer._normalizer = CcxtUnifiedNormalizer(descriptor)
    for row in fixture["result"]["list"]:
        message = RawMessage(payload={"schema": CCXT_UNIFIED_MARKER, "kind": "kline", "value": row[:6]},
                             source=DataSource.HTTP_BACKFILL, stream_type=StreamType.KLINE,
                             received_at_ms=fixture["time"])
        event = layer.parse_all(message)[0]
        assert event.data["open_time"] == int(row[0])
        assert event.data["close_time"] == int(row[0]) + 299999
        assert event.data["volume"] == float(row[5])
        assert event.data["basis_qualification"] == "fixture_verified"


def test_session_provider_early_close_through_boundary_contract():
    from app.data_engine.ingestion.normalize import NormalizeLayer
    from app.data_engine.ingestion.config import IngestionConfig
    from app.data_engine.ingestion.models import RawMessage, StreamDescriptor
    from app.exchanges import bootstrap_default_adapters
    bootstrap_default_adapters()
    layer = NormalizeLayer(IngestionConfig(), StreamDescriptor("AAPL", StreamType.KLINE, interval="1d", exchange="twelvedata", market_type="stock"))
    event = layer.parse_all(RawMessage(payload=dict(datetime="2024-11-29", open="1", high="2", low="1", close="2", volume="10"),
        source=DataSource.HTTP_BACKFILL, stream_type=StreamType.KLINE, received_at_ms=ms("2024-11-30T00:00Z")))[0]
    assert event.data["open_time"] == ms("2024-11-29T00:00Z")
    assert event.data["close_time"] == ms("2024-11-29T18:00Z") - 1
    assert event.data["basis_id"].startswith("native-bar/1:twelvedata:stock:")


def test_custom_native_phase_is_validated_without_relabeling(monkeypatch):
    from types import SimpleNamespace
    from app.data_engine.bar_basis import NativeBarSpec
    from app.data_engine.ingestion.models import RawMessage, StreamDescriptor
    from app.exchanges.ccxt_ext.unified import CcxtUnifiedNormalizer, CCXT_UNIFIED_MARKER
    contract = NativeBarSpec("custom", "spot", "kline", "history", "5m", "5m~a1~60000", "declared")
    monkeypatch.setattr("app.exchanges.get_exchange_registry", lambda: SimpleNamespace(
        get_capabilities=lambda _: SimpleNamespace(bar_spec=lambda *_: contract)))
    normalizer = CcxtUnifiedNormalizer(StreamDescriptor("BTC", StreamType.KLINE, interval="5m", exchange="custom"))
    def message(at):
        return RawMessage(payload={"schema": CCXT_UNIFIED_MARKER, "kind": "kline", "value": [at, 1, 2, 1, 2, 1]},
            source=DataSource.HTTP_BACKFILL, stream_type=StreamType.KLINE, received_at_ms=900000)
    event = normalizer.parse(message(60000))
    assert event.data["open_time"] == 60000 and event.data["close_time"] == 359999
    contract.validate(event.data["open_time"], event.data["close_time"])
    assert normalizer.parse(message(0)) is None
