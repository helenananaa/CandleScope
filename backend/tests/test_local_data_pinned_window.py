"""Bounded immutable initialization input; no active-revision page switching."""
from dataclasses import replace
import sqlite3

import pytest

from app.local_data.service import LocalDatasetError, LocalDatasetService, LocalImportOptions

START = 1704067200000
STEP = 60000
PRICE = "100.123456789123456789"


def publish(tmp_path, *, missing=(), volume=True, final=True, count=1005):
    service = LocalDatasetService(tmp_path / "data with spaces")
    csv = tmp_path / "bars.csv"
    options = LocalImportOptions(name="initial", symbol="BTCUSDT", interval="1m",
        timestamp_unit="ms", last_bar_closed=final)
    csv.write_text(("time,open,high,low,close" + (",volume" if volume else "") + "\n") + "".join(
        f"{START+i*STEP},{PRICE},101,99,{PRICE}" + (",3" if volume else "") + "\n"
        for i in range(count) if i not in missing))
    manifest = service.import_csv(csv, options)
    return service, csv, options, manifest


def opened(service, manifest, *, count=1005):
    return service.open_pinned_bar_window(manifest["dataset_id"], data_epoch=manifest["data_epoch"],
        interval="1m", from_ms=START, through_ms=START+count*STEP-1)


def test_old_revision_pages_and_restart_keep_decimal_input_and_fixed_cutoff(tmp_path, monkeypatch):
    service, csv, options, manifest = publish(tmp_path)
    hash_file = service._file_sha256
    hashed = []
    def counted(path):
        hashed.append(path)
        return hash_file(path)
    monkeypatch.setattr(service, "_file_sha256", counted)
    with opened(service, manifest, count=1002) as reader:
        assert len(hashed) == 1
        first = reader.read_window(start_ms=START)
        assert len(first) == 1000 and first[0]["close"] == PRICE
        csv.write_text(csv.read_text().replace(PRICE, "100.9"))
        newer = service.import_csv(csv, replace(options, dataset_id=manifest["dataset_id"]))
        assert newer["data_epoch"] != manifest["data_epoch"]
        hashed.clear()
        tail = reader.read_window(start_ms=START+1000*STEP)
        assert [row["open_time_ms"] for row in tail] == [START+1000*STEP, START+1001*STEP]
        assert all(row["close"] == PRICE for row in tail)
        assert reader.read_window(start_ms=START+1002*STEP) == []
        assert hashed == []
    service = LocalDatasetService(service.root)
    with opened(service, manifest, count=1002) as restored:
        assert restored.read_window(start_ms=START+1000*STEP) == tail
    assert service.get_manifest(manifest["dataset_id"])["data_epoch"] == newer["data_epoch"]


def test_missing_input_cannot_skip_forward_or_be_filled_from_new_revision(tmp_path):
    service, csv, options, manifest = publish(tmp_path, missing={1000})
    with opened(service, manifest) as reader:
        assert len(reader.read_window(start_ms=START)) == 1000
        with pytest.raises(LocalDatasetError, match="source gap"):
            reader.read_window(start_ms=START+1000*STEP)
        # Old input stays unavailable even when the current version repairs it.
        csv.write_text(csv.read_text() + f"{START+1000*STEP},100,101,99,100,3\n")
        lines = csv.read_text().splitlines()
        csv.write_text(lines[0]+"\n"+"\n".join(sorted(lines[1:]))+"\n")
        service.import_csv(csv, replace(options, dataset_id=manifest["dataset_id"]))
        with pytest.raises(LocalDatasetError, match="source gap"):
            reader.read_window(start_ms=START+1000*STEP)


def test_reader_is_readonly_bounded_and_closed_explicitly(tmp_path):
    service, _, _, manifest = publish(tmp_path)
    reader = opened(service, manifest)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        reader._connection.execute("DELETE FROM bars")
    for kwargs in ({"limit":1001}, {"limit":0}, {"limit":True}, {"start_ms":START-STEP}, {"start_ms":START+1}):
        with pytest.raises(LocalDatasetError, match="Invalid bounded"):
            reader.read_window(**{"start_ms":START, **kwargs})
    reader.close(); reader.close()
    with pytest.raises(LocalDatasetError, match="closed"):
        reader.read_window(start_ms=START)


@pytest.mark.parametrize("volume,final", [(False,True), (True,False)])
def test_forming_or_volume_missing_input_rejected_before_execution(tmp_path, volume, final):
    service, _, _, manifest = publish(tmp_path, volume=volume, final=final)
    with pytest.raises(LocalDatasetError, match="closed OHLCV"):
        opened(service, manifest)


def test_corrupt_or_removed_pinned_revision_has_no_active_version_fallback(tmp_path):
    service, _, _, manifest = publish(tmp_path)
    directory = service._specific_revision_dir(manifest["dataset_id"],manifest["data_epoch"])
    with (directory / "bars.sqlite").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(LocalDatasetError, match="hash changed"):
        opened(service, manifest)
    (directory / "bars.sqlite").unlink()
    with pytest.raises(LocalDatasetError, match="unreadable"):
        opened(service, manifest)
