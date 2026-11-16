"""R129 detached targets must release state and fence suspended source work."""
import asyncio
from dataclasses import replace

import pytest

from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig, BarInputSource, MergeMode
from app.data_engine.aggregation.blocks import BlockRevisionChanged
from tests.test_component_incremental import component


def owner():
    agg=BarAggregator(BarAggregatorConfig(finalize_timeout_ms=10**15,update_throttle_ms=0,
        emit_expired_events=True,use_event_driven_close=True))
    agg.add_target('BTCUSDT','1m')
    return agg


async def ingest(agg,index=0,**changes):
    value=component(index,merge_mode=MergeMode.SNAPSHOT,source=BarInputSource.REALTIME,**changes)
    await agg.ingest_bar_input('binance','spot','BTCUSDT','1m',value)


@pytest.mark.parametrize('reattach',[False,True])
def test_detach_fences_input_suspended_in_previous_bucket_expiry_callback(reattach):
    async def run():
        agg=owner()
        await ingest(agg,closed=False)
        entered,released=asyncio.Event(),asyncio.Event()
        async def on_closed(event):
            entered.set()
            await released.wait()
        agg.publisher.on_bar_expired(on_closed)
        task=asyncio.create_task(ingest(agg,1,closed=False))
        await asyncio.wait_for(entered.wait(),2)
        agg.remove_target('BTCUSDT','1m')
        if reattach:
            agg.add_target('BTCUSDT','1m')
            await ingest(agg,1,closed=False,close=777.,sequence=99)
        released.set()
        result=await asyncio.gather(task,return_exceptions=True)
        state=agg.get_bucket_state('BTCUSDT','1m',60000)
        assert (state.close == 777. if reattach else state is None)
        assert isinstance(result[0],BlockRevisionChanged)
    asyncio.run(run())


@pytest.mark.parametrize('reattach',[False,True])
def test_detach_fences_late_component_readback_without_history_runtime(reattach):
    async def run():
        agg=BarAggregator(BarAggregatorConfig(finalize_timeout_ms=10**15,update_throttle_ms=0))
        agg.add_target('BTCUSDT','89m')
        entered,released=asyncio.Event(),asyncio.Event()
        async def readback(*args):
            entered.set()
            await released.wait()
            return []
        agg.set_source_component_reader(readback)
        value=component(0,extra={'source_ref':{'series':'source','revision':1}})
        task=asyncio.create_task(agg.ingest_bar_input('binance','spot','BTCUSDT','89m',value))
        await asyncio.wait_for(entered.wait(),2)
        agg.remove_target('BTCUSDT','89m')
        if reattach:
            agg.add_target('BTCUSDT','89m')
            await agg.ingest_bar_input('binance','spot','BTCUSDT','89m',component(1,closed=False,close=777.))
        released.set()
        result=await asyncio.gather(task,return_exceptions=True)
        state=agg.get_bucket_state('BTCUSDT','89m',0)
        assert (state.close == 777. and len(state.source_snapshots)==1 if reattach else state is None)
        assert isinstance(result[0],BlockRevisionChanged)
    asyncio.run(run())


def test_detach_releases_closed_correction_state_without_destroying_pipeline_hooks():
    async def run():
        agg=owner()
        pipeline=agg.get_pipeline('1m')
        original_strategy=pipeline.bar_state._component_merge_strategy
        for index in range(64):
            symbol=f'CHURN{index}USDT'
            agg.add_target(symbol,'1m')
            await agg.ingest_bar_input('binance','spot',symbol,'1m',
                replace(component(0,merge_mode=MergeMode.SNAPSHOT),symbol=symbol))
            assert len(agg.get_recent_bars(symbol,'1m'))==1
            agg.remove_target(symbol,'1m')
        assert agg.memory_usage()['closed_bars']==0
        assert agg.get_pipeline('1m') is pipeline
        assert pipeline.bar_state._component_merge_strategy is original_strategy
        assert agg.has_series_target('BTCUSDT','1m','binance','spot',component(0).identity)
    asyncio.run(run())


def test_detach_closed_state_is_scoped_to_exact_market_and_symbol():
    async def run():
        agg=owner()
        for symbol,market in [('BTCUSDT','spot'),('ETHUSDT','spot'),('BTCUSDT','futures')]:
            agg.add_target(symbol,'1m',market_type=market)
            await agg.ingest_bar_input('binance',market,symbol,'1m',
                replace(component(0,merge_mode=MergeMode.SNAPSHOT),symbol=symbol,market_type=market))
        agg.remove_target('BTCUSDT','1m')
        assert agg.get_recent_bars('BTCUSDT','1m')==[]
        assert len(agg.get_recent_bars('ETHUSDT','1m'))==1
        assert len(agg.get_recent_bars('BTCUSDT','1m',market_type='futures'))==1
    asyncio.run(run())


def test_detach_keeps_source_delivery_retry_snapshot_and_pipeline_customization():
    from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
    async def run():
        agg=owner()
        pipeline=agg.get_pipeline('1m')
        strategy=pipeline.bar_state.merge_strategy
        pipeline.bar_state.set_merge_strategy(strategy)
        finalizer=pipeline.finalizer
        seen=[]
        unavailable=True
        async def durable_callback(event):
            if unavailable:
                raise BarDeliveryUnavailable('controlled delivery outage')
            seen.append(event.bar.to_storage_dict())
        agg.publisher.on_bar_closed(durable_callback)
        value=component(0,merge_mode=MergeMode.SNAPSHOT,
            extra={'source_ref':{'series':'source','revision':1}})
        with pytest.raises(BarDeliveryUnavailable):
            await agg.ingest_bar_input('binance','spot','BTCUSDT','1m',value)
        expected=agg.get_recent_bars('BTCUSDT','1m')[0].to_storage_dict()
        assert len(agg.publisher._pending_source_events)==1
        agg.remove_target('BTCUSDT','1m')
        assert agg.get_recent_bars('BTCUSDT','1m')==[]
        assert len(agg.publisher._pending_source_events)==1
        assert pipeline.bar_state.merge_strategy is strategy
        assert pipeline.bar_state._merge_strategy_overridden
        assert pipeline.finalizer is finalizer
        unavailable=False
        await agg.publisher.retry_source_deliveries()
        assert seen == [expected]
        assert not agg.publisher._pending_source_events
    asyncio.run(run())


def test_detach_does_not_clear_other_semantic_identity():
    async def run():
        agg=owner()
        identity=replace(component(0).identity,price_adjustment='adjusted')
        agg.add_target('BTCUSDT','1m',series_identity=identity)
        for value in [component(0,merge_mode=MergeMode.SNAPSHOT),
                      component(0,merge_mode=MergeMode.SNAPSHOT,series_identity=identity)]:
            await agg.ingest_bar_input('binance','spot','BTCUSDT','1m',value)
        agg.remove_target('BTCUSDT','1m')
        assert agg.get_recent_bars('BTCUSDT','1m')==[]
        assert len(agg.get_recent_bars('BTCUSDT','1m',series_identity=identity))==1
    asyncio.run(run())


def test_duplicate_registration_does_not_cancel_suspended_input():
    async def run():
        agg=owner()
        await ingest(agg,closed=False)
        entered,released=asyncio.Event(),asyncio.Event()
        async def on_expired(event):
            entered.set()
            await released.wait()
        agg.publisher.on_bar_expired(on_expired)
        task=asyncio.create_task(ingest(agg,1,closed=False))
        await asyncio.wait_for(entered.wait(),2)
        agg.add_target('BTCUSDT','1m')
        released.set()
        await task
        assert agg.get_bucket_state('BTCUSDT','1m',60000) is not None
    asyncio.run(run())


def test_explicit_unregistered_maintenance_ingest_keeps_its_public_contract():
    async def run():
        agg=owner()
        agg.remove_target('BTCUSDT','1m')
        await ingest(agg,closed=False)
        assert agg.get_bucket_state('BTCUSDT','1m',0) is not None
        assert not agg.get_targets()
    asyncio.run(run())
