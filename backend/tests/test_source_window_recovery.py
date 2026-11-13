"""Bounded source receipts only; full cold recovery is a separate consumer gate."""
from dataclasses import replace,FrozenInstanceError
import json

import pytest

from app.data_engine.aggregation.blocks import BlockUnavailable,BlockRevisionChanged
from app.data_engine.aggregation.source_window import SourceWindowVersion,MAX_SOURCE_DATA_BYTES
from app.data_engine.ingestion.models import MarketEvent,StreamType,DataSource,StreamDescriptor
from app.data_engine.storage import klines_repo,kline_sources,source_retention

W=60000
DESC=StreamDescriptor('BTCUSDT',StreamType.KLINE,interval='1m',market_type='futures')
KEY=kline_sources.series(DESC)


@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(klines_repo,'KLINES_DB_PATH',tmp_path/'source.sqlite')
    klines_repo.init_klines_storage()


def record(index,*,quote=2.,closed=True,sequence=None,conn=None):
    opened=index*W
    seq=opened+W+1 if sequence is None else sequence
    envelope=dict(open='10',high='20',low='5',close='11',volume='1',quoteVolume=str(quote),
        trades=1,takerBuyBaseVolume='0.5',takerBuyQuoteVolume='1',closeTime=opened+W-1,eventTime=seq)
    data=dict(interval='1m',open_time=opened,close_time=opened+W-1,is_closed=closed,
        open=10.,high=20.,low=5.,close=11.,volume=1.,quote_volume=quote,trades=1,
        taker_buy_base=.5,taker_buy_quote=1.,source_candle=envelope)
    event=MarketEvent(event_type=StreamType.KLINE,symbol='BTCUSDT',event_time_ms=seq,received_at_ms=seq+1,source=DataSource.WEBSOCKET,
        exchange='binance',market_type='futures',data=data)
    return kline_sources.record(event,DESC,_connection=conn)


def test_large_source_only_window_reads_finite_immutable_pages_and_no_canonical_rows(database,monkeypatch):
    with klines_repo._connect() as conn:
        kline_sources._schema(conn)
        conn.execute('BEGIN IMMEDIATE')
        for i in range(257): record(i,conn=conn)
        conn.commit()
    version=kline_sources.capture_source_window(KEY,0,257*W,W)
    assert version.closed_count==version.revision_sum==257
    statements=[]
    connect=klines_repo._connect
    def traced():
        conn=connect();conn.set_trace_callback(statements.append);return conn
    monkeypatch.setattr(klines_repo,'_connect',traced)
    pages=[];position=0
    while position is not None:
        page=kline_sources.read_source_window_page(version,position)
        pages.append(page)
        position=page.next_position_ms
    assert [len(p.components) for p in pages]==[128,128,1]
    assert [x['data']['open_time'] for p in pages for x in p.components]==list(range(0,257*W,W))
    with pytest.raises(TypeError): pages[0].components[0]['data']['volume']=999
    with pytest.raises(FrozenInstanceError): version.revision_sum=999
    selects=[s for s in statements if 'o.data_json' in s]
    assert len(selects)==3 and all('LIMIT 128' in s for s in selects)
    assert not klines_repo.query_klines('BTCUSDT','1m',market_type='futures')


def test_partial_source_window_keeps_gap_and_excludes_future_forming_tail(database):
    record(0);record(1,closed=False);record(2);record(3,closed=False)
    version=kline_sources.capture_source_window(KEY,0,7*W,W)
    assert version.through_ms==3*W and version.closed_count==version.revision_sum==2
    page=kline_sources.read_source_window_page(version,max_rows=1)
    assert [x['data']['open_time'] for x in page.components]==[0]
    assert page.next_position_ms==W
    page=kline_sources.read_source_window_page(version,page.next_position_ms,max_rows=1)
    assert [x['data']['open_time'] for x in page.components]==[2*W] and page.next_position_ms is None
    # Former gap becomes confirmed, so old source content proof is stale.
    record(1,closed=True,sequence=9*W)
    with pytest.raises(BlockRevisionChanged):kline_sources.read_source_window_page(version)


def test_stale_duplicate_identical_and_unrelated_activity_do_not_invalidate_content(database):
    first=record(0);record(1)
    version=kline_sources.capture_source_window(KEY,0,2*W,W)
    record(0,sequence=4*W)  # Identical values, newer selected observation.
    record(0,quote=999,sequence=1)  # Audited, but not selected.
    record(9)
    with klines_repo._connect() as conn:assert kline_sources.source_window_current(conn,version)
    assert kline_sources.rest_watermark()>version.revision_sum
    assert kline_sources.read_source_window_page(version).version==version
    kline_sources.acknowledge(first['ref'])
    source_retention.compact(retention_days=1,now_ms=3*86400000)
    with klines_repo._connect() as conn:assert kline_sources.source_window_current(conn,version)


def test_opposite_corrections_change_proof_even_when_total_is_equal(database):
    record(0);record(1)
    version=kline_sources.capture_source_window(KEY,0,2*W,W)
    record(0,quote=1.,sequence=4*W);record(1,quote=3.,sequence=4*W)
    new=kline_sources.capture_source_window(KEY,0,2*W,W)
    assert new.closed_count==version.closed_count and new.revision_sum==version.revision_sum+2
    with pytest.raises(BlockRevisionChanged):kline_sources.read_source_window_page(version)
    assert sum(x['data']['quote_volume'] for x in kline_sources.read_source_window_page(new).components)==4


def test_source_transaction_rollback_does_not_expire_committed_receipt(database):
    record(0)
    version=kline_sources.capture_source_window(KEY,0,W,W)
    with klines_repo._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        record(0,quote=1.,sequence=4*W,conn=conn)
        assert not kline_sources.source_window_current(conn,version)
        conn.rollback()
        assert kline_sources.source_window_current(conn,version)
    assert kline_sources.read_source_window_page(version).components[0]['data']['quote_volume']==2


def test_change_after_page_read_is_rejected_before_return(database,monkeypatch):
    record(0);record(1)
    version=kline_sources.capture_source_window(KEY,0,2*W,W)
    current=kline_sources.source_window_current
    calls=[]
    def check(conn,proof):
        calls.append(1)
        if len(calls)==2:record(0,quote=1.,sequence=4*W)
        return current(conn,proof)
    monkeypatch.setattr(kline_sources,'source_window_current',check)
    with pytest.raises(BlockRevisionChanged):kline_sources.read_source_window_page(version)
    assert len(calls)==2


@pytest.mark.parametrize('variant',['oversize','malformed','off-grid','unclosed-json','close-time'])
def test_unusable_selected_json_never_becomes_a_successful_page(database,variant):
    record(0)
    version=kline_sources.capture_source_window(KEY,0,W,W)
    with klines_repo._connect() as conn:
        row=conn.execute('SELECT data_json FROM kline_source_observations WHERE id=1').fetchone()
        data=json.loads(row[0])
        if variant=='oversize':data['extra']='x'*MAX_SOURCE_DATA_BYTES
        elif variant=='off-grid':data['open_time']=1
        elif variant=='unclosed-json':data['is_closed']=False
        elif variant=='close-time':data['close_time']+=1
        payload='{' if variant=='malformed' else json.dumps(data)
        conn.execute('UPDATE kline_source_observations SET data_json=? WHERE id=1',(payload,));conn.commit()
    with pytest.raises(BlockUnavailable):kline_sources.read_source_window_page(version)


@pytest.mark.parametrize('max_rows',[0,129,True,-1])
def test_page_limit_is_enforced_before_read(database,max_rows):
    record(0)
    version=kline_sources.capture_source_window(KEY,0,W,W)
    with pytest.raises(ValueError):kline_sources.read_source_window_page(version,max_rows=max_rows)


@pytest.mark.parametrize('args',[
    (KEY,0,65537*W,W),('x'*1025,0,W,W),('[]',0,W,W),(KEY,1,W,W),(KEY,0,W,1000),
    (KEY,0,True,W),(KEY,0,W,True),
])
def test_invalid_or_unbounded_window_is_rejected(database,args):
    with pytest.raises(ValueError):kline_sources.capture_source_window(*args)


def test_empty_window_does_not_manufacture_zero_data(database):
    record(1,closed=False)
    with pytest.raises(BlockUnavailable):kline_sources.capture_source_window(KEY,0,2*W,W)


def test_missing_source_journal_is_unavailable_without_creating_schema(database):
    with pytest.raises(BlockUnavailable):kline_sources.capture_source_window(KEY,0,W,W)
    with klines_repo._connect() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='kline_source_heads'").fetchone() is None


def incoming(index, *, quote=2., closed=True, ref=None):
    from app.data_engine.bar_aggregator.models import BarInput, BarInputSource, MergeMode
    from app.data_engine.market_data.kline_metrics import declared_enhanced_fields
    values=dict(open=10., high=20., low=5., close=11., volume=1., quote_volume=quote,
                trades=1, taker_buy_base=.5, taker_buy_quote=1.)
    return BarInput(symbol='BTCUSDT', exchange='binance', market_type='futures',
        source_interval='1m', source=BarInputSource.CORRECTION, merge_mode=MergeMode.COMPONENT,
        open_time_ms=index*W, close_time_ms=(index+1)*W-1, is_closed=closed,
        enhanced_fields=declared_enhanced_fields('binance','futures',values),
        extra={'source_ref':ref or dict(series=KEY,open_time=index*W,revision=1)}, **values)


def fold(count, index=0, *, cancel=None, source=None):
    from threading import Event
    from app.data_engine.storage.source_window_summary import fold_source_window
    return fold_source_window(KEY,0,count*W,W,source or incoming(index),cancel or Event())


def test_folding_large_source_only_window_keeps_summary_and_one_leaf(database):
    from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
    with klines_repo._connect() as conn:
        kline_sources._schema(conn); conn.execute('BEGIN IMMEDIATE')
        for i in range(2048): record(i,conn=conn)
        conn.commit()
    summary=fold(2048)
    assert len(summary.parts)==1 and summary.pages==16
    assert summary.estimated_bytes<32768
    assert not summary.covers(0) and summary.covers(W) and summary.covers(2047*W)
    result=summary.merge([ComponentSnapshotOHLCVMerge._snapshot_from_input(incoming(0))])
    assert result.count==2048 and result.values.quote_volume==4096
    assert result.coverage(0,2048*W).closed
    assert not klines_repo.query_klines('BTCUSDT','1m',market_type='futures')


def test_sparse_closed_runs_merge_interior_forming_hole_in_time_order(database):
    from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
    record(0); record(1,closed=False); record(2); record(3)
    summary=fold(4,index=3)
    assert [part.first for part in summary.parts]==[0,2*W]
    hole=replace(incoming(1,closed=False),close=19.)
    latest=replace(incoming(3),close=12.)
    rows=[ComponentSnapshotOHLCVMerge._snapshot_from_input(v) for v in (hole,latest)]
    result=summary.merge(rows)
    assert result.values.open==10. and result.values.close==12.
    assert result.count==4 and result.values.volume==4
    assert not result.coverage(0,4*W).closed
    assert not summary.covers(W)
    with pytest.raises(ValueError):summary.merge([ComponentSnapshotOHLCVMerge._snapshot_from_input(incoming(2))])


def test_folding_rejects_correction_after_final_page_and_cancel(database,monkeypatch):
    from threading import Event
    record(0);record(1)
    read=kline_sources.read_source_window_page
    def changed(*a,**kw):
        page=read(*a,**kw)
        record(1,quote=1.,sequence=4*W)
        return page
    monkeypatch.setattr(kline_sources,'read_source_window_page',changed)
    with pytest.raises(BlockRevisionChanged):fold(2)
    cancel=Event();cancel.set()
    with pytest.raises(BlockUnavailable,match='cancelled'):fold(2,cancel=cancel)


def test_excessive_source_fragmentation_has_explicit_bounded_failure(database):
    from app.data_engine.memory_budget import MemoryBudgetExceeded
    for i in range(0,70,2):record(i)
    with pytest.raises(MemoryBudgetExceeded,match='fragmented'):fold(70)


def test_source_summary_rejects_stale_incoming_ref_or_mismatched_value(database):
    record(0);record(1)
    with pytest.raises(BlockRevisionChanged):fold(2,source=incoming(0,ref=dict(series=KEY,open_time=0,revision=9)))
    with pytest.raises(BlockUnavailable):fold(2,source=incoming(0,quote=999))
