"""Compact transport of owned, flat MarketEvent snapshots to a spawn worker.

No global pickle reducer is installed. Unsupported objects retain their original
pickle behavior; the worker always receives the original tuple/MarketEvent API.
"""
from app.core.config import getenv
from app.market_dataset.snapshot import MarketEvent


def _unchanged(events):
    return events


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
    return _PackedEvents(events)
