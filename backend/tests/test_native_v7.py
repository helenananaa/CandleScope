import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_external_strategy_v2 import source, tape
from app.backtest.native import invoke, digest


def config(payload, language):
    body='''if bar_index == 0:
    strategy.entry("L", strategy.long, qty=4)
if bar_index == 1:
    strategy.close("L")
'''
    return {**payload,"language":language,"source":source(language,body.replace(':','')),
        "execution_mode":"CANDLESCOPE","host_settings":{"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}}


@pytest.mark.parametrize('language',['pine'])
def test_worker_and_single_shot_preserve_complete_financial_reports_and_disclose_contract(runtime,language):
    host,payload=runtime
    request=config(payload,language)
    first=terminal(host.native,host.native.create(request,'worker')['run_id'])
    host.native.runner=lambda *args,**kwargs: invoke(*args,**kwargs)
    second=terminal(host.native,host.native.create(request,'single')['run_id'])
    assert first['state']==second['state']=='COMPLETED', (first.get('error'),second.get('error'))
    expected = 'historical-prefix/1'
    assert first['result']['evaluation_contract'] == expected
    assert second['result']['evaluation_contract'] == 'historical-prefix/1'
    for record in (first, second):
        report = {k: v for k, v in record['result'].items() if k != 'report_hash'}
        assert digest(report) == record['result']['report_hash']
    # Different declared endpoint semantics intentionally produce a different
    # report identity. Every financial/source/graphics field remains identical
    # for this script, which does not inspect historical endpoint flags.
    fields = lambda result: {k: v for k, v in result.items() if k not in {'evaluation_contract', 'report_hash'}}
    assert fields(first['result']) == fields(second['result'])


@pytest.mark.parametrize('language',['pine'])
@pytest.mark.parametrize('callbacks',[False,True])
def test_installed_engines_walk_full_depth_with_one_account(runtime,language,callbacks):
    host,payload=runtime
    data=tape(); events=[]
    for i,event in enumerate(data['events']):
        p=float(event['payload']['price'])
        events.append({'time_ms':event['time_ms'],'role':'ORDER_BOOK','payload':{
            'book_sequence':i+1,'snapshot':True,'depth_complete':True,
            'bids':[[str(p-.1),'2'],[str(p-.2),'50']], 'asks':[[str(p),'2'],[str(p+.1),'50']]}})
        events.append({**event,'payload':{**event['payload'],'aggressor_side':'BUY'}})
    data['events']=events
    request={**config(payload,language),'execution_fidelity':'BOOK_DEPTH','execution_data':data}
    if callbacks:
        from tests.test_external_feedback import PINE
        request.update(source=PINE,fill_recalculation=True)
    result=terminal(host.native,host.native.create(request,'depth')['run_id'])
    assert result['state']=='COMPLETED',result.get('error')
    report=result['result']
    assert report['fill_model']=='FULL_L2_PESSIMISTIC_FIFO_V1'
    assert report['fidelity']=='BOOK_DEPTH' and report['account_authority']=='candlescope'
    assert [float(fill['qty']) for fill in report['trades']]==[2,2,2,2]
    assert [float(fill['price']) for fill in report['trades'][:2]]==[10,10.1]
    assert float(report['trades'][-1]['position_after'])==0
    assert report['raw_output']['depth_model']['queue_exact'] is False
    if callbacks:
        passes=[p for group in report['raw_output']['execution_passes'] for p in group if not p['confirmed']]
        assert [p['account']['position_size'] for p in passes]==[2,4,2,0]
    events[1]['payload'].pop('aggressor_side')
    with pytest.raises(ValueError,match='aggressor_side'):
        host.native.create(request,'missing-side')
