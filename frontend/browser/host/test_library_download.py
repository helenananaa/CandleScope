import asyncio
import csv
import hashlib
import io
import json

import pytest

from library_download import Selection, cache_key, okx_trade_rows, public_markets


def test_cache_provenance_keeps_old_spot_receipts_separate_from_perpetuals():
    legacy_wire = '{"kind":"bars","symbol":"ETHUSDT","start_ms":60000,"end_ms":180000}'
    spot = Selection(**json.loads(legacy_wire))
    assert cache_key(spot) == hashlib.sha256(legacy_wire.encode()).hexdigest()
    assert len({cache_key(spot.model_copy(update={"exchange": v, "market_type": m}))
                for v in ("binance", "okx") for m in ("spot", "futures")}) == 4


def test_market_picker_requires_an_actual_minute_basis():
    catalog = public_markets()
    assert set(catalog["okx"]["trades"]) == {"spot", "futures"}
    assert "swap.linear" in catalog["bybit"]["markets"]
    assert "swap.inverse" not in catalog["bybit"]["markets"]
    assert not catalog["bitget"]["trades"]


@pytest.mark.asyncio
async def test_okx_swap_trade_cursor_preserves_side_quantity_and_large_ids():
    selection = Selection(kind="aggTrades", symbol="ETH-USDT-SWAP", exchange="okx", market_type="futures",
                          start_ms=60000, end_ms=120000)
    high = 2**53 + 200
    market = {"id": selection.symbol, "contract": True, "contractSize": "0.1"}
    queries = []

    class Exchange:
        async def public_get_market_history_trades(self, params):
            queries.append(params)
            if len(queries) == 1:
                assert params["type"] == "2" and params["after"] == "120000"
                ids = range(high, high - 100, -1)
            else:
                assert params["type"] == "1" and params["after"] == str(high - 99)
                ids = (high - 100, high - 101)
            return {"data": [{"instId": market["id"], "tradeId": str(i), "ts": 61000 if i > high-101 else 59000,
                              "px":"3100.10", "sz":"7", "side":"sell"} for i in ids]}

    output = io.StringIO()
    job = {"rows":0}
    await okx_trade_rows(Exchange(), selection, market, csv.writer(output), job, lambda: asyncio.sleep(0))
    rows = list(csv.reader(io.StringIO(output.getvalue())))
    assert len(queries) == 2 and job["rows"] == len(rows) == 101
    assert [int(r[1]) for r in rows] == list(range(high-100,high+1))
    assert all(r[3:] == ["0.7","true"] for r in rows)
