from pathlib import Path
import zipfile
import httpx
import pytest
from fastapi import FastAPI
from app.plugin_core_v2.api import create_core_plugin_router
from app.plugin_core_v2.runtime import CorePluginPlatform
from app.plugin_core_v2.runtime_install import is_runtime_bundle
from app.plugin_security_v2.management import LocalManagementGuard
from app.plugin_runtime.registry import default_runtime_registry_path, load_runtime_registry
from tests.plugin_runtime_bundle_testkit import build_hello_bundle


def test_runtime_bundle_routing_requires_distinct_archive_type(tmp_path):
    path = tmp_path / 'bundle.cspkg'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', '{}')
    assert is_runtime_bundle(path)
    with zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('bundle.json', '{}')
    assert not is_runtime_bundle(path)


def test_desktop_registry_is_scoped_to_profile(tmp_path):
    assert default_runtime_registry_path({'CANDLE_DATA_DIR': str(tmp_path)}) == tmp_path / 'plugins/runtime-registry.json'


@pytest.mark.anyio
async def test_guarded_runtime_install_verifies_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv('CANDLE_DATA_DIR', str(tmp_path / 'profile'))
    monkeypatch.delenv('CANDLESCOPE_RUNTIME_REGISTRY', raising=False)
    fixture = build_hello_bundle(tmp_path / 'bundle', version='0.1.0')
    platform = CorePluginPlatform(root=tmp_path / 'platform', host_name='CandleScope', host_version='0.3.0')
    guard = LocalManagementGuard(('http://127.0.0.1:5173',), session_token='runtime-session-token-0123456789abcdef', csrf_token='runtime-csrf-token-0123456789abcdef')
    app = FastAPI()
    app.state.plugin_platform_v2 = platform
    app.state.plugin_platform_v2_management_guard = guard
    app.include_router(create_core_plugin_router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 43200)), base_url='http://127.0.0.1') as client:
        body = fixture.bundle.path.read_bytes()
        route = '/api/v2/plugins/manage/install'
        headers = {'Content-Type': 'application/vnd.candlescope.plugin+zip', 'X-CandleScope-Bundle-SHA256': fixture.bundle.sha256}
        assert (await client.post(route, content=body, headers=headers)).status_code == 403
        headers.update(guard.trusted_headers(user_action='install-bundle'))
        bad = dict(headers, **{'X-CandleScope-Bundle-SHA256': 'sha256:' + '0' * 64})
        assert (await client.post(route, content=body, headers=bad)).status_code == 400
        headers.update(guard.trusted_headers(user_action='install-bundle'))
        response = await client.post(route, content=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()['kind'] == 'script-runtime'
        platform.trust_ux_enabled = True
        headers.update(guard.trusted_headers(user_action='install-bundle'))
        assert (await client.post(route, content=body, headers=headers)).status_code == 409
        platform.trust_ux_enabled = False
        registry = Path(response.json()['installation']['registryPath'])
        assert registry.parent == tmp_path / 'profile/plugins'
        spec = load_runtime_registry(registry).by_id()['hello-runtime']
        assert spec.executable.parent.parent.name == 'venv'
        assert not list((platform.root / 'incoming-v2').glob('*.cspkg'))
