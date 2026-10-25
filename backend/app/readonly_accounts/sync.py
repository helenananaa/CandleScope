"""Resumable REST backfill plus raw WS observations and periodic reconciliation."""
from __future__ import annotations

import asyncio
import calendar
import time
from datetime import UTC, datetime
from typing import Any

import ccxt

from . import normalization as normal
from .normalization import AccountDataError, Contract
from .okx import OKX_AUTH_ERRORS, account_identity
from .repository import AccountRepository

HISTORY = {
    "fills":("privateGetTradeFillsHistory","billId",normal.fill),
    "bills":("privateGetAccountBillsArchive","billId",normal.bill),
    "orders":("privateGetTradeOrdersHistoryArchive","ordId",normal.order),
}
TERMINAL_ERRORS = frozenset({"READONLY_KEY_REQUIRED", "HEDGE_ACCOUNT_REQUIRED",
                            "ACCOUNT_AUTHENTICATION_FAILED", "ACCOUNT_IDENTITY_CHANGED"}) | OKX_AUTH_ERRORS


def three_months_before(now_ms: int) -> int:
    now = datetime.fromtimestamp(now_ms/1000,UTC)
    month_index = now.year*12 + now.month-1 - 3
    year, month_zero = divmod(month_index,12)
    month = month_zero+1
    earlier = now.replace(year=year,month=month,day=min(now.day,calendar.monthrange(year,month)[1]))
    return int(earlier.timestamp()*1000)


def error_code(exc: BaseException) -> str:
    if isinstance(exc,AccountDataError):
        return exc.code
    if isinstance(exc,ccxt.AuthenticationError):
        return "ACCOUNT_AUTHENTICATION_FAILED"
    if isinstance(exc,ccxt.RateLimitExceeded):
        return "ACCOUNT_RATE_LIMITED"
    if isinstance(exc,ccxt.NetworkError):
        return "ACCOUNT_NETWORK_UNAVAILABLE"
    return "ACCOUNT_SYNC_FAILED"


def response_rows(response: Any, limit: int = 100) -> list[dict]:
    if (not isinstance(response,dict) or response.get("code") != "0"
            or not isinstance(response.get("data"),list) or len(response["data"]) > limit
            or not all(isinstance(row,dict) for row in response["data"])):
        raise AccountDataError("EXCHANGE_RESPONSE_INVALID")
    return response["data"]


def uncovered_ranges(start: int, end: int, coverage: list[dict]) -> list[tuple[int,int]]:
    gaps = []
    cursor = start
    for row in sorted(coverage,key=lambda row:row["start_ms"]):
        if row["end_ms"] < cursor:
            continue
        if row["start_ms"] > end:
            break
        if row["start_ms"] > cursor:
            gaps.append((cursor,min(end,row["start_ms"]-1)))
        cursor = max(cursor,row["end_ms"]+1)
        if cursor > end:
            return gaps
    if cursor <= end:
        gaps.append((cursor,end))
    return gaps


class AccountSynchronizer:
    def __init__(self, repository: AccountRepository, client, *, now_ms=None):
        self.repository = repository
        self.client = client
        self.now_ms = now_ms or (lambda:int(time.time()*1000))
        self.contracts: dict[str,Contract] = {}
        self.last_full_scan = 0
        self.last_position_history_ms = 0
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.changed = asyncio.Event()
        self.stream_status = "waiting"
        self.last_ws_received_ms: int | None = None
        self.ws_error: str | None = None
        self.overflow = False
        self.ignored_contracts = 0
        self.requested_full = False
        self.channel_errors: dict[str,str] = {}

    async def initialize(self, expected_uid: str) -> None:
        identity = account_identity(await self.client.privateGetAccountConfig())
        if identity["venueUid"] != expected_uid:
            raise AccountDataError("ACCOUNT_IDENTITY_CHANGED")
        markets = await self.client.load_markets()
        metadata = []
        for market in markets.values():
            raw = market.get("info")
            if not isinstance(raw,dict):
                raise AccountDataError("CONTRACT_METADATA_UNAVAILABLE")
            try:
                contract = Contract.from_okx(raw)
            except AccountDataError as exc:
                if exc.code in {"UNSUPPORTED_CONTRACT","UNSUPPORTED_PRODUCT"}:
                    self.ignored_contracts += 1
                    continue
                raise
            self.contracts[contract.instrument] = contract
            metadata.append({"raw":raw,"normalized":contract.wire()})
        if not self.contracts:
            raise AccountDataError("CONTRACT_METADATA_UNAVAILABLE")
        await asyncio.to_thread(self.repository.save_snapshot,"contracts",metadata,self.now_ms())

    def contract(self, raw: dict) -> Contract | None:
        instrument = raw.get("instId")
        if isinstance(instrument,str) and "-USDC-" in instrument:
            return None  # Explicitly outside the two user-selected settlement scopes.
        contract = self.contracts.get(instrument)
        if contract is None:
            raise AccountDataError("CONTRACT_METADATA_UNAVAILABLE")
        return contract

    def observe(self, message: dict) -> None:
        try:
            self.queue.put_nowait((self.now_ms(),message))
        except asyncio.QueueFull:
            self.overflow = True
            self.ws_error = "ACCOUNT_STREAM_OVERFLOW"
        self.changed.set()

    async def consume(self) -> None:
        while True:
            received, message = await self.queue.get()
            try:
                channel = message["arg"]["channel"]
                await asyncio.to_thread(self.repository.observe,channel,message["data"],received_ms=received)
                self.last_ws_received_ms = received
                self.channel_errors.pop(channel,None)
                self.ws_error = next(iter(self.channel_errors.values()),None)
                self.stream_status = "reconnecting" if self.channel_errors else "observed"
                self.changed.set()
            finally:
                self.queue.task_done()

    async def watch(self, channel: str) -> None:
        delay = 1
        while True:
            try:
                if channel == "orders":
                    await self.client.watch_orders(params={"type":"swap"})
                elif channel == "positions":
                    await self.client.watch_positions(params={"instType":"SWAP"})
                else:
                    await self.client.watch_balance()
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.stream_status = "reconnecting"
                self.ws_error = self.channel_errors[channel] = error_code(exc)
                self.changed.set()
                await asyncio.sleep(delay)
                delay = min(delay*2,60)

    async def project(self, kind: str, raw_rows: list[dict]) -> list[tuple[str,dict,dict]]:
        _, identity_key, normalize = HISTORY[kind]
        # A malformed exchange record is evidence too. Preserve it before
        # projection fails; the historical cursor must remain retryable.
        await asyncio.to_thread(self.repository.observe_rest,kind,raw_rows,identity_key)
        projected = []
        for raw in raw_rows:
            key = normal.identifier(raw.get(identity_key))
            if kind == "bills":
                value = normalize(raw)
            else:
                contract = self.contract(raw)
                if contract is None:
                    continue
                value = normalize(raw,contract)
            projected.append((key,raw,value))
        return projected

    async def recent(self) -> None:
        # A long initial backfill must not hide incoming activity. These bounded
        # head reads are provisional observations, never proof of full coverage.
        for kind,(method,_,_) in HISTORY.items():
            params = {"begin":str(max(0,self.now_ms()-10*60*1000)),"end":str(self.now_ms()),"limit":"100"}
            if kind != "bills":
                params["instType"] = "SWAP"
            rows = response_rows(await getattr(self.client,method)(params))
            await asyncio.to_thread(self.repository.ingest_recent,kind,await self.project(kind,rows))

    async def history(self, kind: str, *, full: bool, page_budget: int = 20) -> bool:
        now = self.now_ms()
        account = await asyncio.to_thread(self.repository.account)
        if account is None:
            raise AccountDataError("ACCOUNT_NOT_CONNECTED")
        available_from = three_months_before(now)
        scans = await asyncio.to_thread(self.repository.scans)
        coverage = [row for row in await asyncio.to_thread(self.repository.coverage) if row["kind"] == kind]
        unfinished = next((row for row in scans if row["kind"] == kind and not row["complete"]),None)
        if unfinished is not None and unfinished["start_ms"] < available_from:
            for start,end in uncovered_ranges(unfinished["start_ms"],min(available_from-1,unfinished["end_ms"]),coverage):
                await asyncio.to_thread(self.repository.mark_gap,kind,start,end,
                                        abandon_scan=unfinished["end_ms"] < available_from)
            if unfinished["end_ms"] < available_from:
                await asyncio.to_thread(self.repository.discard_expired_scan,kind,unfinished["end_ms"])
                unfinished = None
        through = max((row["end_ms"] for row in coverage),default=account["requested_from_ms"])
        if through < available_from:
            for start,end in uncovered_ranges(through,available_from-1,coverage):
                await asyncio.to_thread(self.repository.mark_gap,kind,start,end)
        start = max(available_from,account["requested_from_ms"] if full else through-10*60*1000)
        scan = unfinished or await asyncio.to_thread(self.repository.start_scan,kind,start,now)
        method, identity_key, _ = HISTORY[kind]
        for _ in range(page_budget):
            params = {"begin":str(scan["start_ms"]),"end":str(scan["end_ms"]),"limit":"100"}
            if kind != "bills":
                params["instType"] = "SWAP"
            if scan["cursor"]:
                params["after"] = scan["cursor"]
            raw_rows = response_rows(await getattr(self.client,method)(params))
            projected = await self.project(kind,raw_rows)
            cursor = normal.identifier(raw_rows[-1].get(identity_key)) if raw_rows else None
            await asyncio.to_thread(self.repository.page,kind,scan["cursor"],projected,
                                    next_cursor=cursor,complete=not raw_rows)
            if not raw_rows:
                return True
            scan = {**scan,"cursor":cursor}
            await asyncio.sleep(0)
        return False

    async def current(self) -> None:
        positions = response_rows(await self.client.privateGetAccountPositions({"instType":"SWAP"}),1000)
        normalized_positions = []
        for raw in positions:
            contract = self.contract(raw)
            if contract is not None:
                normalized_positions.append(normal.position(raw,contract))
        await asyncio.to_thread(self.repository.save_snapshot,"positions",
                                {"raw":positions,"positions":normalized_positions},self.now_ms())
        # Open orders also paginate: one page must never masquerade as the full set.
        orders, seen, after = [], set(), None
        for _ in range(100):
            params = {"instType":"SWAP","limit":"100"}
            if after:
                params["after"] = after
            page = response_rows(await self.client.privateGetTradeOrdersPending(params))
            if not page:
                break
            after = normal.identifier(page[-1].get("ordId"))
            if after in seen:
                raise AccountDataError("SYNC_CURSOR_STALLED")
            seen.add(after)
            for raw in page:
                contract = self.contract(raw)
                if contract is not None:
                    orders.append({"raw":raw,"order":normal.order(raw,contract)})
        else:
            raise AccountDataError("OPEN_ORDER_PAGE_BUDGET")
        await asyncio.to_thread(self.repository.save_snapshot,"open_orders",orders,self.now_ms())
        balance = response_rows(await self.client.privateGetAccountBalance(),10)
        await asyncio.to_thread(self.repository.save_snapshot,"balances",balance,self.now_ms())

    async def reconcile(self, *, force_full: bool = False) -> bool:
        account = await asyncio.to_thread(self.repository.account)
        identity = account_identity(await self.client.privateGetAccountConfig())
        if account is None or identity["venueUid"] != account["venue_uid"]:
            raise AccountDataError("ACCOUNT_IDENTITY_CHANGED")
        await self.current()
        await self.recent()
        now = self.now_ms()
        full = force_full or self.requested_full or self.overflow or now-self.last_full_scan >= 60*60*1000
        scans = {row["kind"]:row for row in await asyncio.to_thread(self.repository.scans)}
        pending = [kind for kind in HISTORY if kind not in scans or not scans[kind]["complete"]]
        # Finish the durable round before starting another one. Otherwise a
        # shorter channel can perpetually restart while a longer one catches up.
        completed = [await self.history(kind,full=full) for kind in (pending or list(HISTORY))]
        if all(completed):
            await self.position_history(force=full)
            if full:
                self.last_full_scan = now
                self.requested_full = False
            self.overflow = False
            await asyncio.to_thread(self.repository.status,"synced",success=True)
            return True
        await asyncio.to_thread(self.repository.status,"syncing")
        return False

    async def position_history(self, *, force: bool = False) -> None:
        now = self.now_ms()
        if not force and now - self.last_position_history_ms < 60_000:
            return
        self.last_position_history_ms = now
        floor = three_months_before(now)
        cursor = None
        records = {}
        try:
            for page in range(20):
                params = {"instType": "SWAP", "limit": "100"}
                if cursor is not None:
                    params["after"] = str(cursor)
                # OKX returns every row sharing the boundary uTime, so a page
                # may exceed its requested limit. The total is still bounded.
                rows = response_rows(await self.client.privateGetAccountPositionsHistory(params), 1000)
                times = [normal.timestamp(row.get("uTime")) for row in rows]
                if cursor is not None and any(value >= cursor for value in times):
                    raise AccountDataError("POSITION_HISTORY_CURSOR_STALLED")
                for row, updated in zip(rows, times, strict=True):
                    if row.get("instType") != "SWAP" or updated > now or normal.timestamp(row.get("cTime")) > updated:
                        raise AccountDataError("POSITION_HISTORY_INVALID")
                    if floor <= updated <= now:
                        key = (normal.identifier(row.get("posId")), normal.timestamp(row.get("cTime")), updated)
                        if key in records and records[key] != row:
                            raise AccountDataError("POSITION_HISTORY_CONFLICT")
                        records[key] = row
                if len(records) > 5000:
                    raise AccountDataError("POSITION_HISTORY_RECORD_LIMIT")
                if not rows or min(times) < floor:
                    payload = {"rows": list(records.values()), "fromMs": floor, "throughMs": now,
                               "complete": True, "pages": page + 1}
                    await asyncio.to_thread(self.repository.save_snapshot, "position_history", payload, self.now_ms())
                    await asyncio.to_thread(self.repository.save_snapshot, "position_history_state",
                                            {"error": None, "complete": True}, self.now_ms())
                    return
                cursor = min(times)
            raise AccountDataError("POSITION_HISTORY_PAGE_BUDGET")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = error_code(exc)
            if code in TERMINAL_ERRORS:
                raise
            # Optional corroborating evidence cannot erase successfully read
            # fills/bills or make their synchronization appear to have failed.
            await asyncio.to_thread(self.repository.save_snapshot, "position_history_state",
                                    {"error": code, "complete": False}, self.now_ms())

    async def run(self) -> None:
        tasks = [asyncio.create_task(self.consume())]
        tasks.extend(asyncio.create_task(self.watch(channel)) for channel in ["orders","positions","account"])
        delay = 1
        try:
            while True:
                self.changed.clear()
                if tasks[0].done():
                    tasks[0].result()
                try:
                    complete = await self.reconcile()
                    delay = 30 if complete else 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    code = error_code(exc)
                    await asyncio.to_thread(self.repository.status,"error",error=code)
                    if code in TERMINAL_ERRORS:
                        raise
                    delay = min(max(delay*2,2),60)
                try:
                    await asyncio.wait_for(self.changed.wait(),timeout=delay)
                    await asyncio.sleep(1)  # Coalesce private events and respect REST budgets.
                except TimeoutError:
                    pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
