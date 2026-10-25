import asyncio
from aiohttp import web
from ccxt.pro.okx import okx as CcxtOkx
import pytest
from app.readonly_accounts.normalization import AccountDataError
from app.readonly_accounts.okx import ReadOnlyOkx, account_identity, validate_rest, validate_ws, readonly_session

URL = "wss://ws.okx.com:8443/ws/v5/private"


@pytest.mark.parametrize("path", ["trade/order", "trade/cancel-order", "trade/amend-order", "asset/transfer", "asset/withdrawal", "account/set-position-mode", "account/set-leverage"])
def test_all_execution_and_account_mutation_requests_fail_before_network(path):
    asyncio.run(_denied_operation(path))


async def _denied_operation(path):
    client = ReadOnlyOkx({"apiKey":"fixture", "secret":"fixture", "password":"fixture"})
    try:
        with pytest.raises(AccountDataError, match="READONLY_OPERATION_DENIED"):
            await client.request(path, "private", "POST", {})
    finally:
        await client.close()


@pytest.mark.parametrize("operation", ["order", "batch-orders", "cancel-order", "amend-order"])
def test_websocket_execution_cannot_bypass_rest_boundary(operation):
    with pytest.raises(AccountDataError):
        validate_ws(URL, {"op":operation, "args":[{"instId":"BTC-USDT-SWAP"}]})


def test_only_swap_private_read_channels_and_fixed_origins_are_accepted():
    for channel in ["orders", "positions"]:
        validate_ws(URL, {"op":"subscribe", "args":[{"channel":channel,"instType":"SWAP"}]})
        with pytest.raises(AccountDataError):
            validate_ws(URL, {"op":"subscribe", "args":[{"channel":channel,"instType":"ANY"}]})
    validate_ws(URL, {"op":"subscribe", "args":[{"channel":"account"}]})
    with pytest.raises(AccountDataError):validate_ws("wss://example.com/ws/v5/private", None)
    with pytest.raises(AccountDataError):validate_rest("public/instruments","public","GET",{"instType":"SPOT"})


def test_raw_fetch_cannot_send_secrets_to_an_arbitrary_host_or_write_path():
    asyncio.run(_denied_destinations())


async def _denied_destinations():
    client = ReadOnlyOkx({"apiKey":"fixture", "secret":"fixture", "password":"fixture"})
    try:
        for url in ["https://example.com/api/v5/account/config", "https://www.okx.com/api/v5/trade/order", "http://www.okx.com/api/v5/account/config"]:
            with pytest.raises(AccountDataError):await client.fetch(url)
    finally:
        await client.close()


@pytest.mark.parametrize("permission,mode", [("read_only,trade","long_short_mode"),("read_only,withdraw","long_short_mode"),("read_only","net_mode"),("","long_short_mode")])
def test_reject_privileged_keys_and_wrong_account_mode_without_auto_switch(permission, mode):
    with pytest.raises(AccountDataError):
        account_identity({"code":"0","data":[{"uid":"123","perm":permission,"posMode":mode}]})


def test_account_configuration_proves_identity_and_scope():
    assert account_identity({"code":"0","data":[{"uid":"123","perm":"read_only","posMode":"long_short_mode","acctLv":"2"}]}) == {
        "venueUid":"123", "positionMode":"long_short_mode", "accountLevel":"2"}


def test_rest_and_websocket_redirects_stop_before_forwarding_auth_headers():
    async def run():
        received = []
        async def target(request):
            received.append(dict(request.headers))
            return web.Response(text="unexpected")
        target_app = web.Application(); target_app.router.add_get("/target", target)
        target_runner = web.AppRunner(target_app); await target_runner.setup()
        target_site = web.TCPSite(target_runner, "127.0.0.1", 0); await target_site.start()
        target_port = target_site._server.sockets[0].getsockname()[1]
        async def redirect(request):
            raise web.HTTPFound(f"http://127.0.0.1:{target_port}/target")
        source_app = web.Application(); source_app.router.add_get("/redirect", redirect)
        source_runner = web.AppRunner(source_app); await source_runner.setup()
        source_site = web.TCPSite(source_runner, "127.0.0.1", 0); await source_site.start()
        source_port = source_site._server.sockets[0].getsockname()[1]
        try:
            async with readonly_session(connector=None, loop=asyncio.get_running_loop(), trust_env=False) as session:
                for method in [session.get, session.ws_connect]:
                    with pytest.raises(AccountDataError, match="READONLY_REDIRECT_DENIED"):
                        async with method(f"http://127.0.0.1:{source_port}/redirect", headers={"OK-ACCESS-KEY":"fixture-sentinel"}):
                            pass
            assert received == []
        finally:
            await source_runner.cleanup(); await target_runner.cleanup()
    asyncio.run(run())


def test_owned_sessions_disable_header_logs_and_close_all_transports():
    async def run():
        client = ReadOnlyOkx({"apiKey":"fixture","secret":"fixture","password":"fixture"}, proxy="socks5h://127.0.0.1:12345")
        client.open()
        session = client.session
        socks = client.get_socks_proxy_session(client.socksProxy)
        assert client.wsSocksProxy == client.socksProxy
        assert client.logger.disabled and not client.logger.propagate
        assert len(session.trace_configs) == len(socks.trace_configs) == 1
        await client.close()
        assert session.closed and socks.closed
        assert client.apiKey == client.secret == client.password == ""
    asyncio.run(run())


def test_ccxt_private_entrypoints_generate_only_allowed_subscription_frames(monkeypatch):
    captured = []
    class StopBeforeNetwork(Exception):
        pass
    def watch(self, url, hashes, message=None, *args, **kwargs):
        captured.append((url, message))
        raise StopBeforeNetwork
    monkeypatch.setattr(CcxtOkx, "watch", watch)
    monkeypatch.setattr(CcxtOkx, "watch_multiple", watch)
    async def ready(*args, **kwargs):
        return {}
    async def run():
        client = ReadOnlyOkx({"apiKey":"fixture","secret":"fixture","password":"fixture"})
        client.load_markets = ready
        client.authenticate = ready
        try:
            for call in [lambda:client.watch_orders(params={"type":"swap"}),
                         lambda:client.watch_positions(params={"instType":"SWAP"}),client.watch_balance]:
                with pytest.raises(StopBeforeNetwork):
                    await call()
            assert [item[1]["args"][0]["channel"] for item in captured] == ["orders","positions","account"]
            for url,message in captured:
                validate_ws(url,message)
        finally:
            await client.close()
    asyncio.run(run())


def test_position_history_retains_get_only_perpetual_boundary():
    validate_rest('account/positions-history','private','GET',{'instType':'SWAP'})
    with pytest.raises(AccountDataError):validate_rest('account/positions-history','private','POST',{'instType':'SWAP'})
    with pytest.raises(AccountDataError):validate_rest('account/positions-history','private','GET',{'instType':'FUTURES'})
