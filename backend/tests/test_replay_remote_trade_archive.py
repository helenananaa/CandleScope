from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from app.data_engine.storage.raw_trade_archive import (
    RawAggTradeSelectionWindow,
    VerifiedRawAggTradeBarWindow,
    VerifiedRawAggTradeWindow,
)
from app.replay.bars.trade_parity import trade_bar_parity_policy
from app.replay.remote_history import ReplayHistoryOriginUnavailable
from app.replay.remote_trade_archive import (
    RemoteRawAggTradeArchive,
    publish_remote_agg_trade_index,
    sync_official_agg_trade_availability,
)
from app.replay.trade_import import official_agg_trade_urls
from tests.fixtures.replay.trade_service_fakes import (
    DAY_START_MS,
    INTERVAL_MS,
    TRADE_REPLAY_MINUTES,
    TRADE_REPLAY_START_MS,
    verified_trade_archive,
)


def test_retired_day_is_hidden_and_recoverable_after_interruption(tmp_path, monkeypatch):
    from contextlib import nullcontext

    from app.data_engine.storage import raw_trade_archive
    from app.data_engine.storage.raw_trade_archive import VerifiedRawAggTradeDay, VerifiedTradeDayRetired
    from app.replay.trade_import import import_official_date_range, trade_archive_day_acquisition

    cache_root = tmp_path / "cache"
    local = verified_trade_archive(cache_root)
    origin_root = tmp_path / "origin"
    verified_trade_archive(origin_root)
    listing = "<ListBucketResult>"
    for day_text in ("2026-05-31", "2026-06-01", "2026-06-02"):
        key = f"data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-{day_text}.zip"
        listing += f"<Contents><Key>{key}</Key></Contents><Contents><Key>{key}.CHECKSUM</Key></Contents>"
    listing += "<IsTruncated>false</IsTruncated></ListBucketResult>"
    sync_official_agg_trade_availability(
        origin_root, exchange="binance", market_type="futures", symbol="BTCUSDT",
        as_of_date=date(2026, 6, 3), opener=lambda *_args, **_kwargs: io.BytesIO(listing.encode()),
    )
    publish_remote_agg_trade_index(origin_root)
    remote = RemoteRawAggTradeArchive(cache_root, origin_root, refresh_seconds=0)
    identity = {"exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT"}
    request = {**identity, "start_time_ms": TRADE_REPLAY_START_MS,
               "end_time_ms": TRADE_REPLAY_START_MS + INTERVAL_MS - 1}
    expected = local.freeze_dataset(**request)
    before_epoch, before_windows = remote.selection_snapshot(**identity)
    receipt, = cache_root.glob("exchange=*/market_type=*/symbol=*/date=*/_verified_import.json")
    originals = {file.name: file.read_bytes() for file in receipt.parent.iterdir()}
    day = date(2026, 6, 1)
    day_id = "sha256:" + hashlib.sha256(originals[receipt.name]).hexdigest()

    def move(*, restore=False, approved=True, receipt_id=day_id):
        return local.move_verified_retention_day(
            identity=tuple(identity.values()), day=day.isoformat(), day_id=receipt_id,
            restore=restore, authorize=lambda _key, _receipt: nullcontext(approved),
        )

    assert move(receipt_id="sha256:" + "0" * 64) == "STALE_RECEIPT"
    assert move(approved=False) == "RETENTION_NOT_AUTHORIZED"
    with trade_archive_day_acquisition(local, **identity, day=day):
        assert move() == "DAY_ACQUISITION_IN_PROGRESS"
    pin = remote.pin_dataset(expected)
    try:
        assert move() == "PARTITION_RETENTION_LEASE"
    finally:
        remote.release_dataset(pin)

    extra = receipt.parent / "unmanaged-file"
    extra.write_text("keep")
    assert move() == "PARTITION_UNSAFE"
    assert extra.read_text() == "keep"
    extra.unlink()

    def interrupted(_path):
        raise OSError("injected interruption after rename")

    with monkeypatch.context() as patch:
        patch.setattr(raw_trade_archive, "_sync_retention_directory", interrupted)
        with pytest.raises(OSError, match="after rename"):
            move()
    assert move() == "RETIRED"
    assert not receipt.parent.exists()
    assert remote.selection_snapshot(**identity) != (before_epoch, before_windows)
    day_ms = 86_400_000
    assert remote.list_selection_windows(**identity) == (
        RawAggTradeSelectionWindow(DAY_START_MS - day_ms, DAY_START_MS - 1, 1),
        RawAggTradeSelectionWindow(DAY_START_MS + day_ms, DAY_START_MS + 2 * day_ms - 1, 1),
    )
    assert local.scan_range(**request) == []
    assert local.list_verified_windows(**identity) == ()

    def unexpected_download(*_args, **_kwargs):
        pytest.fail("retired day requested a network body")

    monkeypatch.setattr(remote, "_official_opener", unexpected_download)
    monkeypatch.setattr(remote, "_materialize_file", unexpected_download)
    with pytest.raises(VerifiedTradeDayRetired):
        remote.freeze_dataset(**request)
    with pytest.raises(VerifiedTradeDayRetired):
        remote._materialize_official_day(**identity, day=day)
    with pytest.raises(VerifiedTradeDayRetired):
        remote._materialize_receipt(receipt.relative_to(cache_root).as_posix())
    metadata = VerifiedRawAggTradeDay(**json.loads(originals[receipt.name])["metadata"])
    with pytest.raises(VerifiedTradeDayRetired):
        local.import_verified_day(iter(()), metadata)
    with pytest.raises(VerifiedTradeDayRetired):
        import_official_date_range(
            archive_dir=cache_root, **identity, start=day, end=day,
            require_checksum=True, opener=unexpected_download,
        )

    assert move(restore=True, approved=False) == "RETENTION_NOT_AUTHORIZED"
    retired = receipt.parent.with_name(".retired-" + receipt.parent.name)
    body = next(retired.glob("*.parquet"))
    body.write_bytes(originals[body.name] + b"corruption")
    assert move(restore=True) == "PARTITION_UNSAFE"
    body.write_bytes(originals[body.name])
    assert move(restore=True) == "RESTORED"
    assert move(restore=True) == "RESTORED"
    assert remote.selection_snapshot(**identity) == (before_epoch, before_windows)
    assert remote.freeze_dataset(**request) == expected
    assert {file.name: file.read_bytes() for file in receipt.parent.iterdir()} == originals


@pytest.mark.parametrize("origin_state", ["window_removed", "unavailable"])
def test_freeze_reuses_verified_day_after_catalog_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin_state: str,
) -> None:
    cache_root = tmp_path / "cache"
    local = verified_trade_archive(cache_root)
    request = {
        "exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT",
        "start_time_ms": TRADE_REPLAY_START_MS,
        "end_time_ms": TRADE_REPLAY_START_MS + INTERVAL_MS - 1,
    }
    expected = local.freeze_dataset(**request)
    assert len(expected.objects) == 1
    origin_root = tmp_path / "origin"
    verified_trade_archive(origin_root)
    publish_remote_agg_trade_index(origin_root)
    remote = RemoteRawAggTradeArchive(cache_root, origin_root, refresh_seconds=0)
    remote.cache.max_scan_files = 1  # Limit the requested slice, not the whole day.
    identity = {name: request[name] for name in ("exchange", "market_type", "symbol")}
    previous_epoch, _ = remote.selection_snapshot(**identity)

    if origin_state == "window_removed":
        for receipt in origin_root.rglob("_verified_import.json"):
            receipt.unlink()
        day = date(2026, 6, 2)
        key = f"data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-{day}.zip"
        listing = (
            "<ListBucketResult>"
            f"<Contents><Key>{key}</Key></Contents>"
            f"<Contents><Key>{key}.CHECKSUM</Key></Contents>"
            "<IsTruncated>false</IsTruncated></ListBucketResult>"
        ).encode()
        sync_official_agg_trade_availability(
            origin_root, exchange="binance", market_type="futures", symbol="BTCUSDT",
            as_of_date=date(2026, 6, 3), opener=lambda *_args, **_kwargs: io.BytesIO(listing),
        )
        publish_remote_agg_trade_index(origin_root)
    else:
        def unavailable(*_args, **_kwargs):
            raise ReplayHistoryOriginUnavailable("controlled outage")

        monkeypatch.setattr(remote.origin, "read_json", unavailable)
        (cache_root / "_remote_metadata" / "trade-index.json").unlink()

    def unexpected_download(*_args, **_kwargs):
        pytest.fail("a verified local day requires no download")

    monkeypatch.setattr(remote, "_official_opener", unexpected_download)
    refreshes = remote._metrics["remote_index_refreshes"]
    assert remote.freeze_dataset(**request) == expected
    assert remote._metrics["remote_index_refreshes"] == refreshes
    # Selection checks receipt/sidecar metadata without hashing the data files.
    from app.data_engine.storage import raw_trade_archive
    hash_file = raw_trade_archive._file_sha256

    def hash_sidecars(path: Path):
        assert path.suffix != ".parquet"
        return hash_file(path)

    monkeypatch.setattr(raw_trade_archive, "_file_sha256", hash_sidecars)
    epoch, windows = remote.selection_snapshot(**identity)
    assert epoch != previous_epoch
    day_count = 2 if origin_state == "window_removed" else 1
    assert windows == (RawAggTradeSelectionWindow(
        DAY_START_MS, DAY_START_MS + day_count * 86_400_000 - 1, day_count,
    ),)
    assert remote.list_verified_identities() == [identity]
    assert remote.diagnostics()["verified_partitions_available"] is True
    if origin_state == "unavailable":
        offline_origin = tmp_path / "offline-origin"
        offline_origin.mkdir()
        restarted = RemoteRawAggTradeArchive(cache_root, offline_origin)
        assert restarted.selection_snapshot(**identity) == (epoch, windows)
    (cache_root / expected.objects[0].object_id).unlink()
    after_removal, remaining = remote.selection_snapshot(**identity)
    assert after_removal != epoch
    if origin_state == "unavailable":
        assert remaining == ()
        assert remote.list_verified_identities() == []
        assert remote.diagnostics()["state"] == "degraded"
    else:
        assert remaining == (RawAggTradeSelectionWindow(
            DAY_START_MS + 86_400_000, DAY_START_MS + 2 * 86_400_000 - 1, 1,
        ),)


def test_remote_agg_trade_selection_uses_receipts_without_bar_parity_proofs(
    tmp_path: Path,
) -> None:
    origin_root = tmp_path / "origin"
    origin = verified_trade_archive(origin_root)
    end_ms = TRADE_REPLAY_START_MS + TRADE_REPLAY_MINUTES * INTERVAL_MS - 1
    dataset_ref = origin.freeze_dataset(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        start_time_ms=TRADE_REPLAY_START_MS,
        end_time_ms=end_ms,
    )
    remote_index = publish_remote_agg_trade_index(origin_root)
    assert remote_index.compatibility_indexes == ()
    cache_root = tmp_path / "cache"
    remote = RemoteRawAggTradeArchive(cache_root, origin_root)

    windows = remote.list_verified_windows(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
    )

    assert windows == (
        VerifiedRawAggTradeWindow(
            start_time_ms=DAY_START_MS,
            end_time_ms=DAY_START_MS + 86_400_000 - 1,
            first_agg_trade_id=1_000,
            last_agg_trade_id=1_007,
            partition_count=1,
        ),
    )
    assert remote.list_verified_identities() == [
        {
            "exchange": "binance",
            "market_type": "futures",
            "symbol": "BTCUSDT",
        }
    ]
    assert list(cache_root.rglob("*.parquet")) == []
    assert remote.diagnostics()["remote_index_epoch"] == remote_index.index_epoch
    assert remote.diagnostics()["bar_parity_required"] is False

    frozen = remote.freeze_dataset(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        start_time_ms=TRADE_REPLAY_START_MS,
        end_time_ms=end_ms,
    )

    assert frozen.data_epoch == dataset_ref.data_epoch
    assert frozen.objects == dataset_ref.objects
    assert len(list(cache_root.rglob("*.parquet"))) == len(dataset_ref.objects)
    diagnostics = remote.diagnostics()
    assert diagnostics["materialized_partitions"] == 1
    assert diagnostics["materialized_objects"] == len(dataset_ref.objects) * 2
    assert diagnostics["materialization_failures"] == 0

    # A mirrored partition remains recoverable if one local body is corrupt.
    damaged = cache_root / frozen.objects[0].object_id
    damaged.write_bytes(b"corrupt cached parquet")
    repaired = remote.freeze_dataset(
        exchange="binance", market_type="futures", symbol="BTCUSDT",
        start_time_ms=TRADE_REPLAY_START_MS, end_time_ms=end_ms,
    )
    assert repaired == frozen
    assert remote.diagnostics()["materialized_objects"] == diagnostics["materialized_objects"] + 1


def test_remote_agg_trade_compatibility_is_independent_of_partial_body_cache(
    tmp_path: Path,
) -> None:
    origin_root = tmp_path / "origin"
    origin = verified_trade_archive(origin_root)
    end_ms = TRADE_REPLAY_START_MS + TRADE_REPLAY_MINUTES * INTERVAL_MS - 1
    dataset_ref = origin.freeze_dataset(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        start_time_ms=TRADE_REPLAY_START_MS,
        end_time_ms=end_ms,
    )
    revision = "sha256:" + "b" * 64
    policy = trade_bar_parity_policy(compare_trade_count=False)
    origin.publish_bar_compatibility(
        dataset_ref=dataset_ref,
        interval="1m",
        interval_ms=INTERVAL_MS,
        bar_source_revision=revision,
        parity_policy=policy,
        checked_bar_count=TRADE_REPLAY_MINUTES,
        mismatch_bar_count=0,
        compatible_windows=(
            VerifiedRawAggTradeBarWindow(
                start_time_ms=TRADE_REPLAY_START_MS,
                end_time_ms=end_ms,
                bar_count=TRADE_REPLAY_MINUTES,
            ),
        ),
    )
    publish_remote_agg_trade_index(origin_root)

    empty = RemoteRawAggTradeArchive(tmp_path / "empty", origin_root)
    partial_root = tmp_path / "partial"
    first = dataset_ref.objects[0]
    source = origin_root / first.object_id
    destination = partial_root / first.object_id
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())
    partial = RemoteRawAggTradeArchive(partial_root, origin_root)

    request = {
        "exchange": "binance",
        "market_type": "futures",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "interval_ms": INTERVAL_MS,
        "bar_source_revision": revision,
        "parity_policy": policy,
    }
    assert empty.list_verified_bar_windows(**request) == partial.list_verified_bar_windows(
        **request
    )


def test_official_availability_selects_full_day_then_downloads_on_demand(
    tmp_path: Path,
) -> None:
    origin_root = tmp_path / "origin"
    cache_root = tmp_path / "cache"
    day = date(2026, 6, 1)
    prefix = "data/futures/um/daily/aggTrades/BTCUSDT/"
    listing = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<ListBucketResult xmlns='http://s3.amazonaws.com/doc/2006-03-01/'>"
        f"<Contents><Key>{prefix}BTCUSDT-aggTrades-{day}.zip</Key></Contents>"
        f"<Contents><Key>{prefix}BTCUSDT-aggTrades-{day}.zip.CHECKSUM</Key>"
        "</Contents><IsTruncated>false</IsTruncated></ListBucketResult>"
    ).encode()
    sync_official_agg_trade_availability(
        origin_root,
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        as_of_date=date(2026, 6, 2),
        now_ms=1,
        opener=lambda *_args, **_kwargs: io.BytesIO(listing),
    )
    remote_index = publish_remote_agg_trade_index(origin_root, now_ms=2)
    assert remote_index.verified_receipts == ()
    assert len(remote_index.official_availability_indexes) == 1

    filename = f"BTCUSDT-aggTrades-{day}.zip"
    csv_name = filename.removesuffix(".zip") + ".csv"
    rows = [
        (
            f"{1_000 + index},{100 + index // 2},1,{10_000 + index},"
            f"{10_000 + index},{TRADE_REPLAY_START_MS + index * 1_000},"
            f"{'true' if index % 2 == 0 else 'false'}"
        )
        for index in range(8)
    ]
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            csv_name,
            "agg_trade_id,price,quantity,first_trade_id,last_trade_id,"
            "transact_time,is_buyer_maker\n" + "\n".join(rows) + "\n",
        )
    zip_payload = body.getvalue()
    digest = hashlib.sha256(zip_payload).hexdigest()
    source_url, checksum_url, _ = official_agg_trade_urls(
        market_type="futures",
        symbol="BTCUSDT",
        day=day,
    )
    downloads = {
        source_url: zip_payload,
        checksum_url: f"{digest}  {filename}\n".encode(),
    }

    def official_opener(url: str, **_kwargs: object) -> io.BytesIO:
        return io.BytesIO(downloads[url])

    remote = RemoteRawAggTradeArchive(
        cache_root,
        origin_root,
        official_opener=official_opener,
    )
    assert remote.list_verified_windows(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
    ) == ()
    assert remote.list_selection_windows(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
    ) == (
        RawAggTradeSelectionWindow(
            start_time_ms=DAY_START_MS,
            end_time_ms=DAY_START_MS + 86_400_000 - 1,
            partition_count=1,
        ),
    )
    selection_epoch, selection_windows = remote.selection_snapshot(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
    )
    assert selection_epoch.startswith("sha256:")
    assert selection_windows == remote.list_selection_windows(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
    )
    assert list(cache_root.rglob("*.parquet")) == []

    frozen = remote.freeze_dataset(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        start_time_ms=TRADE_REPLAY_START_MS,
        end_time_ms=TRADE_REPLAY_START_MS + 7_999,
        page_rows=2,
    )

    assert frozen.row_count == 8
    assert frozen.expected_first_agg_trade_id == 1_000
    assert frozen.expected_last_agg_trade_id == 1_007
    assert list(cache_root.rglob("*.parquet"))
    diagnostics = remote.diagnostics()
    assert diagnostics["selection_basis"] == "official_daily_availability"
    assert diagnostics["official_daily_archive_count"] == 1
    assert diagnostics["official_days_downloaded"] == 1
    assert diagnostics["official_rows_imported"] == 8

    def unexpected_download(*_args: object, **_kwargs: object) -> io.BytesIO:
        raise AssertionError("cached official day must not be downloaded again")

    restarted = RemoteRawAggTradeArchive(
        cache_root,
        origin_root,
        official_opener=unexpected_download,
    )
    cached = restarted.freeze_dataset(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        start_time_ms=TRADE_REPLAY_START_MS,
        end_time_ms=TRADE_REPLAY_START_MS + 7_999,
        page_rows=2,
    )

    assert cached.data_epoch == frozen.data_epoch
    restarted_diagnostics = restarted.diagnostics()
    assert restarted_diagnostics["official_cache_hits"] == 1
    assert restarted_diagnostics["official_days_downloaded"] == 0
