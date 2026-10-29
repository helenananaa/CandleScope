"""Installed Pine sees the Host's actual account settlement and recovery."""
from decimal import Decimal
import json

import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider
from app.market_dataset.snapshot import MarketEvent
from tests.test_backtest_account_v2_m4 import rules
from tests.test_backtest_dual_clock import _trade
from tests.test_chart_pine_callbacks import service as service, RecordingProvider, pytestmark as pytestmark
from tests.test_chart_pine_risk_stops import config


def tape(*, stamp=70000, compound=False):
    raw=[rules(1),MarketEvent(2,2,"MARK_INDEX",{"mark_price":"100","index_price":"100"}),
        _trade(1,1000,"100","100"),_trade(2,60000,"125" if compound else "100","100")]
    if not compound:
        raw.append(MarketEvent(5,stamp,"MARK_INDEX",{"mark_price":"80","index_price":"80"}))
    raw.extend((_trade(3,130000,"81","100"),_trade(4,180000,"82","100")))
    return tuple(MarketEvent(i+1,row.event_time_ms,row.role,row.payload) for i,row in enumerate(raw))


def text(rule=""):
    return '''//@version=6
strategy("Account settlement",calc_on_order_fills=true,pyramiding=4)
''' + rule + '''
if barstate.isconfirmed and bar_index==0
    strategy.entry("L",strategy.long,qty=50)
if strategy.position_size==0 and bar_index>0
    strategy.order("after_settlement",strategy.long,qty=1)
'''


def execute(host,record,rows,provider=None):
    return host.execute_dual_clock_run(record["run_id"],events=rows,provider=provider or PineEngineProvider(),now_ms=4,
        observation_market={"venue":"binance","symbol":"BTCUSDT"})


@pytest.mark.parametrize("rule", ["", "strategy.risk.max_position_size(50)\n",
    "strategy.risk.max_drawdown(100,strategy.percent_of_equity)\n"])
@pytest.mark.parametrize("compound", [False,True])
def test_installed_pine_sees_distinct_fill_and_real_liquidation_frames(service,rule,compound):
    value=config(service,text(rule),tape=True,account_model="LINEAR_PERP_ONE_WAY_V2",leverage="10",funding_mode="OFF",contract_data_mode="HISTORICAL_CONTRACT_V1")
    run=service.create_run(value,idempotency_key="liquidation",now_ms=3)
    provider=RecordingProvider()
    result=execute(service,run,tape(compound=compound),provider)
    fills=result["report"]["fills"]
    assert len(fills)==2
    assert [float(row["position_after"]) for row in fills]==[50,0]
    assert fills[-1]["reason"]=="ACCOUNT_LIQUIDATION"
    assert fills[-1]["account_liquidation"]["trigger"]==("FILL" if compound else "MARK_INDEX")
    assert result["report"]["pine_orders"]["open_entries"]==[]
    frames=provider.observations
    assert [float(frame.account_view["position_size"]) for frame in frames[:3]]==[0,50,0]
    assert [frame.event_time_ms for frame in frames[:3]]==[59999,60000,60000 if compound else 70000]
    assert float(frames[2].bar["close"])==(125 if compound else 100)
    assert float(frames[2].bar["volume"])==100
    assert Decimal(str(result["report"]["ledger"]["account"]["position_qty"]))==0
    assert result["report"]["strategy"]["pineExecution"]["fillCallbackCount"]==2


def test_deferred_real_pine_liquidation_callback_restores_at_an_account_event(service):
    value=config(service,text(),tape=True,account_model="LINEAR_PERP_ONE_WAY_V2",leverage="10",funding_mode="OFF",contract_data_mode="HISTORICAL_CONTRACT_V1")
    rows=tape(stamp=120000)
    baseline=execute(service,service.create_run(value,idempotency_key="baseline",now_ms=3),rows)
    record=service.create_run(value,idempotency_key="restore",now_ms=3)
    save=service.repository.save_checkpoint
    def interrupt(checkpoint):
        saved=save(checkpoint)
        if checkpoint["sequence"]==5:
            raise KeyboardInterrupt("durable account settlement before an observable bar")
        return saved
    service.repository.save_checkpoint=interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            execute(service,record,rows)
    finally:
        service.repository.save_checkpoint=save
    saved=json.loads(service.repository.latest_checkpoint(record["run_id"])["payload_json"])
    assert saved["engine"]["account_fill_callbacks"]["pending"]==[{"order_id":"ord-2","execution_time_ms":120000}]
    assert service.requeue_interrupted_run(record["run_id"],expected_generation=1,now_ms=8)
    provider=RecordingProvider()
    resumed=execute(service,record,rows,provider)
    for field in ("fills","orders","pine_orders","ledger"):
        assert resumed["report"][field]==baseline["report"][field]
    for field in ("decision_hash","fill_hash","ledger_hash","report_hash"):
        assert resumed["result"][field]==baseline["result"][field]
    assert provider.observations[0].event_time_ms==130000
    assert float(provider.observations[0].account_view["position_size"])==0
    assert float(provider.observations[0].bar["close"])==81


def test_real_account_liquidation_is_reexecuted_for_independent_cost_scenarios(service):
    from tests.test_pine_cost_sensitivity import scenarios
    value=config(service,text(),tape=True,account_model="LINEAR_PERP_ONE_WAY_V2",leverage="10",funding_mode="OFF",
        contract_data_mode="HISTORICAL_CONTRACT_V1",execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate="1",taker_fee_bps="1")
    result=execute(service,service.create_run(value,idempotency_key="cost-liquidation",now_ms=3),tape())
    rows=scenarios(result)
    assert rows["BASELINE"]["hashes"]["fill"]==result["result"]["fill_hash"]
    assert rows["BASELINE"]["metrics"]["fill_count"]==2
    for name in ("COSTS_PLUS_25_PERCENT","COSTS_PLUS_50_PERCENT"):
        assert rows[name]["metrics"]["fill_count"]==2
        assert float(rows[name]["metrics"]["ending_position"])==0
        assert rows[name]["hashes"]["fill"]!=rows["BASELINE"]["hashes"]["fill"]
