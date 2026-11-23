from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
import json

import pytest
from app.data_engine.synthetic_series.signals import ChartSignalSeries, normalize_signal_chart, SyntheticError
from app.data_engine.synthetic_series.core import SyntheticConfig, SyntheticKernel
from app.market_dataset.snapshot import MarketEvent
from app.simulation.kernel import SimulationKernel
from app.backtest.strategy.chart_signals import ChartSignalClock
from app.backtest.strategy.host_planner import HostOrderPlanner
from app.backtest.strategy.protocol import StrategyOutput


def bar(i, close, *, opening=None, high=None, low=None):
    opening = close if opening is None else opening
    return dict(open_time_ms=i*60000,close_time_ms=(i+1)*60000-1,
        open=str(opening),high=str(max(opening,close) if high is None else high),
        low=str(min(opening,close) if low is None else low),close=str(close),volume='6',is_closed=True)


def event(i, close, **kw):
    payload=bar(i,close,**kw)
    return MarketEvent(i+1,payload['close_time_ms'],'BARS',payload)


@pytest.mark.parametrize('transform', ['heikin-ashi','renko','point-and-figure','kagi','line-break'])
def test_fixed_price_steps_match_display_and_checkpoint_prefix(transform):
    config=dict(transform=transform,box_size=2,min_tick=1,reversal_amount=2)
    rows=[bar(i,c) for i,c in enumerate([100,106,110,99,97,106,105,104,108])]
    full=ChartSignalSeries(config)
    seen=[]
    for i,row in enumerate(rows):
        out=full.observe(row,row['close_time_ms']);seen.extend(out)
        restored=ChartSignalSeries(config);restored.restore(json.loads(json.dumps(full.snapshot())))
        if i+1<len(rows):
            assert restored.observe(rows[i+1],rows[i+1]['close_time_ms']) == ChartSignalSeriesTail(full,rows[i+1])
    kernel=SyntheticKernel(SyntheticConfig(**config))
    displayed=kernel.replace([dict(time=r['open_time_ms']//1000,**{k:float(r[k]) for k in ('open','high','low','close','volume')},is_closed=True) for r in rows])
    expected=displayed[:-1] if transform in {'point-and-figure','kagi'} else displayed
    assert [(x['bar']['open'],x['bar']['close']) for x in seen]==[(str(x['open']),str(x['close'])) for x in expected]
    assert [x['ordinal'] for x in seen]==list(range(len(seen)))
    assert all(x['source_time_ms']<=x['available_time_ms'] for x in seen)
    assert len(json.dumps(full.snapshot()))<5000


def ChartSignalSeriesTail(series,row):
    clone=ChartSignalSeries(series.definition);clone.restore(series.snapshot())
    return clone.observe(row,row['close_time_ms'])


def test_atr_causal_prefix_and_failed_observation_rollback():
    config=dict(transform='renko',mode='atr',atr_length=3,min_tick=.1)
    series=ChartSignalSeries(config)
    emitted=[]
    for i,c in enumerate([100,103,106,100]):emitted+=series.observe(bar(i,c,opening=c-1), (i+1)*60000-1)
    prefix=deepcopy(emitted);saved=series.snapshot()
    with pytest.raises(SyntheticError):series.observe(bar(2,100),999999)
    assert series.snapshot()==saved
    later=series.observe(bar(4,1000,opening=1),299999)
    assert emitted==prefix
    assert all(x['available_time_ms']==299999 for x in later)
    with pytest.raises(SyntheticError):normalize_signal_chart({})


def test_same_time_bricks_serial_admission_real_gap_fill_and_no_brick_matching():
    kernel=SimulationKernel(slippage_bps=Decimal(0),taker_fee_bps=Decimal(0))
    planner=HostOrderPlanner()
    frames=[]
    class Adapter:
        def observe(self,**frame):
            frames.append(frame)
            # Only the first brick asks for a position. It will fill on the next
            # actual market bar even though that bar cannot create another brick.
            return dict(kind='TARGET_POSITION',sequence=frame['sequence'],payload={'targetExposure':'1'}) if frame['sequence']==1 else None
    clock=ChartSignalClock(dict(transform='renko',box_size=2,min_tick=1),Adapter(),planner,
        market={'symbol':'TEST'},warmup=0,features=lambda b:{'close':b['close']},context=lambda e:None)
    kernel.run([event(0,100),event(1,106),event(2,107,opening=120,high=121,low=106)],lambda v,e:clock.observe(e))
    assert [float(f['bar']['close']) for f in frames]==[102,104,106]
    assert [f['sequence'] for f in frames]==[1,2,3]
    assert [f['bar']['open_time_ms'] for f in frames]==[60000]*3
    assert [f['event_time_ms'] for f in frames]==[119999]*3
    assert len(kernel.fills)==1
    assert kernel.fills[0].price==Decimal(120)
    assert kernel.fills[0].event_time_ms==179999
    assert len(kernel.decisions)==3
    saved=planner.snapshot();restored=HostOrderPlanner();restored.signal_input=ChartSignalSeries(clock.series.definition);restored.restore(saved)
    assert restored.signal_input.snapshot()==clock.series.snapshot()


@pytest.mark.parametrize('transform',['heikin-ashi','renko','point-and-figure','kagi','line-break'])
@pytest.mark.parametrize('python',[False,True])
def test_fixed_and_continuing_service_real_provider_resume_agree(tmp_path,monkeypatch,transform,python):
    from dataclasses import asdict
    from tests.test_continuous_bar_host import prepare,apply
    from tests.test_strategy_bar_continuation import events
    from tests.test_backtest_control_plane import _payload
    from app.backtest.continuous_bar_host import ContinuousBarHost
    from app.backtest.continuous_store import ContinuousStrategyStore
    from app.backtest.identity import canonical_json
    service,_,definition,factory,store=prepare(tmp_path,monkeypatch,python=python)
    config=dict(transform=transform,box_size=1,min_tick=.1,reversal_amount=2)
    row=service.create_run(_payload(parameters={'fast':3,'slow':5},warmup_bars=3,taker_fee_bps='3',maker_fee_bps='1',signal_chart=config),idempotency_key='chart-ref',now_ms=2)
    definition['configuration']=json.loads(row['config_json'])
    ContinuousBarHost.create_run(store,'cs_chart',definition=definition,mode='HISTORY_LIVE',data_revision='r1',event_time_ms=0,provider_factory=factory)
    host=ContinuousBarHost.resume(store,'cs_chart',factory)
    try:
        apply(host,events()[:11]);host.close();store.close()
        store=ContinuousStrategyStore(tmp_path/'continuous.db');host=ContinuousBarHost.resume(store,'cs_chart',factory)
        apply(host,events()[11:20]);apply(host,events()[20:],caught_up=True)
        actual=asdict(host.kernel.run((),host._observe,finalize=True))
        reference=service.execute_bar_run(row['run_id'],events=events(),provider=factory(definition),now_ms=3)['result']
        for key in ['decision_hash','fill_hash','ledger_hash','fills','ledger','orders','equity_curve']:
            assert canonical_json(actual[key])==canonical_json(reference[key]),key
        assert host.planner.signal_input.count != 25 or transform=='heikin-ashi'
        assert store.summary('cs_chart')['sequence']==25
    finally:host.close();store.close();service.shutdown()


def test_dual_clock_multiple_bricks_use_first_real_post_close_print():
    from app.simulation.dual_clock_kernel import DualClockSimulationKernel
    from tests.test_backtest_dual_clock import _trade
    kernel=DualClockSimulationKernel('1m')
    planner=HostOrderPlanner()
    frames=[]
    class Adapter:
        def observe(self,**frame):
            frames.append(frame)
            return dict(kind='ORDER_INTENT',payload={'intents':[{'side':'BUY','type':'MARKET','qty':'1'}]})
    clock=ChartSignalClock(dict(transform='renko',box_size=2,min_tick=1),Adapter(),planner,
        market={'symbol':'X'},warmup=0,features=lambda b:{},context=lambda e:None)
    tape=(_trade(1,1000,'100','10'),_trade(2,60000,'106','10'),_trade(3,120000,'120','10'),_trade(4,121000,'121','10'))
    kernel.run(tape,lambda v,e:clock.observe(e),end_time_ms=180000)
    assert [float(f['bar']['close']) for f in frames[:3]]==[102,104,106]
    assert len(kernel.execution.fills)>=3
    assert [f.price for f in kernel.execution.fills[:3]]==[Decimal(120)]*3
    assert len(kernel.decisions)==len(frames)


@pytest.mark.parametrize('order,expected',[
    ({'side':'BUY','type':'MARKET','qty':'1'},'120'),
    ({'side':'BUY','type':'LIMIT','qty':'1','limit_price':'104'},None),
    ({'side':'BUY','type':'STOP','qty':'1','stop_price':'105'},'120'),
])
def test_synthetic_trigger_does_not_invent_same_bar_or_synthetic_price_fills(order,expected):
    kernel=SimulationKernel(slippage_bps=Decimal(0),taker_fee_bps=Decimal(0))
    planner=HostOrderPlanner()
    class Adapter:
        def observe(self,**f):
            return dict(kind='ORDER_INTENT',payload={'intents':[order]}) if f['sequence']==1 else None
    clock=ChartSignalClock(dict(transform='renko',box_size=2,min_tick=1),Adapter(),planner,
        market={},warmup=0,features=lambda b:{},context=lambda e:None)
    kernel.run([event(0,100),event(1,106)],lambda v,e:clock.observe(e))
    assert not kernel.fills
    kernel.run([event(2,120,opening=120,high=121,low=119)],lambda v,e:clock.observe(e))
    assert [f.price for f in kernel.fills]==([] if expected is None else [Decimal(expected)])


def test_later_brick_target_sizing_sees_orders_admitted_by_previous_bricks():
    from tests.test_backtest_host_policy_m5 import config
    from app.backtest.service import _planning_context
    kernel=SimulationKernel(slippage_bps=Decimal(0))
    planner=HostOrderPlanner(config('FIXED_QTY_V1'))
    projected=[]
    class Adapter:
        def observe(self,**frame):
            projected.append(kernel.projected_position_qty)
            return dict(kind='SIGNAL',payload={'direction':'LONG'})
    clock=ChartSignalClock(dict(transform='renko',box_size=2,min_tick=1),Adapter(),planner,
        market={},warmup=0,features=lambda b:{},context=lambda e:_planning_context(kernel,e))
    kernel.run([event(0,100),event(1,106)],lambda v,e:clock.observe(e))
    assert projected==[Decimal(0),Decimal(1),Decimal(1)]
    assert len(kernel.orders)==1
    assert not kernel.fills
