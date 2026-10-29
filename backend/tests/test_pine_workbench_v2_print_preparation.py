import asyncio
import os
from decimal import Decimal as D
import httpx
import pytest

from app.backtest.native import invoke
from tests.test_external_preparation import environment, START_MS
from tests.test_data_preparation import async_test, terminal
from tests.test_native_strategy_plugins import plugin
from tests.test_backtest_account_v2_m4 import rules


@async_test
@pytest.mark.parametrize("callbacks",[False,True])
@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PYTHON"),reason="requires installed Pine worker")
async def test_automatic_v2_trade_preparation_preserves_account_and_rejects_bad_profile_before_acquisition(tmp_path,callbacks):
    runtime,service,app,run,calls,_=environment(tmp_path)
    runtime.native.runner,runtime.native.resolver=invoke,plugin
    t=START_MS
    account={"symbol":"BTCUSDT","events":[
        dict(time_ms=t-2,role="INSTRUMENT_RULES",payload=dict(rules(t-2).payload)),
        dict(time_ms=t-1,role="MARK_INDEX",payload={"mark_price":"100","index_price":"100"}),
        dict(time_ms=t+70000,role="MARK_INDEX",payload={"mark_price":"120","index_price":"120"}),
        dict(time_ms=t+90000,role="FUNDING",payload={"rate":".001","period_id":"p1"})],"provenance":{"fixture":"prepared-physical-account"}}
    source='//@version=6\nstrategy("prepared V2"'+(',calc_on_order_fills=true' if callbacks else '')+')\nif bar_index==0 and barstate.isconfirmed\n    strategy.entry("L",strategy.long,qty=.25)\nif bar_index==2 and barstate.isconfirmed\n    strategy.close("L")\nplot(strategy.position_size)'
    body={"idempotency_key":"automatic-v2-trade", "language":"pine","source":source,
        "execution":{"execution_fidelity":"TRADE_TAPE","host_settings":{"initial_balance":1000,"slippage_bps":0,"taker_fee_bps":0},
            "fill_recalculation":callbacks,"account_model":"LINEAR_PERP_ONE_WAY_V2","leverage":10,
            "funding_mode":"HISTORICAL_REQUIRED","account_data":account,"cost_sensitivity_mode":"SKIP"},
        "context":{**{key:run[key] for key in ("exchange","market_type","interval","start_time_ms","end_time_ms")},
            "symbol":"BTCUSDT","range_mode":"CUSTOM","fidelity_preference":"FAST"}}
    await service.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            bad=await client.post("/data-preparations/native-strategy",json={**body,"language":"pyne"})
            assert bad.status_code==422 and not calls,bad.text
            response=await client.post("/data-preparations/native-strategy",json=body)
            assert response.status_code==202,response.text
            # This path starts actual isolated interpreters. The shared helper's
            # five seconds is for in-memory adapters; native calls retain their
            # own bounded timeouts, independently of this integration wait.
            job=await terminal(service,response.json()["id"],timeout=30)
            assert job["state"]=="READY",job.get("error")
            assert job["attempts"]==0 and job.get("error") is None
            assert (await client.post("/data-preparations/native-strategy",json=body)).json()["id"]==job["id"]
        for _ in range(2000):
            record=runtime.native.get(job["result"]["native_run"]["run_id"])
            if record["state"] in {"COMPLETED","FAILED"}: break
            await asyncio.sleep(.01)
        assert record["state"]=="COMPLETED",record.get("error")
        result=record["result"]
        assert record["config"]["account_data"]==account
        assert result["account_model"]=="LINEAR_PERP_ONE_WAY_V2"
        assert [D(row["qty"]) for row in result["trades"]]==[D('.25'),D('.25')]
        assert result["position"]["funding_event_count"]==1
        assert D(result["position"]["cumulative_funding"])==D('-.03')
        assert len(calls)==2 and len(runtime.native.list())==1
    finally:
        await service.shutdown()
        runtime.shutdown()
