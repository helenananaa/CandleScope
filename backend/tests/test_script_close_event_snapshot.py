"""Closed-only scripts must calculate the close they are publishing."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.v1.stream_script_subscriptions import handle_script_indicator_subscribe
from app.api.v1.stream_indicator_payloads import _query_script_snapshot_bars
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey
from app.indicator.runtime_routes import IndicatorRuntimeRoute, IndicatorRuntimeRoutes
from app.indicator.runtime_service import IndicatorRuntimeService

T0 = 1_800_000_000
SOURCE = """INDICATOR={'name':'Close event','overlay':True,'window':3}
def compute(bars, params):
    return {'lines':{'main':[value*4 for value in bars['close']]}}
"""


class Host:
    def __init__(self):
        from candlescope_plugin_python_indicator.runtime import PythonIndicatorRuntime

        self.runtime = PythonIndicatorRuntime()
        self.requests = []

    async def descriptor(self, runtime_id):
        return self.runtime.describe()

    async def execute_batch(self, runtime_id, request):
        self.requests.append(request)
        return self.runtime.execute_batch(request)


class Market:
    def __init__(self, *, amended=False):
        self.closed = BarData(T0 + 120, 10, 20, 0, 13, 1, is_closed=True)
        # The notification's close is final, while this query view still has
        # its preceding forming record and has already observed the next bar.
        self.bars = [BarData(T0 + i * 60, 10, 20, 0, 10 + i, 1,
                             is_closed=i < 2) for i in range(4)]
        if amended:
            self.bars[2] = BarData(T0 + 120, 10, 20, 0, 19, 1, is_closed=True)
        self.before_queries = []

    def query_latest(self, *args, **kwargs):
        return SimpleNamespace(bars=self.bars[-kwargs['limit']:])

    def query_before(self, symbol, interval, before_ms, **kwargs):
        self.before_queries.append((before_ms, kwargs))
        return SimpleNamespace(bars=[bar for bar in self.bars if bar.time * 1000 < before_ms][-kwargs['limit']:])

    async def ensure_stream(self, *args, **kwargs):
        pass

    def subscribe(self, **kwargs):
        if kwargs.get('symbol'):
            self.callback = kwargs['callback']
        return kwargs['callback']


@pytest.mark.parametrize('time,closed', [(T0 + 60, True), (T0 + 120, False)])
def test_close_input_cannot_promote_a_forming_or_different_event(time, closed):
    market = Market()
    bar = BarData(time, 10, 20, 0, 13, 1, is_closed=closed)
    with pytest.raises(ValueError, match='does not match'):
        _query_script_snapshot_bars(market, {'historyLimit': 3},
                                   bar_time=T0 + 120, closed_bar=bar)


@pytest.mark.parametrize('amended', [False, True])
def test_close_event_uses_causal_final_input_without_reopening_a_newer_amendment(amended, monkeypatch):
    # Exercise the repository's real optional runtime without making it a
    # production backend dependency or requiring a preinstalled plugin wheel.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]
        / 'packages/candlescope-plugin-python-indicator/src'))
    asyncio.run(_check_close_event(amended))


async def _check_close_event(amended):
    host, market = Host(), Market(amended=amended)
    runtime_id = host.runtime.describe().id
    service = IndicatorRuntimeService(IndicatorRuntimeRoutes((
        IndicatorRuntimeRoute(language='python', mode='sidecar', runtime_id=runtime_id),
    )), host=host, legacy_languages=frozenset())
    tasks, metas, handles, sent = {}, {}, {}, []
    queue = asyncio.Queue()

    async def send(payload):
        sent.append(payload)

    async def unsubscribe(client_id):
        pass

    try:
        await handle_script_indicator_subscribe(dm=market, custom_handles=handles,
            custom_tasks=tasks, queue=queue, client_meta=metas, client_id='closed-python',
            symbol='BTCUSDT', interval='1m', exchange='binance', market_type='spot',
            name='Close event', language='python', custom_id='closed-python', script=SOURCE,
            params={}, security_mode=None, history_limit=3, send_json=send,
            stream_consumer_id='close-owner', unsubscribe_client=unsubscribe,
            queue_message=lambda q, payload: q.put_nowait(payload), runtime_service=service)
        await market.callback(DataEvent(event_type=DataEventType.BAR_CLOSED,
            key=SeriesKey('BTCUSDT', '1m', exchange='binance', market_type='spot'),
            bar=market.closed, timestamp_ms=market.closed.time * 1000))
        message = await asyncio.wait_for(queue.get(), 5)
        assert message['type'] == 'indicator.patch'
        expected = 19 if amended else 13
        assert message['lines'][0]['data'] == [{'time': T0 + 120, 'value': expected * 4}]
        assert [bar.time for bar in host.requests[-1].bars] == [T0, T0 + 60, T0 + 120]
        assert all(bar.is_closed for bar in host.requests[-1].bars)
        assert market.before_queries[0][0] == (T0 + 120) * 1000 + 1
        assert market.before_queries[0][1]['auto_backfill'] is False
    finally:
        for meta in metas.values():
            meta['_disposed'] = True
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        await service.stop()
