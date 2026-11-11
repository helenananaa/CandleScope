from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.data_engine.storage.raw_trade_archive import (
    ParquetRawAggTradeArchive,
    RawAggTradeCursor,
)
from app.replay.trade_import import (
    ReplayTradeImportError,
    _download_official,
    import_local_verified_day,
    import_official_date_range,
    list_official_agg_trade_days,
    official_agg_trade_urls,
)


DAY = date(2026, 6, 1)
START_MS = int(
    datetime.combine(DAY, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    * 1000
)
SYMBOL = "BTCUSDT"


class _StepClock:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class _ShortReadResponse:
    def __init__(self, chunks: list[bytes], *, destination: Path | None = None) -> None:
        self._chunks = iter(chunks)
        self._destination = destination
        self.read_sizes: list[int] = []
        self.observed_partial_size: int | None = None
        self.socket_timeouts: list[float] = []
        socket = type(
            "FakeSocket",
            (),
            {"settimeout": lambda _self, value: self.socket_timeouts.append(value)},
        )()
        raw = type("FakeRaw", (), {"_sock": socket})()
        self.fp = type("FakeFp", (), {"raw": raw})()

    def __enter__(self) -> _ShortReadResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read1(self, size: int) -> bytes:
        self.read_sizes.append(size)
        if self._destination is not None and len(self.read_sizes) == 2:
            temporary = tuple(
                self._destination.parent.glob(f".{self._destination.name}.*.tmp")
            )
            assert len(temporary) == 1
            self.observed_partial_size = temporary[0].stat().st_size
        return next(self._chunks)


def test_official_listing_requires_complete_zip_checksum_pairs_across_pages() -> None:
    prefix = "data/futures/um/daily/aggTrades/BTCUSDT/"

    def xml_page(keys: list[str], *, truncated: bool, marker: str = "") -> bytes:
        contents = "".join(
            f"<Contents><Key>{key}</Key><Size>1</Size></Contents>" for key in keys
        )
        next_marker = f"<NextMarker>{marker}</NextMarker>" if marker else ""
        return (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<ListBucketResult xmlns='http://s3.amazonaws.com/doc/2006-03-01/'>"
            f"{contents}<IsTruncated>{str(truncated).lower()}</IsTruncated>"
            f"{next_marker}</ListBucketResult>"
        ).encode()

    first_marker = f"{prefix}BTCUSDT-aggTrades-2026-06-02.zip"
    pages = {
        None: xml_page(
            [
                f"{prefix}BTCUSDT-aggTrades-2026-06-01.zip",
                f"{prefix}BTCUSDT-aggTrades-2026-06-01.zip.CHECKSUM",
                f"{prefix}BTCUSDT-aggTrades-2026-06-02.zip",
            ],
            truncated=True,
            marker=first_marker,
        ),
        first_marker: xml_page(
            [
                f"{prefix}BTCUSDT-aggTrades-2026-06-02.zip.CHECKSUM",
                f"{prefix}BTCUSDT-aggTrades-2026-06-03.zip",
                f"{prefix}BTCUSDT-aggTrades-2026-06-03.zip.CHECKSUM",
            ],
            truncated=False,
        ),
    }

    def opener(url: str, **_kwargs: object) -> io.BytesIO:
        from urllib.parse import parse_qs, urlparse

        marker = parse_qs(urlparse(url).query).get("marker", [None])[0]
        return io.BytesIO(pages[marker])

    assert list_official_agg_trade_days(
        market_type="futures",
        symbol=SYMBOL,
        as_of_date=date(2026, 6, 3),
        opener=opener,
    ) == (date(2026, 6, 1), date(2026, 6, 2))


def test_official_download_streams_short_reads_with_visible_progress(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "BTCUSDT-aggTrades-2026-06-01.zip"
    response = _ShortReadResponse([b"abc", b"de", b""], destination=destination)

    _download_official(
        "https://data.binance.vision/data/futures/um/daily/aggTrades/"
        "BTCUSDT/BTCUSDT-aggTrades-2026-06-01.zip",
        destination,
        opener=lambda *_args, **_kwargs: response,
        timeout_seconds=5,
        max_bytes=10,
        monotonic=_StepClock([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]),
    )

    assert destination.read_bytes() == b"abcde"
    assert response.observed_partial_size == 3
    assert response.read_sizes == [64 * 1024, 64 * 1024, 64 * 1024]
    assert response.socket_timeouts == pytest.approx([4.9, 4.7, 4.5])


def test_official_download_enforces_total_budget_despite_continuous_short_reads(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "BTCUSDT-aggTrades-2026-06-01.zip"
    response = _ShortReadResponse([b"a", b"b", b"c", b""])

    with pytest.raises(ReplayTradeImportError, match="total time budget"):
        _download_official(
            "https://data.binance.vision/data/futures/um/daily/aggTrades/"
            "BTCUSDT/BTCUSDT-aggTrades-2026-06-01.zip",
            destination,
            opener=lambda *_args, **_kwargs: response,
            timeout_seconds=1,
            max_bytes=10,
            monotonic=_StepClock([0, 0.1, 0.4, 0.7, 1.1]),
        )

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".*.tmp"))
    assert response.socket_timeouts == pytest.approx([0.9, 0.3])


def _rows(*, bad_schema: bool = False, wrong_date: bool = False) -> list[list[str]]:
    timestamp = START_MS - 1 if wrong_date else START_MS + 1_000
    values = [
        ["100", "100.10", "0.50", "1000", "1001", str(timestamp), "true"],
        ["101", "100.20", "0.25", "1002", "1002", str(timestamp), "false"],
        ["102", "100.15", "0.75", "1003", "1005", str(timestamp + 1), "true"],
        ["103", "100.30", "1.00", "1006", "1006", str(timestamp + 2), "false"],
    ]
    if bad_schema:
        values[1] = values[1][:-1]
    return values


def _zip_bytes(rows: list[list[str]], *, header: bool = True) -> tuple[bytes, str]:
    filename = f"{SYMBOL}-aggTrades-{DAY.isoformat()}.zip"
    csv_name = filename.removesuffix(".zip") + ".csv"
    lines: list[str] = []
    if header:
        lines.append(
            "agg_trade_id,price,quantity,first_trade_id,last_trade_id,"
            "transact_time,is_buyer_maker"
        )
    lines.extend(",".join(row) for row in rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(csv_name, "\n".join(lines) + "\n")
    return buffer.getvalue(), filename


def _write_verified_input(
    root: Path,
    rows: list[list[str]],
    *,
    checksum_override: str | None = None,
) -> tuple[Path, Path, str]:
    payload, filename = _zip_bytes(rows)
    zip_path = root / filename
    checksum_path = root / f"{filename}.CHECKSUM"
    zip_path.write_bytes(payload)
    digest = checksum_override or hashlib.sha256(payload).hexdigest()
    checksum_path.write_text(f"{digest}  {filename}\n", encoding="utf-8")
    source_url, _, _ = official_agg_trade_urls(
        market_type="futures",
        symbol=SYMBOL,
        day=DAY,
    )
    return zip_path, checksum_path, source_url


def test_explicit_redownload_resumes_exact_retired_day_without_refetch(tmp_path, monkeypatch):
    from contextlib import nullcontext

    from app.data_engine.storage.raw_trade_archive import VerifiedTradeDayRetired
    from app.replay.trade_import import redownload_official_day

    archive_dir = tmp_path / "archive"
    archive = ParquetRawAggTradeArchive(archive_dir, max_rows_per_file=2)
    zip_path, checksum_path, source_url = _write_verified_input(tmp_path, _rows())
    identity = dict(exchange="binance", market_type="futures", symbol=SYMBOL)
    import_local_verified_day(
        archive, zip_path=zip_path, checksum_path=checksum_path, source_url=source_url, **identity, day=DAY,
    )
    receipt, = archive_dir.glob("exchange=*/market_type=*/symbol=*/date=*/_verified_import.json")
    originals = {file.name: file.read_bytes() for file in receipt.parent.iterdir()}
    expected = archive.freeze_dataset(**identity, start_time_ms=START_MS, end_time_ms=START_MS + 2_000)
    day_id = "sha256:" + hashlib.sha256(originals[receipt.name]).hexdigest()

    def approve(_partition, _receipt):
        return nullcontext(True)

    move = dict(identity=tuple(identity.values()), day=DAY.isoformat(), day_id=day_id, authorize=approve)
    assert archive.move_verified_retention_day(**move, restore=False) == "RETIRED"
    reclaimed = archive.reclaim_retired_verified_day(**move, max_files=4, max_bytes=100_000)
    assert reclaimed.status == "RECLAIMED"
    retired = receipt.parent.with_name(".retired-" + receipt.parent.name)
    checksum_url = source_url + ".CHECKSUM"
    transfer_bytes = zip_path.stat().st_size + checksum_path.stat().st_size
    calls = []

    def opener(url, **_kwargs):
        calls.append(url)
        return io.BytesIO((checksum_path if url == checksum_url else zip_path).read_bytes())

    def redownload(*, restore_budget=reclaimed.removed_logical_bytes, transfer_budget=transfer_bytes):
        return redownload_official_day(
            archive_dir=archive_dir, **identity, day=DAY, day_id=day_id,
            max_download_bytes=transfer_budget, max_restore_bytes=restore_budget, opener=opener,
        )

    with pytest.raises(VerifiedTradeDayRetired):
        import_official_date_range(
            archive_dir=archive_dir, **identity, start=DAY, end=DAY, require_checksum=True, opener=opener,
        )
    assert not calls
    checksum_original = checksum_path.read_bytes()
    checksum_path.write_text(f"{'0' * 64}  {zip_path.name}\n", encoding="utf-8")
    with pytest.raises(ReplayTradeImportError, match="differs from the retired receipt"):
        redownload()
    assert calls == [checksum_url]
    checksum_path.write_bytes(checksum_original)
    calls.clear()
    with pytest.raises(ReplayTradeImportError, match="byte limit"):
        redownload(transfer_budget=transfer_bytes - 1)
    assert calls == [checksum_url, source_url]
    calls.clear()
    assert redownload(restore_budget=reclaimed.removed_logical_bytes - 1) == "RESTORE_BUDGET_EXCEEDED"
    assert sorted(file.name for file in retired.iterdir()) == ["_reclaim_started", receipt.name]
    assert not receipt.parent.exists()

    original_replace = Path.replace
    calls.clear()

    def interrupt(source, target):
        result = original_replace(source, target)
        if target.parent == retired:
            raise OSError("injected after restoring first file")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", interrupt)
        with pytest.raises(OSError, match="after restoring first file"):
            redownload()
    assert calls == [checksum_url, source_url]
    assert not receipt.parent.exists()
    with pytest.raises(VerifiedTradeDayRetired):
        archive.require_day_not_retired(tuple(identity.values()), DAY.isoformat())
    calls.clear()
    assert redownload() == "RESTORED"
    assert redownload() == "RESTORED"
    assert not calls
    assert not retired.exists()
    assert {file.name: file.read_bytes() for file in receipt.parent.iterdir()} == originals
    assert archive.freeze_dataset(**identity, start_time_ms=START_MS, end_time_ms=START_MS + 2_000) == expected


def test_verified_import_is_idempotent_and_freezes_checksum_generation(
    tmp_path: Path,
) -> None:
    archive_dir = tmp_path / "archive"
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    archive = ParquetRawAggTradeArchive(archive_dir, max_rows_per_file=2)
    zip_path, checksum_path, source_url = _write_verified_input(
        input_dir,
        _rows(),
    )

    accepted, metadata = import_local_verified_day(
        archive,
        zip_path=zip_path,
        checksum_path=checksum_path,
        source_url=source_url,
        exchange="binance",
        market_type="futures",
        symbol=SYMBOL,
        day=DAY,
    )
    assert accepted == metadata.row_count == 4
    repeated, repeated_metadata = import_local_verified_day(
        archive,
        zip_path=zip_path,
        checksum_path=checksum_path,
        source_url=source_url,
        exchange="binance",
        market_type="futures",
        symbol=SYMBOL,
        day=DAY,
    )
    assert repeated == 0
    assert repeated_metadata == metadata
    assert len(list(archive_dir.rglob("*.parquet"))) == 2

    dataset = archive.freeze_dataset(
        exchange="binance",
        market_type="futures",
        symbol=SYMBOL,
        start_time_ms=START_MS,
        end_time_ms=START_MS + 59_999,
        page_rows=1,
    )
    assert dataset.row_count == 4
    assert dataset.expected_first_agg_trade_id == 100
    assert dataset.expected_last_agg_trade_id == 103
    assert dataset.source_quality == "binance_public_checksum"
    assert len(dataset.objects) == 2
    assert all(item.source_checksum_sha256 for item in dataset.objects)
    verified_windows = archive.list_verified_windows(
        exchange="binance",
        market_type="futures",
        symbol=SYMBOL,
    )
    assert len(verified_windows) == 1
    assert verified_windows[0].start_time_ms == START_MS
    assert verified_windows[0].end_time_ms == START_MS + 86_400_000 - 1
    assert verified_windows[0].first_agg_trade_id == 100
    assert verified_windows[0].last_agg_trade_id == 103
    assert verified_windows[0].partition_count == 1

    first = archive.scan_page(
        exchange="binance",
        market_type="futures",
        symbol=SYMBOL,
        start_time_ms=dataset.start_time_ms,
        end_time_ms=dataset.end_time_ms,
        start_agg_trade_id=dataset.expected_first_agg_trade_id,
        end_agg_trade_id=dataset.expected_last_agg_trade_id,
        limit=1,
        dataset_ref=dataset,
    )
    assert [row["agg_trade_id"] for row in first.rows] == [100]
    assert first.next_cursor == RawAggTradeCursor(START_MS + 1_000, 100)
    assert not first.exhausted

    token = archive.pin_dataset(dataset)
    assert archive.diagnostics()["active_pins"] == 1
    archive.release_dataset(token)
    archive.release_dataset(token)
    assert archive.diagnostics()["active_pins"] == 0


def test_verified_import_conflicting_checksum_quarantines_partition(
    tmp_path: Path,
) -> None:
    archive = ParquetRawAggTradeArchive(tmp_path / "archive", max_rows_per_file=10)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _write_verified_input(first_dir, _rows())
    second_rows = _rows()
    second_rows[-1][1] = "100.31"
    second = _write_verified_input(second_dir, second_rows)
    import_local_verified_day(
        archive,
        zip_path=first[0],
        checksum_path=first[1],
        source_url=first[2],
        exchange="binance",
        market_type="futures",
        symbol=SYMBOL,
        day=DAY,
    )

    with pytest.raises(RuntimeError, match="conflicts"):
        import_local_verified_day(
            archive,
            zip_path=second[0],
            checksum_path=second[1],
            source_url=second[2],
            exchange="binance",
            market_type="futures",
            symbol=SYMBOL,
            day=DAY,
        )
    assert list((tmp_path / "archive").rglob("_verified_import_conflict.json"))
    assert list((tmp_path / "archive" / "_quarantine").glob("conflict-*"))
    assert archive.list_verified_windows(
        exchange="binance",
        market_type="futures",
        symbol=SYMBOL,
    ) == ()
    with pytest.raises(RuntimeError, match="quarantined"):
        archive.freeze_dataset(
            exchange="binance",
            market_type="futures",
            symbol=SYMBOL,
            start_time_ms=START_MS,
            end_time_ms=START_MS + 59_999,
        )


@pytest.mark.parametrize(
    ("rows", "checksum", "message"),
    [
        (_rows(), "0" * 64, "checksum mismatch"),
        (_rows(bad_schema=True), None, "wrong schema"),
        (_rows(wrong_date=True), None, "requested date"),
    ],
)
def test_failed_official_download_import_is_quarantined(
    tmp_path: Path,
    rows: list[list[str]],
    checksum: str | None,
    message: str,
) -> None:
    payload, filename = _zip_bytes(rows)
    digest = checksum or hashlib.sha256(payload).hexdigest()
    source_url, checksum_url, _ = official_agg_trade_urls(
        market_type="futures",
        symbol=SYMBOL,
        day=DAY,
    )
    objects = {
        source_url: payload,
        checksum_url: f"{digest}  {filename}\n".encode(),
    }

    def opener(url: str, **_kwargs: object) -> io.BytesIO:
        return io.BytesIO(objects[url])

    with pytest.raises((ReplayTradeImportError, RuntimeError), match=message):
        import_official_date_range(
            archive_dir=tmp_path / "archive",
            exchange="binance",
            market_type="futures",
            symbol=SYMBOL,
            start=DAY,
            end=DAY,
            require_checksum=True,
            opener=opener,
        )
    quarantine = list((tmp_path / "archive" / "_quarantine").glob("download-*"))
    assert len(quarantine) == 1
    assert (quarantine[0] / "report.json").is_file()


def test_disabled_archive_does_not_touch_lazy_pyarrow_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.data_engine.storage import raw_trade_archive as archive_module

    def fail_loader() -> tuple[object, object]:
        raise AssertionError("lazy PyArrow loader was touched in disabled mode")

    monkeypatch.setattr(archive_module, "_load_pyarrow", fail_loader)
    disabled = archive_module.DisabledRawAggTradeArchive()
    assert disabled.diagnostics()["backend"] == "disabled"
    assert disabled.scan_range(
        exchange="binance",
        market_type="futures",
        symbol=SYMBOL,
    ) == []
