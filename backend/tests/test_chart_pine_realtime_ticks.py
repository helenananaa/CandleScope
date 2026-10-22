"""Actual observed aggregate-trade Pine stream, costs and durable restart."""
import json
import os
import subprocess

import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider
from tests.test_chart_pine_callbacks import service as service,pytestmark as pytestmark
from tests.test_chart_pine_callbacks import payload,execute,RecordingProvider
from tests.test_native_backtests import runtime as runtime


SOURCE='''//@version=6
strategy("observed ticks",calc_on_every_tick=true,calc_on_order_fills=true)
varip int n=0
n+=1
if n==1
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0
    strategy.close_all()
plot(n)
plot(strategy.position_size)
plot(close)
plot(volume)
'''


@pytest.mark.parametrize("inline,spot,flags",[(True,False,""),(False,False,""),(True,True,""),
    (True,False,"without_fills"),(True,False,"both_tick_flags")])
def test_actual_source_prints_evaluate_once_after_matching_and_costs_use_the_same_clock(service,inline,spot,flags):
    service._colocated_worker=inline
    source=SOURCE.replace(',calc_on_order_fills=true','') if flags=="without_fills" else SOURCE
    if flags=="both_tick_flags": source=source.replace('calc_on_every_tick=true','calc_on_every_tick=true,calc_on_every_history_tick=true')
    value=payload(service,source,execution_model_revision="EXECUTION_REALISM_V2",participation_rate=".5",
                  **({"account_model":"SPOT_CASH_V1","market_type":"spot"} if spot else {}))
    run=service.create_run(value,idempotency_key="observed-ticks",now_ms=3)
    provider=RecordingProvider()
    result=execute(service,run,provider)
    frames=provider.observations
    assert [frame.event_time_ms for frame in frames]==[1000,59999,60000,70000,119999,119999,120000,179999,180000]
    assert [frame.account_view["position_size"] for frame in frames]==[0,0,2,0,0,0,0,0,0]
    assert [frame.features["pineExecutionContext"]["is_new"] for frame in frames]==[True,False,True,False,False,False,True,False,True]
    assert all(frame.features["pineExecutionContext"]["bar_state"]=="realtime" for frame in frames)
    assert [fill["event_time_ms"] for fill in result["report"]["fills"]]==[60000,70000]
    metadata=result["report"]["strategy"]["pineExecution"]
    assert metadata["profile"]=="OBSERVED_AGG_TRADE_TICK_STREAM"
    assert metadata["realtimeTickCount"]==6 and metadata["confirmationCount"]==3 and metadata["fillCallbackCount"]==0
    assert result["report"]["cost_sensitivity"]["baseline_reexecution_verified"] is True
    saved=provider.snapshot()
    assert saved["stream_checkpoint"]["cursor"]==3 and saved["stream_checkpoint"]["bar_open"]
    restored=PineEngineProvider()
    try:
        restored.restore(saved)
        assert restored.snapshot()==saved
    finally: restored.close()


def test_supervised_whole_run_worker_executes_realtime_ticks_and_cost_scenarios(service):
    service._colocated_worker=False
    value=payload(service,SOURCE,execution_model_revision="EXECUTION_REALISM_V2",participation_rate=".5")
    result=execute(service,service.create_run(value,idempotency_key="whole-tick-worker",now_ms=3))
    assert result["report"]["strategy"]["pineExecution"]["realtimeTickCount"]==6
    assert result["report"]["cost_sensitivity"]["baseline_reexecution_verified"] is True


def test_trade_checkpoint_restores_open_bar_and_never_rematches_its_recorded_fills(service):
    value=payload(service,SOURCE)
    baseline=execute(service,service.create_run(value,idempotency_key="ticks-baseline",now_ms=3))
    run=service.create_run(value,idempotency_key="ticks-interrupted",now_ms=3)
    original=service.repository.save_checkpoint
    def save(value):
        result=original(value)
        if value["sequence"]==3: raise KeyboardInterrupt("interrupt after recorded close fill and its tick")
        return result
    service.repository.save_checkpoint=save
    try:
        with pytest.raises(KeyboardInterrupt): execute(service,run)
    finally: service.repository.save_checkpoint=original
    checkpoint=service.repository.latest_checkpoint(run["run_id"])
    saved=json.loads(checkpoint["payload_json"])
    assert saved["provider"]["provider"]["stream_checkpoint"]["bar_open"]
    assert service.requeue_interrupted_run(run["run_id"],expected_generation=1,now_ms=8)
    recovered=execute(service,run)
    assert recovered["report"]["fills"]==baseline["report"]["fills"]
    assert recovered["report"]["hashes"]==baseline["report"]["hashes"]


def test_v2_historical_marks_and_liquidation_reach_the_next_tick_without_duplicate_executions(service):
    from tests.test_chart_pine_liquidation import tape
    source=SOURCE[:SOURCE.index('if strategy.position_size>0')]+"plot(n)\nplot(strategy.position_size)\n"
    source=source.replace("qty=2","qty=50")
    value=payload(service,source,account_model="LINEAR_PERP_ONE_WAY_V2",initial_balance="1000",leverage="10",
        funding_mode="OFF",contract_data_mode="HISTORICAL_CONTRACT_V1",execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate="1",taker_fee_bps="1")
    run=service.create_run(value,idempotency_key="tick-liquidation",now_ms=3)
    provider=RecordingProvider()
    result=service.execute_dual_clock_run(run["run_id"],events=tape(),provider=provider,now_ms=4,
        observation_market={"venue":"binance","symbol":"BTCUSDT"})
    observations=provider.observations
    tick_frames=[frame for frame in observations if frame.features["pineExecutionContext"]["trigger"]=="realtime_tick"]
    assert [frame.event_time_ms for frame in tick_frames]==[1000,60000,130000,180000]
    assert [frame.account_view["position_size"] for frame in tick_frames]==[0,50,0,0]
    assert any(row.get("account_liquidation") for row in result["report"]["fills"])
    assert result["report"]["strategy"]["pineExecution"]["fillCallbackCount"]==0
    assert result["report"]["cost_sensitivity"]["baseline_reexecution_verified"] is True


def test_realtime_confirmed_closing_fills_keep_explicit_context_and_account_feedback(service):
    source=SOURCE.replace('calc_on_order_fills=true','calc_on_order_fills=true,process_orders_on_close=true')
    source=source.replace('if n==1','if barstate.isconfirmed and n==2')
    value=payload(service,source)
    provider=RecordingProvider()
    result=execute(service,service.create_run(value,idempotency_key="tick-closing",now_ms=3),provider)
    assert [fill["event_time_ms"] for fill in result["report"]["fills"]]==[59999,59999]
    close_frames=[frame for frame in provider.observations if frame.features["pineExecutionContext"]["trigger"]=="closing_fill"]
    assert [frame.account_view["position_size"] for frame in close_frames]==[2,0]
    assert all(frame.features["pineExecutionPass"]["confirmed"] for frame in close_frames)


def test_foreign_rows_wait_for_observed_realtime_availability_and_restore_exactly(service,runtime):
    from tests.test_native_additional_inputs import additional
    host,_=runtime
    reference=additional(host,"realtime-foreign","ETHUSDT","2m",120000,[100,200,300,400,500])
    service.pine_local_data_root=str(host.local_data.root)
    source=SOURCE+'\nplot(request.security("BINANCE:ETHUSDT","2",close))\n'
    value=payload(service,source,pine_contexts=[{**reference,"symbol":"BINANCE:ETHUSDT","timeframe":"2"}])
    class RequestedValues(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.values=[]
        def step(self,frame):
            output=super().step(frame)
            self.values.append(self.stream.output()["output"]["plots"][-1]["values"][-1])
            return output
    provider=RequestedValues()
    execute(service,service.create_run(value,idempotency_key="realtime-foreign",now_ms=3),provider)
    assert provider.values==[None,None,None,None,100,100,100,100,100]
    saved=provider.snapshot()
    observations=[item["evaluation"] for group in saved["execution_schedule"] for item in group]
    assert [item["request_observed_at_ms"] for item in observations]==[frame.event_time_ms for frame in provider.observations]
    assert [len(item["request_updates"]) for item in observations]==[0,0,0,0,1,0,0,0,0]
    restored=PineEngineProvider()
    try:
        restored.restore(saved)
        assert restored.snapshot()==saved
    finally: restored.close()


def test_actual_host_observations_match_independent_native_realtime_state_and_chart_boundaries(service):
    source='''//@version=6
strategy("native realtime control",calc_on_every_tick=true)
varip int n=0
n+=1
plot(n)
plot(last_bar_index)
plot(last_bar_time)
plot(close[1])
plot(ta.sma(close,2))
plot(ta.cum(volume))
plot(request.security(syminfo.tickerid,timeframe.period,close))
'''
    provider=RecordingProvider()
    value=payload(service,source)
    execute(service,service.create_run(value,idempotency_key="native-observation-control",now_ms=3),provider)
    saved=provider.snapshot()
    native='''import json,sys,pine_compat
x=json.load(sys.stdin)
s=pine_compat.create_realtime_session(x["source"],chart_symbol="BINANCE:BTCUSDT",chart_timeframe="1")
s.seed([])
for group in x["schedule"]:
 for item in group:
  frame=item["evaluation"]
  bar={**frame["bar"],"time":frame["bar"]["time"]*1000}
  result=(s.update_confirmed if frame["confirmed"] else s.update_forming)(bar,execution_time=frame["event_time_ms"])
print(json.dumps(result["plots"]))
'''
    expected=json.loads(subprocess.check_output([os.environ["NATIVE_TEST_PINE_PYTHON"],"-I","-c",native],
        input=json.dumps(dict(source=source,schedule=saved["execution_schedule"])),text=True))
    restored=PineEngineProvider()
    try:
        restored.restore(saved)
        assert restored.stream.output()["output"]["plots"]==expected
    finally: restored.close()
