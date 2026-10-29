"""Durable chart recovery after discovery and actual supervised execution."""
import json
import pytest

from tests.test_chart_pine_callbacks import service as service,pytestmark as pytestmark
from tests.test_native_backtests import runtime_at
from tests.test_chart_pine_bar_callbacks import config,execute
from app.backtest.strategy.pine_engine import PineEngineProvider


@pytest.fixture
def runtime(tmp_path):
    directory=tmp_path/"native-window-recovery"
    directory.mkdir()
    yield from runtime_at(directory)


SOURCE='''//@version=6
strategy("recover observed window",calc_on_every_history_tick=true,calc_bars_count=1)
strategy.risk.max_intraday_filled_orders(2)
varip int n=0
n+=1
if n==1
    strategy.entry("L",strategy.long,qty=1)
s=strategy.position_size>0?syminfo.tickerid:"BINANCE:ETHUSDT"
plot(request.security(s,"1",ta.cum(close),calc_bars_count=3))
plot(n)
plot(strategy.position_size)
'''


def value_for(service,runtime):
    from tests.test_native_additional_inputs import additional
    host,_=runtime
    reference=additional(host,"window-recovery","ETHUSDT","1m",60000,[100,200,300,400,500])
    service.pine_local_data_root=str(host.local_data.root)
    return config(service,source=SOURCE,cost_sensitivity_mode="SKIP",
        pine_contexts=[{**reference,"symbol":"BINANCE:ETHUSDT","timeframe":"1"}])


@pytest.mark.parametrize("stage",["trial","committed"])
def test_recovery_preserves_only_a_sealed_canonical_prefix_and_never_rematches_its_fills(service,runtime,monkeypatch,stage):
    value=value_for(service,runtime)
    baseline=execute(service,value,"window-recovery-baseline")
    run=service.create_run(value,idempotency_key="window-interrupted",now_ms=3)
    class Interrupted(PineEngineProvider):
        def step(self,frame):
            if (self.stream is not None and self.stream.last.get("window_status",{}).get("requires_discovery")
                    and self.stream.passes>=1):
                raise KeyboardInterrupt("interrupt tentative matching before its window changes")
            return super().step(frame)
    provider=Interrupted() if stage=="trial" else PineEngineProvider()
    save=service.repository.save_checkpoint
    def interrupted_save(payload):
        result=save(payload)
        if payload["sequence"]==3:
            raise KeyboardInterrupt("interrupt after the first retained canonical bar")
        return result
    if stage=="committed": service.repository.save_checkpoint=interrupted_save
    try:
        with pytest.raises(KeyboardInterrupt): execute(service,value,"window-interrupted",provider,run)
    finally:
        service.repository.save_checkpoint=save
    checkpoint=service.repository.latest_checkpoint(run["run_id"])
    state=json.loads(checkpoint["payload_json"])
    assert state["sequence"]==(0 if stage=="trial" else 3)
    assert len(state["engine"]["fills"])==(0 if stage=="trial" else 1)
    if stage=="committed":
        saved=state["provider"]["provider"]["stream_checkpoint"]
        assert saved["input_skip"]==2 and saved["cursor"]==1
        assert any(item["command"]["operation"]=="stream_rebase" and item["command"]["seal"]
                   for item in saved["journal"])
        from app.simulation.pine_chart_kernel import PineChartBarKernel
        fill=PineChartBarKernel._fill
        def guard(kernel,*args,**kwargs):
            assert kernel._last_event.event_time_ms>179999,"restored ledger matched an old event"
            return fill(kernel,*args,**kwargs)
        monkeypatch.setattr(PineChartBarKernel,"_fill",guard)
    assert service.requeue_interrupted_run(run["run_id"],expected_generation=1,now_ms=8)
    recovered=execute(service,value,"window-interrupted",run=run)
    for name in ("fills","orders","pine_orders","pine_risk_stops"):
        assert recovered["report"][name]==baseline["report"][name]
    for name in ("decision_hash","fill_hash","ledger_hash","report_hash"):
        assert recovered["result"][name]==baseline["result"][name]


def test_supervised_whole_run_worker_uses_the_same_observed_window_contract(service,runtime):
    value=value_for(service,runtime)
    service._colocated_worker=False
    result=execute(service,value,"window-supervised",PineEngineProvider())
    report=result["report"]
    assert len(report["fills"])==1 and report["fills"][0]["event_time_ms"]==120000
    metadata=report["strategy"]["pineExecution"]
    assert metadata["inputSkip"]==2 and metadata["historicalTickCount"]==12


def test_cancellation_at_window_transfer_never_persists_tentative_fills(service,runtime):
    from app.backtest.errors import BacktestError
    value=value_for(service,runtime)
    run=service.create_run(value,idempotency_key="window-cancelled",now_ms=3)
    provider=PineEngineProvider()
    saved=[]
    save=service._save_bar_checkpoint
    def observe_save(*args,**kwargs):
        saved.append((kwargs["sequence"],len(kwargs["kernel"].fills)))
        return save(*args,**kwargs)
    service._save_bar_checkpoint=observe_save
    check=service._assert_execution_control
    def cancel(*args,**kwargs):
        if provider.stream and provider.stream.last.get("window_status",{}).get("rebase_required"):
            raise BacktestError("RUN_CANCELLED","cancelled at observed window transfer")
        return check(*args,**kwargs)
    service._assert_execution_control=cancel
    with pytest.raises(BacktestError,match="cancelled at observed window transfer"):
        execute(service,value,"window-cancelled",provider,run)
    assert saved==[(0,0)]
    # Ordinary cancellation follows the existing failed-run cleanup policy.
    assert service.repository.latest_checkpoint(run["run_id"]) is None
