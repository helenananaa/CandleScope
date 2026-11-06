"""Keep existing ingestion claims through source repair, without unsafe output."""
import asyncio
from types import SimpleNamespace

from starlette.websockets import WebSocketDisconnect
from app.api.v1.stream_kline_batch import KlineBatchConnection,KlineBatchLimits,_BatchSubscription
from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.data_manager.continuity import SourceGapRegistry
from app.data_engine.data_manager.models import SeriesKey,BarData,DataEvent,DataEventType

KEY=SeriesKey('BTCUSDT','1s')
OTHER=SeriesKey('ETHUSDT','1s')


class Socket:
    def __init__(self):
        self.input=asyncio.Queue();self.messages=[];self.closes=[]
    async def receive_text(self):
        item=await self.input.get()
        if isinstance(item,BaseException):raise item
        return item
    async def send_json(self,message):self.messages.append(message)
    async def send_text(self,message):self.messages.append(message)
    async def close(self,code,reason):
        self.closes.append((code,reason));await self.input.put(WebSocketDisconnect(code))


class Manager:
    def __init__(self,gaps):self.gaps=gaps;self.releases=[];self.waits=0
    async def unsubscribe_async(self,handle):pass
    async def release_stream(self,*args,**kwargs):
        self.releases.append(dict(pending=bool(self.gaps.pending(KEY))))
    async def wait_for_source_continuity(self,key,*,fail_on_error=False):
        self.waits+=1
        await self.gaps.wait_cleared(key,fail_on_error=fail_on_error)


def build_fixture():
    gaps=SourceGapRegistry();gap,_=gaps.open(KEY,1000,1000)
    # An unrelated permanently failed market cannot block this chart's repair.
    unrelated,_=gaps.open(OTHER,1000,1000);unrelated.fail('source_repair_failed')
    socket=Socket();dm=Manager(gaps)
    connection=KlineBatchConnection(socket,dm,limits=KlineBatchLimits.from_config())
    connection.subscriptions['chart']=_BatchSubscription(client_id='chart',exchange='binance',
        market_type='spot',symbol='BTCUSDT',consumer_id='chart-owner',
        handles={'1s':SimpleNamespace(id='source-consumer',key=KEY)})
    return gaps,gap,socket,dm,connection


async def until(check):
    async with asyncio.timeout(1):
        while not check():await asyncio.sleep(0)


def timeout():return ConsumerRecoveryRequired('source_gap_timeout',subscription_id='source-consumer')


def test_repair_keeps_single_source_claim_and_resyncs_only_after_verified_repair():
    async def run():
        gaps,gap,socket,dm,connection=build_fixture()
        wire=asyncio.create_task(connection.run())
        recovery=asyncio.create_task(connection._require_resync(timeout()))
        await until(lambda:dm.waits==1)
        assert socket.messages[0]['status']=='reconnecting'
        assert not socket.closes and not dm.releases
        await connection._require_resync(timeout())
        assert dm.waits==1
        await connection._event_callback('chart')(DataEvent(DataEventType.BAR_CLOSED,KEY,
            BarData(time=2,open=1,high=2,low=1,close=2,volume=1,source='backfill')))
        await socket.input.put('ping');await until(lambda:'pong' in socket.messages)
        assert not any(isinstance(m,dict) and m.get('type')=='kline' for m in socket.messages)
        assert gaps.resolve_verified(gap,[BarData(time=1,open=1,high=2,low=1,close=2,
            volume=1,is_closed=True,source='backfill')],set())
        await asyncio.wait_for(recovery,1);await asyncio.wait_for(wire,1)
        assert socket.closes==[(1013,'CONSUMER_RESYNC_REQUIRED')]
        assert dm.releases==[{'pending':False}]
        assert not connection.subscriptions
        gaps.close()
    asyncio.run(run())


def test_client_disconnect_cancels_repair_wait_and_drains_claims():
    async def run():
        gaps,gap,socket,dm,connection=build_fixture()
        wire=asyncio.create_task(connection.run())
        recovery=asyncio.create_task(connection._require_resync(timeout()))
        await until(lambda:dm.waits==1)
        await socket.input.put(WebSocketDisconnect(1000))
        await asyncio.wait_for(wire,1);await asyncio.wait_for(recovery,1)
        assert not socket.closes
        assert dm.releases==[{'pending':True}]
        assert not gap.future.cancelled()
        assert not connection.subscriptions
        gaps.close()
    asyncio.run(run())


def test_source_failure_future_wakes_wait_without_registry_changed_notification():
    async def run():
        gaps,gap,socket,dm,connection=build_fixture()
        wire=asyncio.create_task(connection.run())
        recovery=asyncio.create_task(connection._require_resync(timeout()))
        await until(lambda:dm.waits==1)
        gap.fail('source_repair_failed')
        await asyncio.wait_for(recovery,1);await asyncio.wait_for(wire,1)
        assert len(socket.closes)==1 and dm.releases==[{'pending':True}]
        gaps.close()
    asyncio.run(run())


def test_explicit_handle_cancellation_cannot_leave_silent_live_connection():
    async def run():
        gaps,gap,socket,dm,connection=build_fixture()
        wire=asyncio.create_task(connection.run())
        recovery=asyncio.create_task(connection._require_resync(timeout()))
        await until(lambda:dm.waits==1)
        recovery.cancel()
        await asyncio.gather(recovery,return_exceptions=True)
        await asyncio.wait_for(wire,1)
        assert len(socket.closes)==1 and dm.releases==[{'pending':True}]
        assert not gap.future.cancelled()
        gaps.close()
    asyncio.run(run())


def test_non_source_failure_still_terminates_immediately_during_repair_wait():
    async def run():
        gaps,gap,socket,dm,connection=build_fixture()
        wire=asyncio.create_task(connection.run())
        recovery=asyncio.create_task(connection._require_resync(timeout()))
        await until(lambda:dm.waits==1)
        await connection._require_resync(ConsumerRecoveryRequired('replay_window_exhausted'))
        await asyncio.wait_for(wire,1);await asyncio.wait_for(recovery,1)
        assert len(socket.closes)==1 and dm.releases==[{'pending':True}]
        gaps.close()
    asyncio.run(run())


def test_other_failed_handle_joins_existing_wait_without_stopping_either_source():
    async def run():
        gaps,gap,socket,dm,connection=build_fixture()
        gaps.retire(OTHER);second,_=gaps.open(OTHER,1000,1000)
        connection.subscriptions['second']=_BatchSubscription(client_id='second',exchange='binance',
            market_type='spot',symbol='ETHUSDT',consumer_id='second-owner',
            handles={'1s':SimpleNamespace(id='second-consumer',key=OTHER)})
        wire=asyncio.create_task(connection.run())
        recovery=asyncio.create_task(connection._require_resync(timeout()))
        await until(lambda:dm.waits==1)
        await connection._require_resync(ConsumerRecoveryRequired('source_gap_timeout',subscription_id='second-consumer'))
        repaired=BarData(time=1,open=1,high=2,low=1,close=2,volume=1,is_closed=True,source='backfill')
        assert gaps.resolve_verified(gap,[repaired],set())
        await until(lambda:dm.waits==2)
        assert not socket.closes and not dm.releases
        # A new gap in the first market must also remain protected while the
        # second market repairs; testing old futures alone would miss it.
        again,_=gaps.open(KEY,2000,2000)
        assert gaps.resolve_verified(second,[repaired],set())
        for _ in range(4):await asyncio.sleep(0)
        assert not socket.closes
        repaired2=BarData(time=2,open=1,high=2,low=1,close=2,volume=1,is_closed=True,source='backfill')
        assert gaps.resolve_verified(again,[repaired2],set())
        await asyncio.wait_for(recovery,1);await asyncio.wait_for(wire,1)
        assert len(socket.closes)==1 and len(dm.releases)==2
        assert all(not row['pending'] for row in dm.releases)
        gaps.close()
    asyncio.run(run())
