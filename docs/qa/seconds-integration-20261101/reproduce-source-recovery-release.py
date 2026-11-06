"""Real batch connection cleanup while its source repair is still pending."""
import asyncio,json
from starlette.websockets import WebSocketDisconnect
from app.api.v1.stream_kline_batch import KlineBatchConnection,KlineBatchLimits,_BatchSubscription
from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.data_manager.continuity import SourceGapRegistry
from app.data_engine.data_manager.models import SeriesKey

async def main():
    key=SeriesKey('BTCUSDT','1s')
    gaps=SourceGapRegistry()
    gap,_=gaps.open(key,1000,1000)
    released=[]
    class Socket:
        def __init__(self):self.input=asyncio.Queue();self.closed=[]
        async def receive_text(self):
            item=await self.input.get()
            if isinstance(item,BaseException):raise item
            return item
        async def close(self,code,reason):
            self.closed.append(dict(code=code,reason=reason))
            await self.input.put(WebSocketDisconnect(code))
    class Manager:
        async def unsubscribe_async(self,handle):pass
        async def release_stream(self,*args,**kwargs):
            # A real DataManager stops the coordinator transport after this
            # client's last registered claim is released (manager.py).
            released.append(dict(source_repair_pending=not gap.future.done(),args=args))
    socket=Socket();connection=KlineBatchConnection(socket,Manager(),limits=KlineBatchLimits.from_config())
    connection.subscriptions['chart']=_BatchSubscription(client_id='chart',exchange='binance',
        market_type='spot',symbol='BTCUSDT',consumer_id='chart-owner',handles={'1s':object()})
    task=asyncio.create_task(connection.run())
    await asyncio.sleep(0)
    await connection._require_resync(ConsumerRecoveryRequired('source_gap_timeout'))
    await asyncio.wait_for(task,1)
    out=dict(wire_closes=socket.closed,lease_releases=released,source_gap_still_pending=not gap.future.done())
    assert out['source_gap_still_pending'] and released[0]['source_repair_pending'],out
    print(json.dumps(out,indent=2));gaps.close()
asyncio.run(main())
