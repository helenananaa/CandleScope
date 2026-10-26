"""Real Pine engines on host spot cash, with real-bar/print execution."""
import json
from decimal import Decimal as D

import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_external_strategy_v2 import source, tape


def spot_payload(host, payload):
    snapshot = host.preview_snapshot(dataset_id=payload['dataset_id'], data_epoch=payload['data_epoch'],
                                    start_time_ms=0, end_time_ms=599999, interval='1m', market_type='spot')
    return {**payload, 'market_type': 'spot', 'snapshot_hash': snapshot['snapshot_hash']}


@pytest.mark.parametrize('language', ['pine'])
@pytest.mark.parametrize('fidelity', ['BAR_APPROX', 'TRADE_TAPE', 'BOOK_ASSISTED'])
def test_spot_host_rejects_borrowing_and_shorting_and_keeps_realized_feedback(runtime, language, fidelity):
    host, payload = runtime
    operation = '''if bar_index == 0:
    strategy.entry("too-big", strategy.long, qty=10)
if bar_index == 1:
    strategy.entry("short", strategy.short, qty=1)
if bar_index == 2:
    strategy.entry("L", strategy.long, qty=0.5)
if bar_index == 4:
    strategy.close("L")'''
    if language == 'pine': operation = operation.replace(':', '')
    config = {**spot_payload(host, payload), 'language': language, 'source': source(language, operation),
              'execution_mode': 'CANDLESCOPE', 'execution_fidelity': fidelity,
              'host_settings': {'initial_balance': 100, 'slippage_bps': 0, 'taker_fee_bps': 10}}
    if fidelity in {'TRADE_TAPE', 'BOOK_ASSISTED'}:
        data = tape()
        if fidelity == 'BOOK_ASSISTED':
            events = []
            for index, event in enumerate(data['events']):
                # Zero-spread snapshots isolate cash/base constraints while the
                # same original trade stream remains the execution clock.
                price = event['payload']['price']
                events.append({'time_ms': event['time_ms'], 'role': 'ORDER_BOOK',
                    'payload': {'book_sequence': index + 1, 'snapshot': index == 0,
                                'bid': price, 'ask': price}})
                events.append(event)
            data['events'] = events
        config['execution_data'] = data
    run = terminal(host.native, host.native.create(config, 'spot-host')['run_id'])
    assert run['state'] == 'COMPLETED', run.get('error')
    result = run['result']
    assert result['account_model'] == result['position']['account_model'] == 'SPOT_CASH_V1'
    assert {r['reason'] for r in result['diagnostics']} == {'SPOT_INSUFFICIENT_CASH', 'SPOT_INSUFFICIENT_BASE'}
    assert [D(row['price']) for row in result['trades']] == [D(20), D(5)]
    assert [D(row['qty']) for row in result['trades']] == [D('.5'), D('.5')]
    assert D(result['position']['quote_balance']) == D('92.4875')
    assert D(result['position']['position_qty']) == 0
    assert result['raw_output']['account_feedback'][3]['netprofit'] == -.01
    assert result['raw_output']['account_feedback'][3]['equity'] == 99.99
    with host.native.lock:
        row = host.native.db.execute('SELECT wire FROM native_inputs WHERE id=?', (run['run_id'],)).fetchone()
    assert json.loads(row[0])['account_model'] == 'SPOT_CASH_V1'
    assert host.native.create(config, 'spot-host')['run_id'] == run['run_id']


@pytest.mark.parametrize('language', ['pine'])
def test_spot_fill_callback_does_not_report_asset_purchase_as_realized_loss(runtime, language):
    from tests.test_external_feedback import run, PINE
    host, payload = runtime
    record = run(host, spot_payload(host, payload), language, PINE, 'TRADE_TAPE')
    assert record['state'] == 'COMPLETED', record.get('error')
    result = record['result']
    passes = result['raw_output']['execution_passes'][1]
    assert passes[0]['account']['position_size'] == 4
    assert passes[0]['account']['netprofit'] == -.004
    assert passes[0]['account']['equity'] == 9999.996
    assert D(result['position']['quote_balance']) == D('10003.9916')
    assert D(result['position']['position_qty']) == 0
