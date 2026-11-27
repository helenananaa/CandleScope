"""PL-10: the read-only synchronizer's WS reconnect loop, round backoff and overflow rescans.

The loops sleep for up to a minute between attempts. Each test swaps the
``asyncio`` name inside ``app.readonly_accounts.sync`` for a proxy whose
``sleep`` and ``wait_for`` record the requested delay and return at once, so
the real event loop, queues and threads are untouched.
"""
import asyncio
from datetime import UTC, datetime

import ccxt
import pytest

from app.readonly_accounts import sync as sync_module
from app.readonly_accounts.normalization import AccountDataError, Contract
from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts.sync import HISTORY, AccountSynchronizer, three_months_before

NOW = int(datetime(2026, 10, 25, tzinfo=UTC).timestamp() * 1000)
MARKET = {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "ctType": "linear", "settleCcy": "USDT",
          "ctValCcy": "BTC", "ctVal": "0.01", "lotSz": "0.01"}
REAL_SLEEP = asyncio.sleep


class FastClock:
    """``asyncio`` as sync.py sees it, with recorded, instant sleeps and waits."""

    def __init__(self, *, max_sleeps=None):
        self.sleeps = []
        self.waits = []
        self.max_sleeps = max_sleeps

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, delay):
        if delay:
            self.sleeps.append(delay)
            if self.max_sleeps is not None and len(self.sleeps) > self.max_sleeps:
                raise AssertionError(f"loop kept sleeping: {self.sleeps}")
        await REAL_SLEEP(0)

    async def wait_for(self, awaitable, timeout):
        self.waits.append(timeout)
        task = asyncio.ensure_future(awaitable)
        await REAL_SLEEP(0)
        if task.done():
            return task.result()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise TimeoutError


@pytest.fixture
def clock(monkeypatch):
    fake = FastClock(max_sleeps=100)
    monkeypatch.setattr(sync_module, "asyncio", fake)
    return fake


def message(channel, row):
    return {"arg": {"channel": channel}, "data": [row]}


class Recorder:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


# --- WS reconnect and backoff ----------------------------------------------------------------

def test_ws_watch_doubles_backoff_to_a_minute_and_resets_after_a_received_update(clock):
    async def run():
        outcomes = [ccxt.NetworkError("drop")] * 8 + ["update"] + [ccxt.RequestTimeout("slow")] * 2
        calls = []

        class Client:
            async def watch_orders(self, params):
                calls.append(params)
                if not outcomes:
                    raise asyncio.CancelledError
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return []

        changed = Recorder()
        sync = AccountSynchronizer(None, Client(), now_ms=lambda: NOW, state_changed=changed)
        with pytest.raises(asyncio.CancelledError):
            await sync.watch("orders")
        # 1, 2, 4 ... capped at 60 s; one good receive starts the ladder again.
        assert clock.sleeps == [1, 2, 4, 8, 16, 32, 60, 60, 1, 2]
        assert calls == [{"type": "swap"}] * 12
        assert sync.stream_status == "reconnecting"
        assert sync.ws_error == "ACCOUNT_NETWORK_UNAVAILABLE"
        assert sync.channel_errors == {"orders": "ACCOUNT_NETWORK_UNAVAILABLE"}
        assert changed.calls == 10 and sync.changed.is_set()

    asyncio.run(run())


@pytest.mark.parametrize("channel,method,params", [
    ("orders", "watch_orders", {"params": {"type": "swap"}}),
    ("positions", "watch_positions", {"params": {"instType": "SWAP"}}),
    ("account", "watch_balance", {}),
])
@pytest.mark.parametrize("error,code", [
    (ccxt.RateLimitExceeded("429"), "ACCOUNT_RATE_LIMITED"),
    (ccxt.AuthenticationError("expired"), "ACCOUNT_AUTHENTICATION_FAILED"),
    (ccxt.NetworkError("reset"), "ACCOUNT_NETWORK_UNAVAILABLE"),
    (ValueError("decoder"), "ACCOUNT_SYNC_FAILED"),
])
def test_each_channel_reconnects_with_its_own_subscription_and_public_error_code(clock, channel, method,
                                                                                 params, error, code):
    async def run():
        seen = []

        async def watch(**kwargs):
            seen.append(kwargs)
            if len(seen) == 3:
                raise asyncio.CancelledError
            raise error

        client = type("Client", (), {})()
        setattr(client, method, watch)
        sync = AccountSynchronizer(None, client, now_ms=lambda: NOW)
        with pytest.raises(asyncio.CancelledError):
            await sync.watch(channel)
        # The loop keeps retrying even an authentication failure: the REST round
        # in run() is what ends the session on a terminal error.
        assert seen == [params] * 3 and clock.sleeps == [1, 2]
        assert sync.channel_errors == {channel: code} and sync.ws_error == code

    asyncio.run(run())


def test_cancelling_a_watch_during_backoff_stops_the_loop(monkeypatch):
    # The real sleep here: cancellation must interrupt the backoff wait itself.
    async def run():
        class Client:
            async def watch_balance(self):
                raise ccxt.NetworkError("drop")

        sync = AccountSynchronizer(None, Client(), now_ms=lambda: NOW)
        task = asyncio.create_task(sync.watch("account"))
        for _ in range(10):
            await asyncio.sleep(0)
        assert sync.stream_status == "reconnecting" and not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())


def test_received_messages_clear_only_their_own_channel_error(tmp_path, clock):
    async def run():
        repo = AccountRepository(tmp_path)
        repo.bind("123", "a" * 32, three_months_before(NOW))
        now = [NOW]

        class Client:
            async def watch_orders(self, params):
                raise ccxt.NetworkError("orders down")

            async def watch_positions(self, params):
                raise ccxt.RateLimitExceeded("positions throttled")

        sync = AccountSynchronizer(repo, Client(), now_ms=lambda: now[0])
        clock.max_sleeps = 0  # The first backoff ends each watch: one failure per channel.
        for channel in ("orders", "positions"):
            with pytest.raises(AssertionError, match="kept sleeping"):
                await sync.watch(channel)
        assert sync.channel_errors == {"orders": "ACCOUNT_NETWORK_UNAVAILABLE",
                                       "positions": "ACCOUNT_RATE_LIMITED"}
        consumer = asyncio.create_task(sync.consume())
        try:
            now[0] += 1
            sync.observe(message("orders", {"ordId": "1", "state": "live"}))
            await asyncio.wait_for(sync.queue.join(), timeout=5)
            assert sync.stream_status == "reconnecting"
            assert sync.ws_error == "ACCOUNT_RATE_LIMITED"
            assert sync.last_ws_received_ms == NOW + 1
            now[0] += 1
            sync.observe(message("positions", {"posId": "7"}))
            await asyncio.wait_for(sync.queue.join(), timeout=5)
            assert sync.stream_status == "observed" and sync.ws_error is None
            assert sync.channel_errors == {} and sync.last_ws_received_ms == NOW + 2
        finally:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
        with repo.connection() as db:
            kinds = [row[0] for row in db.execute("SELECT kind FROM raw_fact ORDER BY kind")]
        assert kinds == ["ws:orders", "ws:positions"]

    asyncio.run(run())


# --- the reconcile round loop ----------------------------------------------------------------

class StatusLog:
    def __init__(self):
        self.calls = []

    def status(self, state, **kwargs):
        self.calls.append((state, kwargs))


def test_round_backoff_doubles_on_failure_and_follows_completion(clock):
    async def run():
        idle = asyncio.Event()

        class Client:
            async def watch_orders(self, params):
                await idle.wait()

            async def watch_positions(self, params):
                await idle.wait()

            async def watch_balance(self):
                await idle.wait()

        outcomes = ([ccxt.NetworkError("down")] * 7 + [False, True, ccxt.RequestTimeout("slow"), True]
                    + [AccountDataError("ACCOUNT_IDENTITY_CHANGED")])
        log = StatusLog()
        sync = AccountSynchronizer(log, Client(), now_ms=lambda: NOW)

        async def reconcile():
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        sync.reconcile = reconcile
        before = asyncio.all_tasks()
        with pytest.raises(AccountDataError, match="ACCOUNT_IDENTITY_CHANGED"):
            await sync.run()
        # Failures: 2, 4 ... capped at 60. An unfinished round retries in 1 s and a
        # finished one in 30 s; the next failure doubles from the delay before it.
        assert clock.waits == [2, 4, 8, 16, 32, 60, 60, 1, 30, 60, 30]
        errors = [kwargs["error"] for state, kwargs in log.calls if state == "error"]
        assert errors == ["ACCOUNT_NETWORK_UNAVAILABLE"] * 8 + ["ACCOUNT_IDENTITY_CHANGED"]
        # The consumer and all three watch tasks are cancelled with the round loop.
        await REAL_SLEEP(0)
        assert not [task for task in asyncio.all_tasks() - before if not task.done()
                    and task is not asyncio.current_task()]

    asyncio.run(run())


def test_a_crashed_consumer_ends_the_round_loop_for_the_service_to_restart(tmp_path, clock):
    async def run():
        idle = asyncio.Event()

        class Client:
            async def watch_orders(self, params):
                await idle.wait()

            async def watch_positions(self, params):
                await idle.wait()

            async def watch_balance(self):
                await idle.wait()

        repo = AccountRepository(tmp_path)
        repo.bind("123", "a" * 32, three_months_before(NOW))
        sync = AccountSynchronizer(repo, Client(), now_ms=lambda: NOW)
        rounds = []

        async def reconcile():
            rounds.append(len(rounds))
            if len(rounds) == 1:
                # More than 1000 rows in one WS event is rejected by the repository.
                sync.observe({"arg": {"channel": "orders"}, "data": [{"ordId": str(i)} for i in range(1001)]})
                await REAL_SLEEP(0.05)
            return True

        sync.reconcile = reconcile
        with pytest.raises(AccountDataError, match="ACCOUNT_EVENT_INVALID"):
            await asyncio.wait_for(sync.run(), timeout=10)
        assert rounds == [0]

    asyncio.run(run())


# --- queue overflow forces a full rescan ----------------------------------------------------

class Okx:
    """The REST surface reconcile() reads, with history pages recorded per kind."""

    def __init__(self):
        self.history_calls = {kind: [] for kind in HISTORY}
        self.endless = set()

    async def privateGetAccountConfig(self):
        return {"code": "0", "data": [{"uid": "123", "perm": "read_only", "posMode": "long_short_mode",
                                       "acctLv": "2"}]}

    async def privateGetAccountPositions(self, params):
        return {"code": "0", "data": []}

    async def privateGetTradeOrdersPending(self, params):
        return {"code": "0", "data": []}

    async def privateGetAccountBalance(self):
        return {"code": "0", "data": []}

    async def privateGetAccountPositionsHistory(self, params):
        return {"code": "0", "data": []}

    def _history(self, kind, params):
        self.history_calls[kind].append(dict(params))
        if kind not in self.endless:
            return {"code": "0", "data": []}
        page = len(self.history_calls[kind])
        return {"code": "0", "data": [{"billId": f"{kind}-{page}", "ordId": f"{kind}-{page}", "type": "2",
                                       "ccy": "USDT", "balChg": "0", "bal": "1", "ts": str(NOW - 1000)}]}

    async def privateGetTradeFillsHistory(self, params):
        return self._history("fills", params)

    async def privateGetAccountBillsArchive(self, params):
        return self._history("bills", params)

    async def privateGetTradeOrdersHistoryArchive(self, params):
        return self._history("orders", params)


def scan_begins(client, kind):
    # recent() also reads a bounded 10-minute head; only paged scans carry the account's own range.
    head = str(max(0, client_now[0] - 10 * 60 * 1000))
    return [call["begin"] for call in client.history_calls[kind] if call["begin"] != head]


client_now = [NOW]


@pytest.fixture
def account(tmp_path):
    client_now[0] = NOW
    repo = AccountRepository(tmp_path)
    repo.bind("123", "a" * 32, three_months_before(NOW))
    client = Okx()
    sync = AccountSynchronizer(repo, client, now_ms=lambda: client_now[0])
    sync.contracts = {"BTC-USDT-SWAP": Contract.from_okx(MARKET)}
    return repo, client, sync


def fill_queue(sync):
    for index in range(sync.queue.maxsize):
        sync.observe(message("orders", {"ordId": str(index)}))
    assert not sync.overflow and sync.ws_error is None


def test_queue_overflow_drops_the_newest_event_and_flags_the_stream(account):
    async def run():
        _, _, sync = account
        changed = Recorder()
        sync.state_changed = changed
        fill_queue(sync)
        sync.changed.clear()
        sync.observe(message("orders", {"ordId": "overflow"}))
        assert sync.overflow and sync.ws_error == "ACCOUNT_STREAM_OVERFLOW"
        assert sync.queue.qsize() == sync.queue.maxsize
        assert sync.changed.is_set() and changed.calls == sync.queue.maxsize + 1
        newest = [sync.queue.get_nowait()[1] for _ in range(sync.queue.maxsize)][-1]
        assert newest["data"][0]["ordId"] == str(sync.queue.maxsize - 1)

    asyncio.run(run())


def test_overflow_turns_the_next_incremental_round_into_a_full_rescan(account):
    async def run():
        repo, client, sync = account
        floor = str(three_months_before(NOW))
        assert await sync.reconcile()
        assert scan_begins(client, "fills") == [floor]
        through = max(row["end_ms"] for row in repo.coverage() if row["kind"] == "fills")

        # Five minutes later the hourly full scan is not due: an ordinary round is incremental.
        client_now[0] = NOW + 5 * 60 * 1000
        assert await sync.reconcile()
        assert scan_begins(client, "fills")[-1] == str(through - 10 * 60 * 1000)

        client_now[0] = NOW + 10 * 60 * 1000
        fill_queue(sync)
        sync.observe(message("orders", {"ordId": "dropped"}))
        assert await sync.reconcile()
        rescan_floor = str(three_months_before(client_now[0]))
        assert [scan_begins(client, kind)[-1] for kind in HISTORY] == [rescan_floor] * 3
        assert not sync.overflow

        # The overflow was answered; the following round is incremental again.
        through = max(row["end_ms"] for row in repo.coverage() if row["kind"] == "fills")
        client_now[0] = NOW + 15 * 60 * 1000
        assert await sync.reconcile()
        assert scan_begins(client, "fills")[-1] == str(through - 10 * 60 * 1000)

    asyncio.run(run())


def test_overflow_stays_pending_until_an_unfinished_full_rescan_completes(account):
    async def run():
        repo, client, sync = account
        assert await sync.reconcile()
        client_now[0] = NOW + 5 * 60 * 1000
        fill_queue(sync)
        sync.observe(message("orders", {"ordId": "dropped"}))
        # More bills than one round's page budget: the rescan cannot finish yet.
        client.endless.add("bills")
        assert not await sync.reconcile()
        assert sync.overflow
        assert [row for row in repo.scans() if row["kind"] == "bills" and not row["complete"]]
        client.endless.clear()
        assert await sync.reconcile()
        assert not sync.overflow

    asyncio.run(run())


def test_overflow_during_an_incremental_round_still_forces_a_full_rescan(account):
    async def run():
        repo, client, sync = account
        assert await sync.reconcile()
        client_now[0] = NOW + 5 * 60 * 1000
        through = max(row["end_ms"] for row in repo.coverage() if row["kind"] == "fills")
        reads = client.privateGetTradeFillsHistory

        async def overflow_while_reading(params):
            if "after" not in params and params["begin"] == str(through - 10 * 60 * 1000):
                fill_queue(sync)
                sync.observe(message("orders", {"ordId": "dropped"}))
            return await reads(params)

        client.privateGetTradeFillsHistory = overflow_while_reading
        assert await sync.reconcile()
        assert scan_begins(client, "fills")[-1] == str(through - 10 * 60 * 1000)
        # The round began before the overflow, so it cannot have answered it.
        assert sync.overflow
        client.privateGetTradeFillsHistory = reads
        client_now[0] = NOW + 6 * 60 * 1000
        assert await sync.reconcile()
        assert scan_begins(client, "fills")[-1] == str(three_months_before(client_now[0]))
        assert not sync.overflow

    asyncio.run(run())
