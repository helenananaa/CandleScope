"""FOLLOW for HOST-authority strategies (ADR-BACKTEST-015 §3.4, step P4b).

A FOLLOW run keeps a chart's strategy up to date as bars close. It is the
forward-run advancer (``ContinuousBarHost``: provider session, planner and bar
kernel) without its persistence: no store, no commits, no repair approval. It
consumes the chart's own closed bars at the chart's interval, exactly as a FIXED
run does. A chart cell holds it through a lease; it stops when no chart holds it
and is shared by identical inputs.

Invariant (§3.4): for deterministic close-bar strategies, the result after any
sequence of ``extend`` calls is the result of one fixed pass over the same bars,
because ``SimulationKernel.advance`` preserves the BAR event order across batches.
The shown result is the un-finalized state: a FIXED run ends by appending a
terminal equity point and cancelling working orders; a FOLLOW run has no end.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict
from typing import Any

from app.market_dataset.snapshot import MarketEvent

from .continuous_bar_host import ContinuousBarHost
from .errors import BacktestError
from .strategy.protocol import canonical_hash

ID_PREFIX = "fl_"


def _invalid(message: str) -> BacktestError:
    return BacktestError("FOLLOW_INPUT_INVALID", message)


def _closed(payload: Mapping[str, Any]) -> bool:
    final = payload.get("is_closed")
    # Stored snapshots carry integer 1; the live feed True; derived bars omit it.
    return final is None or final is True or (type(final) is int and final == 1)


class FollowSession:
    """One FOLLOW run's live state: consecutive closed base bars in, the current result out."""

    def __init__(self, follow_id: str, definition: Mapping[str, Any], provider_factory, *, interval: str,
                 generation: int = 1) -> None:
        from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec

        spec = parse_interval_spec(interval)
        fixed = spec is not None and not spec.timezone and spec.alignment is not IntervalAlignment.CALENDAR_MONTH
        step = spec.nominal_ms if fixed else None
        if not isinstance(step, int) or step <= 0:
            raise BacktestError("FIDELITY_UNSUPPORTED", "FOLLOW needs a fixed-length chart interval")
        self.follow_id = follow_id
        self.definition = definition
        self.interval = interval
        self.step_ms = step
        # A recomputation (processed bars were revised) starts a new generation of the same run.
        self.generation = generation
        # CATCHING_UP until the run first reaches the latest closed bar; then LIVE.
        # WAITING_DATA while the source cannot supply complete closed bars.
        self.phase = "CATCHING_UP"
        self.caught_up = False
        self.lock = threading.RLock()
        self.host = ContinuousBarHost(follow_id, definition, provider_factory)
        self.sequence = 0
        self.through_ms: int | None = None
        self.revision = 0
        self.failed: BaseException | None = None
        self.closed = False
        self._released = False

    def extend(self, events: Iterable[MarketEvent]) -> int:
        """Apply newly closed chart-interval bars, consecutive with what was applied; returns the revision."""
        with self.lock:
            if self.closed:
                raise BacktestError("FOLLOW_CLOSED", "This FOLLOW run has stopped")
            if self.failed is not None:
                raise BacktestError("FOLLOW_FAILED", "This FOLLOW run failed; recompute it from its start")
            batch: list[MarketEvent] = []
            sequence, through = self.sequence, self.through_ms
            for event in events:
                payload = event.payload
                opened, close = payload.get("open_time_ms"), payload.get("close_time_ms")
                if (event.role != "BARS" or not _closed(payload) or type(opened) is not int or type(close) is not int
                        or close != opened + self.step_ms - 1 or event.event_time_ms != close):
                    raise _invalid("FOLLOW takes closed bars of the chart interval only")
                if event.sequence != sequence + 1 or (through is not None and opened != through + 1):
                    raise _invalid("FOLLOW bars must continue exactly where the run is")
                sequence, through = event.sequence, close
                batch.append(event)
            if not batch:
                return self.revision
            try:
                self.host.kernel.advance(batch, self.host._observe)
            except BaseException as failure:
                # The kernel may have applied part of the batch: the run must start over.
                self.failed = failure
                raise
            finally:
                if self.closed:  # stopped while this batch ran: release what close() could not
                    self._release()
            self.sequence, self.through_ms = sequence, through
            self.revision += 1
            return self.revision

    def result(self) -> dict[str, Any]:
        """The current state as ``candlescope.run-result/1`` (clock policy FOLLOW)."""
        from .run_result import from_host_result

        with self.lock:
            if self.failed is not None:
                raise BacktestError("FOLLOW_FAILED", "This FOLLOW run failed; recompute it from its start")
            raw = asdict(self.host.kernel.result())
        return from_host_result(raw, interval=self.interval, fidelity="BAR_APPROX", clock_policy="FOLLOW")

    def close(self) -> None:
        """Stop the run without waiting for a batch in progress; that batch releases the provider when it ends."""
        self.closed = True
        if self.lock.acquire(blocking=False):
            try:
                self._release()
            finally:
                self.lock.release()

    def _release(self) -> None:
        if not self._released:
            self._released = True
            self.host.close()


def follow_identity(definition: Mapping[str, Any], interval: str, from_ms: int | None = None) -> str:
    """Identical inputs share one FOLLOW run (ADR O2: cached by input identity).

    Where a live run starts is part of its input: the same code from another bar is another run.
    """
    value = {"schema": "candlescope.follow-input/1", "definition": dict(definition), "interval": interval}
    if from_ms is not None:
        value["from_ms"] = from_ms
    return canonical_hash(value)


class _Entry:
    def __init__(self, session: FollowSession, identity: str, interval: str) -> None:
        self.session = session
        self.identity = identity
        self.interval = interval
        self.leases: dict[str, float] = {}


class FollowSessions:
    """FOLLOW runs held by chart-cell leases. A run without a live lease stops (§3.4: no chart, no run).

    Bounded: at most ``capacity`` runs at once; a new input beyond that is refused.
    """

    def __init__(self, provider_factory, *, capacity: int = 16, lease_ms: int = 30_000,
                 clock: Callable[[], float] = time.monotonic,
                 on_stop: Callable[[FollowSession], None] | None = None) -> None:
        if capacity < 1 or lease_ms < 1:
            raise ValueError("FOLLOW limits must be positive")
        self.provider_factory = provider_factory
        # Told, under the lock, when a run stops: whoever reads it next must see it stopped.
        self.on_stop = on_stop
        self.capacity = capacity
        self.lease_s = lease_ms / 1000
        self.clock = clock
        self.lock = threading.RLock()
        self._entries: dict[str, _Entry] = {}
        self._by_identity: dict[str, str] = {}
        self._counter = 0

    def open(self, definition: Mapping[str, Any], *, interval: str, holder: str,
             from_ms: int | None = None) -> tuple[FollowSession, bool]:
        """The FOLLOW run for this input, shared if one exists; returns (session, created)."""
        identity = follow_identity(definition, interval, from_ms)
        with self.lock:
            self._sweep()
            existing = self._by_identity.get(identity)
            if existing is not None:
                entry = self._entries[existing]
                self._hold(entry, holder)
                return entry.session, False
            if len(self._entries) >= self.capacity:
                raise BacktestError("FOLLOW_CAPACITY_EXCEEDED", "Too many charts follow strategies at once")
            self._counter += 1
            follow_id = f"{ID_PREFIX}{identity[7:39]}{self._counter:04x}"
            session = FollowSession(follow_id, definition, self.provider_factory, interval=interval)
            entry = _Entry(session, identity, interval)
            self._entries[follow_id] = entry
            self._by_identity[identity] = follow_id
            self._hold(entry, holder)
            return session, True

    def get(self, follow_id: str) -> FollowSession:
        with self.lock:
            self._sweep()
            entry = self._entries.get(follow_id)
            if entry is None:
                raise BacktestError("RUN_NOT_FOUND", "unknown or stopped FOLLOW run")
            return entry.session

    def recompute(self, follow_id: str) -> FollowSession:
        """Start the run over from its first bar (its processed input was revised); leases carry over."""
        with self.lock:
            entry = self._entries.get(follow_id)
            if entry is None:
                raise BacktestError("RUN_NOT_FOUND", "unknown or stopped FOLLOW run")
            old = entry.session
            entry.session = FollowSession(follow_id, old.definition, self.provider_factory, interval=entry.interval,
                                          generation=old.generation + 1)
            old.close()
            return entry.session

    def renew(self, follow_id: str, holder: str) -> None:
        with self.lock:
            self._sweep()
            entry = self._entries.get(follow_id)
            if entry is None:
                raise BacktestError("RUN_NOT_FOUND", "unknown or stopped FOLLOW run")
            self._hold(entry, holder)

    def release(self, follow_id: str, holder: str) -> None:
        """A chart cell lets go. The run stops once no cell holds it."""
        with self.lock:
            entry = self._entries.get(follow_id)
            if entry is None:
                return
            entry.leases.pop(holder, None)
            if not entry.leases:
                self._stop(follow_id)

    def sweep(self) -> None:
        with self.lock:
            self._sweep()

    def stop(self, follow_id: str) -> None:
        """Stop a run whatever holds it (its feed ended)."""
        with self.lock:
            self._stop(follow_id)

    def close(self) -> None:
        with self.lock:
            for follow_id in list(self._entries):
                self._stop(follow_id)

    def diagnostics(self) -> dict[str, int]:
        with self.lock:
            return {"runs": len(self._entries), "leases": sum(len(entry.leases) for entry in self._entries.values())}

    def _hold(self, entry: _Entry, holder: str) -> None:
        if not isinstance(holder, str) or not 1 <= len(holder) <= 200:
            raise _invalid("a FOLLOW lease names its chart cell")
        entry.leases[holder] = self.clock() + self.lease_s

    def _sweep(self) -> None:
        now = self.clock()
        for follow_id, entry in list(self._entries.items()):
            for holder, expires in list(entry.leases.items()):
                if expires <= now:
                    del entry.leases[holder]
            if not entry.leases:
                self._stop(follow_id)

    def _stop(self, follow_id: str) -> None:
        entry = self._entries.pop(follow_id, None)
        if entry is None:
            return
        self._by_identity.pop(entry.identity, None)
        entry.session.close()
        if self.on_stop is not None:
            self.on_stop(entry.session)
