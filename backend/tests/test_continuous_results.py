"""Committed bounded views against actual account results and WAL interleavings."""
from copy import deepcopy
from decimal import Decimal
import json
import sqlite3
import subprocess
import sys

import pytest

from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.continuous_results import KINDS, MAX_PAGE_BYTES, HEAD_OVERHEAD_BYTES
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json
from tests.test_continuous_strategy_store import create,resume,commit,checkpoint
from tests.test_strategy_bar_continuation import make_kernel,events,strategy
from tests.test_kline_revision_contract import storage as storage
from tests.test_continuous_guarded_source import setup_host,acquire,apply,cleanup


def projection(store,kind):
    first=store.results.read('cs_test',kind=kind,limit=2)
    values=[row['value'] for row in first['items']]
    while first['more']:
        first=store.results.read('cs_test',kind=kind,limit=2,after=first['next_cursor'],expected=first['identity'])
        values.extend(row['value'] for row in first['items'])
    return values


def assert_current(store):
    state=store.load('cs_test')['checkpoint']['engine']
    head=store.results.read('cs_test')
    account={key:value for key,value in state['account'].items() if key!='journal'}
    assert head['summary']['account']==account
    assert head['summary']['fee_total']==state['fee_total']
    assert head['summary']['latest_equity']==(state['equity_curve'][-1] if state['equity_curve'] else None)
    for kind in KINDS:
        expected=state['account']['journal'] if kind=='ledger' else state.get(kind,[])
        assert projection(store,kind)==expected,kind
        assert head['counts'][kind]==len(expected),kind
    stored=store.db.execute("SELECT * FROM result_heads WHERE run_id='cs_test'").fetchone()
    size=store.db.execute("SELECT COALESCE(SUM(stored_bytes),0) FROM result_items WHERE run_id='cs_test'").fetchone()[0]
    assert stored['stored_bytes']==size+len(stored['head_json'].encode())+len(stored['counts_json'].encode())+HEAD_OVERHEAD_BYTES


@pytest.mark.parametrize('daily',[False,True])
@pytest.mark.parametrize('sparse',[False,True])
def test_paged_results_and_coalesced_updates_equal_committed_engine_across_restore(tmp_path,daily,sparse):
    store=ContinuousStrategyStore(tmp_path/'results.db');kernel=make_kernel(sparse=sparse);calls=[]
    if daily:kernel.equity_curve_mode='UTC_DAILY_CLOSE_V1'
    row=resume(store,create(store,kernel));client={kind:{} for kind in KINDS};since=0
    try:
        for start,end in [(0,1),(1,3),(3,10),(10,20),(20,25)]:
            kernel.advance(events()[start:end],strategy(calls));row=commit(store,row,kernel,calls)
            page=store.results.read('cs_test',since_revision=since,limit=2)
            identity=page['identity']
            while True:
                for item in page['items']:client[item['kind']][item['index']]=item['value']
                if not page['more']:break
                page=store.results.read('cs_test',since_revision=since,limit=2,change_cursor=page['next_cursor'],expected=identity)
            for kind in KINDS:
                assert [value for _,value in sorted(client[kind].items())]==projection(store,kind),kind
            assert_current(store)
            since=row['checkpoint_revision']
        assert any(order['status']=='OPEN' for order in projection(store,'orders'))
        assert projection(store,'fills') and projection(store,'ledger')
        assert len(projection(store,'equity_curve'))==(1 if daily else 1 if sparse else 25)
        before=store.results.read('cs_test',since_revision=since)
        assert before['items']==[]
        saved=store.load('cs_test');store.close();store=ContinuousStrategyStore(tmp_path/'results.db')
        assert store.load('cs_test')==saved and store.results.read('cs_test',since_revision=since)==before
        # Phase/generation can advance without changing the financial checkpoint.
        row=store.stop('cs_test',generation=row['generation'],revision=row['revision'])
        row=resume(store,row)
        current=store.results.read('cs_test')
        assert current['identity']['checkpoint_revision']==since and current['identity']['generation']>identity['generation']
        with pytest.raises(BacktestError,match='identity changed'):
            store.results.read('cs_test',kind='orders',expected=identity)
        assert_current(store)
    finally:store.close()


def test_reader_never_selects_checkpoint_provider_or_source_definition(tmp_path,monkeypatch):
    store=ContinuousStrategyStore(tmp_path/'reads.db');kernel=make_kernel();calls=[]
    row=resume(store,create(store,kernel));kernel.advance(events(),strategy(calls));commit(store,row,kernel,calls)
    def forbidden(*args,**kwargs):raise AssertionError('Bounded views cannot decode recovery state')
    monkeypatch.setattr(store,'load',forbidden)
    def authorize(action,table,column,*_):
        if action==sqlite3.SQLITE_READ and (table=='checkpoints' or (table=='runs' and column=='definition_json')):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    store.db.set_authorizer(authorize)
    try:
        assert store.results.read('cs_test')['summary']['account']
        for kind in KINDS:projection(store,kind)
        assert store.results.read('cs_test',since_revision=0)['items']
    finally:store.db.set_authorizer(None);store.close()


@pytest.mark.parametrize('model,short',[
    ('SPOT_CASH_V1',False),('LINEAR_PERP_ONE_WAY_V1',False),('LINEAR_PERP_ONE_WAY_V1',True),
])
def test_current_valuation_matches_actual_account_and_does_not_use_sparse_equity_tail(tmp_path,model,short):
    from app.simulation.kernel import SimulationKernel
    from app.simulation.execution_realism import EXECUTION_REALISM_V2, BAR_PATH_SCENARIO
    kernel=SimulationKernel(account_model=model,execution_model_revision=EXECUTION_REALISM_V2,
        bar_path_scenario=BAR_PATH_SCENARIO,participation_rate=Decimal('0.1'),equity_curve_event_interval=100,
        taker_fee_bps=Decimal('3'),maker_fee_bps=Decimal('1'))
    calls=[]
    observe=strategy(calls)
    def step(visible,event):
        values=observe(visible,event)
        if short:
            for value in values:value['side']='SELL' if value['side']=='BUY' else 'BUY'
        return values
    store=ContinuousStrategyStore(tmp_path/'valuation.db');row=resume(store,create(store,kernel))
    try:
        initial=store.results.read('cs_test')
        assert Decimal(initial['summary']['valuation']['equity'])==kernel.account.equity()
        kernel.advance(events(),step);commit(store,row,kernel,calls)
        head=store.results.read('cs_test')['summary']
        assert Decimal(head['valuation']['equity'])==kernel.account.equity()
        assert Decimal(head['valuation']['unrealized_pnl'])==kernel.account.unrealized()
        assert head['valuation']['account_model']==model
        assert head['latest_equity']['sequence']==1
        assert Decimal(head['latest_equity']['equity'])!=kernel.account.equity()
        assert str(kernel.account.position_qty).startswith('-')==short
    finally:store.close()


def test_one_read_snapshot_survives_concurrent_financial_writer_then_rejects_old_page(tmp_path):
    path=tmp_path/'race.db';one=ContinuousStrategyStore(path);two=ContinuousStrategyStore(path)
    kernel=make_kernel();calls=[];row=resume(one,create(one,kernel))
    kernel.advance(events()[:10],strategy(calls));row=commit(one,row,kernel,calls)
    old=one.results.read('cs_test',kind='fills',limit=1);before=one.load('cs_test')
    kernel.advance(events()[10:],strategy(calls));written=[]
    def interleave(sql):
        if sql.startswith('SELECT * FROM result_heads') and not written:
            written.append(commit(two,row,kernel,calls))
    one.db.set_trace_callback(interleave)
    try:
        snapshot=one.results.read('cs_test',kind='fills',limit=1,expected=old['identity'])
        assert written and written[0]['sequence']==25
        assert snapshot==old
        assert snapshot['summary']['account']=={key:value for key,value in before['checkpoint']['engine']['account'].items() if key!='journal'}
        with pytest.raises(BacktestError,match='identity changed'):
            one.results.read('cs_test',kind='fills',after=old['next_cursor'],limit=1,expected=old['identity'])
    finally:one.db.set_trace_callback(None);one.close();two.close()


def test_projection_failure_rolls_back_checkpoint_and_source_ack_then_retry_has_no_duplicate_fills(storage,tmp_path,monkeypatch):
    service,_row,_definition,factory,store,manager,host=setup_host(storage,tmp_path,monkeypatch)
    try:
        proof,values=acquire(manager,host,10);apply(manager,host,proof,values)
        before=store.load('cs_guarded');view=store.results.read('cs_guarded')
        ack=manager.bars.prefixes.inspect(proof.owner)['committed_acquisition']
        store.db.execute("CREATE TRIGGER fail_projection BEFORE UPDATE ON result_heads BEGIN SELECT RAISE(ABORT,'result-write-failure'); END")
        proof,values=acquire(manager,host,25)
        with pytest.raises(sqlite3.IntegrityError,match='result-write-failure'):apply(manager,host,proof,values)
        assert store.load('cs_guarded')['checkpoint']==before['checkpoint']
        after=store.results.read('cs_guarded')
        assert after['counts']==view['counts'] and after['summary']==view['summary']
        assert manager.bars.prefixes.inspect(proof.owner)['committed_acquisition']==ack
        store.db.execute('DROP TRIGGER fail_projection')
        from app.backtest.continuous_bar_host import ContinuousBarHost
        host=ContinuousBarHost.resume(store,'cs_guarded',factory,retry_failed=True)
        proof,values=acquire(manager,host,25);apply(manager,host,proof,values)
        actual=store.results.read('cs_guarded',kind='fills')
        expected=store.load('cs_guarded')['checkpoint']['engine']['fills']
        assert [item['value'] for item in actual['items']]==expected
    finally:cleanup(service,store,host)


def test_preparation_indexes_only_new_tails_active_orders_and_equity_last_point(tmp_path):
    store=ContinuousStrategyStore(tmp_path/'work.db');kernel=make_kernel();calls=[]
    row=resume(store,create(store,kernel));kernel.advance(events()[:20],strategy(calls));row=commit(store,row,kernel,calls)
    old=store.results.read('cs_test');old_counts=old['counts']
    active={row[0] for row in store.db.execute("SELECT item_index FROM result_items WHERE kind='orders' AND active=1")}
    kernel.advance(events()[20:],strategy(calls));state=kernel.snapshot();reads=[]
    class Guarded(list):
        def __init__(self,kind,values):super().__init__(values);self.kind=kind
        def __iter__(self):raise AssertionError('Projection cannot iterate indexed history')
        def __getitem__(self,index):
            assert type(index) is int
            resolved=index if index>=0 else len(self)+index
            allowed=resolved>=old_counts[self.kind] or (self.kind=='orders' and resolved in active) or (
                self.kind=='equity_curve' and resolved>=old_counts[self.kind]-1)
            assert allowed,(self.kind,index)
            reads.append((self.kind,resolved));return super().__getitem__(index)
    for kind in KINDS:
        if kind=='ledger':state['account']['journal']=Guarded(kind,state['account']['journal'])
        else:state[kind]=Guarded(kind,state.get(kind,[]))
    try:
        queries=[];store.db.set_trace_callback(queries.append)
        patch=store.results.prepare('cs_test',state)
        store.db.set_trace_callback(None)
        assert patch.items and len(reads)<100
        query=next(sql for sql in queries if "kind='orders' AND active=1" in sql)
        plan=[item[3] for item in store.db.execute('EXPLAIN QUERY PLAN '+query)]
        assert any('idx_result_active_orders' in item for item in plan),plan
    finally:store.close()


def legacy_store(tmp_path):
    path=tmp_path/'legacy.db';store=ContinuousStrategyStore(path);kernel=make_kernel();calls=[]
    row=resume(store,create(store,kernel));kernel.advance(events()[:10],strategy(calls));commit(store,row,kernel,calls)
    saved=store.load('cs_test')
    store.db.execute('DROP TABLE result_items');store.db.execute('DROP TABLE result_heads')
    store.db.execute('PRAGMA user_version=2');store.close()
    return path,saved


@pytest.mark.parametrize('tight_budget',[False,True])
def test_schema2_upgrade_preserves_financial_state_and_indexes_only_on_explicit_request(tmp_path,tight_budget):
    path,saved=legacy_store(tmp_path)
    store=ContinuousStrategyStore(path,**({'max_total_checkpoint_bytes':1} if tight_budget else {}))
    try:
        assert store.load('cs_test')==saved
        assert store.db.execute('PRAGMA user_version').fetchone()[0]==3
        assert store.db.execute('SELECT count(*) FROM result_heads').fetchone()[0]==0
        with pytest.raises(BacktestError,match='Prepare the committed'):store.results.read('cs_test')
        if tight_budget:
            with pytest.raises(BacktestError,match='total disk budget'):store.results.ensure('cs_test')
            assert store.db.execute('SELECT count(*) FROM result_heads').fetchone()[0]==0
            assert store.db.execute('SELECT count(*) FROM result_items').fetchone()[0]==0
        else:
            store.results.ensure('cs_test');assert_current(store)
            before=store.db.total_changes;store.results.ensure('cs_test')
            assert store.db.total_changes==before
        assert store.load('cs_test')==saved
    finally:store.close()


def test_byte_limited_pages_and_oversize_item_fail_without_partial_financial_publication(tmp_path):
    store=ContinuousStrategyStore(tmp_path/'bytes.db');kernel=make_kernel();calls=[]
    row=resume(store,create(store,kernel));kernel.advance(events()[:1],strategy(calls))
    state=checkpoint(kernel,calls)
    state['engine']['rejected']=[{'reason':'large','payload':'中'*30_000} for _ in range(8)]
    row=store.commit('cs_test',generation=row['generation'],revision=row['revision'],sequence=1,event_time_ms=60_000,
        data_revision='r1',checkpoint=state,phase='LIVE')
    try:
        page=store.results.read('cs_test',kind='rejected',limit=200)
        assert page['more'] and 1<=len(page['items'])<8
        assert len(encode_response(page))<=MAX_PAGE_BYTES
        assert len(projection(store,'rejected'))==8
        before=store.load('cs_test');view=store.results.read('cs_test',since_revision=0)
        bad=deepcopy(state);bad['engine']['rejected'].append({'payload':'x'*(256*1024)})
        with pytest.raises(BacktestError,match='payload exceeds'):
            store.commit('cs_test',generation=row['generation'],revision=row['revision'],sequence=2,event_time_ms=120_000,
                data_revision='r1',checkpoint=bad,phase='LIVE')
        assert store.load('cs_test')==before and store.results.read('cs_test',since_revision=0)==view
    finally:store.close()


def test_new_process_reads_persisted_index_without_recovery_state(tmp_path):
    path=tmp_path/'process.db';store=ContinuousStrategyStore(path);kernel=make_kernel();calls=[]
    row=resume(store,create(store,kernel));kernel.advance(events(),strategy(calls));commit(store,row,kernel,calls)
    expected=store.results.read('cs_test',kind='fills');store.close()
    code="""
import json,sqlite3,sys
from pathlib import Path
from app.backtest.continuous_store import ContinuousStrategyStore
store=ContinuousStrategyStore(Path(sys.argv[1]))
def authorize(action,table,column,*args):
    return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and table=='checkpoints' else sqlite3.SQLITE_OK
store.db.set_authorizer(authorize)
try:print(json.dumps(store.results.read('cs_test',kind='fills')))
finally:store.close()
"""
    result=subprocess.run([sys.executable,'-B','-c',code,str(path)],text=True,capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==expected


def test_legacy_index_preparation_cannot_replace_concurrent_new_financial_results(tmp_path,monkeypatch):
    path,saved=legacy_store(tmp_path);one=ContinuousStrategyStore(path);two=ContinuousStrategyStore(path)
    original=one.results.prepare
    def interleave(*args,**kwargs):
        patch=original(*args,**kwargs)
        kernel=make_kernel();kernel.restore(saved['checkpoint']['engine'])
        calls=list(saved['checkpoint']['provider']['seen'])
        kernel.advance(events()[10:],strategy(calls));commit(two,two.summary('cs_test'),kernel,calls)
        return patch
    monkeypatch.setattr(one.results,'prepare',interleave)
    try:
        with pytest.raises(BacktestError,match='advanced during legacy'):one.results.ensure('cs_test')
        assert one.results.read('cs_test')['run']['sequence']==25
        assert_current(one)
    finally:one.close();two.close()


def test_result_encoding_completes_before_source_fence(storage,tmp_path,monkeypatch):
    service,_row,_definition,_factory,store,manager,host=setup_host(storage,tmp_path,monkeypatch)
    from app.backtest import continuous_results as module
    original=module.encode;inside=[False];encoded=[]
    def guarded_encode(*args,**kwargs):
        assert not inside[0],'Projection encoding cannot hold the canonical source write fence'
        encoded.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(module,'encode',guarded_encode)
    try:
        proof,values=acquire(manager,host,10)
        def fenced(publish):
            inside[0]=True
            try:return manager.bars.prefixes.commit(proof,publish)
            finally:inside[0]=False
        apply(manager,host,proof,values,guard=fenced)
        assert encoded and store.results.read('cs_guarded')['run']['sequence']==10
    finally:cleanup(service,store,host)


def test_initial_projection_failure_rolls_back_creation_intent_and_source_ack(storage,tmp_path):
    from tests.test_continuous_creation_journal import journal_setup,ready,publish
    from app.backtest.continuous_provider import ContinuousProviderFactory
    store,manager,_definition,row,source=journal_setup(storage,tmp_path)
    try:
        context=ready(store,row,source)
        store.db.execute("CREATE TRIGGER reject_index BEFORE INSERT ON result_heads BEGIN SELECT RAISE(ABORT,'initial-index-failure'); END")
        with pytest.raises(sqlite3.IntegrityError,match='initial-index-failure'):
            publish(store,manager,context,ContinuousProviderFactory(scratch_root=tmp_path))
        assert store.creations.describe('request')['phase']=='READY' and store.list_summaries()==[]
        assert store.db.execute('SELECT count(*) FROM checkpoints').fetchone()[0]==0
        assert store.db.execute('SELECT count(*) FROM result_items').fetchone()[0]==0
        assert manager.bars.prefixes.inspect('strategy:'+row['run_id'])['committed_acquisition']==0
        store.db.execute('DROP TRIGGER reject_index')
        publish(store,manager,context,ContinuousProviderFactory(scratch_root=tmp_path))
        assert store.creations.describe('request')['phase']=='COMMITTED'
        assert store.results.read(row['run_id'])['run']['checkpoint_revision']==1
    finally:source.close();store.close()


def test_opaque_legacy_recovery_data_is_preserved_without_silently_qualifying_results(tmp_path):
    store=ContinuousStrategyStore(tmp_path/'opaque.db')
    state={'engine':{'account':{'legacy_balance':'123'},**{kind:[] for kind in ('orders','fills','decisions','rejected','equity_curve')}},
        'provider':{'original':'data'},'planner':{}}
    try:
        store.create('cs_opaque',definition={'original':'opaque'},mode='HISTORY_LIVE',data_revision='old',event_time_ms=0,checkpoint=state)
        before=store.load('cs_opaque')
        with pytest.raises(BacktestError,match='no qualified result'):store.results.ensure('cs_opaque')
        assert store.load('cs_opaque')==before
        assert store.db.execute('SELECT count(*) FROM result_heads').fetchone()[0]==0
    finally:store.close()


def encode_response(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()


@pytest.mark.parametrize('changes',[
    {'limit':True},{'limit':201},{'after':10**30},{'after':1},{'kind':'provider'},
    {'since_revision':True},{'since_revision':10**30},{'since_revision':0,'kind':'fills'},
    {'since_revision':0,'change_cursor':[1,'fills',0]},
])
def test_read_rejects_unbounded_or_ambiguous_cursors(tmp_path,changes):
    store=ContinuousStrategyStore(tmp_path/'invalid.db');create(store)
    try:
        with pytest.raises(BacktestError,match='CONTINUOUS_INPUT_INVALID'):store.results.read('cs_test',**changes)
    finally:store.close()
