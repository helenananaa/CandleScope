import asyncio
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.synthetic import router
from app.data_engine.data_manager.models import DataEventType, SeriesKey
from app.data_engine.synthetic_series.service import SyntheticSeriesService
from tests.test_synthetic_series import Source, bar


def setup():
    source = Source([bar(60, 100), bar(120, 106, closed=False)])
    service = SyntheticSeriesService(source)
    app = FastAPI()
    app.state.data_manager = SimpleNamespace(synthetic=service)
    app.include_router(router)
    body = {"source": asdict(SeriesKey("BTCUSDT", "1m")),
        "config": {"transform": "renko", "box_size": 2, "min_tick": 1},
        "anchor": 60, "through": 120}
    return TestClient(app), source, service, body


def test_http_pages_share_source_snapshot_ids_and_reject_client_ohlcv():
    client, source, service, body = setup()
    with client:
        first = client.post("/synthetic/query", json={**body, "limit": 2})
        assert first.status_code == 200
        value = first.json()
        assert value["status"] == "ready" and value["total"] == 3
        page = client.post("/synthetic/query", json={**body, "before": value["before"], "generation": value["generation"]})
        assert page.status_code == 200
        assert len(page.json()["rows"]) == 1
        assert not source.active and not service.instances
        assert client.post("/synthetic/query", json={**body, "rows": [bar(60, 999)]}).status_code == 422
        assert client.post("/synthetic/query", json={**body, "config": {"transform": "pyne"}}).status_code == 409


def test_websocket_snapshot_patch_and_disconnect_release():
    client, source, service, body = setup()
    with client:
        with client.websocket_connect("/synthetic/stream") as websocket:
            websocket.send_json(body)
            first = websocket.receive_json()
            assert first["type"] == "snapshot" and first["total"] == 3
            client.portal.call(source.emit, DataEventType.BAR_UPDATED, bar(120, 104, closed=False))
            changed = websocket.receive_json()
            assert changed["type"] == "patch" and changed["total"] == 2
            assert changed["revision"] == first["revision"] + 1
            assert len(source.active) == 1
        async def drained():
            for _ in range(100):
                if not source.active and not service.instances:
                    return
                await asyncio.sleep(0.01)
        client.portal.call(drained)
        assert not source.active and not service.instances
