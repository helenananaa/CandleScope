"""Acquire public Binance spot history into the browser's original research library."""
import asyncio
import csv
import hashlib
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.data_engine.ingestion.config import IngestionConfig
from app.data_preparation.models import Requirement
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


async def trade_rows(client, selection, output, job):
    """An ID cursor keeps trades sharing the page's final millisecond."""
    writer = csv.writer(output)
    writer.writerow(TRADE_COLUMNS)
    cursor = None
    start, end = selection.start_ms, selection.end_ms
    while start < end:
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


async def download(app, key, selection, job):
    library = app.state.local_data_service
    path = library.new_upload_path()
    client = None
    tables = get_shared_ccxt_market_tables()
    try:
        client = _create_exchange(get_ccxt_catalog_entry("binance"), IngestionConfig(), market_type="spot", websocket=False)
        await tables.load(client)
        market = next((m for m in client.markets_by_id.get(selection.symbol, []) if m.get("spot")), None)
        if not market:
            raise ValueError("找不到这个 Binance 现货交易对")
        start, end = selection.start_ms, selection.end_ms
        label = "1m" if selection.kind == "bars" else "aggTrades"
        def utc(ms):
            return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
        name = f"Binance Spot {selection.symbol} · {label} · {utc(start)} – {utc(end)} UTC"
        units = dict(name=name, symbol=selection.symbol, base_asset=market["base"], quote_asset=market["quote"], timestamp_unit="ms")
        with path.open("x", newline="", encoding="utf-8") as output:
            if selection.kind == "bars":
                writer = csv.writer(output)
                fields = ("open_time", "open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
                writer.writerow(fields)
                for first in range(start, end, 86_400_000):
                    requirement = Requirement(exchange="binance", market_type="spot", symbol=selection.symbol,
                                              start_ms=first, end_ms=min(end, first + 86_400_000))
                    rows = await app.state.data_preparation_service.adapter.complete_host_bars(requirement, key)
                    for row in rows:
                        writer.writerow([row.get(field) for field in fields])
                    job["rows"] += len(rows)
            else:
                await trade_rows(client, selection, output, job)
        if selection.kind == "bars":
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
        job.update(status="complete", dataset=result)
    except Exception as exc:
        logging.getLogger(__name__).warning("Library download failed", exc_info=True)
        job.update(status="failed", error=str(exc)[:400] or type(exc).__name__)
    finally:
        path.unlink(missing_ok=True)
        if client is not None:
            tables.release(client)
            await client.close()


@router.post("")
async def submit(selection: Selection, request: Request):
    start, end = selection.start_ms, selection.end_ms
    if start % minute or end % minute or end <= start or end > int(time.time() * 1000):
        raise HTTPException(422, "请选择已结束且对齐到分钟的 UTC 时间区间")
    if (end - start) // minute > (MAX_TRADE_ROWS if selection.kind == "aggTrades" else request.app.state.replay_service.settings.max_bar_dataset_rows):
        raise HTTPException(422, "超出回放资料库的容量，请缩短区间")
    key = hashlib.sha256(selection.model_dump_json().encode()).hexdigest()
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
