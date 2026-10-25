"""Synthetic evidence only: no live accounts or credentials."""
import asyncio
import copy
from decimal import Decimal

import pytest
from app.readonly_accounts import normalization as n
from app.readonly_accounts.reconciliation import reconcile_account
from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts.sync import AccountSynchronizer, three_months_before

NOW = 1792886400000
START = NOW - 100_000
END = NOW - 10_000


def fixture(inverse=False, side='long'):
    market = {'instId': 'BTC-USD-SWAP' if inverse else 'BTC-USDT-SWAP', 'instType': 'SWAP',
              'ctType': 'inverse' if inverse else 'linear', 'settleCcy': 'BTC' if inverse else 'USDT',
              'ctValCcy': 'USD' if inverse else 'BTC', 'ctVal': '100' if inverse else '0.01', 'lotSz': '1'}
    contract = n.Contract.from_okx(market)
    # Exactly representable P&L, including inverse short and fee rebates.
    pnl = contract.pnl(Decimal(2), Decimal(10000), Decimal(20000), side)
    fee = Decimal('0.0001') if inverse else Decimal('-0.1')
    funding = Decimal('-0.0002') if inverse else Decimal('-0.2')
    facts = []
    balance = Decimal(100)
    for idx, (at, price, effect) in enumerate([(START,'10000','open'),(END,'20000','close')], 1):
        raw = {'instId': contract.instrument,'instType':'SWAP','billId':str(idx),'ordId':str(idx+20), 'tradeId':str(idx+40),
               'mgnMode':'cross','posSide':side,'side': 'buy' if (effect=='open') == (side=='long') else 'sell',
               'fillSz':'2','fillPx':price,'fillTime':str(at),'ts':str(at),'fee':str(fee),'feeCcy':contract.settle,
               'fillPnl':str(pnl if effect=='close' else 0)}
        fill = n.fill(raw, contract)
        facts.append({'kind':'fills','key':str(idx),'value':fill,'raw':raw})
        bill = {'billId':str(idx),'ordId':raw['ordId'],'tradeId':raw['tradeId'],'instId':contract.instrument,'instType':'SWAP',
                'type':'2','subType':'3' if effect=='open' else '5','ccy':contract.settle,'pnl':raw['fillPnl'],'fee':str(fee),
                'balChg':str(Decimal(raw['fillPnl'])+fee),'ts':str(at),'sz':'2','mgnMode':'cross'}
        if effect=='close': balance += funding
        balance += Decimal(bill['balChg']); bill['bal']=str(balance)
        facts.append({'kind':'bills','key':str(idx),'value':n.bill(bill),'raw':bill})
    bill = {'billId':'3','instId':contract.instrument,'instType':'SWAP','type':'8','subType':'173','ccy':contract.settle,
            'pnl':str(funding),'fee':'0','balChg':str(funding),'bal':str(Decimal(100)+fee+funding),'ts':str(START+30000),'sz':'2','mgnMode':'cross'}
    facts.append({'kind':'bills','key':'3','value':n.bill(bill),'raw':bill})
    history = {'posId':'100','instId':contract.instrument,'instType':'SWAP','mgnMode':'cross','posSide':side,
               'ccy':contract.settle,'cTime':str(START),'uTime':str(END),'type':'2','closeTotalPos':'2',
               'pnl':str(pnl),'fee':str(2*fee),'fundingFee':str(funding),'realizedPnl':str(pnl+2*fee+funding),'liqPenalty':'0','settledPnl':''}
    return {'account':{'status':'synced','last_success_ms':NOW},'facts':facts,'coverage':[
        {'kind':k,'start_ms':START-1000,'end_ms':NOW} for k in ['fills','bills','orders']], 'gaps':[],
        'snapshots':{'balances':{'receivedMs':NOW,'data':[{'details':[{'ccy':contract.settle,'cashBal':str(balance)}]}]},
                     'position_history':{'receivedMs':NOW,'data':{'rows':[history],'complete':True}},
                     'position_history_state':{'receivedMs':NOW,'data':{'complete':True}}}}


def report(data): return reconcile_account(data, now_ms=NOW)
def history(data): return data['snapshots']['position_history']['data']['rows']


@pytest.mark.parametrize('inverse,side', [(False,'long'),(False,'short'),(True,'long'),(True,'short')])
def test_exact_linear_inverse_hedge_reconciliation_without_source_mutation(inverse, side):
    data=fixture(inverse,side); original=copy.deepcopy(data)
    result=report(data)
    assert result['status']=='matched'
    assert result['fees']['checked']==2 and result['counts']['assignedFunding']==1
    assert result['funding'][0]['positionSide']==side
    assert Decimal(result['cash'][0]['difference'])==0
    assert Decimal(result['positions'][0]['pnlDifference'])==0
    assert data==original and data['facts'][-1]['value']['positionSide'] is None


def test_absent_cash_history_is_unknown_not_zero_and_totals_stay_separate():
    data=fixture();data['snapshots']['balances']['data'][0]['details'].append({'ccy':'OKB','cashBal':'0.1'})
    result=report(data)
    assert result['status']=='partial'
    other=next(row for row in result['cash'] if row['currency']=='OKB')
    assert other['openingDerived'] is None and other['reason']=='missingBills'


@pytest.mark.parametrize('change,reason', [
    ({'fundingFee':'-0.3','realizedPnl':'199.5'},'fundingDifference'),
    ({'fee':'-0.3'},'amountMismatch'), ({'closeTotalPos':'3'},'openingUnknown'),
    ({'type':'6'},'unsupportedPosition'), ({'cTime':str(START-10000)},'openingUnknown'),
    ({'fee':''},'missingAmount')])
def test_incomplete_or_inconsistent_position_never_gets_funding(change,reason):
    data=fixture();history(data)[0].update(change)
    result=report(data)
    assert result['positions'][0]['reason']==reason
    assert result['funding'][0]['positionSide'] is None
    assert result['counts']['unmatchedFills']==2


def test_overlapping_position_snapshots_are_not_double_counted():
    data=fixture();history(data).append(dict(history(data)[0],posId='101'))
    result=report(data)
    assert all(row['reason']=='ambiguousHistory' for row in result['positions'])
    assert result['counts']['assignedFunding']==0


def test_unknown_opposite_leg_prevents_apparently_unique_assignment():
    data=fixture();history(data).append(dict(history(data)[0],posId='101',posSide='short'))
    assert report(data)['counts']['assignedFunding']==0


def test_both_hedge_legs_with_equal_exposure_are_ambiguous_even_when_funding_nets_zero():
    data=fixture();other=fixture(side='short')
    for item in other['facts']:
        if item['kind']=='fills':
            item['value']['fillId']='other'+item['value']['fillId']; data['facts'].append(item)
    history(data).append(dict(history(other)[0],posId='101'))
    result=report(data)
    assert result['counts']['assignedFunding']==0
    assert result['funding'][0]['reason']=='noUniquePosition'


def test_settlement_boundary_is_not_inferred_from_timestamp_sorting():
    data=fixture();data['facts'][-1]['value']['eventTimeMs']=START+1000
    assert report(data)['funding'][0]['reason']=='settlementBoundary'


def test_failed_or_stale_history_is_not_used_even_if_last_good_snapshot_remains():
    for stale in [False,True]:
        data=fixture()
        if stale:data['snapshots']['position_history']['receivedMs']=NOW-300001
        else:data['snapshots']['position_history_state']['data']['complete']=False
        result=report(data)
        assert not result['historyReady'] and result['counts']['assignedFunding']==0


def test_missing_query_interval_and_missing_fee_never_pass():
    data=fixture();data['coverage']=[]
    assert report(data)['positions'][0]['reason']=='coverageGap'
    data=fixture();data['facts'][0]['value']['feeCashChange']=None
    assert report(data)['fees']['status']=='partial'


def test_cash_discontinuity_and_live_difference_are_exposed():
    data=fixture();data['facts'][-1]['raw']['bal']='99'
    data['snapshots']['balances']['data'][0]['details'][0]['cashBal']='300'
    row=report(data)['cash'][0]
    assert row['breaks']==2 and Decimal(row['difference'])!=0 and row['status']=='partial'


def test_repository_read_is_consistent_bounded_and_credential_free(tmp_path):
    repo=AccountRepository(tmp_path);repo.bind('uid','secret-ref',0)
    data=repo.reconciliation_inputs()
    assert 'uid' not in str(data) and 'secret-ref' not in str(data)
    repo.save_snapshot('position_history',{'rows':[history(fixture())[0]]},NOW)
    with repo.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM raw_fact WHERE kind='position_history'").fetchone()[0]==1
    with pytest.raises(n.AccountDataError,match='RECORD_LIMIT'):repo.reconciliation_inputs(maximum=-1)


def test_history_pagination_preserves_timestamp_ties_and_raw_evidence(tmp_path):
    async def run():
        repo=AccountRepository(tmp_path);calls=[]
        class Client:
            async def privateGetAccountPositionsHistory(self,params):
                calls.append(params)
                return {'code':'0','data':[] if 'after' in params else [dict(history(fixture())[0],posId=str(i)) for i in range(101)]}
        sync=AccountSynchronizer(repo,Client(),now_ms=lambda:NOW)
        await sync.position_history(force=True)
        saved=repo.snapshots()['position_history']['data']
        assert saved['complete'] and len(saved['rows'])==101 and calls[1]['after']==str(END)
        with repo.connection() as db: assert db.execute("SELECT COUNT(*) FROM raw_fact").fetchone()[0]==101
    asyncio.run(run())


def test_history_stalled_cursor_keeps_prior_snapshot_and_marks_optional_failure(tmp_path):
    async def run():
        repo=AccountRepository(tmp_path)
        repo.save_snapshot('position_history',{'rows':[],'complete':True},NOW-1)
        class Client:
            async def privateGetAccountPositionsHistory(self,params):return {'code':'0','data':history(fixture())}
        sync=AccountSynchronizer(repo,Client(),now_ms=lambda:NOW)
        await sync.position_history(force=True)
        snapshots=repo.snapshots()
        assert snapshots['position_history']['receivedMs']==NOW-1
        assert snapshots['position_history_state']['data']=={'complete':False,'error':'POSITION_HISTORY_CURSOR_STALLED'}
    asyncio.run(run())


def test_partial_close_then_add_uses_remaining_position_basis():
    data=fixture();base=data['facts'][0]['value']; data['facts']=[]
    for i,(offset,effect,quantity,price,pnl) in enumerate([
        (0,'open','3','100','0'), (20000,'close','1','150','0.5'),
        (40000,'open','2','200','0'), (90000,'close','4','200','2')]):
        f=dict(base,fillId=str(i),eventTimeMs=START+offset,effect=effect,contracts=quantity,
               price=price,feeCashChange='0',exchangeRealizedPnl=pnl)
        data['facts'].append({'kind':'fills','key':str(i),'value':f,'raw':{'mgnMode':'cross'}})
    history(data)[0].update(closeTotalPos='5',pnl='2.5',fee='0',fundingFee='0',realizedPnl='2.5')
    position=report(data)['positions'][0]
    assert position['status']=='matched' and Decimal(position['computedPnl'])==Decimal('2.5')


def test_history_page_budget_does_not_claim_complete(tmp_path):
    async def run():
        repo=AccountRepository(tmp_path)
        class Client:
            async def privateGetAccountPositionsHistory(self,params):
                updated=int(params.get('after',str(END)))-1
                return {'code':'0','data':[dict(history(fixture())[0],uTime=str(updated))]}
        await AccountSynchronizer(repo,Client(),now_ms=lambda:NOW).position_history(force=True)
        snapshots=repo.snapshots()
        assert 'position_history' not in snapshots
        assert snapshots['position_history_state']['data']['error']=='POSITION_HISTORY_PAGE_BUDGET'
    asyncio.run(run())


def test_fills_history_missing_margin_mode_uses_exactly_linked_bill():
    data=fixture()
    for item in data['facts']:
        if item['kind']=='fills':item['raw'].pop('mgnMode')
    assert report(data)['counts']['assignedFunding']==1
    data['facts'][1]['raw']['tradeId']='unrelated'
    result=report(data)
    assert result['fees']['issues'][0]['reason']=='identityMismatch'
    assert result['counts']['assignedFunding']==0


def test_isolated_collateral_is_not_a_fee_or_profit():
    data=fixture();history(data)[0]['mgnMode']='isolated'
    for item in data['facts']:
        item['raw']['mgnMode']='isolated'
    opening=data['facts'][1];closing=data['facts'][3];funding=data['facts'][4]
    for item,collateral in [(opening,Decimal(10)),(closing,Decimal(-10))]:
        item['raw']['posBalChg']=str(collateral)
        item['raw']['balChg']=str(Decimal(item['raw']['balChg'])-collateral)
        item['value']=n.bill(item['raw'])
    for item in [opening,funding]:item['raw']['bal']=str(Decimal(item['raw']['bal'])-10)
    result=report(data)
    assert result['status']=='matched' and result['fees']['checked']==2
    assert result['cash'][0]['breaks']==0
    del opening['raw']['posBalChg']
    assert report(data)['fees']['status']=='partial'


def test_tiny_cash_rounding_is_visible_with_explicit_tolerance():
    data=fixture();balance=data['snapshots']['balances']['data'][0]['details'][0]
    balance['cashBal']=str(Decimal(balance['cashBal'])+Decimal('0.00000000000001'))
    result=report(data);row=result['cash'][0]
    assert row['status']=='matched' and Decimal(row['difference'])==Decimal('0.00000000000001')
    assert Decimal(row['tolerance'])==Decimal('0.000000000001')
    balance['cashBal']=str(Decimal(balance['cashBal'])+Decimal('0.0001'))
    assert report(data)['cash'][0]['reason']=='cashDifference'


def test_overview_does_not_load_large_history_or_contract_payloads(tmp_path):
    repo=AccountRepository(tmp_path)
    repo.save_snapshot('position_history',{'rows':history(fixture())},NOW)
    repo.save_snapshot('contracts',[],NOW)
    repo.save_snapshot('balances',[],NOW)
    assert set(repo.snapshots())=={'position_history','contracts','balances'}
    assert set(repo.snapshots(overview=True))=={'balances'}
