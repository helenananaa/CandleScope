from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.manual_history import router
from app.replay import manual_history_import as bridge
from app.replay.catalog import ReplayCatalog
from app.replay.history_archive import ReplayHistoryRepository
from tests.fixtures.replay.fakes import make_bar

START = 1_710_000_000_000


def setup_job(tmp_path, monkeypatch, count=2000):
    collection = NS(exchange='binance', market_type='spot')
    target = NS(symbol='BTCUSDT', canonical_interval='1m', state='READY',
                sealed_end_open_ms=START+(count-1)*60_000)
    coverage = NS(symbol='BTCUSDT', canonical_interval='1m', status='READY', effective_start_ms=START)
    job = NS(state='SUCCEEDED', collection_id='collection')
    repo = NS(get_job=lambda _: job, get_collection=lambda _: collection,
              list_job_targets=lambda _: [target], list_collection_targets=lambda _: [coverage])
    service = NS(settings=NS(replay_history_origin_uri=None, replay_history_archive_dir=tmp_path/'archive'))
    rows = [make_bar(START+i*60_000) for i in range(count)]
    calls = []
    def query(symbol, interval, **kwargs):
        calls.append((symbol, interval, kwargs))
        return list(rows)
    monkeypatch.setattr(bridge, 'query_klines', query)
    return repo, service, rows, calls, job, target, coverage


def test_completed_download_becomes_eligible_without_live_db_reader(tmp_path, monkeypatch):
    pytest.importorskip('pyarrow')
    repo, service, rows, calls, *_ = setup_job(tmp_path, monkeypatch)
    reader = ReplayHistoryRepository(service.settings.replay_history_archive_dir)
    catalog = ReplayCatalog(reader, native_intervals=lambda _: ('1m',), now_ms=lambda: START+3000*60_000)
    assert not catalog.build(warmup_bars=200, horizon_ms=86_400_000).entries
    result = bridge.import_completed_download(repo, service, 'job:test')
    assert result['rows'] == 2000
    assert calls[0][2]['end_ms'] == START+1999*60_000
    snapshot = catalog.build(warmup_bars=200, horizon_ms=86_400_000)
    assert snapshot.entries[0].eligible_window_count > 0
    revision = result['imported'][0]['source_revision']
    again = bridge.import_completed_download(repo, service, 'job:test')
    assert again['imported'][0]['source_revision'] == revision
    assert reader.get_bounds('BTCUSDT','1m',exchange='binance',market_type='spot')['total_count'] == 2000
    rows[0]['close'] = 123.0
    pinned = reader.query_bars_at_revision(revision, 'BTCUSDT', '1m', start_ms=START, end_ms=START,
                                             exchange='binance', market_type='spot')
    assert float(pinned[0]['close']) == 100.5


@pytest.mark.parametrize('mutation,reason', [
    ('running','download_not_succeeded'), ('no1m','one_minute_download_required'),
    ('released','download_coverage_unavailable'), ('gap','download_coverage_changed'),
    ('duplicate','download_coverage_changed'), ('badclose','download_coverage_changed'),
    ('rowlimit','replay_import_row_limit'), ('remote','remote_archive_read_only'),
    ('dependency','parquet_dependency_missing'),
])
def test_rejects_invalid_sources_without_publishing(tmp_path, monkeypatch, mutation, reason):
    repo, service, rows, calls, job, target, coverage = setup_job(tmp_path, monkeypatch)
    if mutation == 'running': job.state = 'RUNNING'
    if mutation == 'no1m': target.canonical_interval = '15m'
    if mutation == 'released': coverage.status = 'RELEASED'
    if mutation == 'gap': rows.pop(12)
    if mutation == 'duplicate': rows[12] = rows[11]
    if mutation == 'badclose': rows[12]['close_time'] += 1
    if mutation == 'rowlimit': monkeypatch.setattr(bridge, 'MAX_IMPORT_ROWS', 20)
    if mutation == 'remote': service.settings.replay_history_origin_uri = 'https://archive.invalid'
    if mutation == 'dependency': monkeypatch.setattr(bridge, 'find_spec', lambda _: None)
    with pytest.raises(bridge.ManualReplayImportError, match=reason):
        bridge.import_completed_download(repo, service, 'job:test')
    assert not service.settings.replay_history_archive_dir.exists()
    if mutation in ('rowlimit', 'remote', 'dependency'): assert not calls


def test_concurrent_import_fails_without_reading(tmp_path, monkeypatch):
    repo, service, _, calls, *_ = setup_job(tmp_path, monkeypatch)
    bridge._IMPORT_LOCK.acquire()
    try:
        with pytest.raises(bridge.ManualReplayImportError, match='replay_import_busy'):
            bridge.import_completed_download(repo, service, 'job:test')
    finally:
        bridge._IMPORT_LOCK.release()
    assert not calls


def test_endpoint_flag_gate_and_capabilities(tmp_path, monkeypatch):
    repo, service, *_ = setup_job(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(router)
    app.state.replay_service = service
    app.state.data_engine_runtime = NS(manual_history_service=NS(repository=repo))
    client = TestClient(app)
    monkeypatch.setattr('app.api.v1.manual_history.MANUAL_HISTORY_DOWNLOAD_ENABLED', False)
    assert client.post('/settings/storage/manual-downloads/job:test/replay-archive').status_code == 403
    monkeypatch.setattr('app.api.v1.manual_history.MANUAL_HISTORY_DOWNLOAD_ENABLED', True)
    service.settings.replay_history_origin_uri = 'https://archive.invalid'
    cap = client.get('/settings/storage/manual-downloads/capabilities').json()['replay_import']
    assert cap['enabled'] is False
    assert cap['reason'] == 'remote_archive_read_only'
    response = client.post('/settings/storage/manual-downloads/job:test/replay-archive')
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'remote_archive_read_only'
