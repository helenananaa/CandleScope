"""Actual installed Pine worker on the Host's causal aggregate-trade clock."""
import json
import os
from copy import deepcopy
from dataclasses import replace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.backtest.strategy.pine_engine import PineEngineProvider
from app.backtest.strategy.workspace import compile_revision
from app.core.config import load_backtest_settings
from tests.test_backtest_dual_clock import _trade

pytestmark = pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"), reason="requires installed Pine adapter")

SOURCE = '''//@version=6
strategy("Fill callback",calc_on_order_fills=true)
varip int passes=0
passes+=1
if barstate.isconfirmed and bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if not barstate.isconfirmed and strategy.position_size>0 and timenow==60000 and volume==100
    strategy.close("L")
'''


@pytest.fixture
def service(tmp_path):
    settings = load_backtest_settings({"BACKTEST_ENABLED":"1", "BACKTEST_BAR_ENABLED":"1", "BACKTEST_TRADE_TAPE_ENABLED":"1"},
        data_dir=tmp_path, klines_db_path=tmp_path/"klines.db", replay_db_path=tmp_path/"replay.db")
    host = BacktestService.start(settings, enforce_registered_revisions=True, now_ms=1)
    host._colocated_worker = True
    try:
        yield host
    finally:
        host.shutdown()


def payload(service, source=SOURCE, **overrides):
    revision = service.create_strategy_revision({"language":"PINE_ENGINE", "name":"Callback", "source_text":source})
    result = {"strategy_revision_id":revision["revision_id"], "dataset_id":"local-pine", "data_epoch":"epoch-20261019",
        "snapshot_hash":"sha256:snapshot", "fidelity_mode":"AGG_TRADE_EXECUTION", "source_event_kind":"AGG_TRADE",
        "start_time_ms":0, "end_time_ms":240000, "symbol":"BTCUSDT", "interval":"1m", "output_mode":"ORDER_INTENT",
        "parameters":{}, "initial_balance":"10000", "slippage_bps":"0", "taker_fee_bps":"0",
        "signal_clock":"DERIVED_BAR_CLOSE", "signal_interval":"1m", "execution_clock":"NEXT_AGG_TRADE",
        "bar_builder":"TRADE_DERIVED_COMPLETE_BUCKETS_V1", "timezone":"UTC",
        "checkpoint_policy":"INTERVAL", "checkpoint_interval":1}
    result.update(overrides)
    service.smoke_strategy_revision(revision["revision_id"], result, now_ms=2)
    return result


def events():
    return tuple(_trade(i+1, stamp, str(price), "100") for i,(stamp,price) in enumerate(
        ((1000,10),(60000,10),(70000,11),(119999,99),(120000,12),(180000,13))))


class RecordingProvider(PineEngineProvider):
    def __init__(self):
        super().__init__()
        self.observations = []

    def step(self, frame):
        self.observations.append(deepcopy(frame))
        return super().step(frame)


def execute(service, run, provider=None):
    return service.execute_dual_clock_run(run["run_id"], events=events(), provider=provider or PineEngineProvider(), now_ms=4,
        observation_market={"venue":"binance", "symbol":"BTCUSDT"})


@pytest.mark.parametrize("spot,inline", [(False,True),(False,False),(True,True)])
def test_fill_callbacks_use_actual_account_and_observed_forming_bar(service,spot,inline):
    service._colocated_worker = inline
    source = SOURCE.replace("strategy.position_size>0", "strategy.position_size>0 and strategy.netprofit==0")
    config = payload(service,source, **({"account_model":"SPOT_CASH_V1","market_type":"spot"} if spot else {}))
    run = service.create_run(config, idempotency_key="causal", now_ms=3)
    provider = RecordingProvider()
    completed = execute(service, run, provider)
    assert [row["event_time_ms"] for row in completed["report"]["fills"]] == [60000,70000]
    assert [float(row["qty"]) for row in completed["report"]["fills"]] == [2,2]
    frames = provider.observations
    assert [f.sequence for f in frames] == list(range(1,len(frames)+1))
    assert [f.event_time_ms for f in frames] == [59999,60000,70000,119999,179999]
    assert [f.features["pineExecutionPass"]["confirmed"] for f in frames] == [True,False,False,True,True]
    assert [float(f.account_view["position_size"]) for f in frames] == [0,2,0,0,0]
    assert [float(f.bar["volume"]) for f in frames] == [100,100,200,300,100]
    assert [float(f.bar["high"]) for f in frames] == [10,10,11,99,12]
    assert completed["report"]["pine_orders"]["open_entries"] == []
    assert completed["result"]["cost_sensitivity"] == {}
    assert completed["report"]["strategy"]["pineExecution"]["fillCallbackCount"] == 2


@pytest.mark.parametrize("generic,entry_risk",[(False,False),(True,False),(False,True)])
def test_recovery_resumes_an_unconfirmed_fill_group(service,generic,entry_risk):
    source = SOURCE.replace("strategy.entry(","strategy.order(") if generic else SOURCE
    if entry_risk:
        source = source.replace('varip int passes=0', 'if false\n    strategy.risk.max_position_size(1)\nvarip int passes=0')
    config = payload(service,source)
    baseline = execute(service, service.create_run(config,idempotency_key="baseline",now_ms=3))
    run = service.create_run(config,idempotency_key="interrupted",now_ms=3)
    original = service.repository.save_checkpoint
    def save_then_interrupt(value):
        saved = original(value)
        if value["sequence"] == 2:
            raise KeyboardInterrupt("stop after durable forming callback")
        return saved
    service.repository.save_checkpoint = save_then_interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            execute(service,run)
    finally:
        service.repository.save_checkpoint = original
    checkpoint = service.repository.latest_checkpoint(run["run_id"])
    saved = json.loads(checkpoint["payload_json"])
    groups = saved["provider"]["provider"]["execution_passes"]
    assert groups[-1][-1]["confirmed"] is False
    assert groups[-1][-1]["event_time_ms"] == 60000
    assert service.requeue_interrupted_run(run["run_id"],expected_generation=1,now_ms=8)
    resumed = execute(service,run)
    for field in ("fills","orders","pine_orders"):
        assert resumed["report"][field] == baseline["report"][field]
    for field in ("decision_hash","fill_hash","ledger_hash","report_hash"):
        assert resumed["result"][field] == baseline["result"][field]


def test_each_same_print_fill_observes_its_owned_position_before_closing(service):
    source = '''//@version=6
strategy("Owned fills",calc_on_order_fills=true,pyramiding=2)
if barstate.isconfirmed and bar_index==0
    strategy.entry("A",strategy.long,qty=2)
    strategy.entry("B",strategy.long,qty=3)
if not barstate.isconfirmed and strategy.position_size>0
    strategy.close("A")
'''
    run = service.create_run(payload(service,source),idempotency_key="owned",now_ms=3)
    provider = RecordingProvider()
    result = execute(service,run,provider)
    assert [float(row["qty"]) for row in result["report"]["fills"]] == [2,3,2]
    assert [row["event_time_ms"] for row in result["report"]["fills"]] == [60000,60000,70000]
    assert [float(f.account_view["position_size"]) for f in provider.observations[:4]] == [0,2,5,3]
    remaining = result["report"]["pine_orders"]["open_entries"]
    assert len(remaining) == 1 and remaining[0]["entry_id"] == "B" and float(remaining[0]["qty"]) == 3


def test_partial_oca_orders_restore_through_actual_pine_fill_callbacks(service):
    source='''//@version=6
strategy("OCA recovery",calc_on_order_fills=true)
if barstate.isconfirmed and bar_index==0
    strategy.order("A",strategy.long,qty=4,oca_name="g",oca_type=strategy.oca.reduce)
    strategy.order("B",strategy.long,qty=10,oca_name="g",oca_type=strategy.oca.reduce)
if not barstate.isconfirmed and strategy.position_size>0
    strategy.exit("X","A",limit=1000)
'''
    config=payload(service,source)
    rows=tuple(_trade(i+1,stamp,"10",str(qty)) for i,(stamp,qty) in enumerate(
        ((1000,100),(60000,2),(70000,100),(120000,100),(180000,100))))
    def run(record):
        return service.execute_dual_clock_run(record["run_id"],events=rows,provider=PineEngineProvider(),now_ms=4,
            observation_market={"venue":"binance","symbol":"BTCUSDT"})
    baseline=run(service.create_run(config,idempotency_key="oca-baseline",now_ms=3))
    interrupted=service.create_run(config,idempotency_key="oca-interrupted",now_ms=3)
    save=service.repository.save_checkpoint
    def interrupt(value):
        result=save(value)
        if value["sequence"]==2:
            raise KeyboardInterrupt("durable OCA partial fill")
        return result
    service.repository.save_checkpoint=interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            run(interrupted)
    finally:
        service.repository.save_checkpoint=save
    assert service.requeue_interrupted_run(interrupted["run_id"],expected_generation=1,now_ms=8)
    recovered=run(interrupted)
    assert [float(f["qty"]) for f in recovered["report"]["fills"]]==[2,2,6]
    assert [(x["entry_id"],float(x["qty"])) for x in recovered["report"]["pine_orders"]["open_entries"]]==[("A",4),("B",6)]
    for key in ("fills","orders","pine_orders"):
        assert recovered["report"][key]==baseline["report"][key]
    for key in ("decision_hash","fill_hash","ledger_hash","report_hash"):
        assert recovered["result"][key]==baseline["result"][key]


@pytest.mark.parametrize("override", [{"fidelity_mode":"BAR_APPROX","source_event_kind":"BAR","execution_model_revision":"EXECUTION_REALISM_V2","bar_path_scenario":"UNFROZEN_PATH"},{"output_mode":"TARGET_POSITION"}])
def test_callback_profile_requires_order_intents_and_frozen_execution_model(service,override):
    with pytest.raises(BacktestError,match="FIDELITY_UNSUPPORTED"):
        service.create_run(payload(service,**override), idempotency_key="invalid", now_ms=3)


def test_last_millisecond_pass_freezes_requested_visibility_and_symbol_metadata(monkeypatch):
    from tests.test_chart_pine_engine import frame
    source = '''//@version=6
strategy("Pass metadata",calc_on_order_fills=true)
remote=request.security("OKX:ETH-USDT","2",close+syminfo.mintick)
if barstate.isconfirmed and bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if not barstate.isconfirmed and strategy.position_size>0 and na(remote)
    strategy.exit("X","L",limit=10.5)
if barstate.isconfirmed and bar_index==1 and remote==100.25
    strategy.close("L")
'''
    monkeypatch.setattr("app.backtest.pine_requested_data.load_contexts", lambda *_: [
        {"symbol":"OKX:ETH-USDT","timeframe":"2","metadata":{"priceTickSize":".25","currency":"USDT"},
         "closes":[119999], "bars":[dict(time=0,open=100,high=100,low=100,close=100,volume=100)]}])
    compiled = compile_revision({"language":"PINE_ENGINE","name":"metadata","source_text":source}, now_ms=1)
    provider, restored = PineEngineProvider(), PineEngineProvider()
    try:
        provider.prepare({"source":json.loads(compiled["compiled_json"])["executionSource"],"outputMode":"ORDER_INTENT",
            "pineChartMetadata":{"priceTickSize":".1"}})
        def observation(index,sequence,confirmed,position=0):
            return replace(frame(index,10,position),sequence=sequence,
                features={"pineExecutionPass":{"barIndex":index,"confirmed":confirmed}})
        provider.step(observation(0,1,True))
        output = provider.step(observation(1,2,False,2))
        assert [item["action"] for item in output.payload["intents"]] == ["exit"]
        snapshot = deepcopy(provider.snapshot())
        assert snapshot["execution_passes"][1][0]["request_data"][0]["bars"] == []
        restored.restore(snapshot)
        confirmed = observation(1,3,True,2)
        result = provider.step(confirmed)
        assert [item["action"] for item in result.payload["intents"]] == ["close"]
        assert restored.step(confirmed) == result
        assert len(snapshot["execution_passes"][1]) == 1
        assert provider.snapshot() == restored.snapshot()
    finally:
        provider.close()
        restored.close()
