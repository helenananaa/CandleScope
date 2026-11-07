"""Explicit chart domains joining HTTP projection reads and ordered WS input.

Only the already registered runtime owns mathematical history/output. This
adapter retains frozen definition metadata and bounded command handles; market
rows and serialized payloads exist only for the duration of an operation.
"""
from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy

from candlescope_plugin_sdk import ExecuteBatchResult

from app.core import config
from app.core.async_cleanup import finish_cleanup
from app.core.executors import run_indicator, run_storage
from app.indicator.calculation_contract import check_reference, projection_position
from app.indicator.calculation_owner import CalculationOwnerError, RuntimeTailReset
from app.indicator.chart_source import ChartSource
from app.indicator.pine_calculation import PineCalculationRuntime, calculation_identity
from app.indicator.series_reference import series_reference
from app.api.v1.stream_indicator_payloads import (
    IndicatorRangeNotReadyError, _build_plugin_snapshot_from_payload,
    _indicator_warmup_bars, _indicator_compute_query_bounds, _missing_overlaps_target, _plugin_snapshot_or_patch_from_result,
    _closed_indicator_compute_bars, _query_indicator_compute_result,
    _replace_range_from_snapshot, _script_runtime_request,
)
from app.indicator.serialization import serialize_plugin_runtime_result


def _snapshot_payload(client_id, meta, output):
    return _build_plugin_snapshot_from_payload(client_id,meta,
        serialize_plugin_runtime_result(ExecuteBatchResult(ok=True,output=output)))


class ChartCalculation:
    def __init__(self, owner_id, *, dm, meta, range_service):
        self.owner_id, self.binding = owner_id, None
        self.dm, self.meta, self.range_service = dm, deepcopy(meta), range_service
        self.series = series_reference(meta)
        self._lock = asyncio.Lock()
        self._tasks = set()
        self._closing = False
        self._close_task = None
        self._writer = None
        self._dispose_writer = None
        self._inputs = ()
        self._rebuild_notice = None
        self._source_epoch = 0
        self._barrier = None
        self._barrier_ids = deque(maxlen=64)
        self.source = ChartSource(dm,owner_id,meta)

    @property
    def owner(self):
        if self.binding is None: raise CalculationOwnerError('INDICATOR_CALCULATION_NOT_READY')
        return self.binding.owner

    async def initialize(self, service, *, start, end):
        async def seed():
            if self.binding is not None: raise CalculationOwnerError('INDICATOR_CALCULATION_CHANGED')
            revision = self._revision()
            warmup = _indicator_warmup_bars('PINE',self.meta.get('params') or {})
            start_ms,end_ms,compute_start,_ = _indicator_compute_query_bounds(self.dm,self.meta,start,end,warmup_bars=warmup)
            acquisition = await self.source.acquire(start_ms=compute_start,through_ms=self.source.end_ms(end),rebuild=True)
            result,_,_ = await run_storage(_query_indicator_compute_result,self.dm,self.meta,start,end,
                warmup_bars=warmup,auto_backfill=False,min_revision=acquisition.proof.storage_revision)
            rows = _closed_indicator_compute_bars(result,start,end,start_ms,end_ms)
            rows = [row for row in rows if compute_start <= int(row.time)*1000 <= end_ms]
            if not rows or len(rows) > config.SCRIPT_MAX_BARS:
                raise CalculationOwnerError('INDICATOR_CALCULATION_INPUT_INVALID')
            await acquisition.query_proof(result)
            self.binding = await PineCalculationRuntime.open(service,
                _script_runtime_request(self.meta,rows,transport='http.chart.open'), owner_id=self.owner_id,
                series_reference=self.series,start=int(rows[0].time))
            await self._advance(rows,revision,client_id='open',rebuild=False,acquisition=acquisition)
        return await self._command(seed)

    def _revision(self):
        return self.range_service.data_revision_for_meta(self.meta)

    @staticmethod
    def _token(revision): return revision['revisionToken']

    def _input_token(self, revision, epoch=None):
        return self._token(revision) + ':delivery:' + str(self._source_epoch if epoch is None else epoch)

    def invalidate(self):
        # A delivery gap cannot certify opaque intrabar observations. Fence
        # admitted work immediately and rebuild the next generation at origin.
        self._source_epoch += 1

    def require_barrier(self, coordinator, request_id):
        if coordinator is not None and request_id and request_id not in self._barrier_ids:
            self._barrier_ids.append(request_id)
            self._barrier = (coordinator,request_id)
            self.invalidate()

    async def wait_corrections(self):
        # This is a cancellable source wait, outside admitted calculation
        # commands/borrows. A quiet repair cannot block explicit owner close.
        while self._barrier is not None:
            pending = self._barrier
            outcome = await pending[0].wait_for_request(pending[1])
            if (outcome is None or getattr(outcome,'verified_contiguous',False) is not True
                    or bool(getattr(outcome,'retryable',False))):
                raise IndicatorRangeNotReadyError('Chart source correction is not finalized')
            if self._barrier is pending: self._barrier = None

    def _require_source_ready(self):
        if self._barrier is not None:
            raise IndicatorRangeNotReadyError('Chart source correction is awaiting its parent barrier')

    def matches(self, meta):
        candidate = _script_runtime_request(meta, [], transport='chart.attach')
        if calculation_identity(candidate, series_reference(meta)) != self.owner.plan.semantic_identity:
            raise CalculationOwnerError('INDICATOR_CALCULATION_INPUT_INVALID')

    async def _command(self, operation, *, recover_tail=False):
        if self._closing:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CLOSED')
        if len(self._tasks) >= 8:
            raise CalculationOwnerError('INDICATOR_CALCULATION_BUSY')
        async def run():
            async with self._lock:
                try:
                    return await operation()
                except RuntimeTailReset:
                    if not recover_tail:
                        raise
                    # The rejected tail never becomes a public cursor. Keep
                    # the writer and reseed once from the canonical origin.
                    self.invalidate()
                    return await operation(reset_reason='runtimeRebuild')
        task = asyncio.create_task(run(), name='chart-calculation:' + self.owner_id)
        self._tasks.add(task)
        def finished(done):
            self._tasks.discard(done)
            if not done.cancelled(): done.exception()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    def _stamp(self, payload, cursor, revision, acquisition):
        if (self._token(revision) != self._token(self._revision())
                or cursor.input_revision != self._input_token(revision)):
            raise CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_CHANGED')
        def publish():
            payload['calculation'] = projection_position(self.owner, cursor)
            # This owner has proved a closed prefix even when the legacy
            # transport clock only learned about a much older amendment.
            payload['dataRevision'] = {**revision,'closedThrough':cursor.closed_through}
        acquisition.commit(publish)
        return payload

    async def _advance(self, rows, revision, *, client_id, rebuild, acquisition, bar_time=0, epoch=None, reset_reason='sourceRebuild'):
        payload = None
        epoch = self._source_epoch if epoch is None else epoch
        meta = {**self.meta, 'pineLiveUpdate':bool(bar_time), 'pineLiveBarTime':int(bar_time)}
        async def publish(cursor, result):
            nonlocal payload
            payload = await run_indicator(_plugin_snapshot_or_patch_from_result,
                client_id, meta, rows, result, bar_time=bar_time, reason='chart-domain')
            if not bar_time:
                payload['type'] = 'indicator.snapshot'
                payload['range'] = {'start':self.owner.plan.start, 'end':cursor.observed_through}
            self._stamp(payload, cursor, revision, acquisition)
            self._inputs = tuple(dict(item) for item in result.inputs)
        closed = max((row.time for row in rows if row.is_closed),default=0)
        if self.owner.cursor is not None: closed = max(closed,self.owner.cursor.closed_through)
        acquisition.closed(closed)
        cursor = await self.binding.advance(_script_runtime_request(meta, rows,
                transport='websocket.chart' if bar_time else 'http.chart.advance'),
            series_reference=self.series, input_revision=self._input_token(revision,epoch),
            expected=self.owner.cursor, rebuild=rebuild,
            is_current=lambda:self._token(revision) == self._token(self._revision()) and epoch == self._source_epoch,
            on_result=publish,commit_cursor=acquisition.commit)
        self._stamp(payload, cursor, revision, acquisition)
        if rebuild:
            # The owner accepted a new runtime epoch from canonical BARs.
            # Keep its recovery notice for readers of the cached projection.
            self._rebuild_notice = {
                'sessionReset': True,
                'sessionResetReason': reset_reason,
                'sessionRecovered': False,
            }
            payload['meta'] = {**payload.get('meta', {}), **self._rebuild_notice}
        return payload

    async def _query(self, start, end, *, live=False, acquisition):
        result, start_ms, end_ms = await run_storage(_query_indicator_compute_result,
            self.dm, self.meta, start, end, warmup_bars=0, auto_backfill=False,
            min_revision=acquisition.proof.storage_revision)
        if _missing_overlaps_target(result.missing_ranges, start_ms, end_ms):
            raise IndicatorRangeNotReadyError('Chart calculation input is not contiguous')
        rows = [row for row in result.bars if start <= row.time <= end and (live or row.is_closed)]
        if rows and rows[-1].time < end:
            raise IndicatorRangeNotReadyError('Chart input has not reached the requested bar opening')
        if (not rows or rows[0].time != start or len(rows) > config.SCRIPT_MAX_BARS
                or (self.owner.cursor is not None and rows[-1].time < self.owner.cursor.observed_through)):
            raise CalculationOwnerError('INDICATOR_CALCULATION_ORIGIN_REQUIRED')
        await acquisition.query_proof(result)
        return rows

    async def _snapshot(self, client_id, revision, acquisition):
        cursor = self.owner.cursor
        snapshot = await self.binding.read(expected=cursor)
        payload = await run_indicator(_snapshot_payload,client_id,self.meta,snapshot.output)
        payload['range'] = {'start':self.owner.plan.start, 'end':cursor.observed_through}
        if self._inputs: payload['param_schema'] = [dict(item) for item in self._inputs]
        if self._rebuild_notice is not None:
            payload['meta'] = {**payload.get('meta', {}), **self._rebuild_notice}
        return self._stamp(payload, cursor, revision, acquisition)

    async def view(self, reference, *, client_id, start, end, rebuild=False, complete=False):
        async def read(*, reset_reason='sourceRebuild'):
            check_reference(self.owner, reference)
            self._require_source_ready()
            if start < self.owner.plan.start or end < start:
                raise CalculationOwnerError('INDICATOR_CALCULATION_ORIGIN_REQUIRED')
            cursor, revision, epoch = self.owner.cursor, self._revision(), self._source_epoch
            reset = rebuild or self._input_token(revision,epoch) != cursor.input_revision or self.source.needs_rebuild()
            acquisition = await self.source.acquire(start_ms=self.owner.plan.start*1000,
                through_ms=self.source.end_ms(max(end,cursor.observed_through)),rebuild=reset)
            if reset or end > cursor.observed_through:
                rows = await self._query(self.owner.plan.start if reset else max(self.owner.plan.start,cursor.closed_through),
                    max(end, cursor.observed_through), live=cursor.observed_through > cursor.closed_through,
                    acquisition=acquisition)
                # Rebuilds preserve the whole old prefix atomically. They may
                # not be sliced into the narrow range that triggered repair.
                return await self._advance(rows, revision, client_id=client_id, rebuild=reset, epoch=epoch,acquisition=acquisition,reset_reason=reset_reason)
            payload = await self._snapshot(client_id, revision,acquisition)
            if complete:
                payload['type'] = 'indicator.snapshot'
                return payload
            replacement = _replace_range_from_snapshot(payload, reason='chart-domain-view',
                start_s=start, end_s=min(end,cursor.observed_through))
            return self._stamp(replacement, cursor, revision,acquisition)
        return await self._command(read,recover_tail=True)

    async def attach(self, reference, *, writer_id, dispose):
        async def claim():
            check_reference(self.owner, reference, allow_earlier=True)
            if self._writer is not None:
                raise CalculationOwnerError('INDICATOR_CALCULATION_WRITER_BUSY')
            self._writer, self._dispose_writer = writer_id, dispose
        await self._command(claim)

    def detach(self, writer_id):
        if self._writer == writer_id:
            self._writer = self._dispose_writer = None

    async def live(self, *, writer_id, client_id, through=0, input_bar=None):
        async def update(*, reset_reason='sourceRebuild'):
            if self._writer != writer_id:
                raise CalculationOwnerError('INDICATOR_CALCULATION_WRITER_CHANGED')
            self._require_source_ready()
            cursor, revision, epoch = self.owner.cursor, self._revision(), self._source_epoch
            rebuild = self._input_token(revision,epoch) != cursor.input_revision or self.source.needs_rebuild()
            # An ordered observation must not jump ahead to a close whose
            # callback has already arrived but is still queued behind it.
            end = max(cursor.observed_through, int(through),
                int(revision.get('closedThrough') or 0) if rebuild or input_bar is None else 0)
            captured_open_ms = None
            if input_bar is not None and not rebuild:
                if int(input_bar.time) != int(through) or int(through) < cursor.observed_through:
                    raise CalculationOwnerError('INDICATOR_CALCULATION_INPUT_OUT_OF_ORDER')
                if not input_bar.is_closed:
                    if int(through) <= cursor.closed_through:
                        raise CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_CHANGED')
                    captured_open_ms = int(through) * 1000
            acquisition = await self.source.acquire(start_ms=self.owner.plan.start*1000,
                through_ms=self.source.end_ms(end),rebuild=rebuild,captured_open_ms=captured_open_ms)
            if not through and not rebuild and end == cursor.observed_through:
                return await self._snapshot(client_id, revision,acquisition)
            # Keep the last admitted confirmed row as the transport overlap.
            # A forming row is not a committed prefix anchor in the runtime;
            # sending it alone can only reset, which this owner rejects.
            rows = await self._query(self.owner.plan.start if rebuild else max(self.owner.plan.start,cursor.closed_through),
                end, live=True, acquisition=acquisition)
            if input_bar is not None and not rebuild:
                if input_bar.is_closed:
                    # A queued close may precede a newer durable correction.
                    # Its old prices cannot acknowledge the query's newer
                    # source proof. Use canonical rows only after matching.
                    canonical = rows[-1]
                    if not canonical.is_closed or any(getattr(canonical, field) != getattr(input_bar, field)
                            for field in ('open', 'high', 'low', 'close', 'volume')):
                        raise CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_CHANGED')
                else:
                    # Query proves the confirmed prefix; the event owns this
                    # intrabar observation, already replaced in the live cache.
                    # Never write it back into that canonical market cache.
                    rows = [input_bar if row.time == int(through) else row for row in rows]
            return await self._advance(rows, revision, client_id=client_id, rebuild=rebuild,
                bar_time=0 if rebuild else int(through), epoch=epoch,acquisition=acquisition,reset_reason=reset_reason)
        return await self._command(update,recover_tail=True)

    async def close(self):
        if self._close_task is None or (self._close_task.done() and (
                self._close_task.cancelled() or self._close_task.exception() is not None)):
            self._closing = True
            async def drain():
                if self._tasks: await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
                if self._dispose_writer is not None: await self._dispose_writer()
                if self.binding is not None: await self.binding.close(release=self.source.close)
                else: await self.source.close()
            self._close_task = asyncio.create_task(drain(), name='chart-calculation-close:' + self.owner_id)
        await finish_cleanup(self._close_task)
