"""Acquire public exchange history into the browser's original research library."""
import asyncio
import csv
import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict
from decimal import Decimal
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from weakref import WeakValueDictionary

from ccxt.base.errors import NetworkError
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.exchanges import bootstrap_default_adapters
from app.data_engine.ingestion.models import StreamDescriptor, StreamType
from app.data_engine.ingestion.config import IngestionConfig
from app.data_preparation.models import PreparationError, Requirement
from app.exchanges.rate_limits import RateLimitDeferred
from app.exchanges.symbol_catalog import get_cached_symbol_metadata
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry, get_ccxt_catalog
from app.exchanges.ccxt_ext.generic import _create_exchange, resolve_ccxt_symbol
from app.exchanges.ccxt_ext.markets import get_shared_ccxt_market_tables
from app.local_data.service import LocalDatasetError, LocalImportOptions
from app.local_data.user_market_trades import MAX_TRADE_ROWS, TRADE_COLUMNS, UserMarketTradeOptions
from app.research_data.access import require_local_research_access

router = APIRouter(prefix="/api/v1/local/downloads", dependencies=[Depends(require_local_research_access)])
jobs = OrderedDict()
tasks = set()
receipts = Path("/store/download-receipts")
minute = 60_000


class LibraryError(ValueError):
    """A download failure with a stable code; the page translates the code and
    shows this English text as the detail (see serverErrors.ts)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def failure(code, message):
    return {"code": code, "message": message}


class Selection(BaseModel):
    kind: Literal["bars", "aggTrades"]
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_:/.-]{0,63}$")
    start_ms: int = Field(gt=0)
    end_ms: int = Field(gt=0)
    exchange: str = "binance"
    market_type: str = "spot"


@lru_cache(maxsize=1)
def public_markets():
    registry = bootstrap_default_adapters()
    result = {}
    for entry in get_ccxt_catalog():
        if not registry.has(entry.exchange_id):
            continue
        caps = registry.get_capabilities(entry.exchange_id)
        continuous = {m.market_type for m in caps.markets if m.calendar_id == "crypto.24x7.utc"}
        types = {m for channel in caps.channels if channel.channel.value == "kline" and channel.history
                 and "1m" in channel.params.get("interval", ()) for m in channel.market_types}
        supported = [m for m in ("spot", "futures", "swap.linear", "swap")
                     if m in types & continuous and caps.bar_spec(m, "1m", "history").basis_interval == "1m"]
        if supported:
            result[entry.exchange_id] = {"id": entry.exchange_id, "name": entry.name, "markets": supported,
                "trades": [m for m in supported if entry.exchange_id in ("binance", "okx") and m in ("spot", "futures")]}
    return result


def validate_source(exchange, market_type, trades):
    venue = public_markets().get(exchange)
    if venue is None or market_type not in venue["markets"]:
        raise LibraryError("LIBRARY_SOURCE_UNSUPPORTED", f"{exchange} / {market_type} has no 1-minute history for replay")
    if trades and market_type not in venue["trades"]:
        raise LibraryError("LIBRARY_SOURCE_UNSUPPORTED",
                           f"{exchange} / {market_type} replays candles; verifiable trade history is not available yet")


@router.get("/markets")
def markets():
    return list(public_markets().values())



async def trade_rows(client, selection, native_id, writer, job, checkpoint):
    """An ID cursor keeps trades sharing the page's final millisecond."""
    cursor = None
    start, end = selection.start_ms, selection.end_ms
    while start < end:
        await checkpoint()
        # Binance time queries span at most an hour. Switch to its inclusive
        # source-ID cursor as soon as a full page could hide additional trades.
        window_end = min(start + 3_600_000, end)
        params = {"startTime": start, "endTime": window_end - 1} if cursor is None else {"fromId": cursor}
        method = client.public_get_aggtrades if selection.market_type == "spot" else client.fapipublic_get_aggtrades
        page = await method({"symbol": native_id, "limit": 1000, **params})
        if not isinstance(page, list):
            raise ValueError("The exchange returned invalid trades")
        for row in page:
            timestamp, sequence = int(row["T"]), int(row["a"])
            if timestamp >= end:
                return
            if timestamp < start or (cursor is not None and sequence != cursor):
                raise ValueError("Trade IDs or times are not continuous; try again")
            if job["rows"] >= MAX_TRADE_ROWS:
                raise LibraryError("LIBRARY_RANGE_TOO_LARGE", f"More than {MAX_TRADE_ROWS} trades; choose a shorter range")
            writer.writerow((timestamp, sequence, row["p"], row["q"], str(row["m"]).lower()))
            job["rows"] += 1
            cursor = sequence + 1
        if len(page) < 1000:
            if cursor is not None and "fromId" in params:
                return
            start = window_end
            cursor = None


async def okx_trade_rows(client, selection, market, writer, job, checkpoint):
    # Start at the exclusive right edge, then page by trade ID so that
    # records sharing one millisecond survive a page boundary.
    params = {"type": "2", "after": str(selection.end_ms)}
    newest = None
    rows = []
    multiplier = Decimal(str(market["contractSize"])) if market.get("contract") else Decimal(1)
    while True:
        await checkpoint()
        response = await client.public_get_market_history_trades({"instId": market["id"], "limit": "100", **params})
        page = response["data"]
        if not isinstance(page, list):
            raise ValueError("OKX returned invalid historical trades")
        reached_start = False
        for raw in page:
            seq, ts = int(raw["tradeId"]), int(raw["ts"])
            if raw["instId"] != market["id"] or (newest is not None and seq != newest - 1):
                raise ValueError("OKX trades changed symbol or skipped IDs")
            newest = seq
            if ts < selection.start_ms:
                reached_start = True
                break
            if ts < selection.end_ms:
                if raw["side"] not in ("buy", "sell"):
                    raise ValueError("OKX returned an invalid trade side")
                if job["rows"] >= MAX_TRADE_ROWS:
                    raise LibraryError("LIBRARY_RANGE_TOO_LARGE", f"More than {MAX_TRADE_ROWS} trades; choose a shorter range")
                rows.append((ts, seq, raw["px"], format(Decimal(raw["sz"]) * multiplier, "f"), "true" if raw["side"] == "sell" else "false"))
                job["rows"] += 1
        if reached_start or len(page) < 100:
            break
        params = {"type": "1", "after": str(newest)}
    writer.writerows(reversed(rows))


fields = ("open_time", "open", "high", "low", "close", "volume", "quote_volume",
          "trades", "taker_buy_base", "taker_buy_quote")
locks = WeakValueDictionary()


def cache_key(selection):
    # Old receipts are exclusively Binance spot. Preserve them across upgrade.
    legacy = selection.exchange == "binance" and selection.market_type == "spot"
    wire = selection.model_dump_json(exclude={"exchange", "market_type"} if legacy else set())
    return hashlib.sha256(wire.encode()).hexdigest()


def bounds(manifest):
    return manifest["first_open_ms"], manifest["last_open_ms"] + minute


def cached_ranges(library, selection):
    # Only verified downloads carry venue provenance. A manually imported CSV
    # of the same symbol may belong to a different exchange.
    for manifest in library.list_datasets():
        if manifest["interval"] != "1m":
            continue
        if bool(manifest.get("market_trade_input")) != (selection.kind == "aggTrades"):
            continue
        first, end = bounds(manifest)
        if first >= selection.end_ms or end <= selection.start_ms:
            continue
        receipt = receipts / cache_key(selection.model_copy(update={"start_ms": first, "end_ms": end}))
        if receipt.is_file() and json.loads(receipt.read_text()) == [manifest["dataset_id"], manifest["data_epoch"]]:
            yield manifest


def segments(selection, cached):
    cursor = selection.start_ms
    for item in sorted(cached, key=lambda m: (bounds(m)[0], -bounds(m)[1])):
        first, end = bounds(item)
        if end <= cursor:
            continue
        if first > cursor:
            yield cursor, first, None
        stop = min(end, selection.end_ms)
        yield max(cursor, first), stop, item
        cursor = stop
        if cursor == selection.end_ms:
            return
    if cursor < selection.end_ms:
        yield cursor, selection.end_ms, None


def copy_cached(library, item, first, end, kind, writer, job):
    identity = item["dataset_id"], item["data_epoch"]
    if kind == "aggTrades":
        _, count, rows = library.read_user_market_trades(*identity, start_ms=first, end_ms=end-1,
            max_rows=MAX_TRADE_ROWS-job["rows"], include_rows=True)
        writer.writerows((t, seq, price, qty, str(bool(maker)).lower()) for t, seq, price, qty, maker in rows)
    else:
        count = (end-first)//minute
        _, rows = library.load_pinned_closed_bars(identity[0], data_epoch=identity[1], interval="1m",
                                                   through_ms=end-1, limit=count)
        if len(rows) != count or any(row["open_time_ms"] != first+i*minute for i,row in enumerate(rows)):
            raise ValueError("The saved candles do not cover the whole range")
        writer.writerows([row["open_time_ms"], *(row.get(field) for field in fields[1:])] for row in rows)
    job["rows"] += count


async def prepare_range(adapter, selection, job, checkpoint, *, allow_wider=True):
    # Serialize publication for overlapping windows of the same series. The
    # next caller rechecks the committed receipts after obtaining the lock.
    series = selection.exchange, selection.market_type, selection.kind, selection.symbol
    lock = locks.setdefault(series, asyncio.Lock())
    async with lock:
        await checkpoint()
        library = adapter.local_data
        cached = list(cached_ranges(library, selection))
        covering = [m for m in cached if bounds(m)[0] <= selection.start_ms and bounds(m)[1] >= selection.end_ms]
        if not allow_wider:
            covering = [m for m in covering if bounds(m) == (selection.start_ms, selection.end_ms)]
        if covering:
            return min(covering, key=lambda m: m["rows"])
        return await assemble(adapter, selection, cached, job, checkpoint)


async def assemble(adapter, selection, cached, job, checkpoint):
    library = adapter.local_data
    key = cache_key(selection)
    path = Path("/tmp") / f"download-{uuid.uuid4().hex}.csv"
    client = None
    tables = get_shared_ccxt_market_tables()
    start, end = selection.start_ms, selection.end_ms
    # The library uses path-safe native IDs; CCXT chart symbols may include
    # slash and settlement suffix. Receipt keys retain the full acquisition identity.
    replay_symbol = cached[0]["symbol"] if cached else (selection.symbol if "/" not in selection.symbol else None)
    instrument = cached[0]["instrument"] if cached else None
    if instrument is None:
        metadata = get_cached_symbol_metadata(selection.exchange, selection.market_type, selection.symbol) or {}
        if metadata.get("baseAsset") and metadata.get("quoteAsset"):
            instrument = {"base_asset": metadata["baseAsset"], "quote_asset": metadata["quoteAsset"]}
    try:
        with path.open("x", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            bars = selection.kind == "bars"
            writer.writerow(fields if bars else TRADE_COLUMNS)
            for first, stop, item in segments(selection, cached):
                await checkpoint()
                if item is not None:
                    copy_cached(library, item, first, stop, selection.kind, writer, job)
                    continue
                if client is None and (not bars or instrument is None or replay_symbol is None or (selection.market_type != "spot" and not cached)):
                    if selection.exchange == "binance" and selection.market_type == "spot":
                        await asyncio.shield(adapter.replay_library.market_warmup)
                    client = _create_exchange(get_ccxt_catalog_entry(selection.exchange), IngestionConfig(),
                                              market_type=selection.market_type, websocket=False)
                    await tables.load(client)
                    descriptor = StreamDescriptor(selection.symbol, StreamType.KLINE, interval="1m",
                                                  exchange=selection.exchange, market_type=selection.market_type)
                    symbol = resolve_ccxt_symbol(client, descriptor)
                    market = client.markets[symbol]
                    replay_symbol = str(market["id"]).upper() if "/" in selection.symbol else selection.symbol
                    if market.get("contract") and not market.get("linear"):
                        raise LibraryError("LIBRARY_SOURCE_UNSUPPORTED", "This symbol is an inverse contract; replay uses linear contracts")
                    instrument = {"base_asset": market["base"], "quote_asset": market["quote"]}
                job.setdefault("missing_ranges", []).append([first, stop])
                if bars:
                    for chunk in range(first, stop, 86_400_000):
                        await checkpoint()
                        requirement = Requirement(exchange=selection.exchange, market_type=selection.market_type, symbol=selection.symbol,
                                                  start_ms=chunk, end_ms=min(stop, chunk + 86_400_000))
                        rows = await adapter.complete_host_bars(requirement, key)
                        writer.writerows([row.get(field) for field in fields] for row in rows)
                        job["rows"] += len(rows)
                else:
                    window = selection.model_copy(update={"start_ms": first, "end_ms": stop})
                    if selection.exchange == "okx":
                        await okx_trade_rows(client, window, market, writer, job, checkpoint)
                    else:
                        await trade_rows(client, window, market["id"], writer, job, checkpoint)
        await checkpoint()
        def utc(ms):
            return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
        label = "1m" if bars else "aggTrades"
        name = f"{selection.exchange} {selection.market_type} {selection.symbol} · {label} · {utc(start)} – {utc(end)} UTC"
        units = dict(name=name, symbol=replay_symbol, base_asset=instrument["base_asset"],
                     quote_asset=instrument["quote_asset"], timestamp_unit="ms")
        if bars:
            result = library.import_csv(path, LocalImportOptions(**units, interval="1m", time_column="open_time",
                volume_required=True, quote_volume_column="quote_volume", trades_column="trades",
                taker_buy_base_column="taker_buy_base", taker_buy_quote_column="taker_buy_quote"))
        else:
            result = library.import_user_market_trades(path, UserMarketTradeOptions(**units,
                trade_kind="MARKET_TRADE" if selection.exchange == "okx" else "MARKET_AGG_TRADE", coverage_start_ms=start, coverage_end_ms=end))
        receipts.mkdir(exist_ok=True)
        receipt = receipts / key
        temp = receipt.with_suffix(".tmp")
        temp.write_text(json.dumps([result["dataset_id"], result["data_epoch"]]))
        temp.replace(receipt)
        return result
    finally:
        path.unlink(missing_ok=True)
        if client is not None:
            tables.release(client)
            await client.close()


class ReplayLibrary:
    def trade_providers(self):
        return [{"exchange": v["id"], "market_type": m} for v in public_markets().values() for m in v["trades"]]

    def validate(self, request, adapter):
        scope = request.requirements[0]
        local = scope.exchange.startswith("local-") and scope.market_type == "local_bar"
        if not local:
            try:
                validate_source(scope.exchange, scope.market_type, request.intent["replay_setup"]["source_kind"] == "AGG_TRADE")
            except ValueError as exc:
                raise PreparationError("INPUT_UNSUPPORTED", str(exc)) from exc
        if (scope.end_ms-scope.start_ms)//minute > adapter.replay_service.settings.max_bar_dataset_rows:
            raise PreparationError("INPUT_UNSUPPORTED", "The range is larger than replay can hold; choose a shorter range")

    async def prepare(self, request, adapter, job_id, checkpoint):
        scope = request.requirements[0]
        trade = request.intent["replay_setup"]["source_kind"] == "AGG_TRADE"
        job = {"rows": 0, "missing_ranges": []}
        try:
            if scope.market_type == "local_bar":
                result = adapter.local_data.get_manifest(scope.exchange)
                first, end = bounds(result)
                if (result["symbol"] != scope.symbol or (trade and not result.get("market_trade_input"))
                        or scope.start_ms < first or scope.end_ms > end):
                    raise ValueError("The selected library dataset does not cover the training range")
            else:
                result = await prepare_range(adapter, Selection(kind="aggTrades" if trade else "bars",
                    exchange=scope.exchange, market_type=scope.market_type,
                    symbol=scope.symbol, start_ms=scope.start_ms, end_ms=scope.end_ms), job, checkpoint)
        except PreparationError:
            raise
        except RateLimitDeferred as exc:
            raise PreparationError("RATE_LIMIT", "Waiting for the market data source's request quota", retryable=True,
                                   retry_at_ms=int(time.time() * 1000 + exc.retry_after_seconds * 1000)) from exc
        except (NetworkError, TimeoutError, ConnectionError) as exc:
            reason = f"{type(exc).__name__}: {exc}"[:250]
            raise PreparationError("DOWNLOAD_UNAVAILABLE",
                                   f"The browser could not reach the market data source; check the network or use the desktop app: {reason}",
                                   retryable=True) from exc
        except (LocalDatasetError, ValueError) as exc:
            raise PreparationError("INPUT_UNAVAILABLE", str(exc)) from exc
        return {"job_id": job_id, "consumer": "REPLAY", "missing_ranges": job["missing_ranges"],
                "library_market": {"exchange":result["dataset_id"], "market_type":"local_bar", "symbol":result["symbol"]},
                "inputs": [{"dataset_id":result["dataset_id"], "data_epoch":result["data_epoch"]}]}


async def download(app, key, selection, job):
    async def checkpoint():
        await asyncio.sleep(0)
    try:
        result = await prepare_range(app.state.data_preparation_service.adapter, selection, job, checkpoint, allow_wider=False)
        job.update(status="complete", dataset=result)
    except Exception as exc:
        logging.getLogger(__name__).warning("Library download failed", exc_info=True)
        # Data problems explain themselves; anything else keeps its type as a technical detail.
        detail = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
        job.update(status="failed", error=detail[:400], error_code=getattr(exc, "code", "LIBRARY_DOWNLOAD_FAILED"))


@router.post("")
async def submit(selection: Selection, request: Request):
    try:
        validate_source(selection.exchange, selection.market_type, selection.kind == "aggTrades")
    except LibraryError as exc:
        raise HTTPException(422, failure(exc.code, str(exc))) from exc
    start, end = selection.start_ms, selection.end_ms
    if start % minute or end % minute or end <= start or end > int(time.time() * 1000):
        raise HTTPException(422, failure("LIBRARY_RANGE_INVALID", "Choose a finished UTC range aligned to whole minutes"))
    if (end - start) // minute > (MAX_TRADE_ROWS if selection.kind == "aggTrades" else request.app.state.replay_service.settings.max_bar_dataset_rows):
        raise HTTPException(422, failure("LIBRARY_RANGE_TOO_LARGE", "The range is larger than the replay library can hold"))
    key = cache_key(selection)
    job = jobs.get(key)
    if job and job["status"] == "downloading":
        return job
    receipt = receipts / key
    if receipt.is_file():
        dataset_id, epoch = json.loads(receipt.read_text())
        try:
            manifest = request.app.state.local_data_service.get_manifest(dataset_id)
        except LocalDatasetError as exc:
            if exc.code != "dataset_not_found":
                raise
        else:
            if manifest["data_epoch"] == epoch:
                return {"id": key, "status": "complete", "rows": manifest["rows"], "dataset": manifest}
    for old in list(jobs):
        if len(jobs) < 100:
            break
        if jobs[old]["status"] != "downloading":
            del jobs[old]
    job = jobs[key] = {"id": key, "status": "downloading", "rows": 0}
    task = asyncio.create_task(download(request.app, key, selection, job))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return job


@router.get("/{key}")
async def status(key: str):
    if key not in jobs:
        raise HTTPException(404, failure("LIBRARY_DOWNLOAD_ENDED", "The download has ended; submit the same range to read the saved data"))
    return jobs[key]
