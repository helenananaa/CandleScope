"""Isolated real-DM/HTTP/WS fixture. No exchange or user-profile access."""
from __future__ import annotations

from dataclasses import asdict
import os
import tempfile
import time
from types import SimpleNamespace

_fixture_profile = tempfile.TemporaryDirectory(prefix="candlescope-synthetic-fixture-")
os.environ["CANDLE_DATA_DIR"] = _fixture_profile.name

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.synthetic import router
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey
from app.data_engine.synthetic_series.service import SyntheticSeriesService, SyntheticSourcePort
from app.data_engine.data_manager import query as query_module


app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
dm = DataManager()
key = SeriesKey("BTCUSDT", "1m")
leases = set()
start = (int(time.time()) // 60 - 4) * 60
# Freeze only this isolated QueryEngine's wall clock, so a slow cold calendar
# bootstrap cannot turn the controlled forming candle into missing history.
query_module.time = SimpleNamespace(time=lambda: start + 4 * 60 + 30,
    perf_counter=time.perf_counter, monotonic=time.monotonic)
rows = [dict(time=start + i * 60, open=close, high=close + 1, low=close - 1,
    close=close, volume=2, is_closed=i < 4) for i, close in enumerate([100, 106, 102, 110, 114])]


async def ensure(**kwargs):
    leases.add(kwargs["consumer_id"])


async def release(**kwargs):
    leases.discard(kwargs["consumer_id"])


dm.synthetic = SyntheticSeriesService(SyntheticSourcePort(dm.bars.query, dm.subscribe, dm.unsubscribe,
    ensure, release, dm.event_bus.stream_versions, dm.query_row_limit))
app.state.data_manager = dm
app.include_router(router, prefix="/api/v1")
for row in rows:
    dm.cache.upsert(key, BarData(**row, source="backfill"))


@app.get("/api/v1/fixture/bars")
async def bars():
    return {"rows": rows, "source": asdict(key)}


@app.post("/api/v1/fixture/reset")
async def reset():
    assert not dm.synthetic.instances
    rows[-1].update(close=114, high=115, low=113)
    dm.cache.clear()
    dm.event_bus.stream_versions.invalidate(key)
    for row in rows:
        dm.cache.upsert(key, BarData(**row, source="backfill"))
    return {"ok": True}


@app.get("/api/v1/fixture/state")
async def state():
    return {"instances": len(dm.synthetic.instances), "leases": len(leases)}


@app.post("/api/v1/fixture/tick/{close}")
async def tick(close: float):
    row = {**rows[-1], "close": close, "high": max(rows[-1]["open"], close) + 1,
        "low": min(rows[-1]["open"], close) - 1}
    rows[-1] = row
    value = BarData(**row, source="backfill")
    dm.cache.upsert(key, value)
    await dm.event_bus.emit(DataEvent(DataEventType.BAR_UPDATED, key, value))
    return {"row": row}


@app.on_event("shutdown")
async def shutdown():
    await dm.synthetic.close()
    _fixture_profile.cleanup()
