"""Bounded native sessions behind the existing full-snapshot transport.

The host supplies a subscription identity; HTTP computations remain independent.
Changed history is replayed, never mistaken for a realtime append.
"""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass
class Session:
    identity: Any
    native: Any
    confirmed: list[dict]
    forming_time: int | None = None


class PineSessions:
    def __init__(self, capacity: int = 8) -> None:
        self.capacity = capacity
        self.entries: OrderedDict[str, Session] = OrderedDict()

    def clear(self) -> None:
        self.entries.clear()

    def execute(self, engine, source, bars, options, *, session_id, forming):
        identity = (source, options)
        confirmed = bars[:-1] if forming else bars
        entry = self.entries.get(session_id) if session_id else None
        reset = (
            entry is None
            or entry.identity != identity
            or confirmed[:len(entry.confirmed)] != entry.confirmed
            or (entry.forming_time is not None and (
                len(bars) <= len(entry.confirmed)
                or bars[len(entry.confirmed)]["time"] != entry.forming_time
            ))
        )
        try:
            if reset:
                native = engine.create_realtime_session(source, **options)
                native.seed(confirmed)
                entry = Session(identity, native, list(confirmed))
            else:
                for bar in confirmed[len(entry.confirmed):]:
                    entry.native.update_confirmed(bar)
                entry.confirmed = list(confirmed)
                entry.forming_time = None
            if forming:
                # A subscription may begin midway through an already open bar.
                entry.native.update_forming(bars[-1], opening_update=False if reset else None)
                entry.forming_time = bars[-1]["time"]
            raw = entry.native.result()
            if session_id:
                self.entries[session_id] = entry
                self.entries.move_to_end(session_id)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
            return raw, {"sessionReset": reset, "executionMode": "realtime-session",
                         "incremental": not reset, "formingBar": forming,
                         "sessionRetained": bool(session_id)}
        except Exception:
            # A multi-bar update can fail after an earlier bar committed. Never
            # reuse that partially advanced session for the next request.
            self.entries.pop(session_id, None)
            raise
