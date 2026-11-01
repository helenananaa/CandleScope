"""Bounded, serial ownership for the app's mutable builtin indicator engine.

This owner is separate from the historical indicator executor. A command keeps
ownership until physical completion and loop-side delivery; cancelling its
waiter does not let another command mutate the engine concurrently.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import logging
from typing import Any, Callable

from app.core.bounded_executor import BoundedExecutor, ExecutorBusyError
from app.data_engine.data_manager.models import BarData
from app.indicator.engine import indicator_code_hash
from app.indicator.types import IndicatorKey

logger = logging.getLogger("candlescope.indicator.owner")


class IndicatorInputChanged(RuntimeError):
    """A queued history snapshot no longer covers the owner's state."""

    code = "INDICATOR_INPUT_CHANGED"


def _argument(args: tuple, kwargs: dict, index: int, name: str, default=None):
    return args[index] if len(args) > index else kwargs.get(name, default)


def _validate_history_state(engine, method: str, args: tuple, kwargs: dict) -> None:
    """Recheck at the physical owner boundary, without changing any state.

    The bridge's query fence is necessary but insufficient once another close
    can run between its last check and admission to this worker.
    """
    if method not in {"subscribe", "on_bars_backfilled"}:
        return
    subscribing = method == "subscribe"
    source = _argument(args, kwargs, 5 if subscribing else 2, "bars") or ()
    confirmed = [bar for bar in source if bar.is_closed]
    if not confirmed:
        return
    symbol = _argument(args, kwargs, 0, "symbol")
    interval = _argument(args, kwargs, 1, "interval")
    market_type = _argument(args, kwargs, 2 if subscribing else 3, "market_type", "spot")
    exchange = _argument(args, kwargs, 6 if subscribing else 4, "exchange", "binance")
    identity = _argument(args, kwargs, 9 if subscribing else 7, "series_identity")
    name = _argument(args, kwargs, 3, "indicator_name") if subscribing else "__topic__"
    params = _argument(args, kwargs, 4, "params", {}) if subscribing else {}
    key = IndicatorKey(symbol, interval, name, params, market_type=market_type,
                       exchange=exchange, series_identity=identity,
                       code_hash=indicator_code_hash(name) if subscribing else "")
    keys = [key] if subscribing else list(engine._stream_keys.get(key.series_topic, ()))
    last = max((engine._last_committed.get(key, 0) for key in keys), default=0)
    start, end = min(bar.time for bar in confirmed), max(bar.time for bar in confirmed)
    if end < last:
        raise IndicatorInputChanged("Indicator input state changed; history ends before the committed tail")
    if not subscribing:
        minimum = max((engine._instances[key].bar_count for key in keys if key in engine._instances), default=0)
        first = min((engine._first_committed[key] for key in keys if key in engine._first_committed), default=start)
        if len(confirmed) < minimum or start > first:
            raise IndicatorInputChanged("Indicator input state changed; correction omits part of the committed seed")


def _input_snapshot(value: Any) -> Any:
    # Bars are frozen value objects. Copy containers, not every historical bar
    # on the event loop. Small mutable parameter/revision dictionaries are owned
    # by the admitted command from this point onwards.
    if isinstance(value, BarData):
        return value
    if isinstance(value, dict):
        return {key: _input_snapshot(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        if not value or isinstance(value[0], BarData):
            return value.copy() if isinstance(value, list) else value
        return type(value)(_input_snapshot(item) for item in value)
    return value


def _bar_count(value: Any) -> int:
    if isinstance(value, BarData):
        return 1
    if isinstance(value, dict):
        return sum(_bar_count(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        if value and isinstance(value[0], BarData):
            return len(value)
        return sum(_bar_count(item) for item in value)
    return 0


class SerialIndicatorOwner:
    """One physical worker; finite commands and retained input rows.

Listeners and adoption callbacks run on the creating asyncio loop. The engine
itself is created, read, mutated and destroyed only by the dedicated worker.
No engine or mutable indicator instance is exposed through this facade.
"""

    METHODS = frozenset({
        "subscribe", "unsubscribe", "on_bar_closed", "on_bar_updated",
        "preview_for_key", "plan_series_correction", "active_series_intervals",
        "resident_series_intervals", "on_series_correction_invalidated",
        "on_bars_backfilled", "invalidate_source_gap", "get_result",
        "list_instances", "destroy_all", "set_source_delivery_state",
    })

    def __init__(self, *, factory: Callable | None = None,
                 max_pending: int = 64, max_input_bars: int = 500_000) -> None:
        if max_pending < 0 or max_input_bars < 1:
            raise ValueError("Invalid indicator owner capacity")
        self._loop = asyncio.get_running_loop()
        self._factory = factory
        self._engine = None
        self._executor = BoundedExecutor("indicator_realtime", max_workers=1, max_pending=0)
        self._lock = asyncio.Lock()
        self._max_inflight = max_pending + 1
        self._max_input_bars = max_input_bars
        self._inflight = self._input_bars = self._sequence = 0
        self._rejected = self._cancelled_queued = self._cancelled_running = 0
        self._closing = self._closed = False
        self._failure: str | None = None
        self._listeners: list[Callable] = []
        self._snapshot: dict[str, Any] = {"started": False, "instances": []}

    def _assert_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("Indicator owner used from another event loop")

    def add_listener(self, listener: Callable) -> None:
        self._assert_loop()
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable) -> None:
        self._assert_loop()
        if listener in self._listeners:
            self._listeners.remove(listener)

    def snapshot(self) -> dict[str, Any]:
        self._assert_loop()
        return {**deepcopy(self._snapshot), "listener_count": len(self._listeners),
                "serial_owner": {"sequence": self._sequence, "inflight": self._inflight,
                    "max_inflight": self._max_inflight, "input_bars": self._input_bars,
                    "max_input_bars": self._max_input_bars, "rejected": self._rejected,
                    "cancelled_queued": self._cancelled_queued,
                    "cancelled_running": self._cancelled_running,
                    "closing": self._closing, "closed": self._closed,
                    "failure": self._failure,
                    "executor": self._executor.snapshot()}}

    def _execute(self, method: str, args: tuple, kwargs: dict) -> tuple:
        if self._engine is None:
            if self._factory is None:
                from app.indicator import create_engine
                self._engine = create_engine()
            else:
                self._engine = self._factory()
        engine = self._engine
        _validate_history_state(engine, method, args, kwargs)
        events: list = []
        # Capture detached values while the worker owns the engine. Consumers
        # never run on this thread or inspect engine-owned mutable structures.
        def capture(event):
            events.append(deepcopy(event))
        engine.add_listener(capture)
        try:
            if method == "set_source_delivery_state":
                engine.source_delivery_state = dict(args[0])
                result = None
            else:
                result = getattr(engine, method)(*args, **kwargs)
            snapshot = engine.snapshot()
            return deepcopy(result), events, snapshot
        finally:
            engine.remove_listener(capture)

    async def _physical(self, method: str, args: tuple, kwargs: dict) -> tuple:
        physical = self._executor.submit(lambda: self._execute(method, args, kwargs), operation=method)
        future = asyncio.wrap_future(physical)
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(future)
                return result, cancelled
            except asyncio.CancelledError:
                if future.done():
                    # A command itself may fail with CancelledError. It must
                    # not be mistaken for another cancellation of the waiter.
                    result = future.result()
                    if not cancelled:
                        self._cancelled_running += 1
                    return result, True
                if not cancelled:
                    self._cancelled_running += 1
                cancelled = True
                # Ownership and physical capacity remain held. This command
                # has been accepted, so finish its ordered state transition.
                continue

    async def call(self, method: str, *args: Any,
                   adopt: Callable[[Any], None] | None = None, **kwargs: Any) -> Any:
        self._assert_loop()
        if method not in self.METHODS:
            raise ValueError(f"Unsupported indicator owner operation: {method}")
        if self._closing:
            raise RuntimeError("Indicator owner is closing")
        if self._failure is not None:
            raise RuntimeError("Indicator owner failed; rebuild from canonical history")
        count = _bar_count(args) + _bar_count(kwargs)
        if self._inflight >= self._max_inflight or self._input_bars + count > self._max_input_bars:
            self._rejected += 1
            raise ExecutorBusyError("indicator_realtime")
        self._inflight += 1
        self._input_bars += count
        started = False
        try:
            args, kwargs = _input_snapshot(args), _input_snapshot(kwargs)
            async with self._lock:
                if self._closing:
                    raise RuntimeError("Indicator owner is closing")
                if self._failure is not None:
                    raise RuntimeError("Indicator owner failed; rebuild from canonical history")
                started = True
                try:
                    (result, events, snapshot), cancelled = await self._physical(method, args, kwargs)
                except IndicatorInputChanged:
                    # Rejected before any mutation; the caller can fetch a
                    # fresh canonical snapshot without poisoning valid state.
                    raise
                except BaseException as error:
                    # An unexpected worker failure may have partially changed
                    # state. Never continue issuing apparently valid results.
                    self._failure = str(error) or type(error).__name__
                    raise
                self._sequence += 1
                self._snapshot = snapshot
                # Adoption is synchronous on the loop, before a subsequent
                # command or listener can observe the new subscription.
                if adopt is not None:
                    adopt(result)
                for event in events:
                    for listener in tuple(self._listeners):
                        try:
                            listener(event)
                        except Exception:
                            logger.exception("Indicator listener failed")
                if cancelled:
                    raise asyncio.CancelledError
                return result
        except asyncio.CancelledError:
            if not started:
                self._cancelled_queued += 1
            raise
        finally:
            self._inflight -= 1
            self._input_bars -= count

    async def aclose(self) -> None:
        self._assert_loop()
        if self._closed:
            return
        self._closing = True
        async with self._lock:
            if self._closed:
                return
            (_, _, snapshot), cancelled = await self._physical("stop", (), {})
            self._snapshot = snapshot
            self._listeners.clear()
            self._executor.shutdown(wait=False)
            self._closed = True
            if cancelled:
                raise asyncio.CancelledError


async def call_engine(engine: Any, method: str, *args: Any,
                      adopt: Callable[[Any], None] | None = None, **kwargs: Any) -> Any:
    """Support explicit standalone synchronous engines in isolated computations."""
    if isinstance(engine, SerialIndicatorOwner):
        return await engine.call(method, *args, adopt=adopt, **kwargs)
    if method == "set_source_delivery_state":
        engine.source_delivery_state = dict(args[0])
        return None
    result = getattr(engine, method)(*args, **kwargs)
    if adopt is not None:
        adopt(result)
    return result
