"""Funding account balances, deposits, withdrawals and transfers (#575 PL-6)."""
import asyncio

import ccxt
import httpx
import pytest
from ccxt.pro.okx import okx as CcxtOkx
from fastapi import FastAPI

from app.plugin_security_v2.management import LocalManagementGuard
from app.readonly_accounts import sync as sync_module
from app.readonly_accounts.api import router
from app.readonly_accounts.normalization import AccountDataError, deposit, funding_balance, transfer, withdrawal
from app.readonly_accounts.okx import ReadOnlyOkx, validate_rest
from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts.service import ReadOnlyAccountService
from app.readonly_accounts.sync import AccountSynchronizer, three_months_before

NOW = 1_795_000_000_000
DAY = 86_400_000


def test_funding_records_keep_amounts_exact_and_drop_addresses():
    assert funding_balance({"ccy": "USDT", "bal": "1250.5", "availBal": "1200.5", "frozenBal": "50"}) == {
        "currency": "USDT", "total": "1250.5", "available": "1200.5", "frozen": "50"}
    row = {"depId": "d1", "ccy": "BTC", "chain": "BTC-Bitcoin", "amt": "0.015", "state": "2", "ts": str(NOW),
           "from": "", "to": "bc1-private-address", "txId": "private-tx"}
    assert deposit(row) == {"id": "d1", "currency": "BTC", "chain": "BTC-Bitcoin", "amount": "0.015",
                            "state": "completed", "eventTimeMs": NOW}
    out = withdrawal({"wdId": "w1", "ccy": "USDT", "chain": "USDT-TRC20", "amt": "100", "fee": "1", "feeCcy": "USDT",
                      "state": "-2", "ts": str(NOW), "to": "T-private-address", "txId": ""})
    assert out == {"id": "w1", "currency": "USDT", "chain": "USDT-TRC20", "amount": "100", "fee": "1",
                   "feeCurrency": "USDT", "state": "canceled", "eventTimeMs": NOW}
    assert "private" not in repr((deposit(row), out))
    moved = transfer({"billId": "b1", "type": "1", "subType": "12", "ccy": "USDT", "balChg": "-25.5", "from": "18",
                      "to": "6", "ts": str(NOW)})
    assert moved == {"id": "b1", "currency": "USDT", "amount": "25.5", "direction": "out", "from": "trading",
                     "to": "funding", "eventTimeMs": NOW}


@pytest.mark.parametrize(("make", "state", "expected"), [
    (deposit, "0", "pending"), (deposit, "1", "completed"), (deposit, "12", "held"), (deposit, "99", "unknown"),
    (withdrawal, "-3", "pending"), (withdrawal, "-1", "failed"), (withdrawal, "7", "pending"), (withdrawal, "99", "unknown"),
])
def test_exchange_states_collapse_to_what_the_panel_explains(make, state, expected):
    key = "depId" if make is deposit else "wdId"
    assert make({key: "x", "ccy": "BTC", "amt": "1", "state": state, "ts": str(NOW)})["state"] == expected


@pytest.mark.parametrize("bad", [
    lambda: funding_balance({"ccy": "USDT", "bal": "-1", "availBal": "0", "frozenBal": "0"}),
    lambda: deposit({"depId": "d", "ccy": "BTC", "amt": "1e3", "state": "2", "ts": str(NOW)}),
    lambda: withdrawal({"wdId": "w", "ccy": "BTC", "amt": "1", "fee": "-1", "state": "2", "ts": str(NOW)}),
    lambda: transfer({"billId": "b", "type": "2", "ccy": "USDT", "balChg": "1", "ts": str(NOW)}),
    lambda: deposit({"depId": "d", "ccy": "BTC", "chain": "x" * 65, "amt": "1", "state": "2", "ts": str(NOW)}),
])
def test_malformed_funding_records_are_rejected_not_guessed(bad):
    with pytest.raises(AccountDataError):
        bad()


def test_only_the_three_funding_reads_are_allowed():
    for path in ("asset/balances", "asset/deposit-history", "asset/withdrawal-history"):
        validate_rest(path, "private", "GET", {})
        with pytest.raises(AccountDataError):
            validate_rest(path, "private", "POST", {})
    for path in ("asset/transfer", "asset/withdrawal", "asset/bills", "asset/deposit-address", "asset/cancel-withdrawal"):
        with pytest.raises(AccountDataError):
            validate_rest(path, "private", "GET", {})


def test_the_funding_calls_reach_the_network_only_as_allowlisted_gets(monkeypatch):
    """Through CCXT's implicit methods, so a path CCXT builds differently would fail here."""
    sent = []

    async def network(self, url, method="GET", headers=None, body=None):
        sent.append((method, url.split("?")[0].removeprefix("https://www.okx.com/api/v5/"), body))
        return {"code": "0", "data": []}

    monkeypatch.setattr(CcxtOkx, "fetch", network)

    async def run():
        client = ReadOnlyOkx({"apiKey": "fixture", "secret": "fixture", "password": "fixture"})
        try:
            await client.privateGetAssetBalances({})
            await client.privateGetAssetDepositHistory({"limit": "100", "after": "2"})
            await client.privateGetAssetWithdrawalHistory({"limit": "100"})
            await client.privateGetAccountBillsArchive({"type": "1", "begin": "1", "end": "2", "limit": "100"})
        finally:
            await client.close()
    asyncio.run(run())
    assert sent == [("GET", "asset/balances", None), ("GET", "asset/deposit-history", None),
                    ("GET", "asset/withdrawal-history", None), ("GET", "account/bills-archive", None)]


class Funding:
    """The funding reads with a scripted history; times step back a day per record."""

    def __init__(self, deposits=0, withdrawals=0, transfers=0, step=DAY):
        self.calls = {"balances": 0, "deposits": [], "withdrawals": [], "transfers": []}
        self.rows = {"deposits": [{"depId": f"d{i}", "ccy": "USDT", "amt": "1", "state": "2", "ts": str(NOW - i * step)}
                                  for i in range(deposits)],
                     "withdrawals": [{"wdId": f"w{i}", "ccy": "USDT", "amt": "2", "fee": "0.1", "state": "0",
                                      "ts": str(NOW - i * DAY)} for i in range(withdrawals)]}
        self.transfers = [{"billId": f"t{i}", "type": "1", "ccy": "USDT", "balChg": "3", "from": "6", "to": "18",
                           "ts": str(NOW - i * DAY)} for i in range(transfers)]
        self.failure = None

    async def privateGetAssetBalances(self, params):
        self.calls["balances"] += 1
        if self.failure:
            raise self.failure
        return {"code": "0", "data": [{"ccy": "USDT", "bal": "10", "availBal": "9", "frozenBal": "1"}]}

    def _page(self, kind, params):
        self.calls[kind].append(dict(params))
        if self.failure:
            raise self.failure
        after = int(params["after"]) if "after" in params else None
        rows = [row for row in self.rows[kind] if after is None or int(row["ts"]) < after]
        return {"code": "0", "data": rows[:int(params["limit"])]}

    async def privateGetAssetDepositHistory(self, params):
        return self._page("deposits", params)

    async def privateGetAssetWithdrawalHistory(self, params):
        return self._page("withdrawals", params)

    async def privateGetAccountBillsArchive(self, params):
        assert params["type"] == "1"
        self.calls["transfers"].append(dict(params))
        rows = self.transfers
        if "after" in params:
            rows = rows[[row["billId"] for row in rows].index(params["after"]) + 1:]
        return {"code": "0", "data": rows[:100]}


def synchronizer(tmp_path, client, now):
    repo = AccountRepository(tmp_path)
    repo.bind("123", "a" * 32, three_months_before(NOW))
    return repo, AccountSynchronizer(repo, client, now_ms=lambda: now[0])


def test_balances_each_minute_history_every_five_and_history_stays_out_of_the_state(tmp_path):
    async def run():
        now = [NOW]
        client = Funding(deposits=2, withdrawals=1, transfers=1)
        repo, sync = synchronizer(tmp_path, client, now)
        await sync.funding()
        snapshots = repo.snapshots(overview=True)
        assert snapshots["funding_balances"]["data"] == {"balances": [
            {"currency": "USDT", "total": "10", "available": "9", "frozen": "1"}]}
        assert snapshots["funding_history_state"]["data"] == {"error": None, "complete": True}
        assert "funding_history" not in snapshots and "funding_history" not in repo.overview()["snapshots"]
        history = repo.snapshot("funding_history")["data"]
        assert [row["id"] for row in history["deposits"]] == ["d0", "d1"]
        assert history["withdrawals"][0]["fee"] == "0.1" and history["transfers"][0]["from"] == "funding"
        now[0] += 61_000
        await sync.funding()
        assert client.calls["balances"] == 2 and len(client.calls["deposits"]) == 1
        now[0] += 5 * 60_000
        await sync.funding()
        assert len(client.calls["deposits"]) == 2
    asyncio.run(run())


def test_history_pages_without_losing_rows_that_share_a_time(tmp_path):
    async def run():
        hour = 3_600_000
        client = Funding(deposits=150, step=hour)
        # Two deposits share the oldest time on the first page.
        client.rows["deposits"].insert(100, dict(client.rows["deposits"][99], depId="twin"))
        repo, sync = synchronizer(tmp_path, client, [NOW])
        await sync.funding()
        history = repo.snapshot("funding_history")["data"]
        ids = [row["id"] for row in history["deposits"]]
        assert "twin" in ids and len(ids) == 151 == len(set(ids)) and history["complete"]
        assert client.calls["deposits"][1]["after"] == str(NOW - 99 * hour + 1)
    asyncio.run(run())


def test_history_stops_at_three_months(tmp_path):
    async def run():
        client = Funding(deposits=150)  # one a day, so older than three months after about 92
        repo, sync = synchronizer(tmp_path, client, [NOW])
        await sync.funding()
        history = repo.snapshot("funding_history")["data"]
        floor = three_months_before(NOW)
        assert history["fromMs"] == floor and history["complete"] and len(client.calls["deposits"]) == 1
        assert all(row["eventTimeMs"] >= floor for row in history["deposits"])
        assert len(history["deposits"]) == sum(1 for i in range(150) if NOW - i * DAY >= floor)
    asyncio.run(run())


def test_a_page_budget_cut_says_the_history_is_partial(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(sync_module, "FUNDING_PAGES", 1)
        client = Funding(transfers=120)
        repo, sync = synchronizer(tmp_path, client, [NOW])
        await sync.funding()
        assert repo.snapshot("funding_history")["data"]["complete"] is False
        assert len(repo.snapshot("funding_history")["data"]["transfers"]) == 100
        assert repo.snapshots(overview=True)["funding_history_state"]["data"] == {"error": None, "complete": False}
    asyncio.run(run())


def test_a_failed_read_keeps_the_last_values_and_a_revoked_key_still_stops(tmp_path):
    async def run():
        now = [NOW]
        client = Funding(deposits=1)
        repo, sync = synchronizer(tmp_path, client, now)
        await sync.funding()
        before = repo.snapshot("funding_history")
        client.failure = ccxt.NetworkError("offline")
        now[0] += 5 * 60_000
        await sync.funding()
        assert repo.snapshot("funding_history") == before
        states = repo.snapshots(overview=True)
        assert states["funding_balances_state"]["data"] == {"error": "ACCOUNT_NETWORK_UNAVAILABLE"}
        assert states["funding_history_state"]["data"] == {"error": "ACCOUNT_NETWORK_UNAVAILABLE"}
        client.failure = AccountDataError("OKX_AUTH_50111")
        with pytest.raises(AccountDataError, match="OKX_AUTH_50111"):
            await sync.funding(force=True)
    asyncio.run(run())


def test_the_history_endpoint_serves_the_last_read(tmp_path):
    async def run():
        service = ReadOnlyAccountService(tmp_path)
        app = FastAPI()
        guard = LocalManagementGuard(["http://127.0.0.1:61234"])
        app.state.plugin_platform_v2_management_guard = guard
        app.state.readonly_account_service = service
        app.include_router(router, prefix="/api/v1")
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            url = "/api/v1/readonly-accounts/funding-history"
            assert (await api.get(url)).status_code in (401, 403)
            empty = await api.get(url, headers=guard.trusted_headers())
            assert empty.json() == {"receivedMs": None, "data": None}
            service.repository.save_snapshot("funding_history", {"deposits": [], "withdrawals": [], "transfers": [],
                                                                  "fromMs": 1, "throughMs": 2, "complete": True}, 5)
            assert (await api.get(url, headers=guard.trusted_headers())).json()["receivedMs"] == 5
        await service.close()
    asyncio.run(run())
