from decimal import Decimal as D
import pytest
from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_pine_workbench_v2_print import config
from tests.test_backtest_account_v2_m4 import rules


@pytest.mark.parametrize("mode",["BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED"])
@pytest.mark.parametrize("stamp",[70000,120000])
def test_actual_book_account_settlement_closes_only_filled_lots_and_delivers_visible_callback(runtime,mode,stamp):
    host,main=runtime
    value=config(main,mode,True)
    value["host_settings"]["initial_balance"]=15
    value["funding_mode"]="OFF"
    value["source"]='//@version=6\nstrategy("book settlement",calc_on_order_fills=true)\nif bar_index==0 and barstate.isconfirmed\n    strategy.entry("L",strategy.long,qty=10)\nplot(strategy.position_size)'
    value["account_data"]["events"]=[
        dict(time_ms=-2,role="INSTRUMENT_RULES",payload=dict(rules(-2).payload)),
        dict(time_ms=-1,role="MARK_INDEX",payload={"mark_price":"10","index_price":"10"}),
        dict(time_ms=stamp,role="MARK_INDEX",payload={"mark_price":"1","index_price":"1"})]
    record=terminal(host.native,host.native.create(value,"book-account-settlement")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    liquidations=[row for row in result["trades"] if row["reason"]=="ACCOUNT_LIQUIDATION"]
    assert len(liquidations)==1
    settlement=liquidations[0]
    opening=[row for row in result["trades"] if row["side"]=="BUY"]
    assert D(settlement["qty"])==sum(D(row["qty"]) for row in opening)>0
    assert D(settlement["position_after"])==0 and settlement["event_time_ms"]==stamp
    if mode!="BOOK_ASSISTED" and stamp==70000:
        assert D(settlement["qty"])==5  # Only the first visible depth was filled.
    passes=result["raw_output"]["execution_passes"][stamp//60000]
    frames=[row for row in passes if not row["confirmed"] and row["account"]["position_size"]==0]
    assert len(frames)==1 and frames[0]["event_time_ms"]==stamp
    assert frames[0]["bar"]["close"] in {10,11}
    assert D(result["position"]["mark_price"])==1
