"""Event requests on actual realtime Host accounts, with discarded trial ledgers."""
from copy import deepcopy
from decimal import Decimal
import json
import os

import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider
from tests.test_chart_pine_callbacks import service as service,payload,execute
from tests.test_native_backtests import runtime as runtime,terminal

pytestmark=pytest.mark.skipif(not os.environ.get("PINE_EVENT_TEST_PYTHON"),reason="requires installed realtime event worker")

SOURCE='''//@version=6
strategy("realtime event accounts",calc_on_every_tick=true)
varip int n=0
n+=1
varip bool sent=false
r=ticker.renko(syminfo.tickerid,"Traditional",1)
x=request.security(r,timeframe.period,close)
if not na(x) and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=1)
if strategy.position_size>0
    strategy.close_all()
plot(x)
plot(n)
plot(last_bar_index)
plot(request.security(syminfo.tickerid,timeframe.period,close))
'''


@pytest.fixture
def event_worker(monkeypatch):
    from app.backtest import native
    launch=dict(command=[os.environ["PINE_EVENT_TEST_PYTHON"],"-I","-m","candlescope_plugin_pine_compat.native_strategy"],
        plugin_id="candlescope.pine-compat")
    monkeypatch.setattr(native,"resolve_plugin",lambda language:deepcopy(launch))


def test_chart_realtime_event_windows_preserve_partial_prices_and_discard_trial_fills(service,event_worker):
    value=payload(service,SOURCE,cost_sensitivity_mode="FULL",execution_model_revision="EXECUTION_REALISM_V2",participation_rate="1")
    provider=PineEngineProvider()
    completed=execute(service,service.create_run(value,idempotency_key="event-realtime",now_ms=3),provider)
    assert [Decimal(row["price"]) for row in completed["report"]["fills"]]==[Decimal(12),Decimal(13)]
    assert completed["report"]["cost_sensitivity"]["baseline_reexecution_verified"] is True
    saved=provider.snapshot()
    assert saved["stream_checkpoint"]["opening"]["plan_state"]=="realtime"
    assert sum(row["command"]["operation"]=="stream_rebase" for row in saved["stream_checkpoint"]["journal"])>=2
    assert sum(len(group) for group in saved["execution_schedule"])==9
    restored=PineEngineProvider()
    try:
        restored.restore(saved)
        assert [plot["values"] for plot in restored.stream.output()["output"]["plots"]]==[
            [None,99,12,12],[2,6,8,9],[0,1,2,3],[10,99,12,13]]
    finally:restored.close()


def test_chart_realtime_event_checkpoint_resumes_open_bar_without_rematching_discarded_trials(service,event_worker):
    value=payload(service,SOURCE,cost_sensitivity_mode="SKIP")
    baseline=execute(service,service.create_run(value,idempotency_key="event-realtime-base",now_ms=3))
    run=service.create_run(value,idempotency_key="event-realtime-stop",now_ms=3)
    original=service.repository.save_checkpoint
    def save(row):
        result=original(row)
        if row["sequence"]==5:raise KeyboardInterrupt("sealed event evaluator and actual fill checkpoint")
        return result
    service.repository.save_checkpoint=save
    try:
        with pytest.raises(KeyboardInterrupt):execute(service,run)
    finally:service.repository.save_checkpoint=original
    saved=json.loads(service.repository.latest_checkpoint(run["run_id"])["payload_json"])
    assert saved["provider"]["provider"]["stream_checkpoint"]["bar_open"]
    assert service.requeue_interrupted_run(run["run_id"],expected_generation=1,now_ms=8)
    recovered=execute(service,run)
    assert recovered["report"]["fills"]==baseline["report"]["fills"]
    assert recovered["report"]["hashes"]==baseline["report"]["hashes"]


@pytest.mark.parametrize("mode",["TRADE_TAPE","BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED"])
def test_workbench_v2_event_ticks_funding_costs_and_restart_share_one_account_prefix(runtime,mode):
    from tests.test_pine_print_ticks import config
    from tests.test_native_replay import settle
    from app.backtest.native_replay import NativeReplay
    host,main=runtime
    value=config(main,mode,False,"LINEAR_PERP_ONE_WAY_V2")
    # Preserve a position across the historical funding event. Every scenario
    # must rediscover against its own actual wallet, marks, fees and fills.
    value["source"]=SOURCE.replace('if strategy.position_size>0\n    strategy.close_all()\n','')
    value["cost_sensitivity_mode"]="AUTO"
    record=terminal(host.native,host.native.create(value,"event-realtime-v2")["run_id"],timeout=90)
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert result["cost_sensitivity"]["baseline_reexecution_verified"] is True
    assert result["position"]["funding_event_count"]==1
    assert [len(group) for group in result["raw_output"]["execution_schedule"]]==[5]*10
    assert result["graphics"][1]["values"]==list(range(5,51,5))
    assert len(result["trades"])==1
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    replay.command(key,created["revision"],"seek",3)
    assert settle(replay,key).get("error") is None
    replay.shutdown()
    replay=host.native.replay=NativeReplay(host.native)
    replay.command(key,replay.get(key)["revision"],"seek",created["total"])
    state=settle(replay,key)
    assert state.get("error") is None,state
    assert state["result"]==result


@pytest.mark.parametrize("mode",["TRADE_TAPE","BOOK_DEPTH"])
def test_bounded_realtime_event_window_keeps_skipped_account_prefix_and_replays_before_pine_start(runtime,mode):
    from tests.test_pine_print_ticks import config
    from tests.test_native_replay import settle
    host,main=runtime
    value=config(main,mode,False,"LINEAR_PERP_ONE_WAY_V2")
    value["source"]=SOURCE.replace('calc_on_every_tick=true','calc_on_every_tick=true,calc_bars_count=1').replace(
        'request.security(r,timeframe.period,close)','request.security(r,timeframe.period,ta.cum(close),calc_bars_count=1)')
    record=terminal(host.native,host.native.create(value,"bounded-event-realtime")["run_id"],timeout=60)
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    groups=result["raw_output"]["execution_schedule"]
    assert [len(group) for group in groups]==[0]*9+[5]
    assert result["graphics"][1]["values"]==[5]
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    for target in (1,created["total"]):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        state=settle(replay,key)
        assert state.get("error") is None,state
    assert state["result"]==result
