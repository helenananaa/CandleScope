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
