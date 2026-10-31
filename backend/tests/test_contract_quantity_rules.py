"""Authoritative contract rules must survive admission and account recovery."""
from dataclasses import replace
from decimal import Decimal as D

import pytest

from app.market_dataset.snapshot import MarketEvent, MarketDatasetError
from app.simulation.kernel import SimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from app.simulation.pine_v2_bar_kernel import PineV2BarKernel
from tests.test_backtest_account_v2_m4 import rules, ready
from tests.test_pine_bar_kernel import bar


def contract(multiplier='1',minimum='.25',maximum='1000',min_notional='1'):
    source=rules(-2)
    return replace(source,payload={**source.payload,'contract_multiplier':multiplier,
        'quantity_step':'.25','min_quantity':minimum,'max_quantity':maximum,'min_notional':min_notional})


def subject(kind):
    cls={'BAR':SimulationKernel,'TRADE':TradeSimulationKernel,'PINE_BAR':PineV2BarKernel}[kind]
    return cls(account_model='LINEAR_PERP_ONE_WAY_V2',leverage=D(10),slippage_bps=D(0))


def execute(kind,rule,qty):
    kernel=subject(kind)
    rows=[rule,MarketEvent(1,-1,'MARK_INDEX',{'mark_price':'100','index_price':'100'})]
    if kind=='TRADE':
        rows.extend(MarketEvent(0,1000*i,'TRADES',{'source_event_kind':'AGG_TRADE',
            'source_sequence':i,'tie_break':f'AGG_TRADE:{i}','price':'100','qty':'1000'}) for i in range(1,4))
    else:
        rows.extend(bar(100,100,100,100,begin=60000*i) for i in range(3))
    rows=tuple(replace(row,sequence=i+1) for i,row in enumerate(rows))
    calls=[]
    def strategy(*_):
        calls.append(1)
        return [{'type':'MARKET','side':'BUY','qty':qty}] if len(calls)==1 else []
    kwargs={'fill_callback':lambda *_:[]} if kind=='PINE_BAR' else {}
    result=kernel.run(rows,strategy,**kwargs)
    return kernel,result


@pytest.mark.parametrize('kind',['BAR','TRADE','PINE_BAR'])
@pytest.mark.parametrize('multiplier,qty,reason',[
    ('50','.25',None),('.01','100','MIN_NOTIONAL'),
])
def test_minimum_notional_uses_contract_value_in_every_matching_path(kind,multiplier,qty,reason):
    kernel,result=execute(kind,contract(multiplier=multiplier,min_notional='1000'),qty)
    if reason is None:
        assert len(result.fills)==1
        assert kernel.account.position_qty==D(qty)
        assert kernel.account.notional()==D('1250')
    else:
        assert not result.fills
        assert kernel.rejected[0]['reason']==reason


@pytest.mark.parametrize('kind',['BAR','TRADE','PINE_BAR'])
@pytest.mark.parametrize('minimum,maximum,qty,reason',[
    ('2','100','1','MIN_QTY'),('.25','1','2','MAX_QTY'),
])
def test_frozen_quantity_bounds_are_enforced(kind,minimum,maximum,qty,reason):
    kernel,result=execute(kind,contract(minimum=minimum,maximum=maximum),qty)
    assert not result.fills
    assert kernel.rejected[0]['reason']==reason


def test_bounds_survive_snapshot_and_are_cleared_by_an_explicit_new_legacy_rule():
    account=ready()
    account.apply(contract(minimum='2',maximum='10'))
    saved=account.snapshot()
    restored=ready()
    restored.restore(saved)
    assert restored.min_quantity==D('2')
    assert restored.max_quantity==D('10')
    assert restored.snapshot()==saved
    restored.apply(rules(10,version='legacy'))
    assert restored.min_quantity is None and restored.max_quantity is None


@pytest.mark.parametrize('minimum,maximum',[('0','1'),('2','1'),('NaN','3'),('1','Infinity')])
def test_invalid_bounds_are_rejected_before_mutating_account_rules(minimum,maximum):
    account=ready()
    before=account.snapshot()
    with pytest.raises(MarketDatasetError,match='quantity'):
        account.apply(contract(minimum=minimum,maximum=maximum))
    assert account.snapshot()==before
