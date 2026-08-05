from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.local_data import LocalDatasetError, LocalDatasetService, LocalImportOptions


CSV_WITH_GAP = """time,open,high,low,close,volume
1704067200000,100,102,99,101,10
1704067260000,101,104,100,103,12
1704067380000,103,105,102,104,8
"""


def _write_csv(path: Path, content: str = CSV_WITH_GAP) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_import_publishes_immutable_revision_and_terminal_gap(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local-data")
    dataset_id = "local-0123456789abcdef0123456789abcdef"
    manifest = service.import_csv(
        _write_csv(tmp_path / "bars.csv"),
        LocalImportOptions(
            name="BTC sample",
            symbol="BTC-USDT",
            interval="1m",
            timestamp_unit="ms",
            dataset_id=dataset_id,
        ),
    )

    assert manifest["dataset_id"] == dataset_id
    assert manifest["data_epoch"].startswith("sha256:")
    assert manifest["rows"] == 3
    assert manifest["excluded_range_count"] == 1
    revision = manifest["data_epoch"].removeprefix("sha256:")
    revision_dir = service.root / dataset_id / revision
    assert {path.name for path in revision_dir.iterdir()} == {
        "bars.sqlite",
        "manifest.json",
        "quality-report.json",
        "import-receipt.json",
    }
    quality = json.loads(
        (revision_dir / "quality-report.json").read_text(encoding="utf-8")
    )
    assert quality["status"] == "accepted_with_gaps"
    assert quality["excluded_ranges"] == [
        {
            "start_ms": 1704067320000,
            "end_ms": 1704067380000,
            "reason": "source_gap",
            "missing_bars": 1,
        }
    ]

    page = service.query(dataset_id, interval="1m", limit=2)
    assert [row["time"] for row in page["data"]] == [1704067260, 1704067380]
    assert page["has_more"] is True
    assert page["retryable"] is False
    assert page["missing_ranges"] == []
    assert page["excluded_ranges"][0]["reason"] == "source_gap"

    older = service.query(
        dataset_id,
        interval="1m",
        limit=2,
        before_ms=page["next_before_ms"],
    )
    assert [row["time"] for row in older["data"]] == [1704067200]
    assert older["history_state"] == "exhausted"
    assert older["terminal_reason"] == "dataset_boundary"


def test_import_rejects_duplicates_without_publishing(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local-data")
    csv_path = _write_csv(
        tmp_path / "duplicate.csv",
        "time,open,high,low,close,volume\n"
        "1704067200000,1,2,1,2,3\n"
        "1704067200000,2,3,2,3,4\n",
    )

    with pytest.raises(LocalDatasetError, match="duplicate timestamp"):
        service.import_csv(
            csv_path,
            LocalImportOptions(
                name="bad",
                symbol="BAD",
                interval="1m",
                timestamp_unit="ms",
            ),
        )

    assert service.list_datasets() == []


def test_query_rejects_interval_not_present_in_dataset(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local-data")
    manifest = service.import_csv(
        _write_csv(tmp_path / "bars.csv"),
        LocalImportOptions(
            name="BTC sample",
            symbol="BTC-USDT",
            interval="1m",
            timestamp_unit="ms",
        ),
    )

    with pytest.raises(LocalDatasetError) as error:
        service.query(manifest["dataset_id"], interval="5m", limit=10)
    assert error.value.code == "interval_not_available"


def test_import_accepts_tradingview_column_case_and_session_phase(
    tmp_path: Path,
) -> None:
    service = LocalDatasetService(tmp_path / "local-data")
    manifest = service.import_csv(
        _write_csv(
            tmp_path / "tradingview.csv",
            "time,open,high,low,close,Volume\n"
            "1762779600,4097.47,4106.01,4074.07,4083.477,311188\n"
            "1762786800,4083.467,4095.751,4077.595,4094.88,286978\n"
            "1762801200,4095.001,4115.83,4093.17,4110.087,222317\n",
        ),
        LocalImportOptions(
            name="TradingView GOLD",
            symbol="TVC:GOLD",
            interval="2h",
            timestamp_unit="s",
        ),
    )

    assert manifest["rows"] == 3
    assert manifest["alignment"] == "fixed_epoch"
    assert manifest["alignment_offset_ms"] == 3_600_000
    assert manifest["excluded_range_count"] == 1
    revision = manifest["data_epoch"].removeprefix("sha256:")
    receipt = json.loads(
        (
            service.root
            / manifest["dataset_id"]
            / revision
            / "import-receipt.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["columns"]["volume_column"] == "Volume"


def test_import_rejects_timestamp_phase_change(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local-data")
    csv_path = _write_csv(
        tmp_path / "phase-change.csv",
        "time,open,high,low,close,Volume\n"
        "1762779600,1,2,1,2,3\n"
        "1762790400,2,3,2,3,4\n",
    )

    with pytest.raises(LocalDatasetError, match="timestamp phase"):
        service.import_csv(
            csv_path,
            LocalImportOptions(
                name="bad phase",
                symbol="BAD",
                interval="2h",
                timestamp_unit="s",
            ),
        )


def test_import_preserves_missing_volume_as_unavailable(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local-data")
    manifest = service.import_csv(
        _write_csv(
            tmp_path / "ohlc-only.csv",
            "time,open,high,low,close\n"
            "1739577600,97500,98000,97000,97750\n"
            "1739664000,97750,99000,97500,98500\n",
        ),
        LocalImportOptions(
            name="TradingView OHLC only",
            symbol="BINANCE:BTCUSDT",
            interval="1d",
            timestamp_unit="s",
        ),
    )

    assert manifest["schema_version"] == 2
    assert manifest["volume_available"] is False
    page = service.query(manifest["dataset_id"], interval="1d", limit=10)
    assert page["volume_available"] is False
    assert [row["volume"] for row in page["data"]] == [None, None]
    revision = manifest["data_epoch"].removeprefix("sha256:")
    quality = json.loads(
        (
            service.root
            / manifest["dataset_id"]
            / revision
            / "quality-report.json"
        ).read_text(encoding="utf-8")
    )
    assert quality["missing_volume_rows"] == 2


def test_import_can_require_volume(tmp_path: Path) -> None:
    service = LocalDatasetService(tmp_path / "local-data")
    with pytest.raises(LocalDatasetError, match="columns not found: volume"):
        service.import_csv(
            _write_csv(
                tmp_path / "ohlc-only.csv",
                "time,open,high,low,close\n"
                "1739577600,97500,98000,97000,97750\n",
            ),
            LocalImportOptions(
                name="Volume required",
                symbol="BINANCE:BTCUSDT",
                interval="1d",
                timestamp_unit="s",
                volume_required=True,
            ),
        )
