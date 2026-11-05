"""Frozen selected program/configuration reader; synthetic completed-run metadata."""
import json
import os
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.backtests import router
from app.backtest.errors import BacktestError
from tests.test_python_editor import service_at, compile_editor, SOURCE


@pytest.fixture
def service(tmp_path):
    value = service_at(tmp_path)
    try:
        yield value
    finally:
        value.shutdown()


def saved_run(service, revision, *, parameters=None, run_id='bt_selected'):
    row = service.repository.get_strategy_revision(revision['revision_id'])
    compiled = json.loads(row['compiled_json'])
    config = dict(strategy_revision_id=row['revision_id'], strategy_source=compiled['executionSource'],
        parameters=parameters or {'fast': 3, 'slow': 7}, symbol='BTCUSDT', interval='1m',
        exchange='binance', market_type='spot', start_time_ms=60000, end_time_ms=600000,
        initial_balance='10000', taker_fee_bps='4', maker_fee_bps='2', output_mode='TARGET_POSITION',
        python_trusted_confirmed=True)
    service.repository.insert_run(dict(run_id=run_id, study_id=None, idempotency_key=run_id,
        state='COMPLETED', fidelity_mode='BAR_APPROX', source_event_kind='BAR',
        strategy_revision_id=row['revision_id'], dataset_id='fixture', data_epoch='epoch',
        snapshot_hash='sha256:fixture', config_json=json.dumps(config), config_hash='sha256:selected',
        engine_version='fixture', generation=1, failure_code=None, created_at_ms=100, updated_at_ms=100))
    return config


def test_selected_python_is_original_bundle_not_later_editor_or_account(service, monkeypatch):
    revision = compile_editor(service)
    config = saved_run(service, revision)
    compile_editor(service, SOURCE + '\n# later edit\n')
    service.archive_strategy_revision(revision['revision_id'])
    # Reading a selected program must not construct a provider, run user code,
    # or borrow a checkpoint/report/current editor as a source of code.
    monkeypatch.setattr(service, 'build_python_host_provider', lambda *a, **k: pytest.fail('executed selected source'))
    before = service.repository.connection.total_changes
    def authorize(action, table, column, *_):
        if action == sqlite3.SQLITE_READ and table not in {
            'backtest_runs', 'backtest_strategy_revisions', 'backtest_strategy_bundles'}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    service.repository.connection.set_authorizer(authorize)
    try:
        selected = service.selected_run_version('bt_selected')
    finally:
        service.repository.connection.set_authorizer(None)
    assert selected['program']['source_text'] == SOURCE
    assert selected['program']['language'] == 'python'
    assert selected['configuration'] == config
    assert selected['strategy_revision_id'] == revision['revision_id']
    assert selected['program']['bundle_hash'].startswith('sha256:')
    assert selected['version_hash'].startswith('sha256:')
    assert service.repository.connection.total_changes == before
    assert selected == service.selected_run_version('bt_selected')


def test_selected_pine_preserves_frozen_libraries_and_parameters(service, monkeypatch):
    from app.backtest.strategy import pine_engine
    # Explicit test-worker selection; analysis still invokes the real isolated
    # Pine adapter. Never depend on the user's mutable installed registry.
    worker = os.environ.get('NATIVE_TEST_PINE_PYTHON')
    assert worker, 'Set NATIVE_TEST_PINE_PYTHON to the qualified source-candidate worker'
    monkeypatch.setattr(pine_engine, 'plugin', lambda: {
        'command': [worker, '-I', '-m', 'candlescope_plugin_pine_compat.chart_strategy'],
        'plugin_id': 'candlescope.pine-compat',
    })
    source = '//@version=6\nstrategy("Selected")\nimport local/Math/1 as m\nplot(m.twice(close))'
    library = '//@version=6\nlibrary("Math")\nexport twice(float x) => x * 2'
    revision = service.create_strategy_revision(dict(name='Selected Pine', language='PINE_ENGINE',
        source_text=source, libraries={'local/Math/1': library}))
    config = saved_run(service, revision, parameters={'length': 19})
    service.create_strategy_revision(dict(name='Selected Pine', language='PINE_ENGINE',
        source_text=source, libraries={'local/Math/1': library.replace('x * 2', 'x * 3')}))
    value = service.selected_run_version('bt_selected')
    assert value['program']['source_text'] == source
    assert value['program']['language'] == 'pine'
    assert value['program']['libraries'] == {'local/Math/1': library}
    assert value['configuration'] == config


def test_missing_unfinished_and_retired_versions_fail_without_mutation(service):
    with pytest.raises(BacktestError, match='does not exist'):
        service.selected_run_version('bt_missing')
    revision = compile_editor(service)
    saved_run(service, revision)
    c = service.repository.connection
    c.execute("UPDATE backtest_runs SET state='RUNNING' WHERE run_id='bt_selected'"); c.commit()
    with pytest.raises(BacktestError, match='completed'):
        service.selected_run_version('bt_selected')
    c.execute("UPDATE backtest_runs SET state='COMPLETED'")
    c.execute("UPDATE backtest_strategy_revisions SET language='PYNE' WHERE revision_id=?", (revision['revision_id'],)); c.commit()
    before = c.total_changes
    with pytest.raises(BacktestError) as failure:
        service.selected_run_version('bt_selected')
    assert failure.value.code == 'FIDELITY_UNSUPPORTED'
    assert c.total_changes == before


@pytest.mark.parametrize('column,value', [('source_text', 'changed'), ('compiled_json', '{}')])
def test_changed_frozen_source_or_compilation_is_rejected(service, column, value):
    revision = compile_editor(service)
    saved_run(service, revision)
    c = service.repository.connection
    c.execute(f'UPDATE backtest_strategy_revisions SET {column}=? WHERE revision_id=?', (value, revision['revision_id'])); c.commit()
    with pytest.raises(BacktestError) as failure:
        service.selected_run_version('bt_selected')
    assert failure.value.code == 'DATA_SNAPSHOT_MISMATCH'


def test_changed_python_bundle_is_rejected_and_files_preserved(service):
    from pathlib import Path
    revision = compile_editor(service)
    saved_run(service, revision)
    row = service.repository.get_strategy_revision(revision['revision_id'])
    bundle = service.repository.get_strategy_bundle(json.loads(row['source_text'])['bundle_id'])
    path = Path(bundle['store_path']) / 'strategy.py'
    path.chmod(0o600); path.write_text(SOURCE + '\n# changed frozen file\n')
    before = path.read_bytes()
    with pytest.raises(BacktestError) as failure:
        service.selected_run_version('bt_selected')
    assert failure.value.code == 'DATA_SNAPSHOT_MISMATCH'
    assert path.read_bytes() == before


def test_http_selected_version_is_readonly_and_unknown_returns_error(service):
    revision = compile_editor(service)
    saved_run(service, revision)
    app = FastAPI(); app.include_router(router, prefix='/api/v1'); app.state.backtest_service = service
    with TestClient(app) as client:
        response = client.get('/api/v1/backtests/runs/bt_selected/strategy-version')
        assert response.status_code == 200, response.text
        assert response.json()['program']['source_text'] == SOURCE
        assert response.json()['configuration']['maker_fee_bps'] == '2'
        assert client.get('/api/v1/backtests/runs/bt_missing/strategy-version').status_code == 400


def execute_selected_research(service):
    """Real Python editor compilation, subprocess and Host account, no transport."""
    from app.market_dataset.snapshot import MarketEvent
    start = 1700000040000
    revision = compile_editor(service)
    body = dict(strategy_revision_id=revision['revision_id'], dataset_id='selected-20', data_epoch='selected-epoch',
        snapshot_hash='sha256:selected-20', fidelity_mode='BAR_APPROX', source_event_kind='BAR',
        start_time_ms=start, end_time_ms=start + 20 * 60000, symbol='BTCUSDT', interval='1m',
        parameters={'fast': 3, 'slow': 7}, output_mode='TARGET_POSITION', initial_balance='5000',
        account_model='SPOT_CASH_V1', contract_data_mode='LEGACY_FIXED_V1', funding_mode='OFF', funding_rate='0',
        leverage='1', sizing_policy='EQUITY_PERCENT_V1', equity_percent='20', slippage_bps='2', taker_fee_bps='3.5', maker_fee_bps='3.5',
        execution_model_revision='EXECUTION_REALISM_V2', participation_rate='0.1', order_end_policy='CANCEL_AT_END',
        gap_policy='REJECT', quick_preset_id='CRYPTO_SPOT_STANDARD_V1', quick_preset_revision='2', fee_source='user-defined',
        exchange='binance', market_type='spot', python_runtime_mode='TRUSTED_LOCAL', python_trusted_confirmed=True)
    service.smoke_strategy_revision(revision['revision_id'], body)
    provider = service.build_python_host_provider(revision['revision_id'], mode='TRUSTED_LOCAL', trusted_confirmed=True)
    run = service.create_run(body, idempotency_key='selected-actual-20')
    events = tuple(MarketEvent(sequence=i + 1, event_time_ms=start + (i + 1) * 60000 - 1, role='BARS', payload={
        'open': str(100 + i % 7), 'high': str(102 + i % 7), 'low': str(99 + i % 7), 'close': str(101 + i % 7), 'volume': '100',
    }) for i in range(20))
    completed = service.execute_bar_run(run['run_id'], events=events, provider=provider)
    assert completed['state'] == 'COMPLETED'
    assert completed['report']['fills'], 'Real selected research must contain account activity'
    assert provider.runner._process is None
    return run['run_id']


def test_executed_research_selects_old_code_and_full_configuration_after_editor_changes(service):
    run_id = execute_selected_research(service)
    before = service.repository.get_run_by_id(run_id)
    compile_editor(service, SOURCE + '\n# latest editor is a different version\n')
    value = service.selected_run_version(run_id)
    assert value['program']['source_text'] == SOURCE
    assert value['configuration'] == json.loads(before['config_json'])
    assert value['configuration']['equity_percent'] == '20'
    assert service.repository.get_run_by_id(run_id) == before
