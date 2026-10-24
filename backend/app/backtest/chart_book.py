"""Freeze chart OHLCV, physical book data and historical account roles together."""
from copy import deepcopy
import hashlib
import json

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent, sha256_hex
from app.market_dataset.trades import assert_trade_stream
from app.market_dataset.models import DatasetRef
from app.local_data.service import LocalDatasetError
from app.simulation.dual_clock_book import BOOK_MODES, validate_assisted_quote
from .errors import BacktestError
from .request_contracts import ChartBookData

DUAL_MODES = {'AGG_TRADE_EXECUTION', *BOOK_MODES}
SCHEMA = 'candlescope.chart-book-snapshot/1'


def normalize_data(data, *, max_events=500_000, max_bytes=64*1024*1024):
    if data is None:
        raise BacktestError('DATA_ROLE_MISSING', 'chart book execution requires frozen execution_data')
    try:
        model = ChartBookData.model_validate(data)
        if len(model.events) > max_events:
            raise BacktestError('BUDGET_EXCEEDED', 'chart book event ceiling exceeded')
        result = model.model_dump()
        raw = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError) as exc:
        if isinstance(exc, BacktestError):
            raise
        raise BacktestError('DATA_QUALITY_FAILED', 'invalid frozen chart book input') from exc
    if len(raw) > max_bytes:
        raise BacktestError('BUDGET_EXCEEDED', 'frozen chart book input exceeds worker memory ceiling')
    for row in result['events']:
        if row['role'] == 'TRADES':
            source = row['payload'].get('source_sequence')
            if type(source) is not int or source < 0:
                raise BacktestError('DATA_QUALITY_FAILED', 'chart prints require explicit integer source_sequence')
    return result, 'sha256:' + hashlib.sha256(raw).hexdigest()


def freeze(runtime, config, *, allow_incomplete_contract=False):
    from .runtime import _bar_wire, _snapshot_wire, _renumber_timeline, _required_contract_roles
    from .external_market import validate_execution
    mode = config['fidelity_mode']
    if mode not in BOOK_MODES:
        raise BacktestError('FIDELITY_UNSUPPORTED', 'frozen book data requires a chart book mode')
    data, data_hash = normalize_data(config.get('execution_data'),
        max_events=runtime.settings.max_trade_events,
        max_bytes=runtime.settings.worker_memory_mb*1024*1024)
    try:
        manifest = runtime.local_data.get_manifest(str(config['dataset_id']))
    except LocalDatasetError as exc:
        raise BacktestError(exc.code,str(exc)) from exc
    identity = (str(config.get('exchange') or 'binance'),str(config.get('market_type') or 'usdm'),str(manifest['symbol']))
    if (data['exchange'],data['market_type'],data['symbol']) != identity:
        raise BacktestError('DATA_SNAPSHOT_MISMATCH', 'book market identity differs from the chart')
    interval = str(config.get('signal_interval') or config.get('interval') or manifest['interval'])
    roles=('BARS',)
    if config.get('contract_data_mode')=='HISTORICAL_CONTRACT_V1':
        roles+=_required_contract_roles(str(config.get('account_model') or 'LINEAR_PERP_ONE_WAY_V1'),
            str(config.get('funding_mode') or 'OFF'))
    ref=DatasetRef(dataset_id=str(config['dataset_id']),data_epoch=str(config['data_epoch']),snapshot_hash='',
        venue=identity[0],market_type=identity[1],symbol=identity[2],start_time_ms=int(config['start_time_ms']),
        end_time_ms=int(config['end_time_ms']),roles=roles,interval=interval,calendar_id='UTC_FIXED',
        source='local_immutable',retention_policy='user_local')
    try:
        snapshot = runtime.snapshots.open(ref,allow_incomplete_contract=allow_incomplete_contract)
        try:
            bars = [_bar_wire(event) for event in snapshot.events if event.role=='BARS']
            if not bars:
                raise BacktestError('DATA_QUALITY_FAILED', 'chart book snapshot contains no complete bars')
            events = tuple(MarketEvent(index+1,row['time_ms'],row['role'],deepcopy(row['payload']))
                for index,row in enumerate(data['events']))
            if assert_trade_stream(tuple(event for event in events if event.role=='TRADES')) != 'AGG_TRADE':
                raise BacktestError('FIDELITY_MISLABEL', 'chart book clock requires aggregate prints')
            if mode=='BOOK_ASSISTED':
                sequence=None
                for event in events:
                    if event.role=='ORDER_BOOK': sequence=validate_assisted_quote(event.payload,sequence)
            try:
                validate_execution(events,bars,interval,mode)
            except (BacktestError,MarketDatasetError):
                raise
            except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
                raise BacktestError('DATA_QUALITY_FAILED','invalid physical chart book observations') from exc
            preview = _snapshot_wire(snapshot)
            preview.update(snapshot_hash='sha256:'+sha256_hex(dict(schema=SCHEMA,fidelity=mode,
                chart_snapshot=snapshot.snapshot_hash,execution_data=data_hash)),
                fidelity_capabilities=[mode],execution_data_hash=data_hash,
                execution_schema=SCHEMA,execution_row_count=len(events))
            preview['role_hashes'] = {**preview['role_hashes'], **{
                role:'sha256:'+sha256_hex([dict(time_ms=e.event_time_ms,payload=dict(e.payload))
                    for e in events if e.role==role]) for role in ('TRADES','ORDER_BOOK')}}
            preview['quality'] = {**preview['quality'], 'book_execution':dict(status='complete',
                mode=mode,source_kind='AGG_TRADE',row_count=len(events),provenance=data['provenance'])}
            if config.get('account_model')=='LINEAR_PERP_ONE_WAY_V2':
                auxiliary = tuple(event for event in snapshot.events if event.role!='BARS')
                # Preserve physical quote/print source order on ties. The generic
                # contract sorter ranks TRADES ahead of unknown ORDER_BOOK roles.
                tagged = [(event,0,index) for index,event in enumerate(auxiliary)]
                tagged.extend((event,1,index) for index,event in enumerate(events))
                tagged.sort(key=lambda item:(item[0].event_time_ms,item[1],item[2]))
                events = _renumber_timeline(tuple(item[0] for item in tagged))
            if len(events)>runtime.settings.max_trade_events:
                raise BacktestError('BUDGET_EXCEEDED', 'combined chart book/account event ceiling exceeded')
            return preview,events,bars
        finally:
            snapshot.close()
    except MarketDatasetError as exc:
        raise BacktestError(exc.code,exc.message) from exc


def require_identity(record, preview):
    if record['snapshot_hash']!=preview['snapshot_hash'] or record['data_epoch']!=preview['data_epoch']:
        raise BacktestError('DATA_SNAPSHOT_MISMATCH', 'frozen chart/book/account snapshot changed')


def derive_chart_bars(events, interval, end_time_ms):
    from app.simulation.trade_bar_builder import TradeBarBuilder
    builder=TradeBarBuilder(interval)
    result=[]
    for event in events:
        result.extend(builder.push(event) if event.role=='TRADES' else builder.close_before(event.event_time_ms))
    result.extend(builder.close_before(end_time_ms+1))
    return tuple(result)
