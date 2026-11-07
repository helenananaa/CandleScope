"""Real source/provider/accounts across pre-staging and atomic epoch activation."""
from contextlib import closing,contextmanager
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.continuous_results import KINDS
from app.backtest.errors import BacktestError
from app.data_engine.storage import klines_repo
from app.data_engine.storage.prefix_watches import PrefixAcquisitionChanged,ProcessedPrefixChanged
from app.data_engine.storage.prefix_watches import PrefixReceipt
from app.backtest.continuous_source_identity import new_source_owner
from app.backtest.continuous_repair_plan import preview
from app.local_data.service import LocalDatasetService
from tests.test_continuous_guarded_source import setup_host,acquire,apply,END,KEY
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import START,STEP,SOURCE,_row


@contextmanager
def repair_case(storage,tmp_path,monkeypatch,*,complete=True,suffix=False):
    service,_fixed,definition,factory,store,manager,old=setup_host(storage,tmp_path,monkeypatch)
    initial=old.source_receipt
    stage=ContinuousStrategyStore(tmp_path/'stage.sqlite3');host=None;source=None
    try:
        proof,events=acquire(manager,old,10);anchor=apply(manager,old,proof,events)
        proof,events=acquire(manager,old,25);apply(manager,old,proof,events)
        klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+12*STEP,220)],source=SOURCE)
        with pytest.raises(ProcessedPrefixChanged) as changed:acquire(manager,old,25)
        old.fail_input(changed.value)
        before=store.load('cs_guarded');assert before['run']['phase']=='REPAIR_REQUIRED'
        expected=store.results.identity(before['run']);plan={'through_ms':END,'resume_after':False,'plan_id':'confirmed-plan','anchor_revision':anchor['checkpoint_revision']}
        record=store.epochs.reserve('cs_guarded','repair/request',expected=expected,plan=plan)
        revised={**definition,'source_owner':record['source_owner']}
        source=ContinuousMarketBarSource(manager,LocalDatasetService(tmp_path/'datasets'),KEY,clock_ms=lambda:END+1)
        if suffix:
            observed=manager.bars.prefixes.inspect(old.source_receipt.owner)
            point=manager.bars.prefixes.fork_unchanged(old.source_receipt,record['source_owner'],
                through_ms=anchor['event_time_ms'],expected_version=observed['version'])
        else:point=source.register('cs_guarded',from_ms=START,definition=revised)
        store.epochs.prepare(record['id'],source=point.to_dict())
        if suffix:store.repair_publication.seed(record['id'],stage,definition=revised,proof=point)
        else:ContinuousBarHost.create_run(stage,'cs_guarded',definition=revised,mode='HISTORY_LIVE',data_revision=point.incarnation,
            event_time_ms=START-1,provider_factory=factory,source_receipt=point)
        evaluated=[]
        def counting_factory(definition):
            provider=factory(definition);original=provider.step
            def step(frame):evaluated.append(frame.sequence);return original(frame)
            provider.step=step
            return provider
        host=ContinuousBarHost.resume(stage,'cs_guarded',counting_factory)
        proof,events=acquire(manager,host,25 if complete else 24);apply(manager,host,proof,events)
        host.close();host=None
        yield SimpleNamespace(store=store,stage=stage,manager=manager,record=record,before=before,expected=expected,
            plan=plan,factory=factory,initial=initial,definition=definition,evaluated=evaluated,anchor=anchor)
    finally:
        if host:host.close()
        if source:source.close()
        stage.close();old.close();store.close();service.shutdown()


def assert_results(store,run_id='cs_guarded'):
    state=store.load(run_id)['checkpoint']['engine'];head=store.results.read(run_id)
    assert head['summary']['account']=={key:value for key,value in state['account'].items() if key!='journal'}
    for kind in KINDS:
        page=store.results.read(run_id,kind=kind,limit=2);values=[item['value'] for item in page['items']]
        while page['more']:
            page=store.results.read(run_id,kind=kind,after=page['next_cursor'],expected=page['identity'],limit=2)
            values.extend(item['value'] for item in page['items'])
        expected=state['account']['journal'] if kind=='ledger' else state.get(kind,[])
        assert values==expected,kind
    return head


def test_complete_repair_stages_without_mutating_old_account_then_only_metadata_is_switched_under_source_guard(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch) as case:
        raw=case.store.db.execute("SELECT definition_json FROM runs WHERE id='cs_guarded'").fetchone()[0]
        old_rows=[tuple(row) for row in case.store.db.execute('SELECT * FROM result_items')]
        case.store.repair_publication.stage(case.record['id'],case.stage)
        assert case.store.load('cs_guarded')==case.before
        assert case.store.results.read('cs_guarded')['stale'] is True
        assert case.store.db.execute('SELECT count(*) FROM active_continuous_epochs').fetchone()[0]==0
        original=case.manager.bars.prefixes.commit;guarded=[]
        def guard(proof,publish,**kwargs):
            def callback():
                def authorize(action,table,column,*_args):
                    if action==sqlite3.SQLITE_READ and (table in {'result_items','epoch_result_items'} or (table=='checkpoints' and column=='wire')):
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                case.store.db.set_authorizer(authorize)
                try:guarded.append(True);return publish()
                finally:case.store.db.set_authorizer(None)
            return original(proof,callback,**kwargs)
        monkeypatch.setattr(case.manager.bars.prefixes,'commit',guard)
        row=case.store.repair_publication.publish(case.record['id'],case.manager,resume_after=False)
        assert guarded==[True] and row['phase']=='PAUSED' and row['generation']>case.before['run']['generation']
        assert case.store.load('cs_guarded')['checkpoint']==case.stage.load('cs_guarded')['checkpoint']
        assert case.store.db.execute("SELECT definition_json FROM runs WHERE id='cs_guarded'").fetchone()[0]==raw
        assert [tuple(row) for row in case.store.db.execute('SELECT * FROM result_items')]==old_rows
        assert_results(case.store)
        # Original creation remains an exact uncertain retry, without another provider.
        def forbidden(_definition):raise AssertionError('Repair must preserve creation idempotency')
        assert ContinuousBarHost.create_run(case.store,'cs_guarded',definition=case.definition,mode='HISTORY_LIVE',
            data_revision=case.initial.incarnation,event_time_ms=START-1,provider_factory=forbidden,source_receipt=case.initial)==row
        assert case.store.epochs.reserve('cs_guarded','repair/request',expected=case.expected,plan=case.plan)['phase']=='COMMITTED'


def test_wal_reader_observes_one_complete_epoch_while_another_connection_activates_the_next(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch) as case:
        case.store.repair_publication.stage(case.record['id'],case.stage)
        writer=ContinuousStrategyStore(case.store.path);connection=case.store.db;activated=[]
        class Interleaved:
            def __getattr__(self,name):return getattr(connection,name)
            def execute(self,sql,*args):
                if sql.startswith('SELECT * FROM result_heads') and not activated:
                    activated.append(writer.repair_publication.publish(case.record['id'],case.manager,resume_after=False))
                return connection.execute(sql,*args)
        case.store.db=Interleaved()
        try:
            old=case.store.results.read('cs_guarded',since_revision=0)
            assert activated and old['identity']==case.expected and old['stale'] is True
            new=case.store.results.read('cs_guarded',since_revision=0)
            assert new['identity']['generation']>old['identity']['generation'] and new['stale'] is False
            assert_results(case.store)
        finally:case.store.db=connection;writer.close()


def test_revised_source_after_staging_cannot_replace_any_old_financial_result(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch) as case:
        case.store.repair_publication.stage(case.record['id'],case.stage)
        klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+10*STEP,300)],source=SOURCE)
        with pytest.raises(PrefixAcquisitionChanged):case.store.repair_publication.publish(case.record['id'],case.manager,resume_after=False)
        assert case.store.load('cs_guarded')==case.before and case.store.epochs.describe(case.record['id'])['phase']=='READY'
        assert_results(case.store)


def test_cancelled_account_and_incomplete_staging_cannot_be_overwritten(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch,complete=False) as case:
        with pytest.raises(BacktestError,match='did not finish'):case.store.repair_publication.stage(case.record['id'],case.stage)
        assert case.store.load('cs_guarded')==case.before
        row=case.store.summary('cs_guarded');case.store.stop(row['id'],generation=row['generation'],revision=row['revision'],phase='CANCELLED')
        with pytest.raises(BacktestError,match='changed'):case.store.repair_publication.stage(case.record['id'],case.stage)
        assert case.store.summary('cs_guarded')['phase']=='CANCELLED'


def test_staging_budget_failure_rolls_back_only_new_pages_and_keeps_saved_account(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch) as case:
        checkpoint_bytes=case.store.db.execute('SELECT SUM(stored_bytes) FROM checkpoints').fetchone()[0]
        head_bytes=case.store.db.execute('SELECT SUM(stored_bytes) FROM result_heads').fetchone()[0]
        case.store.max_total_checkpoint_bytes=checkpoint_bytes+head_bytes+65536+1
        with pytest.raises(BacktestError,match='total disk budget'):case.store.repair_publication.stage(case.record['id'],case.stage)
        assert case.store.load('cs_guarded')==case.before and case.store.db.execute('SELECT count(*) FROM active_continuous_epochs').fetchone()[0]==0
        assert_results(case.store)


def test_durable_swap_before_source_ack_restores_and_continues_same_account_with_new_projection(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch) as case:
        case.store.repair_publication.stage(case.record['id'],case.stage)
        original=case.manager.bars.prefixes.commit
        def crash(proof,publish,**kwargs):
            def after_financial():publish();raise RuntimeError('crash before source acknowledgement')
            return original(proof,after_financial,**kwargs)
        monkeypatch.setattr(case.manager.bars.prefixes,'commit',crash)
        case.store.repair_publication.publish(case.record['id'],case.manager,resume_after=False)
        assert case.store.epochs.describe(case.record['id'])['phase']=='COMMITTED'
        monkeypatch.setattr(case.manager.bars.prefixes,'commit',original)
        fresh=ContinuousStrategyStore(case.store.path);host=None
        try:
            host=ContinuousBarHost.resume(fresh,'cs_guarded',case.factory)
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(25,30)],source=SOURCE)
            queries=[];fresh.db.set_trace_callback(queries.append)
            proof,events=acquire(case.manager,host,30);apply(case.manager,host,proof,events)
            fresh.db.set_trace_callback(None)
            assert host.row['sequence']==30 and host.source_receipt.owner==case.record['source_owner']
            assert any('idx_epoch_result_active_orders' in query for query in queries)
            assert_results(fresh)
        finally:
            if host:host.close()
            fresh.close()


def test_retained_anchor_reuses_financial_prefix_and_only_evaluates_corrected_suffix(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch,suffix=True) as case:
        assert case.evaluated==list(range(11,26)),"Unchanged prefix must restore rather than rerun strategy steps"
        baseline=ContinuousStrategyStore(tmp_path/'full-reference.sqlite3');host=None
        source=ContinuousMarketBarSource(case.manager,LocalDatasetService(tmp_path/'reference-datasets'),KEY,clock_ms=lambda:END+1)
        try:
            definition={**case.definition,'source_owner':new_source_owner('cs_guarded')}
            initial=source.register('cs_guarded',from_ms=START,definition=definition)
            ContinuousBarHost.create_run(baseline,'cs_guarded',definition=definition,mode='HISTORY_LIVE',data_revision=initial.incarnation,
                event_time_ms=START-1,provider_factory=case.factory,source_receipt=initial)
            host=ContinuousBarHost.resume(baseline,'cs_guarded',case.factory)
            proof,events=acquire(case.manager,host,25);apply(case.manager,host,proof,events)
            assert case.stage.load('cs_guarded')['checkpoint']['engine']==baseline.load('cs_guarded')['checkpoint']['engine']
            assert case.stage.load('cs_guarded')['checkpoint']['provider']==baseline.load('cs_guarded')['checkpoint']['provider']
            case.store.repair_publication.stage(case.record['id'],case.stage)
            case.store.repair_publication.publish(case.record['id'],case.manager,resume_after=False)
            assert case.store.load('cs_guarded')['checkpoint']['engine']==baseline.load('cs_guarded')['checkpoint']['engine']
            assert_results(case.store)
            with pytest.raises(BacktestError,match='existing staging'):
                case.store.repair_publication.seed(case.record['id'],case.stage,definition=definition,proof=initial)
        finally:
            if host:host.close()
            source.close();baseline.close()


def test_repair_anchor_from_another_epoch_or_ahead_of_the_account_is_not_reused(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch,suffix=True) as case:
        case.store.repair_publication.stage(case.record['id'],case.stage)
        with pytest.raises(BacktestError,match='active source epoch'):
            case.store.epochs.checkpoint('cs_guarded',case.record['target_revision'])
        case.store.repair_publication.publish(case.record['id'],case.manager,resume_after=False)
        with pytest.raises(BacktestError,match='active source epoch'):
            case.store.epochs.checkpoint('cs_guarded',case.anchor['checkpoint_revision'])


def test_repair_preview_selects_latest_true_prefix_without_loading_accounts_or_creating_source_work(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch) as case:
        with closing(klines_repo._connect()) as connection:
            watch_count=connection.execute('SELECT count(*) FROM kline_prefix_watches').fetchone()[0]
        def forbidden(*_args,**_kwargs):raise AssertionError('Preview must not decode financial history or reserve source work')
        monkeypatch.setattr(case.store,'load',forbidden)
        monkeypatch.setattr(case.manager.bars.prefixes,'register',forbidden)
        queries=[];case.store.db.set_trace_callback(queries.append)
        plan=preview(case.store,case.manager,'cs_guarded',expected=case.expected,resume_after=False,now_ms=END+1)
        case.store.db.set_trace_callback(None)
        assert plan['anchor_revision']==case.anchor['checkpoint_revision'] and plan['anchor_sequence']==10
        assert plan['from_ms']==START+10*STEP and plan['through_ms']==END
        assert plan['dirty_from_ms']==START+12*STEP and plan['full_reinitialization'] is False
        assert plan['expanded_range_reason'] is None
        assert sum('json_extract(wire' in query for query in queries)==1
        assert not any('SELECT * FROM checkpoints' in query or 'SELECT wire' in query for query in queries)
        same=preview(case.store,case.manager,'cs_guarded',expected=case.expected,resume_after=False,now_ms=END+1)
        assert same==plan
        with closing(klines_repo._connect()) as connection:
            assert connection.execute('SELECT count(*) FROM kline_prefix_watches').fetchone()[0]==watch_count
        changed_intent=preview(case.store,case.manager,'cs_guarded',expected=case.expected,resume_after=True,now_ms=END+1)
        assert changed_intent['plan_id']!=plan['plan_id']
        klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+5*STEP,230)],source=SOURCE)
        expanded=preview(case.store,case.manager,'cs_guarded',expected=case.expected,resume_after=False,now_ms=END+1)
        assert expanded['plan_id']!=plan['plan_id'] and expanded['anchor_revision'] is None
        assert expanded['from_ms']==START and expanded['full_reinitialization'] is True
        assert expanded['expanded_range_reason']=='NO_RETAINED_CHECKPOINT_BEFORE_REVISION'


def test_repair_preview_discloses_revised_initial_snapshot_and_rejects_stale_account(storage,tmp_path,monkeypatch):
    with repair_case(storage,tmp_path,monkeypatch) as case:
        definition={**case.definition,'initial_snapshot':{'through_ms':END}}
        case.store.db.execute("UPDATE runs SET definition_json=? WHERE id='cs_guarded'",(json.dumps(definition),))
        plan=preview(case.store,case.manager,'cs_guarded',expected=case.expected,resume_after=False,now_ms=END+1)
        assert plan['full_reinitialization'] and plan['expanded_range_reason']=='INITIAL_SNAPSHOT_REVISED'
        with pytest.raises(BacktestError,match='cutoff'):
            preview(case.store,case.manager,'cs_guarded',expected=case.expected,resume_after=False,now_ms=END-STEP)
        row=case.store.summary('cs_guarded');case.store.stop(row['id'],generation=row['generation'],revision=row['revision'],phase='CANCELLED')
        with pytest.raises(BacktestError,match='changed'):
            preview(case.store,case.manager,'cs_guarded',expected=case.expected,resume_after=False,now_ms=END+1)
