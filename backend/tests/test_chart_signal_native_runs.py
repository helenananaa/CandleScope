"""Installed Pine subprocess + frozen market/Host execution + replay recovery."""
from tests.test_native_backtests import runtime,terminal,pytestmark
from tests.test_external_replay import payload
from tests.test_native_replay import settle
import pytest


@pytest.mark.parametrize('transform',['heikin-ashi','renko','point-and-figure','kagi','line-break'])
@pytest.mark.parametrize('fidelity',['BAR_APPROX','TRADE_TAPE'])
def test_chart_signals_host_real_fills_replay_resume(runtime,transform,fidelity):
    host,main=runtime
    value=payload(main,fidelity)
    value['signal_chart']=dict(transform=transform,box_size=2,min_tick=1,reversal_amount=2)
    value['source']='''//@version=6
strategy("Chart signals")
if bar_index==0
    strategy.entry("L",strategy.long,qty=1)
plot(close)
plot(ta.sma(close,2))
plot(bar_index)
plot(time)
plot(strategy.position_size)
'''
    origin=terminal(host.native,host.native.create(value,'chart-origin')['run_id'])
    assert origin['state']=='COMPLETED',origin
    result=origin['result']
    assert result['account_authority']=='candlescope'
    assert result['raw_output']['strategy_output'].get('strategy') is None
    # Matching prices come from the real market, never the synthetic close.
    assert result['trades']
    replay=host.native.replay
    record=replay.create(origin['run_id'])
    replay.command(record['replay_id'],record['revision'],'seek',5)
    record=settle(replay,record['replay_id'])
    checkpoint=replay.snapshot(record['replay_id'],record['revision'])
    replay.command(record['replay_id'],checkpoint['revision'],'step')
    advanced=settle(replay,record['replay_id'])
    restored=replay.restore(record['replay_id'],advanced['revision'],checkpoint['snapshots'][0]['snapshot_id'])
    assert restored['result']==record['result']
    replay.command(record['replay_id'],restored['revision'],'seek',record['total'])
    final=settle(replay,record['replay_id'])
    assert final['result']==result


def test_replay_checkpoint_before_first_brick_has_no_evaluator_transcript(runtime):
    host,main=runtime
    value=payload(main,'BAR_APPROX');value['signal_chart']={'transform':'renko','box_size':1000,'min_tick':1}
    origin=terminal(host.native,host.native.create(value,'no-bricks')['run_id'])
    assert origin['state']=='COMPLETED',origin
    assert origin['result']['trades']==[]
    replay=host.native.replay;record=replay.create(origin['run_id'])
    replay.command(record['replay_id'],record['revision'],'seek',5);record=settle(replay,record['replay_id'])
    checkpoint=replay.snapshot(record['replay_id'],record['revision'])
    replay.command(record['replay_id'],checkpoint['revision'],'seek',record['total']);final=settle(replay,record['replay_id'])
    assert final['result']==origin['result']
