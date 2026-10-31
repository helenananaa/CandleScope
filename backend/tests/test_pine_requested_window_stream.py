"""Known requested history windows must not anchor to a growing feed prefix."""
from tests.test_chart_pine_callbacks import service as service,pytestmark as pytestmark
from tests.test_native_backtests import runtime as runtime
from tests.test_chart_pine_bar_callbacks import config,execute,RecordingProvider
import pytest
from copy import deepcopy


@pytest.mark.parametrize("count",[None,2])
def test_historical_chart_uses_the_known_requested_endpoint_without_revealing_future_values(service,runtime,count):
    from tests.test_native_additional_inputs import additional
    host,_=runtime
    reference=additional(host,"requested-window","ETHUSDT","1m",60000,[100,200,300,400,500])
    service.pine_local_data_root=str(host.local_data.root)
    source='//@version=6\nstrategy("known window",calc_on_every_history_tick=true)\nplot(request.security("BINANCE:ETHUSDT","1",ta.cum(close),calc_bars_count=1))'
    if count: source=source.replace('calc_on_every_history_tick=true)','calc_on_every_history_tick=true,calc_bars_count=2)')
    value=config(service,source=source,pine_contexts=[{**reference,"symbol":"BINANCE:ETHUSDT","timeframe":"1"}],
                 cost_sensitivity_mode="SKIP")
    provider=RecordingProvider()
    execute(service,value,"requested-window",provider)
    saved=provider.snapshot()
    planned=saved["stream_checkpoint"]["opening"]["requested_history"]
    assert planned==[dict(symbol="BINANCE:ETHUSDT",timeframe="1",times_ms=[i*60000 for i in range(5)])]
    from app.backtest.strategy.pine_engine import PineEngineProvider
    restored=PineEngineProvider()
    try:
        restored.restore(saved)
        output=restored.stream.output()["output"]
        assert output["plots"][-1]["values"]==([None,500] if count else [None,None,None,None,500])
    finally: restored.close()
    from app.backtest.strategy.protocol import StrategyProviderError
    tampered=deepcopy(saved)
    tampered["stream_checkpoint"]["opening"]["requested_history"][0]["times_ms"][-1]+=60000
    rejected=PineEngineProvider()
    try:
        with pytest.raises(StrategyProviderError,match="requested window endpoints differ"):
            rejected.restore(tampered)
    finally: rejected.close()


@pytest.mark.parametrize("count",[None,2])
def test_workbench_requested_window_and_skipped_chart_accounts_recover_without_changing_the_origin(runtime,count):
    from tests.test_native_additional_inputs import additional
    from tests.test_native_backtests import terminal
    from tests.test_pine_history_tick_workbench import config as workbench_config
    from tests.test_native_replay import settle
    host,main=runtime
    value=workbench_config(main,count=count)
    value["source"]='//@version=6\nstrategy("known Workbench window",calc_on_every_history_tick=true'+(',calc_bars_count=2' if count else '')+')\nplot(request.security("BINANCE:ETHUSDT","1",ta.cum(close),calc_bars_count=3))'
    value["contexts"]=[{**additional(host,"workbench-requested-window","ETHUSDT","1m",60000,list(range(100,1001,100))),
        "symbol":"BINANCE:ETHUSDT","timeframe":"1"}]
    value["cost_sensitivity_mode"]="SKIP"
    record=terminal(host.native,host.native.create(value,"workbench-requested-window")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    expected=[1700,2700] if count else [None]*7+[800,1700,2700]
    assert record["result"]["graphics"][-1]["values"]==expected
    replay=host.native.replay
    created=replay.create(record["run_id"])
    key=created["replay_id"]
    for target in (2,created["total"]):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        state=settle(replay,key)
        assert state.get("error") is None,state
    assert state["result"]==record["result"]
