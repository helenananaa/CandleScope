from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import local_data
from app.local_data import LocalDatasetService


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(local_data, "RUNTIME_MODE", "LOCAL_OFFLINE")
    app = FastAPI()
    app.include_router(local_data.router, prefix="/api/v1")
    service = LocalDatasetService(tmp_path / "local-data")
    service.start()
    app.state.local_data_service = service
    return TestClient(app)


def test_import_list_and_query_local_csv(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    csv_body = (
        "time,open,high,low,close,volume\n"
        "1704067200000,100,102,99,101,10\n"
        "1704067260000,101,103,100,102,11\n"
    )
    response = client.post(
        "/api/v1/local/imports/csv",
        params={
            "name": "Imported BTC",
            "symbol": "BTC-USDT",
            "interval": "1m",
            "timestamp_unit": "ms",
        },
        content=csv_body,
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 201, response.text
    manifest = response.json()

    listed = client.get("/api/v1/local/datasets")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    latest = client.get(
        f"/api/v1/local/datasets/{manifest['dataset_id']}/klines/latest",
        params={"interval": "1m", "limit": 100},
    )
    assert latest.status_code == 200
    assert [row["close"] for row in latest.json()["data"]] == [101.0, 102.0]
    assert latest.json()["source"] == "local_dataset"


def test_event_time_resolution_endpoint_preserves_input_order(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    imported = client.post(
        "/api/v1/local/imports/csv",
        params={
            "name": "Event bars",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "timestamp_unit": "ms",
        },
        content=(
            "time,open,high,low,close\n"
            "1704067200000,100,102,99,101\n"
            "1704067260000,101,103,100,102\n"
        ),
        headers={"content-type": "text/csv"},
    ).json()

    response = client.post(
        f"/api/v1/local/datasets/{imported['dataset_id']}/events/resolve-times",
        json={
            "data_epoch": imported["data_epoch"],
            "times_ms": [1704067230000, 1704067260000, 1704067400000],
            "mode": "containing",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [result["input_index"] for result in body["results"]] == [0, 1, 2]
    assert [result["matched"] for result in body["results"]] == [True, True, False]
    assert body["matched"] == 2
    assert body["rejected"] == 1


def test_import_accepts_default_volume_mapping_for_tradingview(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/local/imports/csv",
        params={
            "name": "TradingView BTC",
            "symbol": "BINANCE:BTCUSDT",
            "interval": "1m",
            "timestamp_unit": "s",
        },
        content=(
            "time,open,high,low,close,Volume\n"
            "1785608340,62632.54,62640,62600.01,62603.16,18.97148\n"
            "1785608400,62617.85,62630,62533.54,62569.41,26.64177\n"
        ),
        headers={"content-type": "text/csv"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["rows"] == 2


def test_import_exposes_ohlc_only_without_fabricating_volume(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    csv_body = (
        "time,open,high,low,close\n"
        "1739577600,97500,98000,97000,97750\n"
        "1739664000,97750,99000,97500,98500\n"
    )
    imported = client.post(
        "/api/v1/local/imports/csv",
        params={
            "name": "TradingView OHLC only",
            "symbol": "BINANCE:BTCUSDT",
            "interval": "1d",
            "timestamp_unit": "s",
        },
        content=csv_body,
        headers={"content-type": "text/csv"},
    )

    assert imported.status_code == 201, imported.text
    assert imported.json()["volume_available"] is False
    dataset_id = imported.json()["dataset_id"]
    latest = client.get(
        f"/api/v1/local/datasets/{dataset_id}/klines/latest",
        params={"interval": "1d", "limit": 10},
    )
    assert latest.status_code == 200
    assert latest.json()["volume_available"] is False
    assert [row["volume"] for row in latest.json()["data"]] == [None, None]

    required = client.post(
        "/api/v1/local/imports/csv",
        params={
            "name": "Volume required",
            "symbol": "BINANCE:BTCUSDT",
            "interval": "1d",
            "timestamp_unit": "s",
            "volume_required": True,
        },
        content=csv_body,
        headers={"content-type": "text/csv"},
    )
    assert required.status_code == 422
