"""Actual chart provider history ticks, costs and durable recovery."""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider
from tests.test_chart_pine_callbacks import service as service,pytestmark as pytestmark
from tests.test_chart_pine_bar_callbacks import config as base_config,execute,RecordingProvider
from tests.test_pine_history_tick_clock import SOURCE
from tests.test_native_backtests import runtime as runtime


def config(service,*,source=SOURCE,**options):
    return base_config(service,source=source,**options)


@pytest.mark.parametrize("spot,inline",[(False,True),(True,True),(False,False)])
def test_chart_runs_four_partial_observations_with_actual_feedback_and_independent_costs(service,spot,inline):
    service._colocated_worker=inline
    provider=RecordingProvider()
    value=config(service,spot=spot,source=SOURCE.replace(",calc_on_order_fills=true",""))
    result=execute(service,value,"chart-ticks",provider)
    report=result["report"]
    assert len(provider.frames)==20
    assert [frame.account_view["position_size"] for frame in provider.frames[:4]]==[0,1,0,0]
    assert [float(frame.bar["close"]) for frame in provider.frames[:4]]==[10,9,11,10]
    assert [float(frame.bar["volume"]) for frame in provider.frames[:4]]==[25,50,75,100]
    assert [Decimal(row["price"]) for row in report["fills"]]==[10,9]*5
    assert report["strategy"]["pineExecution"]["historicalTickCount"]==20
    assert report["cost_sensitivity"]["baseline_reexecution_verified"] is True
    saved=provider.snapshot()
    assert saved["stream_checkpoint"]["cursor"]==5 and saved["stream_checkpoint"]["bar_open"] is False
    assert [len(group) for group in saved["execution_schedule"]]==[4]*5


@pytest.mark.parametrize("midbar",[False,True])
def test_chart_recovers_the_committed_kernel_and_stream_without_repeating_fills(service,midbar):
    value=config(service)
    baseline=execute(service,value,"tick-baseline")
    run=service.create_run(value,idempotency_key="tick-interrupt",now_ms=3)
    if midbar:
        class Interrupted(PineEngineProvider):
            def step(self,frame):
                if frame.features["pineExecutionPass"]["barIndex"]==1 and frame.account_view["position_size"]>0:
                    raise KeyboardInterrupt("interrupt second bar after its open fill")
                return super().step(frame)
        provider=Interrupted()
    else:
        provider=PineEngineProvider()
        original=service.repository.save_checkpoint
        def save(value):
            result=original(value)
            if value["sequence"]==1: raise KeyboardInterrupt("interrupt after first complete chart bar")
            return result
        service.repository.save_checkpoint=save
    try:
        with pytest.raises(KeyboardInterrupt): execute(service,value,"tick-interrupt",provider,run)
    finally:
        if not midbar: service.repository.save_checkpoint=original
    checkpoint=service.repository.latest_checkpoint(run["run_id"])
    saved=json.loads(checkpoint["payload_json"])
    assert saved["observed"]==1
    assert service.requeue_interrupted_run(run["run_id"],expected_generation=1,now_ms=8)
    recovered=execute(service,value,"tick-interrupt",run=run)
    assert recovered["report"]["fills"]==baseline["report"]["fills"]
    assert recovered["report"]["hashes"]==baseline["report"]["hashes"]


def test_actual_whole_run_worker_executes_the_tick_profile(service):
    service._colocated_worker=False
    value=config(service)
    result=execute(service,value,"whole-worker-ticks")
    assert len(result["report"]["fills"])==10
    assert result["report"]["strategy"]["pineExecution"]["historicalTickCount"]==20
    assert result["report"]["cost_sensitivity"]["baseline_reexecution_verified"] is True


def test_calculation_window_skips_keep_original_host_time_and_restore_engine_relative_indices(service):
    source=SOURCE.replace("initial_capital=1000)","initial_capital=1000,calc_bars_count=2)")
    provider=RecordingProvider()
    value=config(service,source=source)
    report=execute(service,value,"short-window",provider)["report"]
    assert len(report["fills"])==4 and report["fills"][0]["event_time_ms"]==180000
    assert report["strategy"]["pineExecution"]["historicalTickCount"]==8
    assert report["strategy"]["pineExecution"]["historicalObservationCount"]==20
    saved=provider.snapshot()
    assert saved["stream_checkpoint"]["cursor"]==2 and saved["stream_checkpoint"]["input_skip"]==3
    restored=PineEngineProvider()
    try:
        restored.restore(saved)
        assert restored.snapshot()==saved
    finally:
        restored.close()
    changed=deepcopy(saved)
    changed["history"][0]["qty"]=99
    with pytest.raises(ValueError,match="intents differ"):
        restored=PineEngineProvider()
        try: restored.restore(changed)
        finally: restored.close()


@pytest.mark.parametrize("account",["LINEAR_PERP_ONE_WAY_V1","SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V2"])
def test_tick_profile_uses_real_v2_capacity_marks_and_cost_accounts(service,account):
    from tests.test_chart_pine_v2_bar import config as v2_config,execute as execute_v2,bars
    from tests.test_pine_v2_bar_kernel import numbered,mark
    from tests.test_backtest_account_v2_m4 import rules
    rows=bars()
    if account=="LINEAR_PERP_ONE_WAY_V2": rows=numbered(rules(-2),mark(-1,10),*rows)
    provider=RecordingProvider()
    value=v2_config(service,account=account,source=SOURCE)
    report=execute_v2(service,value,"v2-ticks",rows,provider)["report"]
    assert [Decimal(row["qty"]) for row in report["fills"]]==[1]*10
    assert len(provider.frames)==20
    assert report["strategy"]["pineExecution"]["historicalTickCount"]==20
    assert report["cost_sensitivity"]["baseline_reexecution_verified"] is True


def test_provider_half_bar_reconstruction_keeps_exact_future_intents_and_accounts(service):
    provider=RecordingProvider()
    value=config(service)
    execute(service,value,"frames-for-restart",provider)
    original=PineEngineProvider()
    recovered=PineEngineProvider()
    try:
        original.prepare(provider.snapshot()["context"])
        original.step(provider.frames[0])
        saved=original.snapshot()
        assert saved["stream_checkpoint"]["bar_open"] and saved["stream_checkpoint"]["passes"]==1
        recovered.restore(saved)
        for frame in provider.frames[1:]:
            assert original.step(frame)==recovered.step(frame)
        assert original.snapshot()==recovered.snapshot()
        assert original.history==provider.history
    finally:
        original.close()
        recovered.close()


def test_chart_requested_history_uses_canonical_visibility_and_recovers_its_feed_cursor(service,runtime):
    from tests.test_native_additional_inputs import additional
    host,_=runtime
    reference=additional(host,"chart-tick-foreign","ETHUSDT","2m",120000,[100,200,300,400,500])
    source=SOURCE+'\nplot(request.security("BINANCE:ETHUSDT","2",close))\n'
    source+='''
varip array<float> requestedSeen=array.new_float(4,na)
array.set(requestedSeen,(n-1)%4,request.security("BINANCE:ETHUSDT","2",close))
plot(array.get(requestedSeen,0))
plot(array.get(requestedSeen,1))
plot(array.get(requestedSeen,2))
plot(array.get(requestedSeen,3))
'''
    service.pine_local_data_root=str(host.local_data.root)
    value=config(service,source=source,pine_contexts=[{**reference,"symbol":"BINANCE:ETHUSDT","timeframe":"2"}])
    provider=RecordingProvider()
    execute(service,value,"chart-foreign-ticks",provider)
    saved=provider.snapshot()
    groups=saved["execution_schedule"]
    assert [item["evaluation"]["request_observed_at_ms"] for item in groups[1]]==[119999]*4
    assert [len(item["evaluation"]["request_updates"]) for item in groups[1]]==[1,0,0,0]
    recovered=PineEngineProvider()
    try:
        recovered.restore(saved)
        assert recovered.snapshot()==saved
        output=recovered.stream.output()["output"]
        assert [plot["values"] for plot in output["plots"][-5:]]==[[None,100,100,200,200]]*5
    finally: recovered.close()
