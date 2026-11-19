"""Acquire public Binance spot history into the browser's original research library."""
import asyncio
import csv
import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from weakref import WeakValueDictionary

from ccxt.base.errors import NetworkError
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.data_engine.ingestion.config import IngestionConfig
from app.data_preparation.models import PreparationError, Requirement
from app.exchanges.symbol_catalog import get_cached_symbol_metadata
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.generic import _create_exchange
from app.exchanges.ccxt_ext.markets import get_shared_ccxt_market_tables
from app.local_data.service import LocalDatasetError, LocalImportOptions
from app.local_data.user_market_trades import MAX_TRADE_ROWS, TRADE_COLUMNS, UserMarketTradeOptions
from app.research_data.access import require_local_research_access

router = APIRouter(prefix="/api/v1/local/downloads", dependencies=[Depends(require_local_research_access)])
jobs = OrderedDict()
tasks = set()
receipts = Path("/store/download-receipts")
minute = 60_000


class Selection(BaseModel):
    kind: Literal["bars", "aggTrades"]
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,40}$")
    start_ms: int = Field(gt=0)
    end_ms: int = Field(gt=0)


async def trade_rows(client, selection, writer, job, checkpoint):
    """An ID cursor keeps trades sharing the page's final millisecond."""
    cursor = None
    start, end = selection.start_ms, selection.end_ms
    while start < end:
        await checkpoint()
        # Binance time queries span at most an hour. Switch to its inclusive
        # source-ID cursor as soon as a full page could hide additional trades.
        window_end = min(start + 3_600_000, end)
        params = {"startTime": start, "endTime": window_end - 1} if cursor is None else {"fromId": cursor}
        page = await client.public_get_aggtrades({"symbol": selection.symbol, "limit": 1000, **params})
        if not isinstance(page, list):
            raise ValueError("交易所返回了无效的成交记录")
        for row in page:
            timestamp, sequence = int(row["T"]), int(row["a"])
            if timestamp >= end:
                return
            if timestamp < start or (cursor is not None and sequence != cursor):
                raise ValueError("成交序号或时间不连续，请重试")
            if job["rows"] >= MAX_TRADE_ROWS:
                raise ValueError(f"逐笔超过资料库上限 {MAX_TRADE_ROWS} 条，请缩短区间")
            writer.writerow((timestamp, sequence, row["p"], row["q"], str(row["m"]).lower()))
            job["rows"] += 1
            cursor = sequence + 1
        if len(page) < 1000:
            if cursor is not None and "fromId" in params:
                return
            start = window_end
            cursor = None


fields = ("open_time", "open", "high", "low", "close", "volume", "quote_volume",
          "trades", "taker_buy_base", "taker_buy_quote")
locks = WeakValueDictionary()


def cache_key(selection):
    return hashlib.sha256(selection.model_dump_json().encode()).hexdigest()


def bounds(manifest):
    return manifest["first_open_ms"], manifest["last_open_ms"] + minute


def cached_ranges(library, selection):
    # Only verified downloads carry venue provenance. A manually imported CSV
    # of the same symbol may belong to a different exchange.
    for manifest in library.list_datasets():
        if manifest["symbol"] != selection.symbol or manifest["interval"] != "1m":
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
            raise ValueError("已保存的 K 线覆盖不完整")
        writer.writerows([row["open_time_ms"], *(row.get(field) for field in fields[1:])] for row in rows)
    job["rows"] += count


async def prepare_range(adapter, selection, job, checkpoint, *, allow_wider=True):
    # Serialize publication for overlapping windows of the same series. The
    # next caller rechecks the committed receipts after obtaining the lock.
    series = selection.kind, selection.symbol
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
    instrument = cached[0]["instrument"] if cached else None
    if instrument is None:
        metadata = get_cached_symbol_metadata("binance", "spot", selection.symbol) or {}
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
                if client is None and (not bars or instrument is None):
                    client = _create_exchange(get_ccxt_catalog_entry("binance"), IngestionConfig(), market_type="spot", websocket=False)
                    await tables.load(client)
                    market = next((m for m in client.markets_by_id.get(selection.symbol, []) if m.get("spot")), None)
                    if not market:
                        raise ValueError("找不到这个 Binance 现货交易对")
                    instrument = {"base_asset": market["base"], "quote_asset": market["quote"]}
                job.setdefault("missing_ranges", []).append([first, stop])
                if bars:
                    for chunk in range(first, stop, 86_400_000):
                        await checkpoint()
                        requirement = Requirement(exchange="binance", market_type="spot", symbol=selection.symbol,
                                                  start_ms=chunk, end_ms=min(stop, chunk + 86_400_000))
                        rows = await adapter.complete_host_bars(requirement, key)
                        writer.writerows([row.get(field) for field in fields] for row in rows)
                        job["rows"] += len(rows)
                else:
                    await trade_rows(client, selection.model_copy(update={"start_ms":first, "end_ms":stop}), writer, job, checkpoint)
        await checkpoint()
        def utc(ms):
            return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
        label = "1m" if bars else "aggTrades"
        name = f"Binance Spot {selection.symbol} · {label} · {utc(start)} – {utc(end)} UTC"
        units = dict(name=name, symbol=selection.symbol, base_asset=instrument["base_asset"],
                     quote_asset=instrument["quote_asset"], timestamp_unit="ms")
        if bars:
            result = library.import_csv(path, LocalImportOptions(**units, interval="1m", time_column="open_time",
                volume_required=True, quote_volume_column="quote_volume", trades_column="trades",
                taker_buy_base_column="taker_buy_base", taker_buy_quote_column="taker_buy_quote"))
        else:
            result = library.import_user_market_trades(path, UserMarketTradeOptions(**units,
                trade_kind="MARKET_AGG_TRADE", coverage_start_ms=start, coverage_end_ms=end))
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
    def validate(self, request, adapter):
        scope = request.requirements[0]
        local = scope.exchange.startswith("local-") and scope.market_type == "local_bar"
        if not local and (scope.exchange != "binance" or scope.market_type != "spot"):
            raise PreparationError("INPUT_UNSUPPORTED", "网页自动补数支持 Binance 现货")
        if (scope.end_ms-scope.start_ms)//minute > adapter.replay_service.settings.max_bar_dataset_rows:
            raise PreparationError("INPUT_UNSUPPORTED", "时间范围超过回放容量，请缩短区间")

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
                    raise ValueError("所选本地资料未覆盖训练区间")
            else:
                result = await prepare_range(adapter, Selection(kind="aggTrades" if trade else "bars",
                    symbol=scope.symbol, start_ms=scope.start_ms, end_ms=scope.end_ms), job, checkpoint)
        except PreparationError:
            raise
        except (NetworkError, OSError) as exc:
            raise PreparationError("DOWNLOAD_UNAVAILABLE", "无法读取行情源，请检查网络后重试") from exc
        except (LocalDatasetError, ValueError) as exc:
            raise PreparationError("INPUT_UNAVAILABLE", str(exc)) from exc
        return {"job_id": job_id, "consumer": "REPLAY", "missing_ranges": job["missing_ranges"],
                "library_market": {"exchange":result["dataset_id"], "market_type":"local_bar"},
                "inputs": [{"dataset_id":result["dataset_id"], "data_epoch":result["data_epoch"]}]}


async def download(app, key, selection, job):
    async def checkpoint():
        await asyncio.sleep(0)
    try:
        result = await prepare_range(app.state.data_preparation_service.adapter, selection, job, checkpoint, allow_wider=False)
        job.update(status="complete", dataset=result)
    except Exception as exc:
        logging.getLogger(__name__).warning("Library download failed", exc_info=True)
        job.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:400])


@router.post("")
async def submit(selection: Selection, request: Request):
    start, end = selection.start_ms, selection.end_ms
    if start % minute or end % minute or end <= start or end > int(time.time() * 1000):
        raise HTTPException(422, "请选择已结束且对齐到分钟的 UTC 时间区间")
    if (end - start) // minute > (MAX_TRADE_ROWS if selection.kind == "aggTrades" else request.app.state.replay_service.settings.max_bar_dataset_rows):
        raise HTTPException(422, "超出回放资料库的容量，请缩短区间")
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
        raise HTTPException(404, "下载任务已结束，请重新提交同一区间以查询已保存的数据")
    return jobs[key]
