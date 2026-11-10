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
    dataset = _dataset(archive)
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps(dataset.to_dict()))
    lock_path = archive.retention_lease_path(dataset.objects[0].object_id.rsplit("/", 1)[0])

    def day():
        return archive.verified_retention_inventory(limit=1)["items"][0]

    assert not day()["retention_lease_busy"]
    assert not lock_path.exists()  # Preview never creates an anchor.
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
    dataset = _dataset(verified_trade_archive(root))
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
