"""Actual installed Pine worker, historical contract account and final report."""
from decimal import Decimal as D

import pytest

from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from app.backtest.errors import BacktestError
from tests.test_pine_workbench_v2_bar import config


@pytest.mark.parametrize('multiplier',['50','0.01'])
@pytest.mark.parametrize('sizing',['explicit','cash','percent_of_equity'])
@pytest.mark.parametrize('model',['LINEAR_PERP_ONE_WAY_V1','LINEAR_PERP_ONE_WAY_V2'])
def test_workbench_contract_sizing_fills_fees_and_report_agree(runtime,multiplier,sizing,model):
    host,main=runtime
    value=config(main)
    rule=value['account_data']['events'][0]['payload']
    rule.update(contract_multiplier=multiplier,quantity_step='0.25',min_quantity='0.25',max_quantity='1000',min_notional='0.001')
    if model=='LINEAR_PERP_ONE_WAY_V1':
        value['account_model']=model
        value.pop('account_data')
        value.pop('leverage')
        value['context']['metadata'].update(pointValue=float(multiplier),quantityStep='0.25',minContract='0.25')
    value['host_settings'].update(initial_balance=10000,slippage_bps=0,taker_fee_bps=10)
    point=D(multiplier);budget=D('1.25')*10*point
    defaults='' if sizing=='explicit' else f',default_qty_type=strategy.{sizing},default_qty_value={budget if sizing=="cash" else budget/100}'
    quantity=',qty=1.49' if sizing=='explicit' else ''
    value['source']=f'''//@version=6
strategy("Contract host",calc_on_order_fills=true{defaults})
if bar_index==0
    strategy.entry("L",strategy.long{quantity})
if bar_index==2 and strategy.position_size>0
    strategy.close_all()
plot(syminfo.pointvalue)
plot(syminfo.mincontract)
'''
    try:
        created=host.native.create(value,'contract-worker')
    except BacktestError as exc:
        pytest.fail(f"{exc}: {exc.details}")
    record=terminal(host.native,created['run_id'])
    assert record['state']=='COMPLETED',record.get('error')
    result=record['result']
    assert [D(row['qty']) for row in result['trades']]==[D('1.25'),D('1.25')]
    assert [D(row['price']) for row in result['trades']]==[D(10),D(20)]
    fees=D('1.25')*D(30)*point*D('.001')
    profit=D('1.25')*D(10)*point-fees
    assert sum(D(row['fee']) for row in result['trades'])==fees
    assert D(result['position']['wallet_balance' if model.endswith('V2') else 'quote_balance'])==D(10000)+profit
    assert D(result['closed_trades'][0]['profit'])==profit
    assert D(result['closed_trades'][0]['entryPrice'])==10
    assert D(result['closed_trades'][0]['return_percent'])==profit/(D('1.25')*10*point)*100
    assert all(D(row['contract_multiplier'])==point for row in result['trades'])
    if sizing=='explicit' and multiplier=='50':
        from tests.test_native_replay import settle
        replay=host.native.replay
        state=replay.create(record['run_id'])
        key=state['replay_id']
        def seek(target):
            replay.command(key,replay.get(key)['revision'],'seek',target)
            state=settle(replay,key)
            assert state.get('error') is None,state
            return state
        first=seek(2)
        saved=replay.snapshot(key,first['revision'])['snapshots'][0]['snapshot_id']
        end=seek(state['total'])
        replay.restore(key,end['revision'],saved)
        assert seek(state['total'])['result']==result
