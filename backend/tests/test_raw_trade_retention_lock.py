from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from app.data_engine.market_data.trade_flow_service import (
    _read_verified_archive_rollups,
    _read_verified_repair_page,
)
from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive
from app.data_engine.storage import raw_trade_retention_lock
from app.data_engine.storage.raw_trade_retention_lock import partition_lease
from tests.fixtures.replay.trade_service_fakes import (
    INTERVAL_MS,
    TRADE_REPLAY_START_MS,
    verified_trade_archive,
)


def _dataset(archive: ParquetRawAggTradeArchive):
    return archive.freeze_dataset(
        exchange="binance", market_type="futures", symbol="BTCUSDT",
        start_time_ms=TRADE_REPLAY_START_MS, end_time_ms=TRADE_REPLAY_START_MS + INTERVAL_MS - 1,
    )


def _child(root: Path, reference: Path, ready: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", """
import json, sys
from pathlib import Path
from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive, RawAggTradeDatasetRef
archive = ParquetRawAggTradeArchive(Path(sys.argv[1]), read_only=True)
ref = RawAggTradeDatasetRef.from_dict(json.loads(Path(sys.argv[2]).read_text()))
token = archive.pin_dataset(ref)
Path(sys.argv[3]).touch()
try:
    sys.stdin.read()
finally:
    archive.release_dataset(token)
""", str(root), str(reference), str(ready)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _await_child(process: subprocess.Popen, ready: Path) -> None:
    deadline = time.monotonic() + 20
    while not ready.exists():
        if process.poll() is not None:
            pytest.fail(process.communicate()[1].decode(errors="replace"))
        if time.monotonic() >= deadline:
            pytest.fail("the archive reader did not acquire its lease")
        time.sleep(0.02)


def test_retention_observes_independent_readers_and_releases_after_process_exit(tmp_path):
    root = tmp_path / "archive"
    archive = verified_trade_archive(root)
    anchors = tuple((root / ".trade-retention-locks").iterdir())
    assert len(anchors) == 1  # The day publisher now takes the partition lease.
    assert not archive.verified_retention_inventory(limit=1)["items"][0]["retention_lease_busy"]
    assert tuple((root / ".trade-retention-locks").iterdir()) == anchors
    empty = ParquetRawAggTradeArchive(tmp_path / "empty", read_only=True)
    assert empty.verified_retention_inventory(limit=1)["items"] == []
    assert not empty.root.exists()  # Preview never creates an anchor.
    dataset = _dataset(archive)
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps(dataset.to_dict()))
    lock_path = archive.retention_lease_path(dataset.objects[0].object_id.rsplit("/", 1)[0])

    def day():
        return archive.verified_retention_inventory(limit=1)["items"][0]

    assert not day()["retention_lease_busy"]
    for crash in (False, True):
        ready = tmp_path / f"ready-{crash}"
        child = _child(root, reference, ready)
        try:
            _await_child(child, ready)
            assert day()["active_pin_count"] == 0
            assert day()["retention_lease_busy"]
            assert "PARTITION_RETENTION_LEASE" in day()["protection_reasons"]
            token = archive.pin_dataset(dataset)
            try:
                assert day()["active_pin_count"] == 1
                with pytest.raises(BlockingIOError):
                    with partition_lease(lock_path, shared=False, create=True):
                        pytest.fail("exclusive retention overlapped a reader")
            finally:
                archive.release_dataset(token)
            assert day()["active_pin_count"] == 0 and day()["retention_lease_busy"]
            if crash:
                child.kill()
            _, error = child.communicate(timeout=15)
            assert (child.returncode != 0) is crash, error.decode(errors="replace")
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=15)
        assert not day()["retention_lease_busy"]
        with partition_lease(lock_path, shared=False, create=True):
            assert day()["retention_lease_busy"]
    assert lock_path.exists()


def test_pin_leases_before_validation_and_unwinds_on_failure(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    archive = verified_trade_archive(root)
    dataset = _dataset(archive)
    lock_path = archive.retention_lease_path(dataset.objects[0].object_id.rsplit("/", 1)[0])

    def fail_validation(_dataset):
        with pytest.raises(BlockingIOError):
            with partition_lease(lock_path, shared=False, create=True):
                pytest.fail("validation was outside the retention lease")
        raise RuntimeError("controlled validation failure")

    monkeypatch.setattr(archive, "validate_dataset", fail_validation)
    with pytest.raises(RuntimeError, match="controlled validation failure"):
        archive.pin_dataset(dataset)
    with partition_lease(lock_path, shared=False, create=True):
        with pytest.raises(BlockingIOError):
            ParquetRawAggTradeArchive(root, read_only=True).pin_dataset(dataset)
    assert archive.diagnostics()["active_pins"] == 0


def test_legacy_read_only_archive_keeps_local_pin_without_creating_lock(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    archive = verified_trade_archive(root)
    dataset = _dataset(archive)
    anchor = archive.retention_lease_path(dataset.objects[0].object_id.rsplit("/", 1)[0])
    anchor.unlink()
    anchor.parent.rmdir()
    readonly = ParquetRawAggTradeArchive(root, read_only=True)
    mkdir = Path.mkdir

    def read_only_mount(path, *args, **kwargs):
        if path.name == ".trade-retention-locks":
            raise OSError(errno.EROFS, "controlled read-only mount")
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", read_only_mount)
    token = readonly.pin_dataset(dataset)
    try:
        item = readonly.verified_retention_inventory(limit=1)["items"][0]
        assert item["active_pin_count"] == 1
        assert item["retention_lease_busy"] is False
        assert "UNMANAGED_RETENTION_POLICY" in item["protection_reasons"]
    finally:
        readonly.release_dataset(token)
    assert not (root / ".trade-retention-locks").exists()


def test_pin_retries_a_brief_exclusive_probe(tmp_path, monkeypatch):
    archive = verified_trade_archive(tmp_path / "archive")
    dataset = _dataset(archive)
    lock_path = archive.retention_lease_path(dataset.objects[0].object_id.rsplit("/", 1)[0])
    acquire = raw_trade_retention_lock._acquire
    contention = Event()

    def observe(stream, *, shared):
        try:
            acquire(stream, shared=shared)
        except BlockingIOError:
            if shared:
                contention.set()
            raise

    monkeypatch.setattr(raw_trade_retention_lock, "_acquire", observe)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with partition_lease(lock_path, shared=False, create=True):
            pending = pool.submit(archive.pin_dataset, dataset)
            assert contention.wait(3)
        token = pending.result(timeout=3)
    archive.release_dataset(token)


@pytest.mark.parametrize("operation", ["history", "quiet", "repair"])
@pytest.mark.parametrize("fail_read", [False, True])
def test_tradeflow_reads_hold_partition_lease_until_they_finish(tmp_path, monkeypatch, operation, fail_read):
    root = tmp_path / "archive"
    archive = verified_trade_archive(root)
    minutes = [TRADE_REPLAY_START_MS - INTERVAL_MS if operation == "quiet" else TRADE_REPLAY_START_MS]
    identity = ("binance", "futures", "BTCUSDT")
    method = "_verified_partition_receipt" if operation == "quiet" else "_scan_manifests"
    original = getattr(ParquetRawAggTradeArchive, method)
    entered, release = Event(), Event()

    def pause(instance, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        if fail_read:
            raise OSError("controlled read failure")
        return original(instance, *args, **kwargs)

    monkeypatch.setattr(ParquetRawAggTradeArchive, method, pause)
    # Preview itself reads receipts. Observe the OS lease directly for the
    # quiet-time case, whose barrier intentionally pauses receipt validation.
    def leased():
        key = "exchange=binance/market_type=futures/symbol=BTCUSDT/date=2026-06-01"
        return archive._retention_lease_busy(key)

    with ThreadPoolExecutor(max_workers=1) as pool:
        if operation == "repair":
            read = pool.submit(
                _read_verified_repair_page, root, identity, 1000, 1001,
                (minutes[0], minutes[0] + INTERVAL_MS - 1), defer_if_busy=False,
            )
        else:
            read = pool.submit(_read_verified_archive_rollups, root, identity, minutes)
        try:
            assert entered.wait(5)
            assert leased()
        finally:
            release.set()
        if operation == "repair" and fail_read:
            with pytest.raises(OSError, match="controlled read failure"):
                read.result(timeout=5)
        else:
            result = read.result(timeout=5)
            if operation == "repair":
                assert [row["agg_trade_id"] for row in result.rows] == [1000, 1001]
            elif fail_read:
                assert not result.rows and not result.verified_empty_opens
            elif operation == "quiet":
                assert result.verified_empty_opens == frozenset(minutes)
            else:
                assert len(result.rows) == 1
    assert not leased()


def test_repair_defers_while_partition_retention_is_busy(tmp_path):
    root = tmp_path / "archive"
    archive = verified_trade_archive(root)
    dataset = _dataset(archive)
    path = archive.retention_lease_path(dataset.objects[0].object_id.rsplit("/", 1)[0])
    args = (
        root, ("binance", "futures", "BTCUSDT"), 1000, 1001,
        (TRADE_REPLAY_START_MS, TRADE_REPLAY_START_MS + INTERVAL_MS - 1),
    )
    with partition_lease(path, shared=False, create=True):
        assert _read_verified_repair_page(*args, defer_if_busy=True) is None
        with pytest.raises(BlockingIOError):
            _read_verified_repair_page(*args, defer_if_busy=False)
    assert len(_read_verified_repair_page(*args, defer_if_busy=True).rows) == 2


def test_history_rechecks_receipt_after_getting_partition_lease(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    verified_trade_archive(root)
    receipt = next(root.rglob("_verified_import.json"))
    enter = ParquetRawAggTradeArchive._enter_retention_lease

    def retire_before_read(instance, leases, partition_key, deadline):
        receipt.rename(receipt.with_name("retired.json"))
        return enter(instance, leases, partition_key, deadline)

    monkeypatch.setattr(ParquetRawAggTradeArchive, "_enter_retention_lease", retire_before_read)
    result = _read_verified_archive_rollups(
        root, ("binance", "futures", "BTCUSDT"), [TRADE_REPLAY_START_MS - INTERVAL_MS],
    )
    assert not result.rows and not result.verified_empty_opens
