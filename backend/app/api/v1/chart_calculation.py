"""Explicit chart domains joining HTTP projection reads and ordered WS input.

Only the already registered runtime owns mathematical history/output. This
adapter retains frozen definition metadata and bounded command handles; market
rows and serialized payloads exist only for the duration of an operation.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

from candlescope_plugin_sdk import ExecuteBatchResult

from app.core import config
from app.core.async_cleanup import finish_cleanup
from app.core.executors import run_indicator, run_storage
from app.indicator.calculation_contract import check_reference, projection_position
from app.indicator.calculation_owner import CalculationOwnerError
from app.indicator.pine_calculation import PineCalculationRuntime, calculation_identity
from app.indicator.series_reference import series_reference
from app.api.v1.stream_indicator_payloads import (
    IndicatorRangeNotReadyError, _build_plugin_snapshot_from_payload,
    _indicator_warmup_bars, _indicator_compute_query_bounds, _missing_overlaps_target, _plugin_snapshot_or_patch_from_result,
    _query_indicator_compute_bars_async, _query_indicator_compute_result,
    _replace_range_from_snapshot, _script_runtime_request,
)
from app.indicator.serialization import serialize_plugin_runtime_result


def _snapshot_payload(client_id, meta, output):
    return _build_plugin_snapshot_from_payload(client_id,meta,
        serialize_plugin_runtime_result(ExecuteBatchResult(ok=True,output=output)))


class ChartCalculation:
    def __init__(self, binding, *, dm, meta, range_service):
        self.binding, self.owner = binding, binding.owner
        self.dm, self.meta, self.range_service = dm, deepcopy(meta), range_service
        self.series = series_reference(meta)
        self._lock = asyncio.Lock()
        self._tasks = set()
        self._closing = False
        self._close_task = None
        self._writer = None
        self._dispose_writer = None
        self._inputs = ()
        self._source_epoch = 0

    @classmethod
    async def open(cls, service, owner_id, *, dm, meta, range_service, start, end, coordinator=None):
        revision = range_service.data_revision_for_meta(meta)
        rows = await _query_indicator_compute_bars_async(dm, meta, start, end,
            warmup_bars=_indicator_warmup_bars('PINE', meta.get('params') or {}),
            backfill_coordinator=coordinator, wait_seconds=None)
        _, end_ms, compute_start, _ = _indicator_compute_query_bounds(dm, meta, start, end,
            warmup_bars=_indicator_warmup_bars('PINE', meta.get('params') or {}))
        rows = [row for row in rows if compute_start <= int(row.time)*1000 <= end_ms]
        if not rows or len(rows) > config.SCRIPT_MAX_BARS:
            raise CalculationOwnerError('INDICATOR_CALCULATION_INPUT_INVALID')
        binding = await PineCalculationRuntime.open(service,
            _script_runtime_request(meta, rows, transport='http.chart.open'), owner_id=owner_id,
            series_reference=series_reference(meta), start=int(rows[0].time))
        calculation = cls(binding, dm=dm, meta=meta, range_service=range_service)
        try:
            await calculation._command(lambda: calculation._advance(rows, revision, client_id='open', rebuild=False))
        except BaseException:
            await calculation.close()
            raise
        return calculation

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

    def matches(self, meta):
        candidate = _script_runtime_request(meta, [], transport='chart.attach')
        if calculation_identity(candidate, series_reference(meta)) != self.owner.plan.semantic_identity:
            raise CalculationOwnerError('INDICATOR_CALCULATION_INPUT_INVALID')

    async def _command(self, operation):
        if self._closing:
            raise CalculationOwnerError('INDICATOR_CALCULATION_CLOSED')
        if len(self._tasks) >= 8:
            raise CalculationOwnerError('INDICATOR_CALCULATION_BUSY')
        async def run():
            async with self._lock:
                return await operation()
        task = asyncio.create_task(run(), name='chart-calculation:' + self.owner.plan.owner_id)
        self._tasks.add(task)
        def finished(done):
            self._tasks.discard(done)
            if not done.cancelled(): done.exception()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    def _stamp(self, payload, cursor, revision):
        if (self._token(revision) != self._token(self._revision())
                or cursor.input_revision != self._input_token(revision)):
            raise CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_CHANGED')
        payload['calculation'] = projection_position(self.owner, cursor)
        payload['dataRevision'] = dict(revision)
        return payload

    async def _advance(self, rows, revision, *, client_id, rebuild, bar_time=0, epoch=None):
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
            self._stamp(payload, cursor, revision)
            self._inputs = tuple(dict(item) for item in result.inputs)
        cursor = await self.binding.advance(_script_runtime_request(meta, rows,
                transport='websocket.chart' if bar_time else 'http.chart.advance'),
            series_reference=self.series, input_revision=self._input_token(revision,epoch),
            expected=self.owner.cursor, rebuild=rebuild,
            is_current=lambda:self._token(revision) == self._token(self._revision()) and epoch == self._source_epoch,
            on_result=publish)
        return self._stamp(payload, cursor, revision)

    async def _query(self, start, end, *, live=False):
        result, start_ms, end_ms = await run_storage(_query_indicator_compute_result,
            self.dm, self.meta, start, end, warmup_bars=0, auto_backfill=False)
        if _missing_overlaps_target(result.missing_ranges, start_ms, end_ms):
            raise IndicatorRangeNotReadyError('Chart calculation input is not contiguous')
        rows = [row for row in result.bars if start <= row.time <= end and (live or row.is_closed)]
        if rows and rows[-1].time < end:
            raise IndicatorRangeNotReadyError('Chart input has not reached the requested bar opening')
        if (not rows or rows[0].time != start or len(rows) > config.SCRIPT_MAX_BARS
                or (self.owner.cursor is not None and rows[-1].time < self.owner.cursor.observed_through)):
            raise CalculationOwnerError('INDICATOR_CALCULATION_ORIGIN_REQUIRED')
        return rows

    async def _snapshot(self, client_id, revision):
        cursor = self.owner.cursor
        snapshot = await self.binding.read(expected=cursor)
        payload = await run_indicator(_snapshot_payload,client_id,self.meta,snapshot.output)
        payload['range'] = {'start':self.owner.plan.start, 'end':cursor.observed_through}
        if self._inputs: payload['param_schema'] = [dict(item) for item in self._inputs]
        return self._stamp(payload, cursor, revision)

    async def view(self, reference, *, client_id, start, end, rebuild=False):
        async def read():
            check_reference(self.owner, reference)
            if start < self.owner.plan.start or end < start:
                raise CalculationOwnerError('INDICATOR_CALCULATION_ORIGIN_REQUIRED')
            cursor, revision, epoch = self.owner.cursor, self._revision(), self._source_epoch
            reset = rebuild or self._input_token(revision,epoch) != cursor.input_revision
            if reset or end > cursor.observed_through:
                rows = await self._query(self.owner.plan.start if reset else max(self.owner.plan.start,cursor.closed_through),
                    max(end, cursor.observed_through), live=cursor.observed_through > cursor.closed_through)
                # Rebuilds preserve the whole old prefix atomically. They may
                # not be sliced into the narrow range that triggered repair.
                return await self._advance(rows, revision, client_id=client_id, rebuild=reset, epoch=epoch)
            payload = await self._snapshot(client_id, revision)
            replacement = _replace_range_from_snapshot(payload, reason='chart-domain-view',
                start_s=start, end_s=min(end,cursor.observed_through))
            return self._stamp(replacement, cursor, revision)
        return await self._command(read)

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

    async def live(self, *, writer_id, client_id, through=0):
        async def update():
            if self._writer != writer_id:
                raise CalculationOwnerError('INDICATOR_CALCULATION_WRITER_CHANGED')
            cursor, revision, epoch = self.owner.cursor, self._revision(), self._source_epoch
            rebuild = self._input_token(revision,epoch) != cursor.input_revision
            end = max(cursor.observed_through, int(through), int(revision.get('closedThrough') or 0))
            if not through and not rebuild and end == cursor.observed_through:
                return await self._snapshot(client_id, revision)
            # Keep the last admitted confirmed row as the transport overlap.
            # A forming row is not a committed prefix anchor in the runtime;
            # sending it alone can only reset, which this owner rejects.
            rows = await self._query(self.owner.plan.start if rebuild else max(self.owner.plan.start,cursor.closed_through),
                end, live=True)
            return await self._advance(rows, revision, client_id=client_id, rebuild=rebuild,
                bar_time=0 if rebuild else int(through), epoch=epoch)
        return await self._command(update)

    async def close(self):
        if self._close_task is None or (self._close_task.done() and (
                self._close_task.cancelled() or self._close_task.exception() is not None)):
            self._closing = True
            async def drain():
                if self._tasks: await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
                if self._dispose_writer is not None: await self._dispose_writer()
                await self.binding.close()
            self._close_task = asyncio.create_task(drain(), name='chart-calculation-close:' + self.owner.plan.owner_id)
        await finish_cleanup(self._close_task)
