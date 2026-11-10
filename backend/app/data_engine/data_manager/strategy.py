"""Fixed-history strategy reads with bounded, commit-driven subscriptions.

The existing backtest service owns execution and durable results. This facade
owns only the consumer lifecycle; releasing a view never cancels a shared run.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from app.backtest.errors import BacktestError

if TYPE_CHECKING:
    from app.backtest.service import BacktestService
    from app.backtest.runtime import BacktestRuntime


SCHEMA = "candlescope.strategy-run-events/1"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
IDENTITY_FIELDS = (
    "run_id", "generation", "strategy_revision_id", "dataset_id", "data_epoch",
    "snapshot_hash", "config_hash", "engine_version", "fidelity_mode", "source_event_kind",
)


class StrategyRunSubscription:
    def __init__(self, owner: StrategyDataManager, run_id: str) -> None:
        self.owner = owner
        self.run_id = run_id
        self._updates = owner.service.repository.run_updates.subscribe(run_id)
        self._identity: tuple[Any, ...] | None = None
        self._first: dict[str, Any] | None = None
        self._iterating = False

    async def _read(self) -> dict[str, Any]:
        # Subscribe and clear before the transaction: a commit racing with the
        # read schedules the next iteration instead of losing the terminal event.
        self._updates.clear_before_read()
        value = await asyncio.to_thread(self.owner.service.repository.read_run_progress, self.run_id)
        if self._updates.closed:
            raise asyncio.CancelledError
        if value is None:
            raise BacktestError("SCHEMA_UNKNOWN_FIELD", f"unknown run {self.run_id}")
        run = value["run"]
        identity = tuple(run[field] for field in IDENTITY_FIELDS)
        if self._identity is not None and identity != self._identity:
            return {"schema": SCHEMA, "type": "error", "terminal": True, "run": run,
                    "error": {"code": "RUN_IDENTITY_CHANGED", "message": "The run generation or fixed input changed; reconnect to the current run."}}
        self._identity = identity
        state = run["state"]
        event = {"schema": SCHEMA, "type": "status", "terminal": state in TERMINAL,
                 "run": run, "progress": value["checkpoint"]}
        if state == "COMPLETED":
            if value["result"] is None:
                raise BacktestError("REPORT_CORRUPT", "completed run has no committed report")
            summary = await asyncio.to_thread(self.owner.service.get_report_view, self.run_id)
            if self._updates.closed:
                raise asyncio.CancelledError
            event.update(type="completed", result={**value["result"], "summary": summary})
        elif state == "FAILED":
            event.update(type="failed", error=value["failure"])
        elif state == "CANCELLED":
            event.update(type="cancelled")
        elif value["checkpoint"] is not None:
            event.update(type="progress")
        return event

    async def prepare(self) -> None:
        self._first = await self._read()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        if self._iterating:
            raise RuntimeError("a strategy subscription has one consumer")
        self._iterating = True
        previous = None
        try:
            event, self._first = self._first, None
            while not self._updates.closed:
                if event is None:
                    event = await self._read()
                if event != previous:
                    yield event
                    previous = event
                if event["terminal"]:
                    return
                event = None
                while not self._updates.closed:
                    try:
                        if not await asyncio.wait_for(self._updates.wait(), self.owner.heartbeat_seconds):
                            return
                        break
                    except TimeoutError:
                        # Keep the transport alive without polling durable state.
                        yield {"schema": SCHEMA, "type": "heartbeat", "terminal": False}
        except BacktestError as exc:
            yield {"schema": SCHEMA, "type": "error", "terminal": True,
                   "run_id": self.run_id, "error": {"code": exc.code, "message": exc.message}}
        except Exception:
            yield {"schema": SCHEMA, "type": "error", "terminal": True,
                   "run_id": self.run_id, "error": {"code": "STRATEGY_STREAM_FAILED",
                   "message": "The committed strategy result could not be read; reconnect to inspect the run."}}
        finally:
            self.close()

    def close(self) -> None:
        self._first = None
        self._updates.close()
        self.owner._subscriptions.discard(self)


class StrategyDataManager:
    def __init__(self, service: BacktestService, *, runtime: BacktestRuntime | None = None, market_manager=None,
                 max_subscriptions: int = 32, heartbeat_seconds: float = 15) -> None:
        if max_subscriptions < 1 or heartbeat_seconds <= 0:
            raise ValueError("strategy subscription limits must be positive")
        self.service = service
        self.runtime = runtime
        self.market_manager = market_manager
        self.continuous = None
        self._continuous_access = None
        self._control_requests = 0
        self.max_subscriptions = max_subscriptions
        self.heartbeat_seconds = heartbeat_seconds
        self._subscriptions: set[StrategyRunSubscription] = set()
        self._closed = False

    def bind_continuous(self, runtime):
        """Adopt one backend owner; observing/unmounting a view never adopts it."""
        if self._closed:
            raise BacktestError("STRATEGY_MANAGER_CLOSED","strategy manager is closed")
        read_only=(self.market_manager is None and runtime.manager is None
            and getattr(runtime,"execution_enabled",True) is False)
        if not read_only and (self.market_manager is None or runtime.manager is not self.market_manager):
            raise BacktestError("CONTINUOUS_SOURCE_UNAVAILABLE","Continuous execution requires this profile's live DataManager")
        if runtime.store.path.parent.resolve() != self.service.settings.db_path.parent.resolve():
            raise BacktestError("CONTINUOUS_INPUT_INVALID","Continuous execution store belongs to another profile")
        if self.continuous is not None and self.continuous is not runtime:
            raise RuntimeError("continuous strategy owner is already bound")
        self.continuous = runtime
        return runtime

    async def shutdown(self):
        self.close()
        if self._continuous_access is not None:
            await self._continuous_access.shutdown()
        elif self.continuous is not None:
            await self.continuous.close()

    def continuous_access(self):
        if self._closed:raise BacktestError("STRATEGY_MANAGER_CLOSED","strategy manager is closed")
        if self._continuous_access is None:
            from .continuous_strategy import ContinuousStrategyAccess
            self._continuous_access=ContinuousStrategyAccess(self)
        return self._continuous_access

    async def start_continuous(self):
        return await self.continuous_access().start()

    def control_plane(self) -> BacktestService:
        if self._closed:
            raise BacktestError("STRATEGY_MANAGER_CLOSED", "strategy manager is closed")
        self._control_requests += 1
        return self.service

    async def subscribe_run(self, run_id: str) -> StrategyRunSubscription:
        if self._closed:
            raise BacktestError("STRATEGY_MANAGER_CLOSED", "strategy manager is closed")
        continuous_count=0 if self._continuous_access is None else len(self._continuous_access.subscriptions)
        if len(self._subscriptions)+continuous_count >= self.max_subscriptions:
            raise BacktestError("RUN_CAPACITY_EXCEEDED", "strategy subscription capacity reached")
        subscription = StrategyRunSubscription(self, run_id)
        self._subscriptions.add(subscription)
        try:
            # Errors in the initial lookup are returned before streaming headers.
            await subscription.prepare()
            return subscription
        except BaseException:
            subscription.close()
            raise

    def diagnostics(self) -> dict[str, int | bool]:
        continuous=() if self._continuous_access is None else tuple(self._continuous_access.subscriptions)
        subscriptions=tuple(self._subscriptions)+continuous
        return {"closed": self._closed, "control_requests": self._control_requests, "subscriptions": len(subscriptions),
                "runs": len({subscription.run_id for subscription in subscriptions})}

    def close(self) -> None:
        self._closed = True
        for subscription in tuple(self._subscriptions):
            subscription.close()
        if self._continuous_access is not None:self._continuous_access.close_views()
