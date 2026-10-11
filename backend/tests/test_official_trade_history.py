from datetime import datetime, timezone

import pytest

from app.data_engine.storage.raw_trade_archive import RawAggTradeSelectionWindow
from app.replay.catalog import ReplayCatalog
from app.replay.history_archive import (
    ReplayHistoryArchiveError,
    ReplayHistoryArchiveWriter,
    ReplayHistoryImportBatch,
)
from app.replay.official_trade_history import (
    DAY,
    MINUTE,
    OfficialTradeHistoryRepository,
)
from tests.fixtures.replay.fakes import make_bar

START = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
IDENTITY = {"exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT"}


class Archive:
    def list_verified_identities(self):
        return [IDENTITY]

    def selection_snapshot(self, **kwargs):
        return "sha256:" + "a" * 64, (
            RawAggTradeSelectionWindow(START, START + 10 * DAY - 1, 10),
        )


def loader(calls):
    def load(root, identity, day_start):
        calls.append(day_start)
        ReplayHistoryArchiveWriter(root).import_batches(
            identity,
            "1m",
            [
                ReplayHistoryImportBatch(
                    rows=[
                        make_bar(day_start + i * MINUTE, price="100")
                        for i in range(1440)
                    ],
                    source_provider="binance-public-kline-v1",
                    source_object_key=str(day_start),
                    source_period="2025-01",
                    source_content_sha256="sha256:" + "b" * 64,
                    source_provider_checksum="sha256:" + "b" * 64,
                )
            ],
        )

    return load


def test_uncached_dates_are_selectable_and_only_requested_days_download(tmp_path):
    calls = []
    repo = OfficialTradeHistoryRepository(tmp_path, Archive(), day_loader=loader(calls))
    catalog = ReplayCatalog(
        repo, native_intervals=lambda _: ("1m",), now_ms=lambda: START + 20 * DAY
    )
    snapshot = catalog.build(warmup_bars=200, horizon_ms=DAY, quality_mode="exact")
    entry = snapshot.entries[0]
    assert entry.eligible_ranges[0].first_start_ms == START + 200 * MINUTE
    assert entry.eligible_ranges[0].last_start_ms == START + 9 * DAY
    assert calls == []
    rows = repo.query_bars_at_revision(
        entry.source_revision,
        "BTCUSDT",
        "1m",
        **{k: v for k, v in IDENTITY.items() if k != "symbol"},
        start_ms=START + 5 * DAY - 2 * MINUTE,
        end_ms=START + 5 * DAY + MINUTE,
        limit=4,
    )
    assert len(rows) == 4
    assert calls == [START + 4 * DAY, START + 5 * DAY]
    # Immutable revision metadata and bodies survive restart, without network.
    restored = OfficialTradeHistoryRepository(
        tmp_path, Archive(), day_loader=lambda *_: pytest.fail("unexpected download")
    )
    assert (
        restored.query_bars_at_revision(
            entry.source_revision,
            "BTCUSDT",
            "1m",
            exchange="binance",
            market_type="futures",
            start_ms=rows[0]["open_time"],
            end_ms=rows[-1]["open_time"],
            limit=4,
        )
        == rows
    )
    with pytest.raises(ReplayHistoryArchiveError):
        restored.query_bars_at_revision(
            entry.source_revision,
            "ETHUSDT",
            "1m",
            exchange="binance",
            market_type="futures",
            start_ms=START,
            limit=1,
        )


def test_download_failure_is_retryable_without_publishing_a_fake_day(tmp_path):
    repo = OfficialTradeHistoryRepository(
        tmp_path,
        Archive(),
        day_loader=lambda *_: (_ for _ in ()).throw(OSError("network unavailable")),
    )
    revision = repo.list_all_series()[0]["source_revision"]
    args = {"exchange": "binance", "market_type": "futures", "start_ms": START, "limit": 1}
    with pytest.raises(OSError):
        repo.query_bars_at_revision(revision, "BTCUSDT", "1m", **args)
    calls = []
    repo._day_loader = loader(calls)
    assert len(repo.query_bars_at_revision(revision, "BTCUSDT", "1m", **args)) == 1
    assert calls == [START]


def test_descending_page_bounds_downloads_even_for_all_history(tmp_path):
    calls = []
    repo = OfficialTradeHistoryRepository(tmp_path, Archive(), day_loader=loader(calls))
    revision = repo.list_all_series()[0]["source_revision"]
    rows = repo.query_bars_at_revision(
        revision,
        "BTCUSDT",
        "1m",
        exchange="binance",
        market_type="futures",
        end_ms=START + 8 * DAY + 5 * MINUTE,
        limit=3,
        order="DESC",
    )
    assert [r["open_time"] for r in rows] == [
        START + 8 * DAY + i * MINUTE for i in (5, 4, 3)
    ]
    assert calls == [START + 8 * DAY]


def test_builtin_catalog_refresh_is_atomic_and_offline_cache_survives(
    tmp_path, monkeypatch
):
    from datetime import date

    import app.replay.remote_trade_archive as remote
    from app.replay.official_trade_catalog import OfficialAggTradeArchive

    monkeypatch.setattr(
        remote,
        "list_official_agg_trade_days",
        lambda **_: (date(2025, 1, 1), date(2025, 1, 2)),
    )
    archive = OfficialAggTradeArchive(tmp_path / "cache", symbols=("BTCUSDT", "ETHUSDT"))
    assert len(archive.list_verified_identities()) == 2
    assert archive.diagnostics()["official_daily_archive_count"] == 4
    original = (archive.catalog_root / "trade-index.json").read_bytes()

    def offline(**_):
        raise OSError("offline")

    monkeypatch.setattr(remote, "list_official_agg_trade_days", offline)
    archive.refresh_official_catalog()
    assert (archive.catalog_root / "trade-index.json").read_bytes() == original
    restored = OfficialAggTradeArchive(tmp_path / "cache", symbols=("BTCUSDT", "ETHUSDT"))
    assert restored.list_verified_identities() == archive.list_verified_identities()


def test_first_launch_offline_keeps_application_startable(tmp_path, monkeypatch):
    import app.replay.remote_trade_archive as remote
    from app.replay.official_trade_catalog import OfficialAggTradeArchive

    def offline(**_):
        raise OSError("offline")

    monkeypatch.setattr(remote, "list_official_agg_trade_days", offline)
    archive = OfficialAggTradeArchive(tmp_path / "cache", symbols=("BTCUSDT", "ETHUSDT"))
    assert archive.list_verified_identities() == []
    assert archive.diagnostics()["verified_partitions_available"] is False


def test_all_symbols_discovered_and_partial_failure_retains_old_symbol(tmp_path, monkeypatch):
    from datetime import date
    import app.replay.official_trade_catalog as builtin
    import app.replay.remote_trade_archive as remote
    monkeypatch.setattr(builtin, "list_official_agg_trade_symbols", lambda **_: ("SOLUSDT", "DOGEUSDT", "LTCUSDT"))
    monkeypatch.setattr(remote, "list_official_agg_trade_days", lambda **_: (date(2025, 1, 1), date(2025, 1, 2)))
    archive = builtin.OfficialAggTradeArchive(tmp_path)
    assert {i["symbol"] for i in archive.list_verified_identities()} == {"SOLUSDT", "DOGEUSDT", "LTCUSDT"}
    assert not archive.needs_catalog_refresh()
    assert archive.historical_instrument_metadata("binance", "futures", "SOLUSDT")["baseAsset"] == "SOL"
    assert archive.historical_instrument_metadata("binance", "spot", "SOLUSDT") is None
    assert archive.historical_instrument_metadata("binance", "futures", "FAKEUSDT") is None
    def partial(*, symbol, **_):
        if symbol == "SOLUSDT":
            raise OSError("one symbol timed out")
        return (date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3))
    monkeypatch.setattr(remote, "list_official_agg_trade_days", partial)
    archive.refresh_official_catalog()
    assert len(archive.list_verified_identities()) == 3
    assert archive.diagnostics()["official_daily_archive_count"] == 8
    assert archive.catalog_failed == 1


def test_symbol_discovery_paginates_and_ignores_invalid_prefixes():
    import io
    from urllib.parse import parse_qs, urlparse
    from app.replay.trade_import import list_official_agg_trade_symbols, ReplayTradeImportError
    calls = []
    def opener(url, **_):
        query = parse_qs(urlparse(url).query)
        calls.append(query)
        if len(calls) == 1:
            return io.BytesIO(b'<ListBucketResult><CommonPrefixes><Prefix>data/futures/um/daily/aggTrades/SOLUSDT/</Prefix></CommonPrefixes><IsTruncated>true</IsTruncated><NextMarker>next</NextMarker></ListBucketResult>')
        return io.BytesIO(b'<ListBucketResult><CommonPrefixes><Prefix>data/futures/um/daily/aggTrades/DOGEUSDT/</Prefix></CommonPrefixes><CommonPrefixes><Prefix>data/futures/um/daily/aggTrades/../</Prefix></CommonPrefixes><IsTruncated>false</IsTruncated></ListBucketResult>')
    assert list_official_agg_trade_symbols(opener=opener) == ("DOGEUSDT", "SOLUSDT")
    assert calls[1]["marker"] == ["next"]
    with pytest.raises(ReplayTradeImportError, match="did not advance"):
        list_official_agg_trade_symbols(opener=lambda *a, **k: io.BytesIO(b'<ListBucketResult><IsTruncated>true</IsTruncated><NextMarker>same</NextMarker></ListBucketResult>'))


def test_deferred_discovery_does_not_block_startup(tmp_path, monkeypatch):
    import app.replay.official_trade_catalog as builtin
    monkeypatch.setattr(builtin, "list_official_agg_trade_symbols", lambda **_: pytest.fail("startup must not use network"))
    archive = builtin.OfficialAggTradeArchive(tmp_path, defer_refresh=True)
    assert archive.list_verified_identities() == []
    assert archive.needs_catalog_refresh()
