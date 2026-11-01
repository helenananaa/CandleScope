"""Account status must be one SQLite snapshot during a concurrent sync commit."""
import asyncio
import json
import threading
from contextlib import contextmanager

from app.readonly_accounts.service import ReadOnlyAccountService


def test_status_does_not_mix_account_and_fact_coverage_generations(tmp_path, monkeypatch):
    async def run():
        service=ReadOnlyAccountService(tmp_path)
        repo=service.repository
        repo.bind('fixture-account','fixture-credential',0)
        repo.status('old')
        original=repo.connection
        read_started=threading.Event();committed=threading.Event();errors=[]
        class Connection:
            def __init__(self, db): self.db=db
            def execute(self, sql, *args):
                if 'COUNT(*)' in sql and 'fact' in sql:
                    assert committed.wait(5)
                cursor=self.db.execute(sql,*args)
                if sql.startswith('SELECT * FROM account'):
                    read_started.set()
                    assert committed.wait(5)
                return cursor
            def __getattr__(self,name):return getattr(self.db,name)
        @contextmanager
        def connection():
            with original() as db: yield Connection(db)
        monkeypatch.setattr(repo,'connection',connection)
        def writer():
            try:
                assert read_started.wait(5)
                with original() as db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute("UPDATE account SET status='new'")
                    db.execute("INSERT INTO fact VALUES('fills','1',10,?, 'hash')",(json.dumps({'fillId':'1','eventTimeMs':10,'contracts':'0.1234567890123456789'}),))
                    db.execute("INSERT INTO coverage VALUES('fills',0,10,11)")
                    db.commit()
            except BaseException as exc:errors.append(exc)
            finally:committed.set()
        thread=threading.Thread(target=writer);thread.start()
        try:
            view=await service.state()
            thread.join(5);assert not thread.is_alive() and not errors
            assert view['account']['status']=='old'
            assert view['counts']=={} and view['coverage']==[]
            assert 'credential_id' not in view['account']
            current=await service.state()
            assert current['account']['status']=='new'
            assert current['counts']=={'fills':1} and len(current['coverage'])==1
            assert repo.facts('fills')[0]['contracts']=='0.1234567890123456789'
        finally:
            committed.set();thread.join(5);await service.close()
    asyncio.run(run())
