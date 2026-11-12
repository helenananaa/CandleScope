import pytest
from app.api.v1.indicators import router as indicators
from app.data_engine.data_manager.models import DataEventType
from app.data_engine.synthetic_series.core import SyntheticKernel, SyntheticConfig
from tests.test_synthetic_api import setup
from tests.test_synthetic_series import bar


def test_brick_ma_uses_authoritative_generation_and_retains_same_time_rows():
    client, source, service, body = setup()
    client.app.include_router(indicators)
    with client:
        with client.websocket_connect('/synthetic/stream') as ws:
            ws.send_json(body)
            snapshot = ws.receive_json()
            request = {'schemaVersion': 1, 'context': {'exchange': 'binance', 'marketType': 'spot',
                'symbol': 'BTCUSDT', 'interval': '1m', 'chartInput': {'request': body,
                'seriesId': snapshot['series_id'], 'generation': snapshot['generation'], 'revision': snapshot['revision']}},
                'ohlcv': [dict(time=i+1, open=999, high=999, low=999, close=999, volume=0) for i in range(3)],
                'requests': [{'clientId': 'ma', 'jobKey': 'ma-2', 'mode': 'builtin', 'name': 'MA', 'params': {'period': 2}}]}
            result = client.post('/indicators/compute/batch', json=request)
            assert result.status_code == 200, result.text
            payload = result.json()['results'][0]['payload']
            assert payload['ok'], payload
            line = payload['lines'][0]['data']
            assert [point['time'] for point in line] == [2, 3]
            assert [point['value'] for point in line] == [103, 105]
            assert len(source.active) == 1
            client.portal.call(source.emit, DataEventType.BAR_UPDATED, bar(120, 104, closed=False))
            changed = ws.receive_json()
            assert changed['revision'] != snapshot['revision']
            assert client.post('/indicators/compute/batch', json=request).status_code == 409
            request['context']['chartInput']['revision'] = changed['revision']
            request['ohlcv'] = request['ohlcv'][:2]
            assert client.post('/indicators/compute/batch', json=request).json()['results'][0]['payload']['lines'][0]['data'][0]['value'] == 103
            request['context']['symbol'] = 'ETHUSDT'
            assert client.post('/indicators/compute/batch', json=request).status_code == 409


@pytest.mark.parametrize('transform', ['renko', 'heikin-ashi', 'point-and-figure', 'kagi', 'line-break'])
def test_display_input_volume_never_multiplies_source_volume(transform):
    config = SyntheticConfig(transform=transform, box_size=2, min_tick=1)
    rows = [{**bar(60+i*60, value), 'volume': 12} for i, value in enumerate([100,106,110,100,108])]
    kernel = SyntheticKernel(config)
    output = kernel.replace_snapshot(rows)
    assert output
    assert all(point['volume'] >= 0 for point in output)
    assert sum(point['volume'] for point in output) <= sum(row['volume'] for row in rows) + 1e-8
    before = [dict(row) for row in output]
    assert kernel.replace_snapshot(rows) == before
