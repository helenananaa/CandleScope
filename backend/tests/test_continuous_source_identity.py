"""Repair source epochs remain bound to one actual continuing account."""
from dataclasses import replace

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_source_identity import new_source_owner,source_owner
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.local_data.service import LocalDatasetService
from tests.test_continuous_guarded_source import setup_host,KEY,acquire,apply
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import START


def test_distinct_durable_source_epoch_restores_under_same_real_account_id(storage,tmp_path,monkeypatch):
    service,_row,definition,factory,original,manager,old=setup_host(storage,tmp_path,monkeypatch)
    staged=ContinuousStrategyStore(tmp_path/'staged.sqlite3')
    source=ContinuousMarketBarSource(manager,LocalDatasetService(tmp_path/'datasets'),KEY,clock_ms=lambda:START)
    host=None
    try:
        owner=new_source_owner('cs_guarded');definition={**definition,'source_owner':owner}
        point=source.register('cs_guarded',from_ms=START,definition=definition)
        assert point.owner==owner and point.incarnation!=old.source_receipt.incarnation
        before=original.load('cs_guarded')
        ContinuousBarHost.create_run(staged,'cs_guarded',definition=definition,mode='HISTORY_LIVE',
            data_revision=point.incarnation,event_time_ms=START-1,provider_factory=factory,source_receipt=point)
        host=ContinuousBarHost.resume(staged,'cs_guarded',factory)
        proof,events=acquire(manager,host,10);apply(manager,host,proof,events)
        host.close();host=ContinuousBarHost.resume(staged,'cs_guarded',factory)
        assert host.source_receipt.owner==owner and host.row['sequence']==10
        assert original.load('cs_guarded')==before
        with pytest.raises(BacktestError,match='Source epoch'):
            ContinuousBarHost._source_point('other',definition,host.source_receipt,host.row['event_time_ms'],point.incarnation)
        with pytest.raises(BacktestError,match='source prefix'):
            ContinuousBarHost._source_point('cs_guarded',definition,replace(host.source_receipt,owner='strategy:cs_guarded'),host.row['event_time_ms'],point.incarnation)
    finally:
        if host:host.close()
        source.close();old.close();staged.close();original.close();service.shutdown()


def test_repair_owner_cannot_alias_another_accounts_legacy_or_repair_namespace():
    first=new_source_owner('account')
    assert len(first)<=128 and source_owner('account',{'source_owner':first})==first
    assert source_owner('account',{})=='strategy:account'
    for owner in (first,'strategy:account:epoch:'+'a'*32):
        with pytest.raises(BacktestError):source_owner('other',{'source_owner':owner})
    with pytest.raises(BacktestError):source_owner('account',{'source_owner':new_source_owner('other')})
    # A colon-containing account id cannot alias a separate epoch owner.
    with pytest.raises(BacktestError):source_owner('account:epoch:'+'a'*32,{'source_owner':first})
