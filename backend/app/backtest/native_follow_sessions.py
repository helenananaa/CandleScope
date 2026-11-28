"""Warm Pine FOLLOW sessions: a bar close executes only the new bars (ADR-BACKTEST-015 O1, B-157a).

A native Pine strategy on the chart follows live bars by rebuilding a FIXED run over
the latest prefix after each bar close (O1). When the runtime declares
``follow_session`` (its engine extends a fixed history), the host keeps one engine
session per followed run (the *base*). A rebuild whose input is the previous
rebuild's over more bars extends that session, so only the new bars execute. Any
other rebuild opens a new session.

The result is the FIXED run of the same input either way (§3.4): the runtime opens
a session only for scripts where incremental and full execution agree, and answers
``supported: false`` otherwise. Every failure falls back to the ordinary full run,
which then decides the result. Sessions are a cache: at most ``WARM_SESSIONS``
stay open, the least recently used and idle ones close, and nothing is persisted.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

from .errors import BacktestError
from .native import digest

FOLLOW_CONTRACT = "candlescope.pine-follow/1"
WARM_SESSIONS = 4
IDLE_SECONDS = 15 * 60
# The fields a rebuild grows; every other field of the input must stay the same.
_GROWING = frozenset({"bars", "execution_times", "host_inputs"})

log = logging.getLogger(__name__)


def _static(wire):
    inputs = {key: value for key, value in (wire.get("host_inputs") or {}).items() if key != "executionTimes"}
    return {**{key: value for key, value in wire.items() if key not in _GROWING}, "host_inputs": inputs}


def _prefix(previous, current, count):
    if previous is None or current is None:
        return previous is None and current is None
    return isinstance(current, list) and len(current) > count and current[:count] == previous


def continues(previous, wire):
    """Whether ``wire`` is ``previous`` over more bars, with every other input unchanged."""
    count = len(previous["bars"])
    return (len(wire["bars"]) > count and wire["bars"][:count] == previous["bars"]
            and _prefix(previous.get("execution_times"), wire.get("execution_times"), count)
            and _prefix((previous.get("host_inputs") or {}).get("executionTimes"),
                        (wire.get("host_inputs") or {}).get("executionTimes"), count)
            and _static(previous) == _static(wire))


def _open_worker(plugin, wire, cancelled):
    from .native_session import SessionWorker
    return SessionWorker(plugin, wire, cancelled)


class _Warm:
    def __init__(self, worker):
        self.worker = worker
        self.wire = None
        self.used = time.monotonic()


class _Unsupported:
    """The runtime keeps full rebuilds for this input; don't start a process to ask again."""

    def __init__(self, key):
        self.key = key
        self.used = time.monotonic()


class FollowSessions:
    def __init__(self, open_worker=_open_worker, *, capacity=WARM_SESSIONS, idle_seconds=IDLE_SECONDS,
                 clock=time.monotonic):
        self.open_worker, self.capacity, self.idle_seconds, self.clock = open_worker, capacity, idle_seconds, clock
        self.lock = threading.Lock()
        self.entries: OrderedDict[str, _Warm | _Unsupported] = OrderedDict()
        self.closed = False

    def run(self, base, plugin, wire, cancelled):
        """The result of ``wire`` from the base's session, or None to run it in full."""
        if wire.get("identity", {}).get("follow_session") != FOLLOW_CONTRACT or "host_settings" in wire:
            return None
        key = digest(_static(wire))
        with self.lock:
            if self.closed:
                return None
            entry = self.entries.pop(base, None)  # exclusive while this rebuild runs
            expired = self._expire_locked()
        self._close(expired)
        if isinstance(entry, _Unsupported):
            if entry.key == key:
                self._keep(base, entry)
                return None
            entry = None
        try:
            if entry is not None and continues(entry.wire, wire):
                result = entry.worker.request({**wire, "operation": "extend"}, cancelled)
            else:
                self._close([entry])
                entry = None
                worker = self.open_worker(plugin, {**wire, "follow_contract": FOLLOW_CONTRACT}, cancelled)
                if not worker.supported:
                    worker.close()
                    self._keep(base, _Unsupported(key))
                    return None
                entry = _Warm(worker)
                result = worker.advance(len(wire["bars"]), cancelled)
        except Exception as exc:
            self._close([entry])
            if isinstance(exc, BacktestError) and exc.code == "NATIVE_CANCELLED":
                raise
            log.info("Pine FOLLOW session for %s fell back to a full rebuild: %s", base, exc)
            return None
        entry.wire, entry.used = wire, self.clock()
        self._keep(base, entry)
        return result

    def drop(self, base):
        with self.lock:
            entry = self.entries.pop(base, None)
        self._close([entry])

    def close(self):
        with self.lock:
            self.closed = True
            entries, self.entries = list(self.entries.values()), OrderedDict()
        self._close(entries)

    def _keep(self, base, entry):
        with self.lock:
            replaced = self.entries.pop(base, None)
            if self.closed:
                stale = [entry, replaced]
            else:
                self.entries[base] = entry
                stale = [replaced] if replaced is not entry else []
                warm = [name for name, item in self.entries.items() if isinstance(item, _Warm)]
                stale += [self.entries.pop(name) for name in warm[:max(0, len(warm) - self.capacity)]]
                while len(self.entries) > 4 * self.capacity:  # bound the memo of unsupported inputs
                    stale.append(self.entries.popitem(last=False)[1])
        self._close(stale)

    def _expire_locked(self):
        now = self.clock()
        idle = [name for name, item in self.entries.items() if now - item.used > self.idle_seconds]
        return [self.entries.pop(name) for name in idle]

    @staticmethod
    def _close(entries):
        for entry in entries:
            if isinstance(entry, _Warm):
                try:
                    entry.worker.close()
                except Exception:
                    log.warning("Pine FOLLOW session did not close cleanly", exc_info=True)
