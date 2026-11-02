"""Committed local-account views, separate from private exchange accounts.

Full replacement views coalesce wakeups; they are not a resumable fill log.
The durable cursor fences ledger reads. Connection sequence also orders live
valuation observations, which retain the existing ten-second cursor flush.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import time
import uuid

from app.core.executors import run_storage
from app.trading_accounts.models import TradingAccountError

SCHEMA = 'candlescope.trading-account-state/1'


@dataclass
class _ReadBatch:
    task: asyncio.Task | None = None
    readers: int = 0
    accepting: bool = True


class TradingStateSubscription:
    def __init__(self, owner, account_id):
        self.owner, self.account_id = owner, account_id
        self._updates = owner.service.store.updates.subscribe('state')
        self._epoch = uuid.uuid4().hex
        self._sequence = 0
        self._first = None
        self._iterating = False
        self._last_read = 0.0

    async def read(self):
        delay = self.owner.min_snapshot_interval_seconds - (time.monotonic() - self._last_read)
        if delay > 0:
            await asyncio.sleep(delay)
        if self._updates.closed:
            raise asyncio.CancelledError
        self._updates.clear_before_read()
        state = await self.owner.read_state(self.account_id)
        if self._updates.closed:
            raise asyncio.CancelledError
        self._last_read = time.monotonic()
        return state

    async def events(self):
        if self._iterating:
            raise RuntimeError('a trading subscription has one consumer')
        self._iterating = True
        state, self._first = self._first, None
        previous = None
        try:
            while not self._updates.closed:
                if state is None:
                    state = await self.read()
                if state != previous:
                    self._sequence += 1
                    yield {'schema': SCHEMA, 'type': 'snapshot', 'replacement': True,
                           'identity': {'accountId': self.account_id, 'ledgerEpoch': state['cursor']['epoch']},
                           'connectionEpoch': self._epoch, 'sequence': self._sequence, 'state': state}
                    previous = state
                state = None
                while not self._updates.closed:
                    try:
                        if not await asyncio.wait_for(self._updates.wait(), self.owner.heartbeat_seconds):
                            return
                        break
                    except TimeoutError:
                        yield {'schema': SCHEMA, 'type': 'heartbeat'}
        except TradingAccountError as error:
            yield {'schema': SCHEMA, 'type': 'error', 'error': error.to_dict()}
        except Exception:
            yield {'schema': SCHEMA, 'type': 'error', 'error': {'code': 'TRADING_STATE_STREAM_FAILED'}}
        finally:
            self.close()

    def close(self):
        self._first = None
        self._updates.close()
        self.owner._subscriptions.discard(self)


class TradingAccountDataManager:
    def __init__(self, service, *, max_subscriptions=16, heartbeat_seconds=15,
                 min_snapshot_interval_seconds=1.0):
        if max_subscriptions < 1 or heartbeat_seconds <= 0 or min_snapshot_interval_seconds < 0:
            raise ValueError('trading subscription limits must be positive')
        self.service = service
        self.max_subscriptions = max_subscriptions
        self.heartbeat_seconds = heartbeat_seconds
        self.min_snapshot_interval_seconds = min_snapshot_interval_seconds
        self._subscriptions = set()
        self._closed = False
        self._control_requests = 0
        self._read_batches = {}
        self._read_jobs = set()

    async def read_state(self, account_id):
        if self._closed:
            raise TradingAccountError('TRADING_UNAVAILABLE', 'Trading accounts are unavailable', status=503)
        batch = self._read_batches.get(account_id)
        if batch is None or not batch.accepting:
            batch = _ReadBatch()
            async def read():
                # Only collect readers BEFORE acquiring the WAL snapshot.
                # Joining an already-running snapshot could clear a new
                # subscriber's commit wakeup then return pre-commit state.
                await asyncio.sleep(.005)
                batch.accepting = False
                return await run_storage(self.service.account_state, account_id)
            batch.task = asyncio.create_task(read())
            self._read_batches[account_id] = batch
            self._read_jobs.add(batch.task)
            def done(task):
                self._read_jobs.discard(task)
                if not task.cancelled():
                    task.exception()  # Consume errors even if all readers left.
            batch.task.add_done_callback(done)
        batch.readers += 1
        try:
            # Releasing one view cannot cancel a sibling's shared read. Each
            # subscriber owns its delivered copy and previous-state comparison.
            return deepcopy(await asyncio.shield(batch.task))
        finally:
            batch.readers -= 1
            if batch.readers == 0:
                if self._read_batches.get(account_id) is batch:
                    self._read_batches.pop(account_id, None)
                if not batch.task.done():
                    batch.task.cancel()

    def control_plane(self):
        if self._closed:
            raise TradingAccountError('TRADING_UNAVAILABLE', 'Trading accounts are unavailable', status=503)
        self._control_requests += 1
        return self.service

    async def subscribe_state(self, account_id):
        self.control_plane()
        if len(self._subscriptions) >= self.max_subscriptions:
            from app.trading_accounts.models import conflict
            raise conflict('Too many account subscriptions', code='TRADING_SUBSCRIPTION_CAPACITY')
        subscription = TradingStateSubscription(self, account_id)
        self._subscriptions.add(subscription)
        try:
            subscription._first = await subscription.read()
            return subscription
        except BaseException:
            subscription.close()
            raise

    def close(self):
        self._closed = True
        for subscription in tuple(self._subscriptions):
            subscription.close()
        for task in tuple(self._read_jobs):
            task.cancel()

    def diagnostics(self):
        return {'closed': self._closed, 'subscriptions': len(self._subscriptions),
                'control_requests': self._control_requests, 'read_jobs': len(self._read_jobs)}
