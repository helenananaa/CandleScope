"""History retry reads original full receipts; deletions never renew them."""
from dataclasses import replace
from contextlib import closing

from app.data_engine.ingestion.models import DataSource,RawMessage,StreamType
from app.data_engine.storage import kline_sources,klines_repo
from app.data_engine.storage.revisions import mark_deleted,series_values,ensure_acquisition,current_revision
from app.data_engine.series_identity import KlineSeriesIdentity
from app.exchanges.ccxt_ext.fork_kline import normalize_fork_kline
from tests.test_source_revision_pipeline import database,message,DESC,OPENED
from tests.test_ccxt_fork_kline import fork_exchange,MARKET


def record_rest(opened=OPENED):
    row=[opened,'100.000000000000001','103','99','102','10',opened+59999,'1010',4,'6','606','0']
    raw=RawMessage(fork_exchange().parse_candlescope_kline(row,MARKET,'1m'),
        DataSource.HTTP_BACKFILL,StreamType.KLINE,opened+60001)
    event=normalize_fork_kline(raw,DESC)
    watermark=kline_sources.rest_watermark()
    with closing(klines_repo._connect()) as conn:
        permission=current_revision(conn)
    with ensure_acquisition(permission):
        receipt=kline_sources.record(event,DESC,rest_watermark=watermark)
    return raw,receipt


def test_complete_page_recovers_exact_fields_and_current_receipts(database):
    first,receipt=record_rest()
    record_rest(OPENED+60000)
    recovered=kline_sources.history_projection_inputs(DESC,OPENED,OPENED+60000,60000)
    assert len(recovered)==2
    assert {k:v for k,v in recovered[0].payload.items() if k!='_source_receipt'}==first.payload
    assert recovered[0].payload['_source_receipt']==receipt
    assert recovered[0].source is DataSource.HTTP_BACKFILL
    assert kline_sources.history_projection_inputs(DESC,OPENED,OPENED+120000,60000) is None
    other=replace(DESC,series_identity=KlineSeriesIdentity.for_exchange('binance',provider_id='other'))
    assert kline_sources.history_projection_inputs(other,OPENED,OPENED,60000) is None


def test_source_deletion_denies_old_receipt_until_a_new_physical_acquisition(database):
    record_rest()
    assert kline_sources.history_projection_inputs(DESC,OPENED,OPENED,60000)
    # Empty canonical deletion is still a permission barrier for old raw pages.
    with closing(klines_repo._connect()) as conn,conn:
        mark_deleted(conn,series_values('BTCUSDT','1m','binance','futures'),OPENED,OPENED)
    assert kline_sources.history_projection_inputs(DESC,OPENED,OPENED,60000) is None
    record_rest()
    assert kline_sources.history_projection_inputs(DESC,OPENED,OPENED,60000)


def test_live_websocket_selection_is_not_relabelled_as_rest_history(database):
    raw=message()
    kline_sources.record(normalize_fork_kline(raw,DESC),DESC)
    assert kline_sources.history_projection_inputs(DESC,OPENED,OPENED,60000) is None


def test_concurrent_first_rest_pages_migrate_original_raw_journal_once(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.data_engine.storage import market_sources
    with closing(klines_repo._connect()) as conn,conn:
        conn.execute('''CREATE TABLE market_source_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,stream_key TEXT NOT NULL,
            transport TEXT NOT NULL,received_at INTEGER NOT NULL,endpoint TEXT NOT NULL,
            payload_json TEXT NOT NULL,sha256 TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0)''')
    start=Barrier(8)
    def record(index):
        start.wait(timeout=5)
        market_sources.record_rest(DESC,[dict(received_at=OPENED+index,endpoint='loopback',payload=[index])])
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(record,range(8)))
    assert len(market_sources.observations(DESC))==8
