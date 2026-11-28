"""Settings → Data sources: keys in the host vault, masked, ahead of the environment."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.data_sources import credentials as credentials_module
from app.data_sources.api import router
from app.data_sources.credentials import DataSourceCredentialError, DataSourceCredentials
from app.data_sources.runtime import start_data_source_credentials, stop_data_source_credentials
from app.exchanges.plugins.twelvedata.adapter import (
    TwelveDataConfigurationError,
    twelve_data_api_key,
    twelve_data_auth_headers,
)
from app.exchanges.plugins.twelvedata.credential_check import TwelveDataCheckError, usage_summary
from app.exchanges.plugins.twelvedata.plugin import TwelveDataPlugin
from app.host_credentials import CredentialVaultError
from app.plugin_security_v2.management import LocalManagementGuard

KEY = "0123456789abcdef0123456789abWXYZ"
NEW_KEY = "fedcba9876543210fedcba98765NEW1"
ENV_KEY = "environment-key-000000000000ENVK"


class Vault:
    def __init__(self):
        self.records = {}
        self.fail_store = False
        self.fail_delete = False
        self.reads = 0

    def store(self, record, secret):
        if self.fail_store:
            raise CredentialVaultError("CREDENTIAL_STORE_FAILED")
        if record in self.records:
            raise CredentialVaultError("CREDENTIAL_STORE_FAILED")
        self.records[record] = secret

    def read(self, record):
        self.reads += 1
        if record not in self.records:
            raise CredentialVaultError("CREDENTIAL_NOT_FOUND")
        return self.records[record]

    def delete(self, record):
        if self.fail_delete:
            raise CredentialVaultError("CREDENTIAL_DELETE_FAILED")
        self.records.pop(record, None)


def service(tmp_path, vault=None, environment=None, supported=True):
    vault = vault if vault is not None else Vault()
    env = dict(environment or {})
    owner = DataSourceCredentials(tmp_path / "data-sources", vault_factory=lambda root: vault,
                                  environment=lambda name: env.get(name, ""),
                                  platform_supported=supported, clock=lambda: 1_700_000_000)
    return owner, vault, env


def field(owner):
    return owner.status()["sources"][0]["fields"][0]


@pytest.fixture(autouse=True)
def no_active_service():
    credentials_module.activate(None)
    yield
    credentials_module.activate(None)


def test_saved_key_is_masked_everywhere_outside_the_vault(tmp_path):
    owner, vault, _ = service(tmp_path)
    owner.save("twelvedata", "apiKey", KEY)
    status = field(owner)
    assert status["saved"] and status["active"] == "saved"
    assert status["savedHint"] == "WXYZ" and status["activeHint"] == "WXYZ"
    assert status["savedAtMs"] == 1_700_000_000_000
    assert KEY not in json.dumps(owner.status())
    index = (tmp_path / "data-sources" / "credentials.json").read_bytes()
    assert KEY.encode() not in index and KEY[:-4].encode() not in index
    assert list(vault.records.values()) == [KEY]
    assert owner.secret("twelvedata", "apiKey") == KEY


def test_short_keys_show_no_characters(tmp_path):
    owner, _, _ = service(tmp_path)
    owner.save("twelvedata", "apiKey", "demo")  # Twelve Data's public trial key
    assert field(owner)["active"] == "saved"
    owner.save("twelvedata", "apiKey", "short-k1")
    assert field(owner)["savedHint"] is None and field(owner)["activeHint"] is None


def test_saved_key_takes_precedence_over_the_environment_and_removal_falls_back(tmp_path):
    owner, vault, _ = service(tmp_path, environment={"INGESTION_TWELVE_DATA_API_KEY": ENV_KEY})
    credentials_module.activate(owner)
    config = SimpleNamespace(twelve_data_api_key=ENV_KEY)
    assert field(owner)["active"] == "environment" and field(owner)["activeHint"] == "ENVK"
    assert twelve_data_api_key(config) == ENV_KEY

    owner.save("twelvedata", "apiKey", KEY)
    assert field(owner)["active"] == "saved" and field(owner)["environmentSet"] is True
    assert twelve_data_api_key(config) == KEY
    assert twelve_data_auth_headers(config)["Authorization"] == f"apikey {KEY}"
    assert TwelveDataPlugin.provider_stream_enabled(config, None)

    owner.remove("twelvedata", "apiKey")
    assert vault.records == {}
    assert field(owner)["saved"] is False and field(owner)["active"] == "environment"
    assert twelve_data_api_key(config) == ENV_KEY


def test_without_a_saved_key_or_environment_twelve_data_is_not_configured(tmp_path):
    owner, _, _ = service(tmp_path)
    credentials_module.activate(owner)
    config = SimpleNamespace(twelve_data_api_key="")
    with pytest.raises(TwelveDataConfigurationError, match="Settings"):
        twelve_data_api_key(config)
    assert not TwelveDataPlugin.provider_stream_enabled(config, None)
    owner.save("twelvedata", "apiKey", KEY)
    assert twelve_data_api_key(config) == KEY
    owner.remove("twelvedata", "apiKey")
    with pytest.raises(TwelveDataConfigurationError):
        twelve_data_api_key(config)
    assert field(owner)["active"] is None


def test_replacing_a_key_deletes_the_old_record(tmp_path):
    owner, vault, _ = service(tmp_path)
    owner.save("twelvedata", "apiKey", KEY)
    owner.save("twelvedata", "apiKey", NEW_KEY)
    assert list(vault.records.values()) == [NEW_KEY]
    assert owner.secret("twelvedata", "apiKey") == NEW_KEY
    assert field(owner)["savedHint"] == "NEW1"
    assert owner.status()["deletionPending"] is False


def test_a_failed_store_keeps_the_previous_key_and_leaks_no_record(tmp_path):
    owner, vault, _ = service(tmp_path)
    owner.save("twelvedata", "apiKey", KEY)
    vault.fail_store = True
    with pytest.raises(DataSourceCredentialError, match="CREDENTIAL_STORE_FAILED"):
        owner.save("twelvedata", "apiKey", NEW_KEY)
    assert owner.secret("twelvedata", "apiKey") == KEY
    assert list(vault.records.values()) == [KEY]
    index = json.loads((tmp_path / "data-sources" / "credentials.json").read_text())
    assert index["retired"] == []


def test_a_staged_record_from_a_stopped_process_is_deleted_at_the_next_start(tmp_path):
    owner, vault, _ = service(tmp_path)
    owner.save("twelvedata", "apiKey", KEY)
    # Simulate a stop after the vault write but before the index named it.
    index_path = tmp_path / "data-sources" / "credentials.json"
    index = json.loads(index_path.read_text())
    vault.records["c" * 32] = NEW_KEY
    index["retired"].append("c" * 32)
    index_path.write_text(json.dumps(index))
    restarted, _, _ = service(tmp_path, vault=vault)
    restarted.load()
    assert list(vault.records.values()) == [KEY]
    assert restarted.secret("twelvedata", "apiKey") == KEY


def test_removal_forgets_the_key_even_when_the_os_deletion_must_wait(tmp_path):
    owner, vault, _ = service(tmp_path)
    credentials_module.activate(owner)
    owner.save("twelvedata", "apiKey", KEY)
    vault.fail_delete = True
    owner.remove("twelvedata", "apiKey")
    assert owner.secret("twelvedata", "apiKey") is None
    assert field(owner)["saved"] is False
    assert owner.status()["deletionPending"] is True
    with pytest.raises(TwelveDataConfigurationError):
        twelve_data_api_key(SimpleNamespace(twelve_data_api_key=""))
    vault.fail_delete = False
    restarted, _, _ = service(tmp_path, vault=vault)
    restarted.load()
    assert vault.records == {} and restarted.status()["deletionPending"] is False
    assert restarted.secret("twelvedata", "apiKey") is None


def test_a_restart_reads_the_saved_key_once(tmp_path):
    owner, vault, _ = service(tmp_path)
    owner.save("twelvedata", "apiKey", KEY)
    restarted, _, _ = service(tmp_path, vault=vault)
    assert restarted.secret("twelvedata", "apiKey") is None
    restarted.load()
    assert restarted.secret("twelvedata", "apiKey") == KEY and vault.reads == 1
    for _ in range(3):
        restarted.secret("twelvedata", "apiKey")
        restarted.status()
    assert vault.reads == 1


def test_a_missing_os_record_is_reported_and_the_environment_still_works(tmp_path):
    owner, vault, _ = service(tmp_path)
    owner.save("twelvedata", "apiKey", KEY)
    vault.records.clear()
    restarted, _, _ = service(tmp_path, vault=vault, environment={"INGESTION_TWELVE_DATA_API_KEY": ENV_KEY})
    restarted.load()
    status = field(restarted)
    assert status["saved"] and status["savedError"] == "CREDENTIAL_NOT_FOUND"
    assert status["active"] == "environment"
    restarted.save("twelvedata", "apiKey", NEW_KEY)
    assert field(restarted)["savedError"] is None and field(restarted)["active"] == "saved"


def test_an_unreadable_index_is_kept_aside_when_a_new_key_is_saved(tmp_path):
    root = tmp_path / "data-sources"
    root.mkdir()
    (root / "credentials.json").write_text("{not json")
    owner, vault, _ = service(tmp_path)
    owner.load()
    assert owner.status()["error"] == "CREDENTIAL_INDEX_INVALID"
    owner.save("twelvedata", "apiKey", KEY)
    assert owner.status()["error"] is None and owner.secret("twelvedata", "apiKey") == KEY
    kept = [path for path in root.iterdir() if path.name.startswith("credentials.json.invalid-")]
    assert len(kept) == 1 and kept[0].read_text() == "{not json"


def test_systems_without_a_vault_still_use_the_environment(tmp_path):
    owner, _, _ = service(tmp_path, environment={"INGESTION_TWELVE_DATA_API_KEY": ENV_KEY}, supported=False)
    owner.load()
    status = owner.status()
    assert status["vaultAvailable"] is False and status["error"] == "CREDENTIAL_VAULT_UNAVAILABLE"
    assert status["sources"][0]["fields"][0]["active"] == "environment"
    with pytest.raises(DataSourceCredentialError, match="CREDENTIAL_VAULT_UNAVAILABLE"):
        owner.save("twelvedata", "apiKey", KEY)


@pytest.mark.parametrize("value", ["", "abc", " " + KEY, KEY + "\n", "é" * 12, "x" * 257, 12345678])
def test_invalid_values_are_rejected_before_the_vault(tmp_path, value):
    owner, vault, _ = service(tmp_path)
    with pytest.raises(DataSourceCredentialError, match="CREDENTIAL_VALUE_INVALID"):
        owner.save("twelvedata", "apiKey", value)
    assert vault.records == {} and not (tmp_path / "data-sources" / "credentials.json").exists()


def test_unknown_sources_and_fields_are_rejected(tmp_path):
    owner, _, _ = service(tmp_path)
    for source, name in [("alpaca", "apiKey"), ("twelvedata", "secret")]:
        with pytest.raises(DataSourceCredentialError, match="DATA_SOURCE_FIELD_UNKNOWN"):
            owner.save(source, name, KEY)
        with pytest.raises(DataSourceCredentialError, match="DATA_SOURCE_FIELD_UNKNOWN"):
            owner.remove(source, name)


def test_startup_publishes_saved_keys_and_shutdown_withdraws_them(tmp_path):
    vault = Vault()
    owner, _, _ = service(tmp_path, vault=vault)
    owner.save("twelvedata", "apiKey", KEY)
    app = FastAPI()

    def factory(root):
        return service(tmp_path, vault=vault)[0]

    asyncio.run(start_data_source_credentials(app, tmp_path / "data-sources", factory=factory))
    assert twelve_data_api_key(SimpleNamespace(twelve_data_api_key=ENV_KEY)) == KEY
    stop_data_source_credentials(app)
    assert twelve_data_api_key(SimpleNamespace(twelve_data_api_key=ENV_KEY)) == ENV_KEY


def test_usage_summary_reads_plan_and_credits():
    summary = usage_summary({"timestamp": "2026-11-26 09:52:42", "current_usage": 3, "plan_limit": 8,
                             "daily_usage": 40, "plan_daily_limit": 800, "plan_category": "basic"})
    assert summary == {"plan": "basic", "minuteCredits": {"used": 3, "limit": 8},
                       "dailyCredits": {"used": 40, "limit": 800}, "websocketSymbols": 8}
    assert usage_summary({"current_usage": 0, "plan_limit": 2584, "plan_category": "ultra"})["dailyCredits"] is None
    with pytest.raises(TwelveDataCheckError, match="DATA_SOURCE_KEY_REJECTED"):
        usage_summary({"code": 401, "message": "**apikey** parameter is incorrect", "status": "error"})
    with pytest.raises(TwelveDataCheckError, match="DATA_SOURCE_RESPONSE_INVALID"):
        usage_summary({"plan_category": "basic"})


def api_fixture(tmp_path, monkeypatch, environment=None):
    owner, vault, env = service(tmp_path, environment=environment)
    credentials_module.activate(owner)
    app = FastAPI()
    guard = LocalManagementGuard(["http://127.0.0.1:61234"])
    app.state.plugin_platform_v2_management_guard = guard
    app.state.data_source_credentials = owner
    app.include_router(router, prefix="/api/v1")
    checked = []

    async def fake_check(api_key, config=None):
        checked.append(api_key)
        if api_key == "rejected-key-0000":
            raise TwelveDataCheckError("DATA_SOURCE_KEY_REJECTED")
        return {"plan": "basic", "minuteCredits": {"used": 1, "limit": 8}, "dailyCredits": None,
                "websocketSymbols": 8}

    monkeypatch.setattr("app.exchanges.plugins.twelvedata.credential_check.check_twelve_data_key", fake_check)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 61235))
    return owner, vault, guard, transport, checked


def test_routes_require_the_desktop_session_and_never_return_the_key(tmp_path, monkeypatch):
    async def run():
        owner, vault, guard, transport, checked = api_fixture(tmp_path, monkeypatch)
        base = "/api/v1/data-sources"
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            assert (await api.get(base)).status_code == 403
            headers = guard.trusted_headers(user_action="data-sources.save")
            for name in ("Origin", "X-CandleScope-Plugin-Session", "X-CandleScope-CSRF", "X-CandleScope-User-Action"):
                partial = {key: value for key, value in headers.items() if key != name}
                response = await api.post(f"{base}/twelvedata/credentials/apiKey", json={"value": KEY}, headers=partial)
                assert response.status_code == 403
            assert vault.records == {}
            evil = {**headers, "Origin": "http://evil.example"}
            assert (await api.post(f"{base}/twelvedata/credentials/apiKey", json={"value": KEY},
                                   headers=evil)).status_code == 403

            response = await api.post(f"{base}/twelvedata/credentials/apiKey", json={"value": KEY}, headers=headers)
            assert response.status_code == 200 and KEY not in response.text
            assert response.json()["sources"][0]["fields"][0]["savedHint"] == "WXYZ"
            response = await api.get(base, headers=headers)
            assert response.status_code == 200 and KEY not in response.text
            assert response.json()["sources"][0]["fields"][0]["active"] == "saved"

            response = await api.post(f"{base}/twelvedata/check", headers=guard.trusted_headers(
                user_action="data-sources.check"))
            assert response.status_code == 200 and response.json()["source"] == "saved"
            assert response.json()["usage"]["minuteCredits"] == {"used": 1, "limit": 8}
            assert checked == [KEY] and KEY not in response.text

            response = await api.post(f"{base}/twelvedata/credentials/apiKey/remove", headers=guard.trusted_headers(
                user_action="data-sources.remove"))
            assert response.status_code == 200 and response.json()["sources"][0]["fields"][0]["saved"] is False
            assert vault.records == {}
            response = await api.post(f"{base}/twelvedata/check", headers=headers)
            assert response.status_code == 409 and response.json()["error"]["code"] == "DATA_SOURCE_KEY_MISSING"
    asyncio.run(run())


def test_rejected_inputs_are_never_echoed(tmp_path, monkeypatch):
    async def run():
        owner, vault, guard, transport, _ = api_fixture(tmp_path, monkeypatch)
        base = "/api/v1/data-sources/twelvedata/credentials/apiKey"
        headers = guard.trusted_headers(user_action="data-sources.save")
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            for content in ['{"value":"SENTINEL1","value":"SENTINEL2"}', '{"value":"SENTINEL1","extra":1}',
                            '"SENTINEL1"', "SENTINEL" * 400, '{"value":"SENTINEL\\u00e9xxxxxxx"}']:
                response = await api.post(base, content=content, headers=headers)
                assert response.status_code == 409 and "SENTINEL" not in response.text
            response = await api.post("/api/v1/data-sources/alpaca/credentials/apiKey",
                                      json={"value": KEY}, headers=headers)
            assert response.json()["error"]["code"] == "DATA_SOURCE_FIELD_UNKNOWN"
        assert vault.records == {}
    asyncio.run(run())


def test_check_uses_the_environment_key_when_nothing_is_saved(tmp_path, monkeypatch):
    async def run():
        _, _, guard, transport, checked = api_fixture(
            tmp_path, monkeypatch, environment={"INGESTION_TWELVE_DATA_API_KEY": "rejected-key-0000"})
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            response = await api.post("/api/v1/data-sources/twelvedata/check",
                                      headers=guard.trusted_headers(user_action="data-sources.check"))
        assert response.status_code == 409 and response.json()["error"]["code"] == "DATA_SOURCE_KEY_REJECTED"
        assert checked == ["rejected-key-0000"] and "rejected-key" not in response.text
    asyncio.run(run())


def test_routes_are_unavailable_without_the_desktop_guard(tmp_path):
    async def run():
        owner, _, _ = service(tmp_path)
        app = FastAPI()
        app.state.data_source_credentials = owner
        app.include_router(router, prefix="/api/v1")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                                     base_url="http://127.0.0.1:8000") as api:
            response = await api.get("/api/v1/data-sources")
        assert response.status_code == 503
    asyncio.run(run())
