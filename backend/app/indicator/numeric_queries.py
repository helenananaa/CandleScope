"""Numeric snapshots using the existing bounded builtin execution and cache."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import asyncio
import hashlib
import json
import math

from app.core.executors import run_storage
from .engine import indicator_code_hash
from .history_worker import run_builtin_history, run_builtin_history_numeric
from .query_contracts import (
    MAX_NUMERIC_SOURCE_SLOTS,
    IndicatorInputUnavailable,
    IndicatorQuery,
    NumericIndicatorSnapshot,
)
from .range_result_service import IndicatorRangeRevisionChangedError


@dataclass
class _NumericFlight:
    task: asyncio.Task
    waiters: int = 0


class NumericIndicatorService:
    def __init__(self, inputs, results, *, compute=run_builtin_history):
        self.inputs, self.results, self.compute = inputs, results, compute
        self.compute_many = run_builtin_history_numeric if compute is run_builtin_history else None
        self.closed = False
        self.subscriptions = set()
        self.queries = set()
        self.flights = {}
        self.stats = dict(queries=0, ready=0, warming=0, stale=0, unavailable=0, cache_hits=0)
        self.stats['input_joins'] = 0

    def snapshot(self):
        return {**self.stats, 'closed': self.closed, 'subscriptions': len(self.subscriptions),
                'active_queries': len(self.queries), 'max_queries': 128, 'max_subscriptions': 256,
                'active_inputs': len(self.flights),
                'max_source_slots': MAX_NUMERIC_SOURCE_SLOTS, 'seed_policy': 'confirmed_rolling_slots_v1'}

    async def subscribe(self, request, callback, *, on_recovery, consumer_id, event_types=None,
                        subscription_tier='indicators'):
        from .numeric_subscriptions import NumericIndicatorSubscription
        if self.closed or len(self.subscriptions) >= 256:
            raise RuntimeError('Numeric indicator subscription capacity unavailable')
        subscription = NumericIndicatorSubscription(self, request, callback,
            on_recovery=on_recovery, consumer_id=consumer_id, event_types=event_types,
            subscription_tier=subscription_tier)
        self.subscriptions.add(subscription)
        try:
            await subscription.start()
            return subscription
        except BaseException:
            await subscription.close()
            raise

    async def close(self):
        self.closed = True
        for subscription in tuple(self.subscriptions):
            await subscription.close()
        tasks = [task for task in self.queries if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def query(self, request: IndicatorQuery) -> NumericIndicatorSnapshot:
        if self.closed:
            return NumericIndicatorSnapshot(request.source, 'unavailable', reason='service_closed')
        if len(self.queries) >= 128:
            return NumericIndicatorSnapshot(request.source, 'unavailable', reason='query_capacity')
        task = asyncio.current_task()
        self.queries.add(task)
        self.stats['queries'] += 1
        try:
            # Share only concurrent identical requests, including the complete
            # event/revision fence. There is no time-based cache of input state:
            # a later call must observe canonical storage again. The worker's
            # final validation fences all waiters against intervening writes.
            key = (json.dumps(asdict(request), sort_keys=True, separators=(',', ':'), allow_nan=False),
                   self.inputs.admission_token(request))
            flight = self.flights.get(key)
            if flight is None or flight.task.done() or flight.task.cancelling():
                flight = _NumericFlight(asyncio.create_task(self._query(request), name='numeric-input'))
                self.flights[key] = flight
            else:
                self.stats['input_joins'] += 1
            flight.waiters += 1
            try:
                result = await asyncio.shield(flight.task)
            finally:
                flight.waiters -= 1
                if flight.waiters == 0:
                    if self.flights.get(key) is flight:
                        del self.flights[key]
                    if not flight.task.done():
                        flight.task.cancel()
                    await asyncio.gather(flight.task, return_exceptions=True)
            self.stats[result.status] += 1
            self.stats['cache_hits'] += result.cache_hits
            return result
        finally:
            self.queries.discard(task)

    async def _query(self, request):
        try:
            code_hashes = {output: indicator_code_hash(output.name) for output in request.outputs}
            if not all(code_hashes.values()):
                return NumericIndicatorSnapshot(request.source, 'unavailable', reason='builtin_unavailable')
            captured = await run_storage(self.inputs.capture, request)
            values, hits = [], 0
            computed_values = None
            for output in request.outputs:
                code_hash = code_hashes[output]
                identity = {'source': asdict(request.source), 'output': asdict(output),
                            'input': captured.fingerprint, 'code': code_hash, 'contract': 'numeric-v1'}
                identity = 'numeric:' + hashlib.sha256(json.dumps(identity, sort_keys=True,
                                                separators=(',', ':')).encode()).hexdigest()
                meta = {**asdict(request.source), 'name': output.name, 'kind': 'builtin',
                        'params': dict(output.params), 'codeHash': code_hash, 'indicatorId': identity}
                async def calculate(output=output, meta=meta):
                    nonlocal computed_values
                    if self.compute_many is not None:
                        if computed_values is None:
                            computed_values = await self.compute_many(request.outputs, meta, captured.bars)
                        raw = computed_values[output]
                    else:
                        result = await self.compute(output.name, meta, captured.bars)
                        latest = result.get_latest()
                        if output.output_id not in latest:
                            raise ValueError('Unknown numeric output ID')
                        raw = latest[output.output_id]
                    # Cache identity includes exact immutable inputs. A result
                    # may be reusable for those inputs after canonical changes,
                    # but no snapshot is published without final validation.
                    return {'numeric_value': float(raw) if raw is not None and math.isfinite(float(raw)) else None}
                frontier = int(captured.bars[-1].time)
                payload, hit, _ = await self.results.get_or_compute(meta=meta, start=frontier,
                    end=frontier, compute=calculate, _revision_retries=0)
                values.append((output, payload['numeric_value']))
                hits += int(hit)
            await run_storage(self.inputs.validate, captured)
            if self.closed:
                return NumericIndicatorSnapshot(request.source, 'unavailable', reason='service_closed')
            return NumericIndicatorSnapshot(request.source,
                'ready' if all(value is not None for _, value in values) else 'warming',
                tuple(values), int(captured.bars[-1].time), captured.slots, len(captured.bars),
                captured.revision, captured.fingerprint, request.seed_policy, cache_hits=hits,
                latest_closed=captured.bars[-1], stream_version=tuple(
                    (name, captured.version[name]) for name in ('epoch', 'generation', 'sequence', 'barrier')))
        except (IndicatorInputUnavailable, IndicatorRangeRevisionChangedError) as error:
            return NumericIndicatorSnapshot(request.source, 'stale', reason=str(error))
