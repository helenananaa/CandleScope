from types import SimpleNamespace
import asyncio
from fastapi import FastAPI, Request
from app.api.v1 import settings

class Session:
    def __init__(self, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def get(self, *args, **kwargs): return self
    status = 200


def test_network_success_does_not_imply_engine_ready(monkeypatch):
    monkeypatch.setattr(settings.aiohttp, 'ClientSession', Session)
    app = FastAPI()
    request = Request({'type': 'http', 'app': app})
    result = asyncio.run(settings.test_proxy_connection(settings.ProxyTestRequest(mode='none'), request))
    assert result['success'] is True
    assert len(result['results']) == 3
    assert result['data_engine'] == 'not_initialized'
    for started, expected in [(True, 'ready'), (False, 'not_started'), (None, 'unknown')]:
        app.state.data_manager = SimpleNamespace(health_snapshot=lambda: {'started': started})
        assert settings._data_engine_status(request) == expected
    def broken(): raise RuntimeError('health failure')
    app.state.data_manager = SimpleNamespace(health_snapshot=broken)
    assert settings._data_engine_status(request) == 'error'
