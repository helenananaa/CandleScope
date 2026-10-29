"""Cross-venue admission, raw pagination, event ordering and completeness."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.exchanges import bootstrap_default_adapters
from app.exchanges.ccxt_ext import trade_candles as engine
from app.exchanges.ccxt_ext.catalog import build_ccxt_capabilities, get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.trade_sources import fetch_public_trades
from app.exchanges.trade_candles import TRADE_CANDLE_PROFILES, supports_trade_candles
from app.data_engine.interval_resolution import IntervalResolver
from app.data_engine.ingestion.models import StreamDescriptor, StreamType, TransportRequest

START = 1_793_232_000_000


def req(venue, market="spot", start=START, end=START + 2000):
    return TransportRequest(StreamDescriptor("BTC/USD", StreamType.KLINE, interval="1s", exchange=venue, market_type=market),
                            start_ms=start, end_ms=end, limit=100)


def fake(method, handler, **market):
    calls = []
    async def call(params):
        calls.append(params)
        return handler(params)
    return SimpleNamespace(market=lambda _: {"id": "BTC", "spot": True, **market}, calls=calls, **{method: call})


@pytest.mark.parametrize("venue", TRADE_CANDLE_PROFILES)
def test_catalog_admission_and_native_priority(venue):
    bootstrap_default_adapters()
    entry = get_ccxt_catalog_entry(venue)
    caps = build_ccxt_capabilities(entry)
    markets = caps.limits["trade_candles.markets"]
    assert markets
    for market in markets:
        assert supports_trade_candles(venue, market)
        route = IntervalResolver().resolve(exchange=venue, market_type=market, interval="7s", purpose="history")
        assert route.kind.value == "trade"
        native = IntervalResolver().resolve(exchange=venue, market_type=market, interval="1m", purpose="history")
        assert native.kind.value == "native"
    assert not supports_trade_candles(venue, "option")


@pytest.mark.anyio
async def test_time_partition_keeps_same_timestamp_trades_and_reduces_only_once(monkeypatch):
    monkeypatch.setattr(engine, "PAGE_SIZE", 3)
    tape = [[9, START + 500, .1, 12], [10, START + 500, -.2, 10],
            [11, START + 1500, .3, 11], [12, START + 1500, .4, 13]]
    ex = fake("publicGetTradesSymbolHist", lambda p: [r for r in tape if p['start'] <= r[1] <= p['end']][:p['limit']])
    result = await engine.fetch_trade_candles(ex, "BTC/USD", req("bitfinex"), now_ms=START + 10000)
    assert len(ex.calls) > 1
    assert result[0]['value'] == [START, '12', '12', '10', '10', '0.3']
    assert result[1]['value'] == [START + 1000, '11', '13', '11', '13', '0.7']
    assert result[-1]['trade_candle_page'] == 'bitfinex.spot'
    assert result[-1]['empty_ranges'] == [[START + 2000, START + 2000]]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["saturation", "budget", "ignores_bounds", "later_error", "cancel"])
async def test_incomplete_windows_never_publish(monkeypatch, failure):
    import asyncio
    monkeypatch.setattr(engine, 'PAGE_SIZE', 2)
    if failure == 'budget': monkeypatch.setattr(engine, 'MAX_TRADE_PAGES', 1)
    def handler(p):
        if failure == 'ignores_bounds': return [[1, START + 90000, 1, 10]]
        if len(ex.calls) > 1:
            if failure == 'later_error': raise RuntimeError('network')
            if failure == 'cancel': raise asyncio.CancelledError()
        ms = START if failure == 'saturation' else p['start']
        return [[1, ms, 1, 10], [2, ms, 1, 12]]
    ex = fake('publicGetTradesSymbolHist', handler)
    with pytest.raises((ValueError, RuntimeError, asyncio.CancelledError)):
        await engine.fetch_trade_candles(ex, 'BTC/USD', req('bitfinex'), now_ms=START + 10000)


@pytest.mark.anyio
async def test_bitvavo_preserves_source_order_with_uuid_ids():
    rows = [{'id': 'a-later', 'timestamp': START, 'price': '11', 'amount': '2'},
            {'id': 'z-earlier', 'timestamp': START, 'price': '10', 'amount': '1'}]
    ex = fake('publicGetMarketTrades', lambda _: rows)
    result = await engine.fetch_trade_candles(ex, 'BTC/USD', req('bitvavo'), now_ms=START + 10000)
    assert result[0]['value'] == [START, '10', '11', '10', '11', '3']


@pytest.mark.anyio
@pytest.mark.parametrize('venue,market,inverse,volume', [
    ('binanceusdm', 'swap.linear', False, '2'), ('binancecoinm', 'swap.inverse', True, '0.02'),
])
async def test_binance_volume_and_bounds(venue, market, inverse, volume):
    method = 'dapiPublicGetAggTrades' if inverse else 'fapiPublicGetAggTrades'
    ex = fake(method, lambda _: [{'a': 9, 'T': START, 'p': '10000', 'q': '2'}], inverse=inverse, spot=False, contractSize=100)
    result = await engine.fetch_trade_candles(ex, 'BTC/USD', req(venue, market), now_ms=START + 10000)
    assert result[0]['value'][-1] == volume
    assert ex.calls[0]['endTime'] == START + 2999


@pytest.mark.anyio
async def test_deribit_exhaustion_sequence_and_inverse_notional():
    rows = [dict(trade_id='BTC-9', trade_seq=9, timestamp=START, instrument_name='BTC', price='10000', amount='100'),
            dict(trade_id='BTC-10', trade_seq=10, timestamp=START, instrument_name='BTC', price='20000', amount='100')]
    ex = fake('publicGetGetLastTradesByInstrumentAndTime', lambda _: {'result': {'has_more': False, 'trades': rows}}, inverse=True)
    result = await engine.fetch_trade_candles(ex, 'BTC/USD', req('deribit', 'swap.inverse'), now_ms=START + 10000)
    assert result[0]['value'] == [START, '10000', '20000', '10000', '20000', '0.015']
    ex = fake('publicGetGetLastTradesByInstrumentAndTime', lambda _: {'result': {'trades': []}})
    with pytest.raises(ValueError, match='exhaustion'):
        await engine.fetch_trade_candles(ex, 'BTC/USD', req('deribit', 'swap.inverse'), now_ms=START + 10000)


@pytest.mark.anyio
async def test_kraken_futures_volume_and_identity():
    trade = dict(uid='execution-id', timestamp=START, price='10000', quantity='2',
                 makerOrder={'tradeable':'BTC'}, takerOrder={'tradeable':'BTC'})
    ex = fake('historyGetMarketSymbolExecutions', lambda _: {'len':1,'elements':[{'event':{'Execution':{'execution':trade}}}]}, inverse=True, contractSize=1)
    result = await engine.fetch_trade_candles(ex, 'BTC/USD', req('krakenfutures','swap.inverse'), now_ms=START + 10000)
    assert result[0]['value'][-1] == '0.0002'
    trade['takerOrder']['tradeable'] = 'WRONG'
    with pytest.raises(ValueError, match='market mismatch'):
        await engine.fetch_trade_candles(ex, 'BTC/USD', req('krakenfutures','swap.inverse'), now_ms=START + 10000)


@pytest.mark.anyio
async def test_coinbase_cursor_consumes_all_boundary_trades(monkeypatch):
    monkeypatch.setattr(engine, 'PAGE_SIZE', 2)
    def row(i, offset):
        return dict(trade_id=i, time=datetime.fromtimestamp((START + offset)/1000, timezone.utc).isoformat().replace('+00:00','Z'), price=str(i),size='1')
    pages=iter([[row(10,1),row(9,0)], [row(8,0),row(7,-1)]])
    ex=fake('publicGetProductsIdTrades',lambda _:next(pages))
    result=await engine.fetch_trade_candles(ex,'BTC/USD',req('coinbaseexchange'),now_ms=START+10000)
    assert ex.calls[1]['after']=='9'
    assert result[0]['value']==[START,'8','10','8','10','3']


@pytest.mark.anyio
@pytest.mark.parametrize('rows', [[], [dict(trade_id=10,time='2026-10-28T23:59:59Z',price='10',size='1')]])
async def test_coinbase_missing_history_and_stalled_cursor_fail(rows):
    ex=fake('publicGetProductsIdTrades',lambda _:rows)
    with pytest.raises(ValueError):
        await engine.fetch_trade_candles(ex,'BTC/USD',req('coinbaseexchange',start=START-86_400_000),now_ms=START+10000)


def bitget_row(i, ms, p='10'):
    return dict(symbol='BTC',tradeId=str(i),ts=str(ms),price=p,size='1')


@pytest.mark.anyio
async def test_bitget_history_lag_cannot_certify_empty_window():
    async def recent(_): return {'code':'00000','data':[bitget_row(100,START+1500)]}
    async def history(_): return {'code':'00000','data':[bitget_row(80,START-10000)]}
    ex=SimpleNamespace(market=lambda _:{'id':'BTC','spot':True},publicSpotGetV2SpotMarketFills=recent,publicSpotGetV2SpotMarketFillsHistory=history)
    with pytest.raises(ValueError,match='not caught up'):
        await engine.fetch_trade_candles(ex,'BTC/USD',req('bitget'),now_ms=START+10000)


@pytest.mark.anyio
async def test_bitget_recent_and_history_join_without_counting_partial_boundary_twice():
    async def recent(_): return {'code':'00000','data':[bitget_row(101,START+2100,'12'),bitget_row(100,START+1500,'11')]}
    async def history(p):
        rows=[bitget_row(102,START+3000)] if p['limit']==1 else [bitget_row(100,START+1500,'11'),bitget_row(99,START+1500,'10'),bitget_row(98,START,'9')]
        return {'code':'00000','data':rows}
    ex=SimpleNamespace(market=lambda _:{'id':'BTC','spot':True},publicSpotGetV2SpotMarketFills=recent,publicSpotGetV2SpotMarketFillsHistory=history)
    result=await engine.fetch_trade_candles(ex,'BTC/USD',req('bitget'),now_ms=START+10000)
    assert [r['value'][-1] for r in result[:-1]]==['1','2','1']
    assert result[1]['value'][1:5]==['10','11','10','11']


@pytest.mark.anyio
async def test_crypto_preserves_nanosecond_order_and_default_cap():
    rows=[dict(d='10',t=START,tn=START*1_000_000+20,p='11',q='1',i='BTC'),dict(d='9',t=START,tn=START*1_000_000+10,p='10',q='2',i='BTC')]
    ex=fake('v1PublicGetPublicGetTrades',lambda _:{'code':0,'result':{'data':rows}})
    result=await engine.fetch_trade_candles(ex,'BTC/USD',req('cryptocom'),now_ms=START+10000)
    assert ex.calls[0]['count']==25
    assert result[0]['value']==[START,'10','11','10','11','3']


@pytest.mark.anyio
@pytest.mark.parametrize('venue,market', [('bitget','spot'),('binancecoinm','swap.inverse'),('binanceusdm','swap.linear'),('deribit','swap.inverse'),('cryptocom','spot')])
async def test_retention_rejected_before_io(venue,market):
    with pytest.raises(ValueError,match='retention'):
        await engine.fetch_trade_candles(None,'BTC/USD',req(venue,market),now_ms=START+1000*86_400_000)


@pytest.mark.anyio
async def test_deribit_old_empty_responses_cannot_certify_history():
    # Current public API can return an empty success for older trades. The
    # admitted one-day boundary must reject that range before issuing I/O.
    with pytest.raises(ValueError, match='retention'):
        await engine.fetch_trade_candles(None, 'BTC/USD', req('deribit', 'swap.inverse'),
                                         now_ms=START + 2 * 86_400_000)


@pytest.mark.anyio
async def test_large_custom_bucket_uses_bounded_time_windows():
    ex=fake('publicGetTradesSymbolHist',lambda p:[[p['start'],p['start'],1,10]])
    trades=await fetch_public_trades(ex,'BTC/USD','bitfinex',START,START+61000,now_ms=START+100000)
    assert len(ex.calls)==2 and len(trades)==2
    assert max(p['end']-p['start'] for p in ex.calls)<60000


def test_history_policy_clips_trade_retention_without_clipping_native_candles():
    from app.data_engine.history.exchange_policy import ExchangeHistoryPolicyResolver
    from app.data_engine.history.service import HistoryAvailabilityService
    resolver = ExchangeHistoryPolicyResolver(HistoryAvailabilityService(), symbol_lookup=lambda *_: None)
    for venue,market,days in [('bitget','spot',90),('binancecoinm','swap.inverse',2),('cryptocom','spot',1),('deribit','swap.inverse',1)]:
        key = resolver.series_key(exchange=venue,market_type=market,symbol='BTC/USD',variant='7s')
        result = resolver.resolve(key,now_ms=START)
        assert result.availability.rolling_retention_ms == days * 86_400_000
        native_key = resolver.series_key(exchange=venue,market_type=market,symbol='BTC/USD',variant='1m')
        native = resolver.resolve(native_key,now_ms=START)
        assert native.availability.rolling_retention_ms is None


def test_empty_evidence_is_isolated_between_sources_and_invalidated_on_late_trade(tmp_path,monkeypatch):
    from app.data_engine.storage import klines_repo,trade_empty_buckets
    monkeypatch.setattr(klines_repo,'KLINES_DB_PATH',tmp_path/'bars.sqlite')
    klines_repo.init_klines_storage()
    trade_empty_buckets.invalidate()
    keys=[('bitfinex','spot','BTC/USD','1s'),('coinbaseexchange','spot','BTC/USD','1s')]
    calendars=[]
    for key in keys:
        trade_empty_buckets.record(*key,[[START,START+2000]])
        calendars.append(trade_empty_buckets.make_calendar(*key))
    assert all(c.count_expected(START,START+2000,'1s')==0 for c in calendars)
    row=dict(open_time=START+1000,close_time=START+1999,open=10,high=10,low=10,close=10,volume=1,quote_volume=0,trades=0,taker_buy_base=0,taker_buy_quote=0)
    store=klines_repo.KlinesRepoAdapter()
    count=store.upsert_bars('BTC/USD','1s',[row],'trade_history_verified','bitfinex','spot')
    assert count==1  # SQL trigger changes must not inflate persisted candle count.
    assert calendars[0].count_expected(START,START+2000,'1s')>0
    assert calendars[1].count_expected(START,START+2000,'1s')==0
    klines_repo.delete_klines('BTC/USD','1s',exchange='bitfinex',market_type='spot')
    assert not trade_empty_buckets.read(*keys[0],START,START+2000)
    assert trade_empty_buckets.read(*keys[1],START,START+2000)


@pytest.mark.parametrize('venue,market,symbol',[('deribit','swap.inverse','BTC/USD:BTC'),('bitget','swap.linear','BTC/USDT:USDT'),('bitget','future.inverse','BTC/USD:BTC-261225'),('krakenfutures','swap.linear','BTC/USD:USD'),('binancecoinm','future.inverse','BTC/USD:BTC-261225')])
def test_manual_download_accepts_admitted_contract_market(venue,market,symbol):
    from app.data_engine.manual_history.planner import ManualHistoryPlanner
    plan = ManualHistoryPlanner(archive_enabled=False,disk_snapshot=lambda:{'free_bytes':10**12,'physical_size_bytes':0}).plan(
        exchange=venue,market_type=market,symbols=[symbol],intervals=['7s'],start_ms=START-70000,now_ms=START)
    assert plan['can_start'],plan
    assert plan['targets'][0]['source_interval']=='7s'
    assert plan['selection']['market_type']==market


def test_manual_download_clips_trade_retention_before_estimating_work():
    from app.data_engine.manual_history.planner import ManualHistoryPlanner
    plan=ManualHistoryPlanner(archive_enabled=False,disk_snapshot=lambda:{'free_bytes':10**12,'physical_size_bytes':0}).plan(
        exchange='binancecoinm',market_type='swap.inverse',symbols=['BTC/USD:BTC'],intervals=['7s'],start_ms=START-3*86_400_000,now_ms=START)
    target=plan['targets'][0]
    assert plan['can_start'] and target['boundary_reason']=='provider_retention'
    assert target['effective_start_ms']>=START-2*86_400_000
    assert target['effective_start_ms']%7000==0
