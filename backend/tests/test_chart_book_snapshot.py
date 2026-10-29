"""Frozen physical book admission reaches the queued chart worker unchanged."""
from copy import deepcopy
from decimal import Decimal
import json
import os
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.backtests import router
from app.backtest.chart_book import freeze
from app.backtest.errors import BacktestError
from app.backtest.runtime import BacktestRuntime
from app.core.config import load_backtest_settings
from app.local_data.service import LocalDatasetService, LocalImportOptions

MODES=('BOOK_ASSISTED','BOOK_DEPTH','BOOK_SAMPLED')
SOURCE='''//@version=6
strategy("physical chart book",calc_on_every_tick=true,calc_on_order_fills=true)
varip int n=0
n+=1
if n==1
    strategy.entry("L",strategy.long,qty=1)
if strategy.position_size>0
    strategy.close_all()
plot(n)
plot(strategy.position_size)
'''


def data(mode):
    events=[]
    for index in range(12):
        stamp=(index//4)*60000+(index%4)*10000
        price=(10,11,9,10)[index%4]
        observed=max(0,stamp-1)
        book=dict(snapshot=True)
        if mode=='BOOK_ASSISTED':
            book.update(book_sequence=index+1,bid=str(price-.1),ask=str(price+.1))
        else:
            book.update(bids=[[str(price-.5),'5']],asks=[[str(price+.5),'5']])
            if mode=='BOOK_DEPTH':
                book.update(book_sequence=index+1,depth_complete=True)
            else:
                book.update(sample_index=index+1,sample_time_ms=observed if index else -1,
                    depth_complete=False,depth_scope='BOUNDED_SAMPLED')
        events.extend([dict(time_ms=observed,role='ORDER_BOOK',payload=book),
            dict(time_ms=stamp,role='TRADES',payload=dict(source_event_kind='AGG_TRADE',
                source_sequence=index+1,tie_break=f'AGG_TRADE:{index+1}',price=str(price),qty='1',aggressor_side='BUY'))])
    return dict(exchange='binance',market_type='usdm',symbol='BTCUSDT',events=events,
        provenance={'fixture':'ordered-physical-source'})


@pytest.fixture
def host(tmp_path):
    csv=tmp_path/'bars.csv'
    csv.write_text('time,open,high,low,close,volume\n'+'\n'.join(f'{i*60000},10,11,9,10,4' for i in range(3)))
    local=LocalDatasetService(tmp_path/'local')
    manifest=local.import_csv(csv,LocalImportOptions(name='book chart',symbol='BTCUSDT',interval='1m',timestamp_unit='ms'))
    settings=load_backtest_settings({'BACKTEST_ENABLED':'1','BACKTEST_BAR_ENABLED':'1',
        'BACKTEST_TRADE_TAPE_ENABLED':'1','BACKTEST_BOOK_ASSISTED_ENABLED':'1'},
        data_dir=tmp_path,klines_db_path=tmp_path/'klines.db',replay_db_path=tmp_path/'replay.db')
    runtime=BacktestRuntime.start(settings,local_data_dir=tmp_path/'local')
    try:
        yield runtime,dict(dataset_id=manifest['dataset_id'],data_epoch=manifest['data_epoch'],
            start_time_ms=0,end_time_ms=179999,interval='1m',exchange='binance',market_type='usdm')
    finally:
        runtime.shutdown()


@pytest.mark.parametrize('mode',MODES)
def test_frozen_book_hash_covers_market_quotes_source_order_and_provenance(host,mode):
    runtime,base=host
    value={**base,'fidelity_mode':mode,'execution_data':data(mode)}
    preview,events,bars=freeze(runtime,value)
    assert preview==runtime.preview_snapshot(**value)
    assert preview['fidelity_capabilities']==[mode]
    assert len(events)==24 and len(bars)==3
    changed=deepcopy(value)
    changed['execution_data']['provenance']['capture']='another-file'
    assert freeze(runtime,changed)[0]['snapshot_hash']!=preview['snapshot_hash']
    changed=deepcopy(value)
    book=changed['execution_data']['events'][0]['payload']
    if mode=='BOOK_ASSISTED': book['ask']='11'
    else: book['asks'][0][1]='6'
    assert freeze(runtime,changed)[0]['snapshot_hash']!=preview['snapshot_hash']
    changed=deepcopy(value)
    changed['execution_data']['market_type']='spot'
    with pytest.raises(BacktestError,match='market identity'):
        freeze(runtime,changed)
    changed=deepcopy(value)
    changed['execution_data']['events'][1]['payload']['price']='999'
    with pytest.raises(BacktestError,match='OHLCV differs'):
        freeze(runtime,changed)
    changed=deepcopy(value)
    changed['execution_data']['events'][0]['time_ms']=True
    with pytest.raises(BacktestError,match='invalid frozen'):
        freeze(runtime,changed)


@pytest.mark.parametrize('override',[{'participation_rate':'0.5'}, {'execution_model_revision':'EXECUTION_REALISM_V2'},
    {'latency_ms':100}, {'latency_events':1}, {'bar_path_scenario':'OHLC_NEAREST_EXTREME_PATH_V2'}])
def test_chart_book_rejects_unconnected_capacity_or_latency_assumptions_before_admission(host,override):
    runtime,base=host
    with pytest.raises(BacktestError,match='declared physical policy'):
        runtime.service.validate_run({**base,'fidelity_mode':'BOOK_DEPTH','execution_data':data('BOOK_DEPTH'),**override})


@pytest.mark.parametrize('mutation',[{'book_sequence':True},{'book_sequence':9},{'bid':True},{'bid':None}])
def test_spread_snapshot_rejects_invalid_quotes_before_publishing_an_execution_identity(host,mutation):
    runtime,base=host
    value={**base,'fidelity_mode':'BOOK_ASSISTED','execution_data':data('BOOK_ASSISTED')}
    value['execution_data']['events'][2]['payload'].update(mutation)
    with pytest.raises(BacktestError): freeze(runtime,value)


@pytest.mark.skipif(not os.environ.get('NATIVE_TEST_PINE_PYTHON'),reason='requires installed Pine')
@pytest.mark.parametrize('mode',MODES)
def test_http_freezes_then_dispatches_actual_pine_book_ticks_and_returns_the_last_bar(host,mode):
    runtime,base=host
    request={**base,'fidelity_mode':mode,'execution_data':data(mode)}
    app=FastAPI()
    app.state.backtest_runtime=runtime
    app.state.backtest_service=runtime.service
    app.include_router(router)
    with TestClient(app) as client:
        response=client.post('/backtests/datasets/snapshot',json=request)
        assert response.status_code==200,response.text
        preview=response.json()
        revision=runtime.service.create_strategy_revision(dict(name='physical chart book',language='PINE_ENGINE',source_text=SOURCE))
        value={**request,'snapshot_hash':preview['snapshot_hash'],'strategy_revision_id':revision['revision_id'],
            'source_event_kind':'TRADE_AND_L2','output_mode':'ORDER_INTENT','symbol':'BTCUSDT',
            'slippage_bps':'0','taker_fee_bps':'0','pine_chart_metadata':{'priceTickSize':'.1','currency':'USDT'},
            'cost_sensitivity_mode':'SKIP','checkpoint_interval':1}
        runtime.service.smoke_strategy_revision(revision['revision_id'],value)
        response=client.post('/backtests/runs/validate',json=value)
        assert response.status_code==200,response.text
        response=client.post('/backtests/runs',json=value,headers={'Idempotency-Key':'queued-book'})
        assert response.status_code==200,response.text
        run=response.json()
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            record=runtime.service.get_run(run['run_id'])
            if record['state'] in {'COMPLETED','FAILED'}: break
            time.sleep(.05)
        assert record['state']=='COMPLETED',record
        report=runtime.service.get_report(run['run_id'])
        assert [row['event_time_ms'] for row in report['fills']]==[10000,20000]
        assert [float(row['price']) for row in report['fills']]==([11.1,8.9] if mode=='BOOK_ASSISTED' else [11.5,8.5])
        assert report['metrics']['signal_event_count']==3
        assert report['metrics']['execution_event_count']==12
        assert report['ledger']['book_execution']['physical_event_count']==24
        assert report['strategy']['pineExecution']['realtimeTickCount']==12
        assert report['strategy']['pineExecution']['confirmationCount']==3
        assert report['fill_model']['name'] in {'BOOK_ASSISTED_CONSERVATIVE_V1','FULL_L2_PESSIMISTIC_FIFO_V1','SAMPLED_L2_VISIBLE_TAKER_ONLY_V1'}
        assert report['fill_model']['queue_exact'] is False
        assert len(runtime.chart_data(run['run_id'])['bars'])==3
        config=json.loads(record['config_json'])
        assert config['chart_book_data_hash']==preview['execution_data_hash']


def v2_config(runtime,base,mode,tmp_path):
    from tests.test_backtest_contract_history_m3 import _bundle,START
    bundle=_bundle()
    for name,role in bundle['roles'].items():
        for row in role['records']:
            for key in ('event_time_ms','settlement_time_ms','effective_from_ms','effective_to_ms'):
                if key in row: row[key]-=START
            if name=='MARK_INDEX': row.update(mark_price='12',index_price='12')
            if name=='INSTRUMENT_RULES': row['contract_multiplier']='50'
            if name=='FUNDING': row['mark_price']='12'
    path=tmp_path/'contract.json'
    path.write_text(json.dumps(bundle),encoding='utf-8')
    attached=runtime.local_data.import_contract_history(path,dataset_id=base['dataset_id'],data_epoch=base['data_epoch'])
    value={**base,'data_epoch':attached['data_epoch'],'fidelity_mode':mode,'execution_data':data(mode),
        'account_model':'LINEAR_PERP_ONE_WAY_V2','contract_data_mode':'HISTORICAL_CONTRACT_V1',
        'funding_mode':'HISTORICAL_REQUIRED','leverage':'10','taker_fee_bps':'10','slippage_bps':'0',
        'cost_sensitivity_mode':'FULL','checkpoint_interval':1,'output_mode':'ORDER_INTENT','symbol':'BTCUSDT'}
    preview=runtime.preview_snapshot(**{key:value[key] for key in (*base,'fidelity_mode','execution_data',
        'account_model','contract_data_mode','funding_mode')})
    value['snapshot_hash']=preview['snapshot_hash']
    source=SOURCE.replace('if strategy.position_size>0','if bar_index==2 and barstate.isnew and strategy.position_size>0')
    source+='\nif syminfo.pointvalue!=50\n    runtime.error("historical contract multiplier not observed")\n'
    revision=runtime.service.create_strategy_revision(dict(name='V2 book',language='PINE_ENGINE',source_text=source))
    value['strategy_revision_id']=revision['revision_id']
    runtime.service.smoke_strategy_revision(revision['revision_id'],value)
    return value


@pytest.mark.skipif(not os.environ.get('NATIVE_TEST_PINE_PYTHON'),reason='requires installed Pine')
@pytest.mark.parametrize('mode',MODES)
def test_queued_v2_chart_book_keeps_account_authority_and_independent_cost_scenarios(host,mode,tmp_path):
    runtime,base=host
    value=v2_config(runtime,base,mode,tmp_path)
    run=runtime.service.create_run(value,idempotency_key='v2-book')
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        record=runtime.service.get_run(run['run_id'])
        if record['state'] in {'COMPLETED','FAILED'}: break
        time.sleep(.05)
    assert record['state']=='COMPLETED',record
    report=runtime.service.get_report(run['run_id'])
    assert report['account']['funding_event_count']==2
    assert Decimal(report['account']['cumulative_funding'])==Decimal('-.12')
    assert Decimal(report['account']['mark_price'])==12
    assert all(Decimal(row['contract_multiplier'])==50 for row in report['fills'])
    assert [row['event_time_ms'] for row in report['fills']]==[10000,130000]
    assert report['cost_sensitivity']['baseline_reexecution_verified'] is True
    scenarios=report['cost_sensitivity']['scenarios']
    assert [row['status'] for row in scenarios][-2:]==[
        'NOT_APPLICABLE_PHYSICAL_BOOK_POLICY','NOT_APPLICABLE_PHYSICAL_BOOK_CAPACITY']
    assert scenarios[0]['hashes']['ledger']!=scenarios[1]['hashes']['ledger']
    assert len(runtime.chart_data(run['run_id'])['bars'])==3


@pytest.mark.skipif(not os.environ.get('NATIVE_TEST_PINE_PYTHON'),reason='requires installed Pine')
@pytest.mark.parametrize('mode',MODES)
def test_v2_book_checkpoint_reconstructs_pine_before_restoring_the_physical_account(host,mode,tmp_path,monkeypatch):
    from app.backtest.strategy.pine_engine import PineEngineProvider
    from app.simulation.dual_clock_book import execution_type
    runtime,base=host
    runtime.worker.shutdown()
    service=runtime.service
    service._colocated_worker=True
    value=v2_config(runtime,base,mode,tmp_path)
    value['cost_sensitivity_mode']='SKIP'
    _,events,_=freeze(runtime,value)
    def execute(run):
        return service.execute_dual_clock_run(run['run_id'],events=events,provider=PineEngineProvider(),
            observation_market={'venue':'binance','market_type':'usdm','symbol':'BTCUSDT'})
    baseline=execute(service.create_run(value,idempotency_key='baseline-book'))
    run=service.create_run(value,idempotency_key='interrupted-book')
    save=service.repository.save_checkpoint
    def interrupt(record):
        result=save(record)
        if record['sequence']==8: raise KeyboardInterrupt('retained physical book prefix')
        return result
    monkeypatch.setattr(service.repository,'save_checkpoint',interrupt)
    with pytest.raises(KeyboardInterrupt): execute(run)
    monkeypatch.setattr(service.repository,'save_checkpoint',save)
    cls=execution_type(mode)
    original_restore,original_match=cls.restore,cls._match
    restored={}
    def restore(kernel,state):
        result=original_restore(kernel,state)
        restored[id(kernel)]=state['last_event']['sequence']
        return result
    def match(kernel,event):
        if id(kernel) in restored: assert event.sequence>restored[id(kernel)],'old physical event was rematched'
        return original_match(kernel,event)
    monkeypatch.setattr(cls,'restore',restore)
    monkeypatch.setattr(cls,'_match',match)
    assert service.requeue_interrupted_run(run['run_id'],expected_generation=1)
    recovered=execute(run)
    assert recovered['report']['fills']==baseline['report']['fills']
    assert recovered['report']['hashes']==baseline['report']['hashes']
    assert recovered['report']['ledger']==baseline['report']['ledger']
