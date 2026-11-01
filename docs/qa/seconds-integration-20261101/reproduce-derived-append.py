"""Real backfill engine/SQLite: a disjoint live append before derived commit."""
import asyncio
import json
from pathlib import Path
import tempfile

from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import acquisition_scope
from app.data_engine.backfill import BackfillEngine, BackfillConfig
from app.data_engine.backfill.models import GapInfo, GapType
from tests.test_binance_backfill_fetcher import _FakeBinanceTransport, _make_binance_rows


class Detector:
    async def detect(self, **kwargs):
        return [GapInfo(symbol='BTCUSDT', interval='7s', gap_type=GapType.INTERIOR,
                        start_ms=91000, end_ms=98000, missing_bars=2,
                        exchange='binance', market_type='spot')]


async def probe(inject, database):
    klines_repo.KLINES_DB_PATH=database
    klines_repo.init_klines_storage()
    class Storage(klines_repo.AsyncKlinesRepoAdapter):
        async def upsert_bars(self, symbol, interval, rows, source='backfill', **kwargs):
            count=await super().upsert_bars(symbol,interval,rows,source,**kwargs)
            if inject and interval=='1s' and source=='backfill':
                # The repair accepted its source page. A distinct live owner
                # appends far beyond both complete historical output buckets.
                with acquisition_scope(None):
                    klines_repo.upsert_klines(symbol,'1s',[dict(
                        open_time=200000,close_time=200999,open=100,high=110,
                        low=90,close=105,volume=1.5,quote_volume=157.5,trades=10,
                        taker_buy_base=.75,taker_buy_quote=78.75)],
                        source='data_manager_exchange_closed')
            return count
    engine=BackfillEngine(BackfillConfig(fetch_rate_limit_delay=0),storage=Storage(),
                         transport=_FakeBinanceTransport(_make_binance_rows(106,1000)))
    # This transport is synthetic and performs no exchange request. Do not
    # consume or depend on the real host-wide public HTTP admission budget.
    async def no_network_admission(*args):
        pass
    engine.fetcher._rate_limit_admission=no_network_admission
    engine.fetcher._rate_limit=no_network_admission
    engine._detector=Detector()
    try:
        report=await engine.run('BTCUSDT',['7s'],91000,98000)
        return dict(injected_disjoint_live_append=inject,status=report.status.value,
                    errors=report.errors,custom_rows=klines_repo.query_klines('BTCUSDT','7s'),
                    native_rows=len(klines_repo.query_klines('BTCUSDT','1s')),
                    metrics=engine.reconciler.snapshot())
    finally:
        await engine.close()


async def main():
    with tempfile.TemporaryDirectory() as root:
        output=[await probe(flag,Path(root)/(str(flag)+'.sqlite')) for flag in (False,True)]
    assert len(output[0]['custom_rows'])==2,output
    assert not output[1]['custom_rows'] and any('changed after acquisition' in e for e in output[1]['errors']),output
    print(json.dumps(output,indent=2))


if __name__=='__main__':
    asyncio.run(main())
