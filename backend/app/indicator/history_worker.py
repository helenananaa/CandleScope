"""Bounded process capacity for stateless builtin historical computations."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import os
import threading
import time
import sys
try:
    import resource
except ImportError:
    resource = None

from app.core import config
from app.core.bounded_executor import BoundedExecutor, ExecutorBusyError
from app.core.process_lane import SerialProcessLane


def _dispatch(request):
    kind, *args = request
    if kind in {'compute', 'numeric'}:
        from app.indicator import create_engine
        from app.indicator.series_reference import identity_kwargs
        name, meta, bars = args
        engine = create_engine()
        try:
            if kind == 'numeric':
                # One bounded input transfer, no RenderIR or complete output
                # series roundtrip for a numeric-only caller.
                value = {}
                for output in name:
                    result = engine.compute(meta['symbol'], meta['interval'], meta['market_type'],
                        output.name, dict(output.params), bars, exchange=meta['exchange'], **identity_kwargs(meta))
                    latest = result.get_latest()
                    if output.output_id not in latest:
                        raise ValueError('Unknown numeric output ID')
                    value[output] = latest[output.output_id]
            else:
                value = engine.compute(meta['symbol'], meta['interval'], meta['market_type'], name,
                                       meta['params'], bars, exchange=meta['exchange'], **identity_kwargs(meta))
        finally:
            engine.stop()
    elif kind == 'range':
        from app.indicator.range_projection import compute_builtin_range_patch_from_bars
        value = compute_builtin_range_patch_from_bars(*args)
    else:
        raise ValueError('Unknown builtin history operation')
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else None
    return value, {'pid': os.getpid(), 'cpu_seconds': time.process_time(),
                   'peak_rss_bytes': (rss * (1 if sys.platform == 'darwin' else 1024)) if rss is not None else None}


class BuiltinHistoryExecutor:
    def __init__(self, *, max_pending=32, max_input_bars=500_000, timeout=30.0):
        self._executor = BoundedExecutor('indicator_history_process', max_workers=1, max_pending=max_pending)
        self._lock = threading.RLock()
        self._rows = 0
        self._limit = max_input_bars
        self._timeout = timeout
        self._closing = False
        self._lane = None
        self._worker = {}
        self._transport = {}
        self._process_starts = 0

    def _execute(self, request):
        if self._lane is None or not self._lane.alive:
            if self._lane is not None:
                self._lane.close()
            self._lane = SerialProcessLane(_dispatch, name='indicator-history', timeout=self._timeout)
            self._process_starts += 1
        with self._lock:
            if self._closing:
                self._lane.request_abort()
        try:
            value, worker = self._lane.call(request)
        finally:
            with self._lock:
                self._transport = self._lane.snapshot()
        with self._lock:
            self._worker = worker
        return value

    def submit(self, request, input_rows):
        with self._lock:
            if self._closing:
                raise RuntimeError('Builtin history executor is closing')
            if input_rows < 0 or self._rows + input_rows > self._limit:
                raise ExecutorBusyError('indicator_history_process')
            self._rows += input_rows
            try:
                future = self._executor.submit(lambda: self._execute(request), operation=request[0])
            except BaseException:
                self._rows -= input_rows
                raise
        def release(_):
            with self._lock:
                self._rows -= input_rows
        future.add_done_callback(release)
        return future

    async def run(self, request, input_rows):
        physical = self.submit(request, input_rows)
        future = asyncio.wrap_future(physical)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            physical.cancel()  # Retracts only work which has not started.
            future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            raise

    def snapshot(self):
        with self._lock:
            return {**self._executor.snapshot(), 'input_bars': self._rows,
                    'max_input_bars': self._limit, 'closing': self._closing,
                    'process_starts': self._process_starts, 'transport': dict(self._transport),
                    'worker': dict(self._worker)}

    def close(self):
        with self._lock:
            self._closing = True
            if self._lane is not None:
                self._lane.request_abort()
        self._executor.shutdown(wait=True, cancel_futures=True)
        if self._lane is not None:
            self._lane.close()
            self._lane = None


_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = BuiltinHistoryExecutor(
                max_pending=config.INDICATOR_HISTORY_PENDING,
                max_input_bars=config.INDICATOR_HISTORY_INPUT_BARS,
                timeout=config.INDICATOR_HISTORY_PROCESS_TIMEOUT_SECONDS,
            )
        return _pool


async def run_builtin_history(name, meta, bars):
    return await _get_pool().run(('compute', name, deepcopy(meta), tuple(bars)), len(bars))


async def run_builtin_history_numeric(outputs, meta, bars):
    if not 1 <= len(outputs) <= 3 or not 1 <= len(bars) <= 250:
        raise ValueError('Numeric builtin request exceeds bounded input contract')
    return await _get_pool().run(('numeric', tuple(outputs), deepcopy(meta), tuple(bars)), len(bars))


async def run_builtin_history_range(client_id, meta, start, end, bars, reason, target_bars):
    return await _get_pool().run(('range', client_id, deepcopy(meta), start, end, tuple(bars), reason, target_bars), len(bars))


def history_executor_snapshot():
    with _pool_lock:
        return _pool.snapshot() if _pool is not None else {'started': False, 'enabled': config.INDICATOR_HISTORY_PROCESS_ENABLED}


async def shutdown_builtin_history():
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        await asyncio.to_thread(pool.close)
