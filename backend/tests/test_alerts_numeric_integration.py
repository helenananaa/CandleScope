"""Public numeric calculations, real canonical revisions and durable alert fences."""
import asyncio
from dataclasses import replace

from app.alerts.facade import AlertFacade
from app.alerts.runtime import AlertRuntimeEngine
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType
from app.data_engine.data_manager.indicator_inputs import IndicatorInputPort
from app.indicator.numeric_queries import NumericIndicatorService
from app.indicator.range_result_service import IndicatorRangeResultService
from tests.test_numeric_indicator_queries import compute
from tests.test_shared_blocks_integration import dm, read_rows, write, KEY, DAY


def rule(facade, **overrides):
    return facade.save_rule({**dict(name='numeric',
        target=dict(symbol=KEY.symbol, interval=KEY.interval, exchange=KEY.exchange, marketType=KEY.market_type),
        expression=dict(left='rsi', comparator='>=', right=dict(type='number', value=0)),
        afterTrigger='keep', cooldownMs=0, actions=[]), **overrides})


def bind(dm, compute_fn):
    from tests.test_custom_history_streaming import rows
    write(rows(400, DAY // 1000))
    dm.query_engine._cfg.max_limit = 500
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=compute_fn)
    dm.bind_indicator_queries(service)
    return service


async def actual(name, meta, bars):
    return compute(name, meta, bars)


def test_rule_edit_during_public_calculation_rejects_old_trigger(dm, tmp_path):
    async def run():
        entered, resume = asyncio.Event(), asyncio.Event()
        async def held(name, meta, bars):
            entered.set()
            await resume.wait()
            return await actual(name, meta, bars)
        service = bind(dm, held)
        facade = AlertFacade(store_path=tmp_path / 'rules.json')
        saved = rule(facade)
        runtime = AlertRuntimeEngine(facade=facade, data_manager=dm)
        event = DataEvent(DataEventType.BAR_CLOSED, KEY, bar=BarData.from_storage_row(dm.query_engine.storage.query_bars(KEY.symbol, KEY.interval, limit=1, order='DESC', market_type=KEY.market_type)[0], market_type=KEY.market_type))
        pending = asyncio.create_task(runtime.evaluate_event(saved['id'], event))
        await asyncio.wait_for(entered.wait(), 5)
        changed = facade.save_rule({**saved, 'name': 'edited while calculating'})
        resume.set()
        assert await pending is None
        assert facade.list_history() == []
        assert facade.get_rule(saved['id'])['definitionRevision'] == changed['definitionRevision']
        assert saved['id'] not in runtime._previous_values
        await service.close()
    asyncio.run(run())


def test_unverified_numeric_input_cannot_turn_not_into_a_trigger(dm, tmp_path, monkeypatch):
    async def run():
        service = bind(dm, actual)
        facade = AlertFacade(store_path=tmp_path / 'rules.json')
        saved = rule(facade, expression=dict(op='NOT', children=[dict(
            left='rsi', comparator='>', right=dict(type='number', value=101))]))
        runtime = AlertRuntimeEngine(facade=facade, data_manager=dm)
        old = BarData.from_storage_row(dm.query_engine.storage.query_bars(KEY.symbol, KEY.interval, limit=1, order='DESC', market_type=KEY.market_type)[0], market_type=KEY.market_type)
        write([replace(old, close=old.close + 1, high=old.high + 1)])
        def forbidden(*args, **kwargs):
            raise AssertionError('Invalid numeric state entered expression evaluation')
        monkeypatch.setattr(facade, 'evaluate', forbidden)
        assert await runtime.evaluate_event(saved['id'], DataEvent(DataEventType.BAR_CLOSED, KEY, bar=old)) is None
        assert facade.list_history() == []
        assert runtime.snapshot()['ruleDiagnostics'][saved['id']]['state'] == 'stale'
        await service.close()
    asyncio.run(run())


def test_same_closed_observation_stays_deduplicated_after_runtime_and_store_restart(dm, tmp_path):
    async def run():
        service = bind(dm, actual)
        path = tmp_path / 'rules.json'
        facade = AlertFacade(store_path=path)
        saved = rule(facade)
        event = DataEvent(DataEventType.BAR_CLOSED, KEY, bar=BarData.from_storage_row(dm.query_engine.storage.query_bars(KEY.symbol, KEY.interval, limit=1, order='DESC', market_type=KEY.market_type)[0], market_type=KEY.market_type))
        runtime = AlertRuntimeEngine(facade=facade, data_manager=dm)
        first = await runtime.evaluate_event(saved['id'], event)
        assert first is not None, runtime.snapshot()
        assert first['definitionRevision'] == saved['definitionRevision']
        assert await runtime.evaluate_event(saved['id'], event) is None
        restored = AlertFacade(store_path=path)
        restarted = AlertRuntimeEngine(facade=restored, data_manager=dm)
        assert await restarted.evaluate_event(saved['id'], event) is None
        assert len(restored.list_history()) == restored.get_rule(saved['id'])['triggerCount'] == 1
        await service.close()
    asyncio.run(run())
