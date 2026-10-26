import asyncio
from datetime import UTC, datetime
import pytest
from app.readonly_accounts.normalization import AccountDataError, Contract
from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts.sync import AccountSynchronizer, three_months_before, uncovered_ranges


def ms(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()*1000)


MARKET={"instType":"SWAP","instId":"BTC-USDT-SWAP","ctType":"linear","settleCcy":"USDT","ctValCcy":"BTC","ctVal":"0.01","lotSz":"0.01"}


def fill_row(at):
    return {"instType":"SWAP","instId":"BTC-USDT-SWAP","billId":"10","tradeId":"20","ordId":"30",
            "side":"buy","posSide":"long","fillPx":"20000","fillSz":"1","fee":"-0.1","feeCcy":"USDT","ts":str(at)}


@pytest.mark.parametrize('now,expected', [('2024-05-31','2024-02-29'),('2025-05-31','2025-02-28'),('2026-01-31','2025-10-31')])
def test_three_calendar_months_not_assumed_ninety_days(now,expected):
    assert three_months_before(ms(now))==ms(expected)


def test_gap_subtraction_does_not_discard_previously_saved_coverage():
    assert uncovered_ranges(0,30,[{'start_ms':5,'end_ms':10},{'start_ms':8,'end_ms':20}])==[(0,4),(21,30)]
    assert uncovered_ranges(0,30,[{'start_ms':0,'end_ms':30}])==[]


def test_incomplete_scan_resumes_same_cursor_as_retention_boundary_moves(tmp_path):
    async def run():
        now=[ms('2026-10-25')]
        repo=AccountRepository(tmp_path);repo.bind('123','a'*32,three_months_before(now[0]))
        calls=[]
        class Client:
            async def privateGetTradeFillsHistory(self,params):
                calls.append(dict(params))
                return {'code':'0','data':[] if params.get('after') else [fill_row(now[0]-1000)]}
        sync=AccountSynchronizer(repo,Client(),now_ms=lambda:now[0])
        sync.contracts={'BTC-USDT-SWAP':Contract.from_okx(MARKET)}
        assert not await sync.history('fills',full=True,page_budget=1)
        first_end=repo.scans()[0]['end_ms'];now[0]+=5000
        assert await sync.history('fills',full=True,page_budget=1)
        assert calls[-1]['after']=='10' and calls[-1]['end']==str(first_end)
        assert len(repo.facts('fills'))==1
        assert repo.gaps()[0]['reason']=='EXCHANGE_RETENTION_LIMIT'
    asyncio.run(run())


def test_repeated_page_stalls_without_false_complete_or_duplicate_fill(tmp_path):
    async def run():
        now=ms('2026-10-25');repo=AccountRepository(tmp_path);repo.bind('123','a'*32,three_months_before(now))
        class Client:
            async def privateGetTradeFillsHistory(self,params):
                return {'code':'0','data':[fill_row(now-1000)]}
        sync=AccountSynchronizer(repo,Client(),now_ms=lambda:now);sync.contracts={'BTC-USDT-SWAP':Contract.from_okx(MARKET)}
        with pytest.raises(AccountDataError,match='CURSOR_STALLED'):
            await sync.history('fills',full=True)
        assert len(repo.facts('fills'))==1 and not repo.coverage()
    asyncio.run(run())


def test_network_failure_then_repository_restart_resumes_committed_page(tmp_path):
    async def run():
        now=ms('2026-10-25');repo=AccountRepository(tmp_path);repo.bind('123','a'*32,three_months_before(now))
        class Client:
            failing=True
            async def privateGetTradeFillsHistory(self,params):
                if params.get('after'):
                    if self.failing:raise ConnectionError('fixture')
                    return {'code':'0','data':[]}
                return {'code':'0','data':[fill_row(now-1000)]}
        client=Client();sync=AccountSynchronizer(repo,client,now_ms=lambda:now);sync.contracts={'BTC-USDT-SWAP':Contract.from_okx(MARKET)}
        with pytest.raises(ConnectionError):await sync.history('fills',full=True)
        assert not repo.coverage()
        client.failing=False
        restarted=AccountSynchronizer(AccountRepository(tmp_path),client,now_ms=lambda:now);restarted.contracts=sync.contracts
        assert await restarted.history('fills',full=True)
        assert len(repo.facts('fills'))==1 and len(repo.coverage())==1
    asyncio.run(run())


def test_expired_recheck_keeps_saved_coverage_and_starts_a_new_scan(tmp_path):
    async def run():
        old_now=ms('2026-05-01');new_now=ms('2026-10-25')
        repo=AccountRepository(tmp_path);repo.bind('123','a'*32,three_months_before(old_now))
        repo.start_scan('fills',three_months_before(old_now),old_now)
        repo.page('fills',None,[],next_cursor=None,complete=True)
        repo.start_scan('fills',three_months_before(old_now),old_now)
        calls=[]
        class Client:
            async def privateGetTradeFillsHistory(self,params):
                calls.append(params);return {'code':'0','data':[]}
        sync=AccountSynchronizer(repo,Client(),now_ms=lambda:new_now)
        assert await sync.history('fills',full=True)
        assert calls[0]['begin']==str(three_months_before(new_now))
        assert repo.coverage()[0]['end_ms']==old_now
        assert repo.gaps()[0]['start_ms']==old_now+1
    asyncio.run(run())


def test_recent_activity_is_visible_without_advancing_unfinished_backfill(tmp_path):
    async def run():
        now = ms('2026-10-25')
        repo = AccountRepository(tmp_path)
        repo.bind('123', 'a'*32, three_months_before(now))
        repo.start_scan('fills', three_months_before(now), now-10000)
        old_scan = repo.scans()
        class Client:
            async def privateGetTradeFillsHistory(self, params):
                return {'code':'0','data':[fill_row(now-1000)]}
            async def privateGetAccountBillsArchive(self, params):
                return {'code':'0','data':[]}
            async def privateGetTradeOrdersHistoryArchive(self, params):
                return {'code':'0','data':[]}
        sync = AccountSynchronizer(repo, Client(), now_ms=lambda:now)
        sync.contracts = {'BTC-USDT-SWAP':Contract.from_okx(MARKET)}
        await sync.recent()
        await sync.recent()
        assert len(repo.facts('fills')) == 1
        assert repo.scans() == old_scan and repo.coverage() == []
    asyncio.run(run())


def test_malformed_financial_record_is_preserved_without_cursor_or_projection(tmp_path):
    async def run():
        now = ms('2026-10-25')
        repo = AccountRepository(tmp_path)
        repo.bind('123', 'a'*32, three_months_before(now))
        class Client:
            async def privateGetTradeFillsHistory(self, params):
                return {'code':'0','data':[{**fill_row(now-1000),'fee':[]}]}
        sync = AccountSynchronizer(repo, Client(), now_ms=lambda:now)
        sync.contracts = {'BTC-USDT-SWAP':Contract.from_okx(MARKET)}
        with pytest.raises(AccountDataError, match='INVALID_DECIMAL'):
            await sync.history('fills', full=True)
        assert repo.facts('fills') == [] and repo.coverage() == []
        assert repo.scans()[0]['cursor'] is None
        with repo.connection() as db:
            assert '"fee":[]' in db.execute('SELECT body FROM raw_fact').fetchone()[0]
    asyncio.run(run())
