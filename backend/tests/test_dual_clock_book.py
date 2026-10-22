"""Chart clock consumes real book liquidity and never turns quotes into ticks."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from app.simulation.dual_clock_kernel import DualClockSimulationKernel

MODES = ('BOOK_ASSISTED','BOOK_DEPTH','BOOK_SAMPLED')


def quote(mode, sequence, stamp, index, *, bid='9', ask='11'):
    common = dict(snapshot=True)
    if mode == 'BOOK_ASSISTED':
        common.update(book_sequence=index,bid=bid,ask=ask)
    else:
        common.update(bids=[[bid,'2']],asks=[[ask,'2']])
        if mode == 'BOOK_DEPTH':
            common.update(book_sequence=index,depth_complete=True)
        else:
            common.update(sample_index=index,sample_time_ms=stamp,depth_complete=False,depth_scope='BOUNDED_SAMPLED')
    return MarketEvent(sequence,stamp,'ORDER_BOOK',common)


def print_event(sequence, stamp, source):
    return MarketEvent(sequence,stamp,'TRADES',dict(source_event_kind='AGG_TRADE',
        source_sequence=source,tie_break=f'AGG_TRADE:{source}',price='10',qty='5',aggressor_side='BUY'))


def rows(mode):
    return (quote(mode,1,0,1),print_event(2,1,101),quote(mode,3,2,2,ask='12'),
            print_event(4,3,102),quote(mode,5,60000,3,ask='13'),print_event(6,60001,103))


@pytest.mark.parametrize('mode',MODES)
def test_quote_updates_only_change_the_next_print_execution_and_restore_capacity(mode):
    events=rows(mode)
    def run(kernel,events):
        def tick(source,forming):
            return [dict(side='BUY',type='MARKET',qty='3')] if source.payload['source_sequence']==101 else []
        return kernel.run(events,lambda *_:[],tick_callback=tick)
    kernel=DualClockSimulationKernel('1m',execution_fidelity=mode)
    run(kernel,events[:3])
    assert not kernel.execution.fills
    assert kernel.execution_event_count==1
    snapshot=deepcopy(kernel.snapshot())
    restored=DualClockSimulationKernel('1m',execution_fidelity=mode)
    restored.restore(snapshot)
    actual=run(restored,events[3:])
    expected=run(kernel,events[3:])
    assert actual==expected
    assert actual.fills[0]['event_time_ms']==3 and Decimal(actual.fills[0]['price'])==12
    if mode=='BOOK_ASSISTED':
        assert len(actual.fills)==1 and Decimal(actual.fills[0]['qty'])==3
    else:
        assert [Decimal(row['qty']) for row in actual.fills]==[Decimal(2),Decimal(1)]
        assert [row['event_time_ms'] for row in actual.fills]==[3,60001]
    assert restored.execution_event_count==3
    assert [(row['trigger'],row['watermark_ms']) for row in restored.decisions]==[
        ('REALTIME_TICK',1),('REALTIME_TICK',3),('BAR_CLOSE',59999),('REALTIME_TICK',60001)]
    with pytest.raises(MarketDatasetError,match='CHECKPOINT_CORRUPT'):
        DualClockSimulationKernel('1m').restore(snapshot)


def test_sampled_quote_at_the_same_millisecond_cannot_supply_a_fill_or_pine_tick():
    mode='BOOK_SAMPLED'
    events=(quote(mode,1,0,1),print_event(2,1,101),quote(mode,3,2,2,ask='12'),
            print_event(4,2,102),print_event(5,3,103))
    kernel=DualClockSimulationKernel('1m',execution_fidelity=mode)
    ticks=[]
    def tick(event,forming):
        ticks.append(event.sequence)
        return [dict(side='BUY',type='MARKET',qty='1')] if event.sequence==2 else []
    result=kernel.run(events,lambda *_:[],tick_callback=tick)
    assert ticks==[2,4,5]
    assert [row['sequence'] for row in result.fills]==[5]


@pytest.mark.parametrize('mode',MODES)
def test_recovery_rejects_regressed_physical_time_and_missing_book_continuity(mode):
    kernel=DualClockSimulationKernel('1m',execution_fidelity=mode)
    kernel.run(rows(mode)[:3],lambda *_:[])
    restored=DualClockSimulationKernel('1m',execution_fidelity=mode)
    restored.restore(kernel.snapshot())
    with pytest.raises(MarketDatasetError,match='DATA_GAP_REJECTED'):
        restored.run((replace(rows(mode)[3],event_time_ms=0),),lambda *_:[])
    bad=quote(mode,4,3,9)
    with pytest.raises(MarketDatasetError,match='gap|continuity'):
        restored.run((bad,),lambda *_:[])


@pytest.mark.parametrize('mode',MODES)
def test_quotes_count_toward_the_physical_event_memory_budget(mode):
    with pytest.raises(MarketDatasetError,match='BUDGET_EXCEEDED'):
        DualClockSimulationKernel('1m',execution_fidelity=mode,max_events=1).run(rows(mode),lambda *_:[])
    kernel=DualClockSimulationKernel('1m',execution_fidelity=mode,max_events=3)
    kernel.run(rows(mode)[:3],lambda *_:[])
    restored=DualClockSimulationKernel('1m',execution_fidelity=mode,max_events=3)
    restored.restore(kernel.snapshot())
    with pytest.raises(MarketDatasetError,match='BUDGET_EXCEEDED'):
        restored.run(rows(mode)[3:4],lambda *_:[])


@pytest.mark.parametrize('mode',MODES)
def test_v2_historical_marks_funding_and_quote_boundary_restore_one_actual_account(mode):
    from tests.test_backtest_account_v2_m4 import rules, event
    events=(replace(rules(-2),sequence=1),replace(event('MARK_INDEX',-1,mark_price='10'),sequence=2),
        quote(mode,3,0,1),print_event(4,1,101),quote(mode,5,2,2,ask='12'),print_event(6,3,102),
        quote(mode,7,59999,3),replace(event('MARK_INDEX',60000,mark_price='20'),sequence=8),
        replace(event('FUNDING',60000,funding_rate='.01',period_id='p1'),sequence=9),
        quote(mode,10,60000,4),print_event(11,60001,103))
    def make():
        return DualClockSimulationKernel('1m',execution_fidelity=mode,
            account_model='LINEAR_PERP_ONE_WAY_V2',funding_mode='HISTORICAL_REQUIRED')
    seen=[]
    def run(kernel,events):
        def close(_,bar):
            seen.append((bar.event_time_ms,str(kernel.account.mark),str(kernel.account.cumulative_funding)))
            return [dict(side='SELL',type='MARKET',qty='1',reduce_only=True)]
        def tick(source,bar):
            return [dict(side='BUY',type='MARKET',qty='1')] if source.payload['source_sequence']==101 else []
        return kernel.run(events,close,tick_callback=tick)
    kernel=make()
    expected=run(kernel,events)
    assert seen==[(59999,'10','0')]
    assert [Decimal(row['price']) for row in expected.fills]==[Decimal(12),Decimal(9)]
    assert kernel.account.position_qty==0
    assert kernel.account.mark==20 and kernel.account.cumulative_funding==Decimal('-.20')
    assert kernel.account.quote_balance==Decimal('9996.80')
    paused=make()
    run(paused,events[:8])
    restored=make()
    restored.restore(paused.snapshot())
    assert run(restored,events[8:])==expected


@pytest.mark.parametrize('mode',MODES)
def test_closing_tick_uses_the_old_book_before_a_boundary_quote_is_visible(mode):
    from app.simulation.closing_tick import match_closing_tick
    events=(quote(mode,1,59000,1),print_event(2,59001,101),
            quote(mode,3,60000,2,ask='13'),print_event(4,60001,102))
    kernel=DualClockSimulationKernel('1m',execution_fidelity=mode,process_orders_on_close=True)
    result=kernel.run(events,lambda *_:[dict(side='BUY',type='MARKET',qty='1')],
        close_callback=lambda bar,sequence:match_closing_tick(kernel.execution,bar,sequence))
    assert len(result.fills)==1
    assert Decimal(result.fills[0]['price'])==11
    assert result.fills[0]['event_time_ms']==59999
    assert result.fills[0]['reason']=='PINE_BAR_CLOSE'
