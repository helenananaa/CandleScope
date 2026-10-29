"""Public OKX close/reconnect evidence; no credentials, fixture instrument metadata."""
import asyncio
import json
import time

from app.data_engine.bar_basis import native_bar_spec
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import StreamDescriptor, StreamType, RawMessage, DataSource
from app.exchanges.ccxt_ext.profiles import OkxSpotCcxtProfile, OkxSwapCcxtProfile
from app.exchanges.plugins.okx.normalizer import OkxNormalizer


async def probe(cls):
    profile = cls()
    spot = profile.market_type == 'spot'
    symbol = 'BTC/USDT' if spot else 'BTC/USDT:USDT'
    native = 'BTC-USDT' if spot else 'BTC-USDT-SWAP'
    descriptor = StreamDescriptor(native, StreamType.KLINE, interval='1m', exchange='okx', market_type=profile.market_type)
    normalizer = OkxNormalizer(IngestionConfig(), descriptor)
    result = dict(market=profile.market_type, metadata='offline instrument fixture', public_only=True, closed=[], lifecycle=[], errors=[])
    received, closed = asyncio.Event(), asyncio.Event()
    observations = []

    def raw_sink(raw):
        if not profile.matches(raw, descriptor):
            return
        event = normalizer.parse(RawMessage(raw.payload, DataSource.WEBSOCKET, StreamType.KLINE, raw.received_at_ms))
        if event:
            row = event.data
            native_bar_spec('okx', profile.market_type, '1m', 'realtime').validate(row['open_time'], row['close_time'])
            observation = dict(open_time=row['open_time'], close_time=row['close_time'], volume=row['volume'], is_closed=row['is_closed'], received_at=raw.received_at_ms)
            observations.append(observation)
            received.set()
            if row['is_closed']:
                result['closed'].append(observation)
                closed.set()

    def lifecycle(event):
        result['lifecycle'].append(dict(state=event.state, at=event.observed_at_ms))

    exchange = profile.create_exchange(IngestionConfig(proxy_mode='none'), raw_event_sink=raw_sink, lifecycle_sink=lifecycle)
    exchange.set_markets([dict(id=native, symbol=symbol, base='BTC', quote='USDT', baseId='BTC', quoteId='USDT',
        type='spot' if spot else 'swap', spot=spot, swap=not spot, future=False, option=False, contract=not spot,
        linear=not spot, inverse=False, settle=None if spot else 'USDT', settleId=None if spot else 'USDT')])
    async def load(*args, **kwargs):
        return exchange.markets
    exchange.load_markets = load
    stopped = False
    async def watch():
        while not stopped:
            try:
                await profile.watch(exchange, descriptor, symbol)
            except Exception as exc:
                result['errors'].append(type(exc).__name__)
                await asyncio.sleep(0.2)
    task = asyncio.create_task(watch())
    try:
        await asyncio.wait_for(received.wait(), 20)
        await asyncio.wait_for(closed.wait(), 75)
        received.clear()
        result['disconnect_at'] = int(time.time() * 1000)
        sockets = [client.connection for client in exchange.clients.values() if client.connection and not client.connection.closed]
        result['forced_sockets'] = len(sockets)
        # Abort the actual transport, leaving the same CCXT instance/watch loop.
        for socket in sockets:
            socket._response.connection.transport.abort()
        async def recovered():
            while True:
                after = [row for row in observations if row['received_at'] > result['disconnect_at']]
                if after and sum(event['state'] == 'connected' for event in result['lifecycle']) >= 2:
                    return after
                received.clear()
                await received.wait()
        after = await asyncio.wait_for(recovered(), 30)
        result['recovered'] = after[-1] if after else None
        result['pass'] = bool(result['closed'] and sockets and after)
        result['observations'] = len(observations)
        result['cache_intervals'] = sorted(exchange.ohlcvs.get(symbol, {}))
    except Exception as exc:
        result['pass'] = False
        result['failure'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        stopped = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await exchange.close()
    return result


async def main():
    print(json.dumps(await asyncio.gather(probe(OkxSpotCcxtProfile), probe(OkxSwapCcxtProfile)), indent=2))

if __name__ == '__main__':
    asyncio.run(main())
