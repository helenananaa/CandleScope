"""Actual Host accounts, OHLC ticks, event discovery and durable restoration."""
from copy import deepcopy
from decimal import Decimal
import os

import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider
from app.market_dataset.snapshot import MarketEvent
from tests.test_chart_pine_callbacks import service as service
from tests.test_chart_pine_bar_callbacks import config, RecordingProvider
from tests.test_native_backtests import runtime as runtime


pytestmark=pytest.mark.skipif(not os.environ.get("PINE_EVENT_TEST_PYTHON"),reason="requires new installed event worker")

SOURCE='''//@version=6
strategy("Host event windows",calc_on_every_history_tick=true)
varip int n=0
n+=1
varip bool sent=false
r=ticker.renko(syminfo.tickerid,"Traditional",1)
x=request.security(r,timeframe.period,close,calc_bars_count=1)
if not na(x) and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=1)
if strategy.position_size>0
    strategy.close_all()
plot(x)
plot(n)
'''


def events():
    return tuple(MarketEvent(i+1,(i+1)*60000-1,"BARS",dict(open_time_ms=i*60000,
        close_time_ms=(i+1)*60000-1,open=str(p),high=str(p+1),low=str(p-1),close=str(p),volume="100"))
        for i,p in enumerate((10,13,15,12,14)))


def test_chart_event_trial_resets_the_ledger_and_restores_the_exact_physical_sources(service,monkeypatch):
    from app.backtest import native
    runtime=dict(command=[os.environ["PINE_EVENT_TEST_PYTHON"],"-I","-m","candlescope_plugin_pine_compat.native_strategy"],
        plugin_id="candlescope.pine-compat")
    monkeypatch.setattr(native,"resolve_plugin",lambda language:deepcopy(runtime))
    value=config(service,source=SOURCE,cost_sensitivity_mode="SKIP")
    record=service.create_run(value,idempotency_key="event-ledger",now_ms=3)
    provider=RecordingProvider()
    from app.backtest.errors import BacktestError
    try:
        result=service.execute_bar_run(record["run_id"],events=events(),provider=provider,now_ms=4,
            observation_market={"venue":"binance","symbol":"BTCUSDT"})
    except BacktestError as error:
        raise AssertionError(error.details) from error
    assert len(result["report"]["fills"])==2
    # Historical vertices match newly observed markets at that vertex; the
    # reducing order uses the later physical low, rather than the Renko close.
    assert [Decimal(item["price"]) for item in result["report"]["fills"]]==[Decimal(14),Decimal(13)]
    assert result["report"]["pine_orders"]["open_entries"]==[]
    saved=provider.snapshot()
    commands=[entry["command"]["operation"] for entry in saved["stream_checkpoint"]["journal"]]
    assert commands.count("stream_rebase")>=2
    restored=PineEngineProvider()
    try:
        restored.restore(saved)
        output=restored.stream.output()["output"]
        assert [plot["values"] for plot in output["plots"]]==[[None,None,None,None,14],[4,8,12,16,20]]
    finally:
        restored.close()
    changed=deepcopy(saved)
    changed["stream_checkpoint"]["opening"]["event_sources"][0]["bars"][-1]["close"]=999
    rejected=PineEngineProvider()
    try:
        from app.backtest.strategy.protocol import StrategyProviderError
        with pytest.raises(StrategyProviderError,match="physical event sources differ"):
            rejected.restore(changed)
    finally:
        rejected.close()


def test_workbench_event_trial_and_replay_use_the_same_actual_account_prefix(runtime):
    from tests.test_pine_history_tick_workbench import config as workbench_config
    from tests.test_native_backtests import terminal
    from tests.test_native_replay import settle
    host,payload=runtime
    value=workbench_config(payload)
    value.update(source=SOURCE,cost_sensitivity_mode="SKIP")
    record=terminal(host.native,host.native.create(value,"event-workbench")["run_id"],timeout=45)
    assert record["state"]=="COMPLETED",record.get("error")
    assert record["result"]["graphics"][-1]["values"]==[4*i for i in range(1,11)]
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    for target in (4,created["total"]):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        state=settle(replay,key)
        assert state.get("error") is None,state
    assert state["result"]==record["result"]
