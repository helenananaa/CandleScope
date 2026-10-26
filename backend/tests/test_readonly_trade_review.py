"""Read-only projection and journal contract. All exchange data here is synthetic."""
import copy
from decimal import Decimal

import pytest

from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts.review import ReadOnlyReview
from app.trading_accounts.models import TradingAccountError
from tests.test_readonly_reconciliation import fixture, history, NOW


def review_fixture(tmp_path, monkeypatch, data=None):
    repo = AccountRepository(tmp_path)
    repo.bind('synthetic-uid', 'synthetic-key-reference', 0)
    data = copy.deepcopy(data or fixture())
    data['account']['venue_uid'] = 'synthetic-uid'
    monkeypatch.setattr(repo, 'reconciliation_inputs', lambda: copy.deepcopy(data))
    review = ReadOnlyReview(repo, clock=lambda: NOW)
    return review, data


def test_verified_trade_identity_facts_journal_and_restart(tmp_path, monkeypatch):
    review, data = review_fixture(tmp_path, monkeypatch)
    listing = review.refresh()
    trade = listing['trades'][0]
    assert Decimal(trade['netPnl']) == Decimal('199.6')
    assert trade['symbol'] == 'BTCUSDT'
    assert trade['readonlySource']['fills'][0]['contracts'] == '2'
    assert [leg['qty'] for leg in trade['legs']] == ['0.02', '0.02']
    assert listing['stats']['rCount'] == 0 and listing['stats']['averageR'] is None
    assert Decimal(listing['stats']['funding']) == Decimal('-0.2')
    assert listing['stats']['currency'] == 'USDT'
    assert listing['stats']['cachedCount'] == 0
    assert review.refresh()['trades'][0] == trade
    assert len(review.store.all('SELECT * FROM review_version')) == 1
    payload = dict(kind='note', exchange='okx', marketType='futures', symbol='BTCUSDT',
                   tradeId=trade['id'], clientEntryId='je_'+'1'*20, fields={'thesis': 'review'})
    entry = review.create_entry(trade['accountId'], payload)
    assert review.create_entry(trade['accountId'], payload)['id'] == entry['id']
    review.save_entry(entry['id'], {'expectedRevision': 1, 'fields': {'thesis': 'updated'}})
    with pytest.raises(TradingAccountError, match='another editor'):
        review.save_entry(entry['id'], {'expectedRevision': 1, 'fields': {'thesis': 'stale'}})
    # Unrelated backfill/order, receipt times and mutable history uTime are not identity.
    history(data)[0]['uTime'] = str(int(history(data)[0]['uTime']) + 1)
    later = review.refresh()['trades'][0]
    assert later['id'] == trade['id']
    assert not review.store.fills(trade['accountId'])
    assert not hasattr(review, 'place_order') and not hasattr(review, 'add_fill')
    review.store.close()
    reopened = ReadOnlyReview(review.repository, clock=lambda: NOW+600_000)
    cached = reopened.refresh()
    assert cached['stats']['cachedCount'] == 1
    detail = reopened.trade_detail(trade['accountId'], trade['id'], trade['readonlySource']['version'])
    assert detail['entries'][0]['fields'] == {'thesis': 'updated'}
    assert detail['entries'][0]['revisionCount'] == 2
    assert detail['metrics']['netR'] is None
    assert detail['netPnl'] == trade['netPnl']
    reopened.store.close()


@pytest.mark.parametrize('change', ['inverse', 'missing_open', 'fee_mismatch', 'stale', 'ambiguous'])
def test_unverified_cycles_never_become_reviewable(tmp_path, monkeypatch, change):
    data = fixture(inverse=change == 'inverse')
    if change == 'missing_open':
        data['facts'] = [row for row in data['facts'] if not (row['kind'] == 'fills' and row['key'] == '1')]
    if change == 'fee_mismatch':
        data['facts'][1]['raw']['fee'] = '99'
    if change == 'stale':
        data['account']['last_success_ms'] = NOW-600_000
    if change == 'ambiguous':
        history(data).append(dict(history(data)[0], posId='101'))
    review, _ = review_fixture(tmp_path, monkeypatch, data)
    result = review.refresh()
    assert result['trades'] == [] and result['excluded']
    assert result['stats']['count'] == 0
    review.store.close()


def test_new_verified_version_keeps_identity_and_old_snapshot(tmp_path, monkeypatch):
    review, data = review_fixture(tmp_path, monkeypatch)
    old = review.refresh()['trades'][0]
    # Fee rebate correction with matching bill, history and net. Cash snapshot is
    # deliberately outside this trade-level proof; no account cash claim is made.
    data['facts'][0]['value']['feeCashChange'] = '0.1'
    data['facts'][1]['raw']['fee'] = '0.1'
    data['facts'][1]['raw']['balChg'] = '0.1'
    data['facts'][1]['value']['cashChange'] = '0.1'
    history(data)[0].update(fee='0', realizedPnl='199.8')
    new = review.refresh()['trades'][0]
    assert new['id'] == old['id']
    assert new['readonlySource']['version'] != old['readonlySource']['version']
    assert Decimal(new['netPnl']) == Decimal('199.8')
    assert review.trade_detail(old['accountId'], old['id'], old['readonlySource']['version'])['netPnl'] == old['netPnl']
    with pytest.raises(TradingAccountError):
        review.trade_detail('acc_'+'0'*20, old['id'])
    review.store.close()


def test_guarded_http_review_lifecycle_and_legacy_notes(tmp_path, monkeypatch):
    import asyncio
    import base64
    import httpx
    from fastapi import FastAPI
    from app.plugin_security_v2.management import LocalManagementGuard
    from app.readonly_accounts.api import router
    from tests.test_readonly_account_service import fixture_service

    async def run():
        owner, _, _, _ = fixture_service(tmp_path)
        owner.repository.bind('synthetic-uid', 'synthetic-reference', 0)
        data = fixture()
        monkeypatch.setattr(owner.repository, 'reconciliation_inputs', lambda: copy.deepcopy(data))
        owner.review.clock = lambda: NOW
        guard = LocalManagementGuard(['http://127.0.0.1:61234'])
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        app.state.readonly_account_service = owner
        app.state.plugin_platform_v2_management_guard = guard
        headers = guard.trusted_headers(user_action='account.review')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1234)),
                                    base_url='http://127.0.0.1:8000') as client:
            base = '/api/v1/readonly-accounts/review'
            assert (await client.get(base+'/trades')).status_code == 403
            trades = (await client.get(base+'/trades', headers=headers)).json()['trades']
            trade = trades[0]
            create = base+f"/accounts/{trade['accountId']}/journal"
            payload = dict(exchange='okx', marketType='futures', symbol='BTCUSDT', kind='note',
                           tradeId=trade['id'], clientEntryId='je_'+'2'*20, fields={'entryBasis': 'synthetic review'})
            missing_csrf = {key: value for key, value in headers.items() if key != 'X-CandleScope-CSRF'}
            assert (await client.post(create, headers=missing_csrf, json=payload)).status_code == 403
            response = await client.post(create, headers=headers, json=payload)
            assert response.status_code == 200, response.text
            entry = response.json()
            assert (await client.post(create, headers=headers, json=payload)).json()['id'] == entry['id']
            entry_url = base+'/journal/'+entry['id']
            snapshot = await client.post(entry_url+'/snapshots', headers=headers,
                json={'image': 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode(), 'state': {'symbol': 'BTCUSDT'}})
            image_url = base+'/snapshots/'+snapshot.json()['snapshots'][0]['id']+'/image'
            assert (await client.get(image_url)).status_code == 403
            assert (await client.get(image_url, headers=headers)).json()['image'].startswith('data:image/png;base64,')
            assert (await client.post(entry_url, headers=headers, content='[]')).status_code == 409
            assert (await client.post(base+'/accounts/'+trade['accountId']+'/orders', headers=headers, json={})).status_code == 404
            # Old journal stays in its original table; only associated fill IDs surface.
            with owner.repository.transaction() as db:
                for version, text in [(1, 'original'), (2, 'later')]:
                    db.execute('INSERT INTO journal_version VALUES(?,?,?,?,?,?)',
                        ('a'*32, version, NOW-200_000+version*1000, NOW-200_000, '1',
                         __import__('json').dumps({'text': text, 'tags': [], 'kind': 'note'})))
            detail_url = base+f"/accounts/{trade['accountId']}/trades/{trade['id']}?version={trade['readonlySource']['version']}"
            detail = (await client.get(detail_url, headers=headers)).json()
            old = next(row for row in detail['entries'] if row['id'].startswith('legacy_'))
            assert [rev['body'] for rev in old['revisions']] == ['original', 'later']
            assert old['createdAtMs'] == NOW-199_000
            assert len(owner.repository.notes()) == 2
        await owner.close()

    asyncio.run(run())


def test_cached_review_survives_record_limit_and_source_reversion(tmp_path, monkeypatch):
    from app.readonly_accounts.normalization import AccountDataError
    review, data = review_fixture(tmp_path, monkeypatch)
    original_data = copy.deepcopy(data)
    old = review.refresh()['trades'][0]
    data['facts'][0]['value']['feeCashChange'] = '0.1'
    data['facts'][1]['raw'].update(fee='0.1', balChg='0.1')
    history(data)[0].update(fee='0', realizedPnl='199.8')
    corrected = review.refresh()['trades'][0]
    assert corrected['readonlySource']['version'] != old['readonlySource']['version']
    data.clear()
    data.update(original_data)
    restored = review.refresh()['trades'][0]
    assert restored['readonlySource']['version'] == old['readonlySource']['version']
    assert restored['readonlySource']['current']
    assert len(review.store.all('SELECT * FROM review_version')) == 2
    assert review.trade_detail(old['accountId'], old['id'])['netPnl'] == old['netPnl']
    monkeypatch.setattr(review.repository, 'reconciliation_inputs', lambda: (_ for _ in ()).throw(AccountDataError('RECONCILIATION_RECORD_LIMIT')))
    cached = review.refresh()
    assert cached['stats']['cachedCount'] == 1
    assert cached['readError'] == 'RECONCILIATION_RECORD_LIMIT'
    assert not cached['trades'][0]['readonlySource']['current']
    review.store.close()


def test_derived_weighted_price_is_not_revalidated_as_raw_exchange_amount(tmp_path, monkeypatch):
    from app.readonly_accounts.review import ReviewTrade
    review, _ = review_fixture(tmp_path, monkeypatch)
    view = review.refresh()['trades'][0]
    # Raw exchange decimals are bounded; a derived weighted average can recur
    # at the reconciliation context's 80-digit precision.
    view['avgEntryPrice'] = '10000.' + '3'*75
    view['entryQty'] = '0.'+'0'*40+'3'
    adapted = ReviewTrade(view)
    assert adapted.to_dict()['avgEntryPrice'] == view['avgEntryPrice']
    assert adapted.to_dict()['entryQty'] == view['entryQty']
    assert adapted.net_pnl == Decimal(view['netPnl'])
    review.store.close()
