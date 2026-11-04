"""Real native trace exposed Spot depth falling into an isolated unit bucket."""
import asyncio

from aiohttp import web
import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.exchanges.ccxt_ext import generic
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.plugins.binance.plugin import BinancePlugin
from app.exchanges.public_admission import get_public_admission
from app.exchanges.rate_limits import HistoricalRequest,get_shared_rate_limit_manager
from tests.test_public_transport_loopback import serve,point_at_loopback


@pytest.mark.parametrize("limit,weight",[(None,5),(1,5),(100,5),(101,25),(500,25),(501,50),(1000,50),(1001,250),(5000,250),(5001,250)])
def test_spot_depth_uses_documented_ip_weight(limit,weight):
    policy=BinancePlugin().rate_limit_policy(IngestionConfig())
    request=HistoricalRequest("binance","spot","/api/v3/depth","BTCUSDT",limit=limit)
    rule=policy.rule_for(request)
    assert rule.request_cost(request)==weight
    klines=policy.rule_for(HistoricalRequest("binance","spot","/api/v3/klines","BTCUSDT"))
    assert rule.bucket_key==klines.bucket_key=="binance:spot:request_weight:ip"
    assert rule.algorithm=="header_weight" and rule.capacity==klines.capacity


def test_actual_ccxt_query_limit_and_response_feed_the_same_ip_bucket():
    async def run():
        received=[]
        async def handler(request):
            received.append((request.path,dict(request.query)))
            return web.json_response({"lastUpdateId":1,"bids":[],"asks":[]},
                headers={"X-MBX-USED-WEIGHT-1M":"50"})
        runner,origin=await serve(handler)
        exchange=generic._create_exchange(get_ccxt_catalog_entry("binance"),
            IngestionConfig(proxy_mode="none",proxy_egress_group="spot-depth-loopback"),
            market_type="spot",websocket=False)
        point_at_loopback(exchange,origin)
        try:
            result=await asyncio.wait_for(exchange.public_get_depth({"symbol":"BTCUSDT","limit":1000}),10)
            assert result["lastUpdateId"]==1
            assert received==[("/api/v3/depth",{"symbol":"BTCUSDT","limit":"1000"})]
            record=get_public_admission().snapshot()["recent"][-1]
            assert record["endpoint"]=="/api/v3/depth" and record["costs"]==[50]
            assert record["buckets"]==["binance:spot:request_weight:ip:egress=spot-depth-loopback"]
            assert record["quota_headers"]=={"x-mbx-used-weight-1m":"50"}
            bucket=get_shared_rate_limit_manager().snapshot()[record["buckets"][0]]
            assert {key.lower():value for key,value in bucket["last_headers"].items()}["x-mbx-used-weight-1m"]=="50"
            assert not bucket["probe_in_flight"]
        finally:await exchange.close();await runner.cleanup()
    asyncio.run(run())
