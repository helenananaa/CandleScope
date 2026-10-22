from copy import deepcopy
from decimal import Decimal as D

import pytest
from app.backtest.errors import BacktestError
from app.market_dataset.snapshot import MarketEvent
from app.simulation.trade_kernel import TradeSimulationKernel
from tests.test_backtest_account_v2_m4 import rules

from app.backtest import pine_print_account as module


def wire():
    return {"pine_v2_print_contract": module.CONTRACT, "account_model":"LINEAR_PERP_ONE_WAY_V2",
        "execution_fidelity":"BOOK_DEPTH", "execution_events":[
            dict(sequence=1,event_time_ms=0,role="ORDER_BOOK",payload={"book_sequence":22}),
            dict(sequence=2,event_time_ms=0,role="TRADES",payload={"price":"900","qty":".1","source_event_kind":"RAW_TRADE"}),
            dict(sequence=3,event_time_ms=20,role="TRADES",payload={"source_sequence":100,"price":"1","qty":".1"})],
        "account_events":[dict(time_ms=-1,role="INSTRUMENT_RULES",payload=dict(rules(-1).payload)),
            dict(time_ms=0,role="MARK_INDEX",payload={"mark_price":"110","index_price":"111"}),
            dict(time_ms=0,role="FUNDING",payload={"rate":".01","period_id":"p1"})]}


@pytest.mark.parametrize("source_sequence", [None, 0])
def test_merge_preserves_each_source_and_puts_account_first_without_mutation(source_sequence):
    source=wire()
    if source_sequence is not None:
        source["execution_events"][1]["payload"]["source_sequence"]=source_sequence
    original=deepcopy(source)
    rows=module.events(source)
    assert [row.role for row in rows]==["INSTRUMENT_RULES","MARK_INDEX","FUNDING","ORDER_BOOK","TRADES","TRADES"]
    assert [row.sequence for row in rows]==list(range(1,7))
    assert [row.payload["source_sequence"] for row in rows if row.role=="TRADES"]==[2,100]
    assert rows[3].payload["book_sequence"]==22
    rows[0].payload["rule_version"]="mutated-result"
    assert source==original


@pytest.mark.parametrize("field,value",[("pine_v2_print_contract","unknown"),("account_model","SPOT_CASH_V1"),("execution_fidelity","BAR_APPROX")])
def test_wrong_contract_model_or_clock_rejects(field,value):
    source=wire(); source[field]=value
    with pytest.raises(BacktestError,match="invalid Pine V2"):
        module.events(source)


def test_legacy_clock_retains_original_event_coordinates():
    source=wire(); source.pop("pine_v2_print_contract")
    rows=module.events(source)
    assert [row.sequence for row in rows]==[1,2,3]
    assert "source_sequence" not in rows[1].payload


def test_trade_quote_does_not_replace_account_mark_and_funding_uses_contract_units():
    kernel=TradeSimulationKernel(account_model="LINEAR_PERP_ONE_WAY_V2", initial_balance=D(1000),leverage=D(10),funding_mode="HISTORICAL_REQUIRED")
    opening=dict(rules(-2).payload, contract_multiplier="50")
    module.apply_account(kernel,MarketEvent(1,-2,"INSTRUMENT_RULES",opening))
    module.apply_account(kernel,MarketEvent(2,-1,"MARK_INDEX",{"mark_price":"100","index_price":"100"}))
    kernel.account.apply_fill(side="BUY",price=D(100),qty=D('.1'),fee=D(0),event_time_ms=0)
    module.apply_account(kernel,MarketEvent(3,50,"MARK_INDEX",{"mark_price":"110","index_price":"110"}),record_equity=True)
    module.observe_market(kernel,MarketEvent(4,100,"TRADES",{"price":"900","qty":".1"}))
    assert kernel.account.mark==D(110)
    assert kernel.account.equity()==D(1050)
    module.apply_account(kernel,MarketEvent(5,150,"FUNDING",{"rate":".01","period_id":"p1"}),record_equity=True)
    assert kernel.account.funding_paid==D('-5.5')  # Signed account cash flow: positive rate debits the long.
    assert kernel.account.equity()==D('1044.5')
    assert [D(row["equity"]) for row in kernel.equity_curve]==[D(1050),D('1044.5')]
