"""Compact transport of owned MarketEvent snapshots to a spawn worker.

No global pickle reducer is installed. Unsupported objects retain their original
pickle behavior; the worker always receives the original tuple/MarketEvent API.

The default form is one columnar ``marshal`` buffer of builtin values, verified
against its SHA-256 before the worker decodes it. marshal accepts only exact
builtin types, keeps value types and dict order, and shares objects that were
shared, so the rebuilt tuple equals the original. Anything else falls back to
the row form below.
"""
import hashlib
import marshal

from app.core.config import getenv
from app.market_dataset.snapshot import MarketEvent

_COLUMNAR = "candlescope.spawn-events.columnar/1"


def _unchanged(events):
    return events


def _restore_columnar(buffer, digest, count):
    if "sha256:" + hashlib.sha256(buffer).hexdigest() != digest:
        raise ValueError("spawned market events do not match their identity")
    tag, sequences, times, roles, payloads, order = marshal.loads(buffer)
    if tag != _COLUMNAR:
        raise ValueError("unsupported spawned market event encoding")
    events = tuple(map(MarketEvent, sequences, times, roles, payloads))
    if order is not None:
        events = tuple(events[index] for index in order)
    if len(events) != count:
        raise ValueError("spawned market event count changed")
    return events


class _ColumnarEvents:
    def __init__(self, events):
        self.events = events

    def __reduce__(self):
        events = self.events
        if any(kind is not MarketEvent for kind in set(map(type, events))):
            return _PackedEvents(events).__reduce__()
        unique, order = events, None
        identities = list(map(id, events))
        if len(set(identities)) != len(identities):
            # Repeated MarketEvent objects stay one object in the worker.
            positions, unique, order = {}, [], []
            for event, identity in zip(events, identities):
                position = positions.get(identity)
                if position is None:
                    position = positions[identity] = len(unique)
                    unique.append(event)
                order.append(position)
        try:
            buffer = marshal.dumps((
                _COLUMNAR,
                [event.sequence for event in unique],
                [event.event_time_ms for event in unique],
                [event.role for event in unique],
                [event.payload for event in unique],
                order,
            ))
        except ValueError:
            return _PackedEvents(events).__reduce__()
        return _restore_columnar, (buffer, "sha256:" + hashlib.sha256(buffer).hexdigest(), len(events))


def _restore(rows):
    memo = {}
    result = []
    for row in rows:
        key = id(row)
        event = memo.get(key)
        if event is None:
            event = MarketEvent(*row)
            memo[key] = event
        result.append(event)
    return tuple(result)


class _PackedEvents:
    def __init__(self, events):
        self.events = events

    def __reduce__(self):
        rows, memo = [], {}
        scalar = (str, int, float, bool, type(None))
        for event in self.events:
            if (type(event) is not MarketEvent or type(event.sequence) is not int
                    or type(event.event_time_ms) is not int or type(event.role) is not str
                    or type(event.payload) is not dict
                    or any(type(key) is not str or type(value) not in scalar for key, value in event.payload.items())):
                return _unchanged, (self.events,)
            key = id(event)
            row = memo.get(key)
            if row is None:
                row = (event.sequence, event.event_time_ms, event.role, event.payload)
                memo[key] = row
            rows.append(row)
        return _restore, (tuple(rows),)


def pack_events(events):
    if (getenv("BACKTEST_COMPACT_SPAWN_ENABLED", "1").strip() != "1"
            or type(events) is not tuple
            or MarketEvent.__slots__ != ("sequence", "event_time_ms", "role", "payload")
            or getattr(getattr(MarketEvent.__init__, "__code__", None), "co_filename", None) != "<string>"
            or getattr(MarketEvent, "__post_init__", None) is not None):
        return events
    if getenv("BACKTEST_COLUMNAR_SPAWN_ENABLED", "1").strip() != "1":
        return _PackedEvents(events)
    return _ColumnarEvents(events)
