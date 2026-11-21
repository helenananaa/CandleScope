"""FOLLOW runs fed by the DataManager (ADR-BACKTEST-015 §3.4, step P4b2).

Each FOLLOW run has one feed: it subscribes to its chart series' bar events,
reads the closed bars the run has not applied (trusted and contiguous), and
advances the run off the event loop. Rules from §3.4:

- no chart, no run: a run stops when no chart-cell lease is live;
- processed bars revised (an amended bar the run has read, or a backfill that
  changed the processed range): the run recomputes from its first bar on its
  own, as a new generation; nothing waits for approval;
- a forming bar never enters: only bars that closed before ``clock_ms()`` do.

A newly closed bar can reach the DataManager a moment after its close; within
``TAIL_GRACE_MS`` the run stays LIVE. Older missing bars are backfilled and the
run reports WAITING_DATA until they arrive.

Bounded: at most ``capacity`` runs; a run starts at most ``MAX_FOLLOW_BARS``
bars back and, once it holds twice that many, restarts from the newest
``MAX_FOLLOW_BARS`` bars (ADR O2: HOST incremental window 20,000).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import Field, ValidationError

from app.backtest.continuous_contracts import CurrentProvider, MarketSeries, StrictInput
from app.backtest.errors import BacktestError
from app.backtest.follow_session import FollowSession, FollowSessions
from app.core.committed_updates import CommittedUpdates
from app.market_dataset.snapshot import MarketEvent

from .models import DataEventType

if TYPE_CHECKING:
    from .strategy import StrategyDataManager

logger = logging.getLogger(__name__)
MAX_FOLLOW_BARS = 20_000
PAGE_BARS = 1000
TAIL_GRACE_MS = 30_000
MAX_ENDED = 256
WAKE_EVENTS = {DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED, DataEventType.BACKFILL_COMPLETED,
               DataEventType.SOURCE_GAP_RESOLVED, DataEventType.STREAM_STARTED}


class FollowCreate(StrictInput):
    holder: str = Field(min_length=1, max_length=200)
    series: MarketSeries
    provider: CurrentProvider
    execution: dict[str, Any]
    from_ms: int = Field(ge=0, le=9_007_199_254_740_991)
    warmup_bars: int = Field(default=0, ge=0, le=200_000)


class FollowFromRun(StrictInput):
    """Keep a completed fixed host run current: the same code, configuration and start, on live bars."""
    holder: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=4, max_length=128, pattern=r"^bt_\S+$")
    series: MarketSeries


class FollowLease(StrictInput):
    holder: str = Field(min_length=1, max_length=200)


def _row_bytes(row: dict[str, Any]) -> bytes:
    return json.dumps(row, sort_keys=True, separators=(",", ":")).encode()


class _Feed:
    """The loop that applies one FOLLOW run's newly closed bars."""

    def __init__(self, owner: StrategyFollows, session: FollowSession, key, from_ms: int, spec) -> None:
        self.owner, self.session, self.key, self.from_ms, self.spec = owner, session, key, from_ms, spec
        self.follow_id = session.follow_id
        self.step = int(spec.nominal_ms)
        self.wake = asyncio.Event()
        self.recompute = False
        self.verify = False
        # The newest bar this generation has read: an amendment at or before it may be in the run.
        self.read_through_ms: int | None = None
        self.digest = hashlib.sha256()
        self.subscription = None
        self.streaming = False
        self.task: asyncio.Task | None = None

    # -- lifecycle ----------------------------------------------------------

    def _stream_args(self) -> dict[str, Any]:
        return {"exchange": self.key.exchange, "market_type": self.key.market_type, "series_identity": self.key.identity,
                "consumer_id": f"strategy-follow:{self.follow_id}", "focus_scope": "background"}

    async def start(self) -> None:
        loop = asyncio.get_running_loop()

        async def changed(event) -> None:
            if event.event_type is DataEventType.BAR_CLOSED and event.bar is not None:
                # The source may report a close just before this clock passes it: wake again at the boundary.
                boundary = int(event.bar.time) * 1000 + self.step
                delay = (boundary - int(self.owner.clock_ms())) / 1000
                if 0 < delay <= 60:
                    loop.call_later(delay, self.wake.set)
            if event.event_type is DataEventType.BAR_AMENDED:
                read = self.read_through_ms
                bar = event.bar or event.previous_bar
                if read is not None and (bar is None or int(bar.time) * 1000 <= read):
                    self.recompute = True
            elif event.event_type is DataEventType.BACKFILL_COMPLETED:
                self.verify = True
            self.wake.set()

        async def lost(_error) -> None:
            # Events may have been missed: check what the run has processed.
            self.verify = True
            self.wake.set()

        self.subscription = await self.owner.market.subscribe_async(
            changed, symbol=self.key.symbol, interval=self.key.interval, exchange=self.key.exchange,
            market_type=self.key.market_type, series_identity=self.key.identity, event_types=WAKE_EVENTS,
            continuity="gap_aware", on_recovery=lost)
        try:
            # The chart's stream may close before its lease expires; the run keeps its own.
            await self.owner.market.bars.ensure_stream(self.key.symbol, self.key.interval, **self._stream_args())
            self.streaming = True
        except Exception:
            logger.warning("FOLLOW run %s could not hold its live stream; it follows stored bars", self.follow_id,
                           exc_info=True)
        self.task = asyncio.create_task(self._run(), name=f"strategy-follow:{self.follow_id}")

    async def cancel(self) -> None:
        task = self.task
        if task is None:
            await self._unsubscribe()
            return
        if task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _unsubscribe(self) -> None:
        if self.subscription is not None:
            subscription, self.subscription = self.subscription, None
            try:
                await self.owner.market.unsubscribe_async(subscription)
            except Exception:
                logger.warning("FOLLOW feed %s did not unsubscribe cleanly", self.follow_id, exc_info=True)
        if self.streaming:
            self.streaming = False
            try:
                await self.owner.market.release_stream(self.key.symbol, self.key.interval, **self._stream_args())
            except Exception:
                logger.warning("FOLLOW feed %s did not release its stream", self.follow_id, exc_info=True)

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.to_thread(self.owner.sessions.sweep)
                current = self.owner.sessions_or_none(self.follow_id)
                if current is None:
                    return
                self.session = current
                await self._step()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=self.owner.sweep_s)
                except TimeoutError:
                    pass
                self.wake.clear()
        finally:
            await self.owner._retire(self)

    # -- one pass -----------------------------------------------------------

    async def _step(self) -> None:
        session = self.session
        if self.recompute:
            session = await self._restart()
        elif self.verify:
            self.verify = False
            try:
                changed = await asyncio.to_thread(self._processed_changed, session)
            except Exception:
                logger.warning("FOLLOW run %s could not re-read its processed bars", self.follow_id, exc_info=True)
                changed = None
            if changed is None:  # not readable now: check again on the next wake
                self.verify = True
                if session.failed is None:
                    self._waiting(session)
                return
            if changed:
                session = await self._restart()
        if session.failed is not None or session.closed:
            return
        try:
            await self._catch_up(session)
        except asyncio.CancelledError:
            raise
        except BacktestError as failure:
            if failure.code == "FOLLOW_CLOSED":
                return
            self._fail(session, failure)
        except Exception as failure:
            self._fail(session, failure)

    def _fail(self, session: FollowSession, failure: BaseException) -> None:
        session.failed = session.failed or failure
        session.phase = "FAILED"
        logger.warning("FOLLOW run %s failed", self.follow_id, exc_info=failure)
        self.owner.notify(self.follow_id)

    def _waiting(self, session: FollowSession) -> None:
        if session.phase != "WAITING_DATA":
            session.phase = "WAITING_DATA"
            self.owner.notify(self.follow_id)

    async def _restart(self, from_ms: int | None = None) -> FollowSession:
        """Start the run over as its next generation (§3.4: revised input recomputes automatically)."""
        self.recompute = self.verify = False
        self.read_through_ms = None
        self.digest = hashlib.sha256()
        if from_ms is not None:
            self.from_ms = from_ms
        self.session = await asyncio.to_thread(self.owner.sessions.recompute, self.follow_id)
        self.owner.notify(self.follow_id)
        return self.session

    def _closed_through(self) -> int:
        """The close of the newest bar that has closed: the bar holding ``now`` is still forming."""
        return int(self.spec.floor_ms(int(self.owner.clock_ms()))) - 1

    async def _catch_up(self, session: FollowSession) -> None:
        through = self._closed_through()
        while True:
            cursor = self.from_ms if session.through_ms is None else session.through_ms + 1
            if (cursor - self.from_ms) // self.step >= 2 * MAX_FOLLOW_BARS:
                session = await self._restart(through + 1 - MAX_FOLLOW_BARS * self.step)
                continue
            if cursor > through:
                break
            last = min(through, cursor + PAGE_BARS * self.step - 1)
            self.read_through_ms = max(self.read_through_ms or -1, last)
            try:
                rows, complete = await asyncio.to_thread(self._read, cursor, last)
            except Exception:
                logger.warning("FOLLOW run %s could not read bars", self.follow_id, exc_info=True)
                self._waiting(session)
                return
            if self.recompute:
                return  # an amendment arrived while reading: these rows may be stale
            if rows:
                events = [MarketEvent(session.sequence + index, row["close_time_ms"], "BARS", row)
                          for index, row in enumerate(rows, start=1)]
                await asyncio.to_thread(session.extend, events)
                for row in rows:
                    self.digest.update(_row_bytes(row))
                self.owner.notify(self.follow_id)
            if not complete:
                if self._overdue(cursor + len(rows) * self.step):
                    self._waiting(session)
                    return
                break  # only the newest bars are late: the run is live up to what has arrived
        if session.phase != "LIVE" or not session.caught_up:
            session.phase, session.caught_up = "LIVE", True
            self.owner.notify(self.follow_id)

    def _overdue(self, missing_open_ms: int) -> bool:
        return int(self.owner.clock_ms()) - (missing_open_ms + self.step - 1) > TAIL_GRACE_MS

    def _read(self, start_ms: int, through_ms: int) -> tuple[list[dict[str, Any]], bool]:
        rows = self._query(start_ms, through_ms, backfill=False)
        missing = start_ms + len(rows) * self.step
        if missing <= through_ms and self._overdue(missing):
            # Bars older than the grace are missing: ask the DataManager to backfill from the first of them.
            rows += self._query(missing, through_ms, backfill=True)
        return rows, start_ms + len(rows) * self.step > through_ms

    def _query(self, start_ms: int, through_ms: int, *, backfill: bool) -> list[dict[str, Any]]:
        """The trusted contiguous closed bars from ``start_ms`` up to ``through_ms``: all of them, or a prefix."""
        from app.local_data.service import LocalDatasetService

        step = self.step
        count = (through_ms + 1 - start_ms) // step
        result = self.owner.market.bars.query(
            self.key.symbol, self.key.interval, exchange=self.key.exchange, market_type=self.key.market_type,
            series_identity=self.key.identity, start_ms=start_ms, end_ms=through_ms - step + 1, limit=count,
            auto_backfill=backfill, backfill_requester="strategy-follow")
        rows: list[dict[str, Any]] = []
        for index, bar in enumerate(result.bars):
            opened = start_ms + index * step
            if not bar.trusted_final or int(bar.time) * 1000 != opened:
                break
            payload = {name: LocalDatasetService._decimal_text(LocalDatasetService._host_decimal(bar, name, index + 1))
                       for name in ("open", "high", "low", "close", "volume")}
            rows.append({**payload, "open_time_ms": opened, "close_time_ms": opened + step - 1, "is_closed": True})
        return rows

    def _processed_changed(self, session: FollowSession) -> bool | None:
        """Whether the processed bars differ from what the run applied; None when they cannot all be read now."""
        through = session.through_ms
        if through is None:
            return False
        digest = hashlib.sha256()
        cursor = self.from_ms
        while cursor <= through:
            last = min(through, cursor + PAGE_BARS * self.step - 1)
            rows = self._query(cursor, last, backfill=False)
            if len(rows) != (last + 1 - cursor) // self.step:
                return None
            for row in rows:
                digest.update(_row_bytes(row))
            cursor = last + 1
        return digest.digest() != self.digest.digest()


class StrategyFollows:
    """The FOLLOW runs of one profile: created and held by chart cells, fed by its DataManager."""

    def __init__(self, owner: StrategyDataManager, *, provider_factory=None, clock_ms: Callable[[], int] | None = None,
                 capacity: int = 16, lease_ms: int = 30_000, sweep_s: float = 5.0) -> None:
        from app.backtest.continuous_provider import ContinuousProviderFactory

        if owner.market_manager is None:
            raise BacktestError("FOLLOW_UNAVAILABLE", "FOLLOW needs this profile's live DataManager")
        self.owner = owner
        self.market = owner.market_manager
        if provider_factory is None:
            scratch = owner.service.settings.db_path.parent / "follow-scratch"
            scratch.mkdir(parents=True, exist_ok=True)
            provider_factory = ContinuousProviderFactory(scratch_root=scratch)
        self._current_code = provider_factory
        self.sessions = FollowSessions(self._provider, capacity=capacity, lease_ms=lease_ms, on_stop=self._stopped)
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.sweep_s = sweep_s
        self.updates = CommittedUpdates()
        self.feeds: dict[str, _Feed] = {}
        # Runs that stopped, so a watcher or a late status read sees CANCELLED rather than an unknown id.
        self.ended: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._versions: dict[str, str | None] = {}
        self._ended_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.closed = False

    def _stopped(self, session: FollowSession) -> None:
        """A run stopped (no lease left, or shutdown); may run on any thread, under the sessions' lock."""
        with self._ended_lock:
            self.ended[session.follow_id] = {"generation": session.generation, "definition": session.definition,
                                             "error": None if session.failed is None else "FOLLOW_FAILED"}
            self.ended.move_to_end(session.follow_id)
            while len(self.ended) > MAX_ENDED:
                gone, _ = self.ended.popitem(last=False)
                self._versions.pop(gone, None)
        self.notify(session.follow_id)
        feed = self.feeds.get(session.follow_id)
        if feed is not None and self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(feed.wake.set)
            except RuntimeError:
                pass  # the loop has closed

    def _provider(self, definition):
        """A followed fixed run runs its own frozen revision; current code runs through the forward-run factory."""
        host = definition.get("host_run")
        if host is None:
            return self._current_code(definition)
        return self.owner.service.build_python_host_provider(
            host["strategy_revision_id"], parameters=dict(definition["input_plan"]["parameters"]),
            mode=host["python_runtime_mode"], trusted_confirmed=host["python_trusted_confirmed"])

    def _definition_from_run(self, request: FollowFromRun, key) -> tuple[dict[str, Any], int]:
        """The FOLLOW definition of a completed fixed run and its first bar (§3.4: FOLLOW equals FIXED)."""
        from app.backtest.models import ENGINE_VERSION
        from app.data_engine.interval_policy import parse_interval_spec

        service = self.owner.service
        try:
            record = service.get_run(request.run_id)
        except BacktestError as failure:
            if failure.code == "SCHEMA_UNKNOWN_FIELD":
                raise BacktestError("RUN_NOT_FOUND", "unknown fixed run to follow") from None
            raise
        if record["state"] != "COMPLETED" or record["fidelity_mode"] != "BAR_APPROX":
            raise BacktestError("FOLLOW_INPUT_INVALID", "FOLLOW continues a completed bar run")
        revision = service.repository.get_strategy_revision(str(record["strategy_revision_id"]))
        if revision is None or revision["base_revision_id"] != "python-source-v1":
            # Pine on the chart follows by rebuilding its prefix (O1); the continuation host does not run it.
            raise BacktestError("FIDELITY_UNSUPPORTED", "Only Python host runs follow live bars here")
        config = json.loads(str(record["config_json"]))
        if (config.get("exchange"), config.get("market_type"), config.get("symbol"), config.get("interval")) != (
                key.exchange, key.market_type, key.symbol, key.interval):
            raise BacktestError("FOLLOW_INPUT_INVALID", "The chart series is not the fixed run's market")
        spec = parse_interval_spec(key.interval)
        start = int(config["start_time_ms"])
        first = spec.floor_ms(start)
        first = first if first == start else first + spec.nominal_ms
        definition = {
            "engine_version": ENGINE_VERSION, "language": "python", "configuration": config,
            "input_plan": {"roles": ["BARS"], "parameters": dict(config.get("parameters") or {})},
            "market": {"venue": key.exchange, "symbol": key.symbol},
            "host_run": {"run_id": request.run_id, "strategy_revision_id": str(record["strategy_revision_id"]),
                         "python_runtime_mode": str(config.get("python_runtime_mode") or "SANDBOXED_LOCAL"),
                         "python_trusted_confirmed": bool(config.get("python_trusted_confirmed"))},
        }
        return definition, first

    def sessions_or_none(self, follow_id: str) -> FollowSession | None:
        try:
            return self.sessions.get(follow_id)
        except BacktestError:
            return None

    def notify(self, follow_id: str) -> None:
        self.updates.notify(follow_id)

    def version_hash(self, follow_id: str, definition: dict[str, Any]) -> str | None:
        """The content-addressed version of the run's code (P3b), recorded once per run."""
        if follow_id in self._versions:
            return self._versions[follow_id]
        from app.backtest.strategy_versions import StrategyVersions, continuous_material
        versions = StrategyVersions(self.owner.service.repository)
        host = definition.get("host_run")
        try:
            if host is not None:
                # A followed fixed run runs that run's version; it is linked when the run's status is read.
                found = versions.for_run(host["run_id"])
                if found is None:
                    return None
                value = found
            else:
                value = versions.record(continuous_material(definition), now_ms=int(time.time() * 1000))
        except Exception:
            logger.warning("Strategy version of FOLLOW run %s is unavailable", follow_id, exc_info=True)
            value = None
        self._versions[follow_id] = value
        return value

    async def open(self, body: object, *, trusted: bool = False) -> dict[str, Any]:
        """Hold the FOLLOW run for this input (shared by identical inputs), starting it if new.

        ``trusted``: the request came from the trusted local application, which Python code requires.
        """
        from app.backtest.continuous_definition import prepare_definition
        from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec

        if self.closed:
            raise BacktestError("STRATEGY_MANAGER_CLOSED", "strategy manager is closed")
        self._loop = asyncio.get_running_loop()
        from_run = isinstance(body, dict) and "run_id" in body
        try:
            request = (FollowFromRun if from_run else FollowCreate).model_validate(body)
        except (ValidationError, ValueError, TypeError):
            raise BacktestError("FOLLOW_INPUT_INVALID", "Invalid FOLLOW request fields") from None
        key = request.series.key()
        if not trusted and (from_run or request.provider.language == "python"):
            raise BacktestError("TRUSTED_ORIGIN_REQUIRED", "Python editor requires a trusted local application origin")
        if isinstance(request, FollowFromRun):
            definition, from_ms = await asyncio.to_thread(self._definition_from_run, request, key)
        else:
            definition = await asyncio.to_thread(
                prepare_definition, request.provider.model_dump(exclude_unset=True, by_alias=True), request.execution,
                key, warmup_bars=request.warmup_bars, follow=True)
            if definition["language"] == "python" and not trusted:
                raise BacktestError("TRUSTED_ORIGIN_REQUIRED", "Python editor requires a trusted local application origin")
            from_ms = request.from_ms
        spec = parse_interval_spec(key.interval)
        if spec is None or spec.timezone or spec.alignment is IntervalAlignment.CALENDAR_MONTH:
            raise BacktestError("FIDELITY_UNSUPPORTED", "FOLLOW needs a fixed-length chart interval")
        if from_ms != spec.floor_ms(from_ms):
            raise BacktestError("FOLLOW_INPUT_INVALID", "FOLLOW starts at a bar's open")
        if (spec.floor_ms(int(self.clock_ms())) - from_ms) // spec.nominal_ms > MAX_FOLLOW_BARS:
            raise BacktestError("BUDGET_EXCEEDED", f"FOLLOW starts at most {MAX_FOLLOW_BARS} bars back")
        session, created = await asyncio.to_thread(
            self.sessions.open, definition, interval=key.interval, holder=request.holder, from_ms=from_ms)
        if created:
            feed = _Feed(self, session, key, from_ms, spec)
            self.feeds[session.follow_id] = feed
            try:
                await feed.start()
            except BaseException:
                self.feeds.pop(session.follow_id, None)
                await asyncio.to_thread(self.sessions.stop, session.follow_id)
                await feed.cancel()
                raise
        return {"follow_id": session.follow_id, "created": created, "from_ms": from_ms,
                "lease_ms": int(self.sessions.lease_s * 1000)}

    async def renew(self, follow_id: str, body: object) -> dict[str, Any]:
        holder = self._holder(body)
        await asyncio.to_thread(self.sessions.renew, follow_id, holder)
        return {"follow_id": follow_id, "held": True, "lease_ms": int(self.sessions.lease_s * 1000)}

    async def release(self, follow_id: str, holder: str) -> dict[str, Any]:
        holder = self._holder({"holder": holder})
        await asyncio.to_thread(self.sessions.release, follow_id, holder)
        feed = self.feeds.get(follow_id)
        if feed is not None and self.sessions_or_none(follow_id) is None:
            await feed.cancel()
        return {"follow_id": follow_id, "held": False}

    @staticmethod
    def _holder(body: object) -> str:
        try:
            return FollowLease.model_validate(body).holder
        except (ValidationError, ValueError, TypeError):
            raise BacktestError("FOLLOW_INPUT_INVALID", "A FOLLOW lease names its chart cell") from None

    async def _retire(self, feed: _Feed) -> None:
        """A feed ended: its run stops, and later reads see it as stopped."""
        if self.feeds.get(feed.follow_id) is feed:
            del self.feeds[feed.follow_id]
        try:
            # Normally already stopped; a feed that ended on its own stops its run (§3.4: no feed, no run).
            await asyncio.to_thread(self.sessions.stop, feed.follow_id)
        finally:
            await feed._unsubscribe()

    async def close(self) -> None:
        self.closed = True
        await asyncio.to_thread(self.sessions.close)
        for feed in list(self.feeds.values()):
            await feed.cancel()
