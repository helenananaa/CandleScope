"""Run the source offered by the editor in a real local Python subprocess."""
import json
from pathlib import Path

import pytest

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.backtest.strategy.python_runner import PythonRunnerError
from app.backtest.colocated import provider_spec
from app.core.config import load_backtest_settings
from app.market_dataset.snapshot import MarketEvent

ROOT = Path(__file__).resolve().parents[2]
SOURCE = json.loads((ROOT / 'frontend/src/features/backtest/chart-tester/chartStrategyTesterUiModel.ts').read_text().split('export const PYTHON_SMA_SOURCE = ', 1)[1].split(';\n', 1)[0])


def service_at(tmp_path):
    return BacktestService.start(load_backtest_settings(
        {"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"},
        data_dir=tmp_path, klines_db_path=tmp_path / 'market.db', replay_db_path=tmp_path / 'replay.db',
    ), enforce_registered_revisions=True)


def compile_editor(service, source=SOURCE):
    return service.create_strategy_revision({"name": "Python SMA", "language": "PYTHON_EDITOR", "source_text": source, "parameter_schema": []})


def test_python_editor_actual_600_bar_run_and_identity(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED', '0')
    monkeypatch.setenv('BACKTEST_PYTHON_STRATEGY_ENABLED', '0')
    service = service_at(tmp_path)
    revision = compile_editor(service)
    assert compile_editor(service)['revision_id'] == revision['revision_id']
    assert compile_editor(service, SOURCE + '\n# edit\n')['revision_id'] != revision['revision_id']
    provider = service.build_python_host_provider(revision['revision_id'], mode='TRUSTED_LOCAL', trusted_confirmed=True)
    assert provider_spec(provider) is None
    body = {
        'strategy_revision_id': revision['revision_id'], 'dataset_id': 'editor-600',
        'data_epoch': 'epoch-editor-600', 'snapshot_hash': 'sha256:editor-600',
        'fidelity_mode': 'BAR_APPROX', 'source_event_kind': 'BAR',
        'start_time_ms': 0, 'end_time_ms': 600 * 60000, 'symbol': 'BTCUSDT', 'interval': '1m',
        'parameters': {}, 'output_mode': 'TARGET_POSITION', 'initial_balance': '10000',
        'account_model': 'LINEAR_PERP_ONE_WAY_V1', 'slippage_bps': '1', 'taker_fee_bps': '4', 'maker_fee_bps': '4',
        'exchange': 'binance', 'market_type': 'usdm', 'python_runtime_mode': 'TRUSTED_LOCAL', 'python_trusted_confirmed': True,
    }
    service.smoke_strategy_revision(revision['revision_id'], body)
    events = tuple(MarketEvent(sequence=i + 1, event_time_ms=(i + 1) * 60000, role='BARS', payload={
        'open': str(100 + i % 20), 'high': str(101 + i % 20), 'low': str(99 + i % 20),
        'close': str(100 + i % 20), 'volume': '100',
    }) for i in range(600))
    run = service.create_run(body, idempotency_key='python-editor-600')
    completed = service.execute_bar_run(run['run_id'], events=events, provider=provider)
    assert completed['state'] == 'COMPLETED'
    assert len(completed['report']['fills']) > 0
    assert provider.runner._process is None
    assert service.get_python_runtime_receipt(revision['revision_id'])['mode'] == 'TRUSTED_LOCAL'


def test_editor_needs_confirmation_and_plain_bundle_keeps_gate(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED', '0')
    service = service_at(tmp_path)
    revision = compile_editor(service)
    with pytest.raises(PythonRunnerError, match='TRUSTED_LOCAL_UNCONFIRMED'):
        service.build_python_host_provider(revision['revision_id'], mode='TRUSTED_LOCAL', trusted_confirmed=False)
    bundle = service.create_python_strategy_bundle(directory=str(ROOT / 'packages/candlescope-backtest-sdk/fixtures/sma_cross'))
    studio = service.create_python_strategy_revision(bundle['bundle_id'])
    with pytest.raises(PythonRunnerError, match='TRUSTED_LOCAL_DISABLED'):
        service.build_python_host_provider(studio['revision_id'], mode='TRUSTED_LOCAL', trusted_confirmed=True)


def test_editor_static_error_has_source_location(tmp_path):
    with pytest.raises(BacktestError, match='BUNDLE_STATIC_DIAGNOSTIC') as error:
        compile_editor(service_at(tmp_path), 'class Strategy:\n    def step(self, observation)\n        pass\n')
    assert 'line' in str(error.value)


def test_http_editor_requires_trusted_origin_and_smoke_consent(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.backtests import router

    monkeypatch.setenv('BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED', '0')
    monkeypatch.setattr('app.backtest.strategy.python_runner.sandbox_available', lambda: False)
    service = service_at(tmp_path)
    api = FastAPI()
    api.include_router(router, prefix='/api/v1')
    api.state.backtest_service = service
    client = TestClient(api)
    body = {'name': 'Editor HTTP', 'language': 'PYTHON_EDITOR', 'source_text': SOURCE}
    untrusted = client.post('/api/v1/backtests/strategy-revisions', json=body, headers={'Origin': 'https://other.example'})
    assert untrusted.json()['error']['code'] == 'TRUSTED_ORIGIN_REQUIRED'
    trusted = client.post('/api/v1/backtests/strategy-revisions', json=body, headers={'Origin': 'http://127.0.0.1:15173'})
    assert trusted.status_code == 200, trusted.text
    revision = trusted.json()['revision_id']
    smoke = {'dataset_id': 'editor-http', 'snapshot_hash': 'sha256:editor-http', 'start_time_ms': 1, 'end_time_ms': 60000,
             'python_runtime_mode': 'TRUSTED_LOCAL', 'python_trusted_confirmed': True}
    # A remote origin is downgraded and cannot borrow local Python approval.
    remote = client.post(f'/api/v1/backtests/strategy-revisions/{revision}/smoke', json=smoke, headers={'Origin': 'https://other.example'})
    assert remote.json()['error']['code'] == 'SANDBOX_UNAVAILABLE'
    smoke['python_trusted_confirmed'] = False
    missing = client.post(f'/api/v1/backtests/strategy-revisions/{revision}/smoke', json=smoke, headers={'Origin': 'http://127.0.0.1:15173'})
    assert missing.json()['error']['code'] == 'TRUSTED_LOCAL_UNCONFIRMED'
    smoke['python_trusted_confirmed'] = True
    passed = client.post(f'/api/v1/backtests/strategy-revisions/{revision}/smoke', json=smoke, headers={'Origin': 'http://127.0.0.1:15173'})
    assert passed.status_code == 200, passed.text


def test_editor_infinite_loop_is_terminated(tmp_path, monkeypatch):
    from app.backtest.strategy.protocol import ObservationFrame, StrategyProviderError
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "0")
    service = service_at(tmp_path)
    source = SOURCE.replace("        self.warmup(observation)\n", "        while True:\n            pass\n")
    revision = compile_editor(service, source)
    provider = service.build_python_host_provider(revision["revision_id"], mode="TRUSTED_LOCAL", trusted_confirmed=True)
    provider.prepare({"run_id": "timeout", "parameters": {}})
    provider.runner.step_timeout_s = 0.05
    frame = ObservationFrame(run_id="timeout", sequence=1, event_time_ms=60000, watermark_ms=60000,
                             phase="RUNNING", market={"symbol": "BTCUSDT"}, input_hash="sha256:timeout",
                             bar={"open": "100", "high": "101", "low": "99", "close": "100", "volume": "100"})
    with pytest.raises(StrategyProviderError, match="PROVIDER_TIMEOUT"):
        provider.step(frame)
    provider.abort()
    assert provider.runner._process is None
