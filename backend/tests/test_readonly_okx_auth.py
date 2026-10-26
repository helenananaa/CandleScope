import asyncio
import json

import ccxt
import pytest

from app.readonly_accounts.api import failure
from app.readonly_accounts.normalization import AccountDataError
from app.readonly_accounts.okx import OKX_AUTH_CODES, ReadOnlyOkx
from app.readonly_accounts.service import ReadOnlyAccountService
from app.readonly_accounts.sync import TERMINAL_ERRORS, error_code


CREDENTIALS = {"apiKey": "fixture-key", "secret": "fixture-secret", "password": "fixture-passphrase"}
SENSITIVE = "fixture-key fixture-secret fixture-passphrase 192.0.2.1"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def denied(*_args, **_kwargs):
        pytest.fail("Authentication diagnostics tests must not contact the exchange")
    monkeypatch.setattr(ReadOnlyOkx, "fetch", denied)


def respond(client, code):
    response = {"code": code, "msg": SENSITIVE, "data": []}
    return client.handle_errors(401, SENSITIVE, "https://www.okx.com/api/v5/account/config",
                                "GET", {}, json.dumps(response), response,
                                {"OK-ACCESS-KEY": SENSITIVE}, SENSITIVE)


@pytest.mark.parametrize("code", sorted(OKX_AUTH_CODES))
def test_provider_auth_code_survives_api_without_raw_message_or_credentials(code):
    async def run():
        client = ReadOnlyOkx(CREDENTIALS)
        try:
            with pytest.raises(AccountDataError) as caught:
                respond(client, code)
            expected = "OKX_AUTH_" + code
            assert str(caught.value) == error_code(caught.value) == expected
            assert json.loads(failure(caught.value).body) == {"error": {"code": expected}}
            assert expected in TERMINAL_ERRORS
        finally:
            await client.close()
    asyncio.run(run())


def test_success_rate_limit_and_unknown_errors_keep_ccxt_behavior_and_safe_fallbacks():
    async def run():
        client = ReadOnlyOkx(CREDENTIALS)
        try:
            assert respond(client, "0") is None
            with pytest.raises(ccxt.RateLimitExceeded) as caught:
                respond(client, "50011")
            assert error_code(caught.value) == "ACCOUNT_RATE_LIMITED"
            assert error_code(caught.value) not in TERMINAL_ERRORS
            with pytest.raises(ccxt.ExchangeError) as caught:
                respond(client, "59999")
            assert json.loads(failure(caught.value).body) == {"error": {"code": "ACCOUNT_SYNC_FAILED"}}
            assert error_code(ccxt.AuthenticationError(SENSITIVE)) == "ACCOUNT_AUTHENTICATION_FAILED"
        finally:
            await client.close()
    asyncio.run(run())


class EmptyVault:
    def read(self, record_id):
        return dict(CREDENTIALS)

    def store(self, *_args):
        pytest.fail("Authentication failure must not store credentials")


@pytest.mark.parametrize("code", sorted(OKX_AUTH_CODES))
def test_auth_failure_stops_worker_and_closes_client_without_automatic_retries(tmp_path, code):
    async def run():
        clients = []

        def factory(credentials, **kwargs):
            client = ReadOnlyOkx(credentials, **kwargs)
            async def rejected():
                return respond(client, code)
            # CCXT generates instance REST methods during construction.
            client.privateGetAccountConfig = rejected
            clients.append(client)
            return client

        service = ReadOnlyAccountService(tmp_path, client_factory=factory, vault_factory=lambda _root: EmptyVault())
        try:
            # A failed initial connection must leave no account or pending key.
            with pytest.raises(AccountDataError, match="OKX_AUTH_" + code):
                await service.connect(dict(CREDENTIALS))
            assert service.repository.account() is None
            assert service.repository.retired_credentials() == []
            # The same rejection after a previous connection must stop retrying.
            service.repository.bind("123", "fixture-reference", 0)
            await asyncio.wait_for(service._run(), timeout=1)
            assert service.repository.account()["error_code"] == "OKX_AUTH_" + code
            assert len(clients) == 2
            assert all(client.apiKey == client.secret == client.password == "" for client in clients)
            assert service.synchronizer is None
        finally:
            await service.close()
    asyncio.run(run())
