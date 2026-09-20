from decimal import Decimal
import io
import json
import tarfile
import zipfile
import pytest
from app.market_dataset.snapshot import MarketEvent, MarketDatasetError
from app.simulation.sampled_book_kernel import SampledBookKernel
from app.simulation.depth_kernel import DepthQueueKernel
from app.backtest.external_market import validate_execution
from app.backtest.errors import BacktestError
from app.backtest.external_orders import ExternalOrders
from scripts.prepare_okx_sampled_backtest import convert


def book(index=1, time=1000, source_time=None, **extra):
    return MarketEvent(index, time, 'ORDER_BOOK', dict(sample_index=index, sample_time_ms=time if source_time is None else source_time,
        snapshot=True, depth_complete=False, depth_scope='BOUNDED_SAMPLED', bids=[['9','10'],['8','20']], asks=[['10','2'],['11','3']], **extra))


def setup():
    kernel = SampledBookKernel(slippage_bps=Decimal(0), taker_fee_bps=Decimal(0))
    orders = ExternalOrders(kernel, fidelity='BOOK_SAMPLED')
    orders.configure(4)
    kernel._apply_book(book())
    kernel.account.mark = Decimal(10)
    return kernel, orders


def enqueue(kernel, orders, **extra):
    intent = dict(action='entry', id='A', direction='long', qty=7, **extra)
    kernel._enqueue_many(orders.translate([intent], 1), current_sequence=1)


def trade(kernel, time=1001, seq=2, price=10):
    event = MarketEvent(seq, time, 'TRADES', dict(price=str(price), qty='100', aggressor_side='SELL'))
    kernel._last_event = event
    kernel.account.mark = Decimal(price)
    kernel._match(event)


def test_bounded_depth_does_not_invent_liquidity_or_passive_priority():
    kernel, orders = setup(); enqueue(kernel, orders)
    trade(kernel)
    assert [(f.price, f.qty) for f in kernel.fills] == [(10,2),(11,3)]
    kernel._apply_book(book(2, 2000)); trade(kernel, 2001, 3)
    assert len(kernel.fills) == 2 and kernel.orders[0].qty == 2
    passive, orders = setup(); enqueue(passive, orders, limit=9)
    trade(passive, price=9)
    assert not passive.fills
    changed = book(2,2000); changed.payload.update(bids=[['7','10']], asks=[['9','1']])
    passive._apply_book(changed); trade(passive,2001,3,9)
    assert [(f.price, f.qty) for f in passive.fills] == [(9,1)]


def test_stale_and_same_ms_books_never_fill_but_stops_observe_prices():
    kernel, orders = setup(); enqueue(kernel, orders, stop=12)
    trade(kernel,1000,2,12)
    assert not kernel.fills and kernel.orders[0].activated
    trade(kernel,3001,3,10)
    assert not kernel.fills and kernel.stale_trade_events == 1
    kernel._apply_book(book(2,4000)); trade(kernel,4001,4,10)
    assert sum(f.qty for f in kernel.fills) == 5


@pytest.mark.parametrize('mutation', [dict(depth_complete=True), dict(book_sequence=123), dict(sample_time_ms=2000), dict(sample_index=0)])
def test_wrong_scope_future_or_forged_sequence_rejected(mutation):
    event = book(); event.payload.update(mutation)
    with pytest.raises(MarketDatasetError): SampledBookKernel()._apply_book(event)


def test_sampled_data_cannot_enter_full_depth_and_partial_invalid_update_is_atomic():
    with pytest.raises(MarketDatasetError, match='book_sequence'): DepthQueueKernel()._apply_book(book())
    kernel, _ = setup()
    bad = book(2, 2000); bad.payload['asks'] = [['8','1']]
    with pytest.raises(MarketDatasetError, match='uncrossed'): kernel._apply_book(bad)
    assert kernel.sample_time_ms == 1000 and kernel.book_sequence == 1


def archives(tmp_path, gap=False):
    path = tmp_path/'book.tar.gz'
    rows = [dict(instId='BTC-USDT', action='snapshot', ts='59000', bids=[['9','5','1']], asks=[['10','5','1']]),
            dict(instId='BTC-USDT', action='update', ts='60000', bids=[], asks=[['10','0','0'],['11','2','1']])]
    data = '\n'.join(json.dumps(r) for r in rows).encode()
    with tarfile.open(path,'w:gz') as tar:
        info = tarfile.TarInfo('book.data'); info.size=len(data); tar.addfile(info,io.BytesIO(data))
    trade_path=tmp_path/'trades.zip'
    with zipfile.ZipFile(trade_path,'w') as z:
        z.writestr('trades.csv','instrument_name,trade_id,side,price,size,created_time\nBTC-USDT,1,buy,10,1,60000\n'
                   f'BTC-USDT,{3 if gap else 2},sell,11,2,61000\n')
    return path,[trade_path]


def test_import_uses_prior_seed_trade_before_same_ms_sample_and_exact_print_bars(tmp_path):
    paths=archives(tmp_path)
    bars, data=convert(*paths,60000,120000)
    assert bars[0] == dict(time=60000,open=10,high=11,low=10,close=11,volume=3)
    assert [e['role'] for e in data['events']] == ['ORDER_BOOK','TRADES','ORDER_BOOK','TRADES']
    assert data['events'][0]['payload']['sample_time_ms'] == 59000
    events=[MarketEvent(i+1,e['time_ms'],e['role'],e['payload']) for i,e in enumerate(data['events'])]
    normalized=[{k:float(v) if k!='time' else v//1000 for k,v in b.items()} for b in bars]
    validate_execution(events,normalized,'1m','BOOK_SAMPLED')
    events[1],events[2]=events[2],events[1]
    with pytest.raises(BacktestError,match='same-ms'): validate_execution(events,normalized,'1m','BOOK_SAMPLED')


def test_import_rejects_trade_gaps_and_missing_prior_seed(tmp_path):
    paths=archives(tmp_path,gap=True)
    with pytest.raises(ValueError,match='Trade ID gap'): convert(*paths,60000,120000)
    with pytest.raises(ValueError,match='prior book'): convert(*paths,0,60000)
