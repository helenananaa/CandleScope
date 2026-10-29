from dataclasses import replace
from decimal import Decimal as D

import pytest

from tests.test_chart_pine_v2_bar import config, execute, bars
from tests.test_chart_pine_bar_callbacks import service as service, pytestmark as pytestmark, RecordingProvider
from tests.test_backtest_account_v2_m4 import rules
from tests.test_pine_v2_bar_kernel import numbered, mark


@pytest.mark.parametrize('model',['LINEAR_PERP_ONE_WAY_V1','LINEAR_PERP_ONE_WAY_V2'])
@pytest.mark.parametrize('multiplier',['50','.01'])
@pytest.mark.parametrize('sizing',['explicit','cash','percent_of_equity'])
def test_chart_contract_metadata_sizing_and_report_match_actual_ledger(service,model,multiplier,sizing):
    point=D(multiplier)
    budget=D('1.25')*10*point
    defaults='' if sizing=='explicit' else f',default_qty_type=strategy.{sizing},default_qty_value={budget if sizing=="cash" else budget/100}'
    quantity=',qty=1.49' if sizing=='explicit' else ''
    source=f'''//@version=6
strategy("Contract chart",calc_on_order_fills=true{defaults})
if bar_index==0
    strategy.entry("L",strategy.long{quantity})
if bar_index==2 and strategy.position_size>0
    strategy.close_all()
plot(syminfo.pointvalue)
plot(syminfo.mincontract)
'''
    options=dict(taker_fee_bps='10',cost_sensitivity_mode='FULL' if multiplier=='50' and sizing=='explicit' else 'SKIP')
    if model.endswith('V1'):
        options['pine_chart_metadata']=dict(priceTickSize='.1',pointValue=float(point),quantityStep='.25',minContract='.25')
    value=config(service,account=model,source=source,**options)
    rows=tuple(replace(row,payload={**row.payload,'volume':'100',**({key:str(price) for key,price in [('open',20),('high',21),('low',19),('close',20)]} if i>=3 else {})})
               for i,row in enumerate(bars()))
    if model.endswith('V2'):
        initial=rules(-2)
        initial=replace(initial,payload={**initial.payload,'contract_multiplier':multiplier,'quantity_step':'.25','min_quantity':'.25','min_notional':'.001'})
        rows=numbered(initial,mark(-1,10),*rows)
    provider=RecordingProvider()
    record=execute(service,value,'contract-chart',rows,provider)
    report=record['report']
    assert [D(row['qty']) for row in report['fills']]==[D('1.25')]*2,report
    assert [D(row['price']) for row in report['fills']]==[D(10),D(20)]
    assert all(D(row['contract_multiplier'])==point for row in report['fills'])
    fees=D('1.25')*30*point*D('.001')
    profit=D('1.25')*10*point-fees
    assert sum(D(row['fee']) for row in report['fills'])==fees
    assert D(report['ledger']['account']['quote_balance'])==D(10000)+profit
    assert D(report['metrics']['realized_net_pnl'])==profit
    metadata=provider.snapshot()['context']['pineChartMetadata']
    assert D(str(metadata['pointValue']))==point
    assert D(metadata['quantityStep'])==D('.25') and D(metadata['minContract'])==D('.25')
    if options['cost_sensitivity_mode']=='FULL':
        assert report['cost_sensitivity']['baseline_reexecution_verified'] is True
