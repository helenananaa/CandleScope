"""Host-owned cursors over frozen requested streams; no core or IPC dependency."""
from bisect import bisect_right
from copy import deepcopy
import hashlib
import json

CONTRACT = "candlescope.pine-request-updates/1"
WINDOW_CONTRACT = "candlescope.pine-request-window-plan/1"


def window_history(contexts):
    return [dict(symbol=item["symbol"],timeframe=item["timeframe"],times_ms=[bar["time"]*1000 for bar in item["bars"]])
            for item in contexts]


def from_wire(wire):
    if wire.get("request_update_contract") is None:
        return None
    if (wire["request_update_contract"] != CONTRACT
            or wire.get("identity", {}).get("request_update_contract") != CONTRACT):
        raise ValueError("PINE_REQUEST_UPDATE_INVALID: requested update contract differs")
    from app.data_engine.interval_policy import parse_interval_spec
    contexts, intervals = wire.get("contexts", []), wire.get("context_intervals", [])
    if not contexts or len(contexts) != len(intervals):
        raise ValueError("PINE_REQUEST_UPDATE_INVALID: requested intervals are missing")
    streams = []
    for context, interval in zip(contexts, intervals, strict=True):
        spec = parse_interval_spec(interval)
        streams.append({**context, "closes": [spec.next_ms(row["time"] * 1000) - 1 for row in context["bars"]]})
    return RequestedObservationFeed(streams)


def pass_observations(groups, *, scheduled):
    result = []
    for group in groups:
        for item in group:
            value = item["evaluation"] if scheduled else item
            result.append(dict(observed_at_ms=value["request_observed_at_ms"], updates=value["request_updates"]))
    return result


def validate_replay(feed, checkpoint, observations):
    if not isinstance(checkpoint, dict):
        raise ValueError("PINE_REQUEST_UPDATE_INVALID: requested cursor checkpoint is missing")
    feed.replay(observations)
    if feed.snapshot() != checkpoint:
        raise ValueError("PINE_REQUEST_UPDATE_INVALID: requested replay cursor differs")


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RequestedObservationFeed:
    def __init__(self, streams):
        self._streams = deepcopy(streams)
        keys = set()
        for stream in self._streams:
            key = stream["symbol"], stream["timeframe"]
            if key in keys or any(not isinstance(value, str) or not value or value != value.strip() for value in key):
                raise ValueError("PINE_REQUEST_UPDATE_INVALID: exact unique stream keys required")
            keys.add(key)
            bars, closes = stream["bars"], stream["closes"]
            from .pine_event_requests import CONTRACT as EVENT_CONTRACT, renko_descriptor
            event_rows = (stream.get("event_series_contract") == EVENT_CONTRACT
                          and renko_descriptor(stream["symbol"]) is not None)
            if stream.get("event_series_contract") is not None and not event_rows:
                raise ValueError("PINE_REQUEST_UPDATE_INVALID: unsupported event-series contract")
            if len(bars) != len(closes):
                raise ValueError("PINE_REQUEST_UPDATE_INVALID: one close timestamp per requested bar required")
            previous = previous_open = None
            for row, closed in zip(bars, closes, strict=True):
                if (type(row["time"]) is not int or type(closed) is not int
                        or closed < row["time"] * 1000
                        or previous_open is not None and (row["time"] < previous_open
                            or row["time"] == previous_open and not event_rows)
                        or previous is not None and (closed < previous
                            or closed == previous and not event_rows)
                        or previous_open is not None and event_rows
                            and ((row["time"] == previous_open) != (closed == previous))):
                    raise ValueError("PINE_REQUEST_UPDATE_INVALID: ordered complete requested bars required")
                previous, previous_open = closed, row["time"]
        self.source_hash = _hash(self._streams)
        self._cursors = [0] * len(self._streams)
        self.observed_at_ms = None

    def advance(self, observed_at_ms):
        if (type(observed_at_ms) is not int
                or self.observed_at_ms is not None and observed_at_ms < self.observed_at_ms):
            raise ValueError("PINE_REQUEST_UPDATE_INVALID: observation clock regressed or is not an integer")
        updates, cursors = [], []
        for stream, start in zip(self._streams, self._cursors, strict=True):
            stop = bisect_right(stream["closes"], observed_at_ms)
            updates.extend(dict(symbol=stream["symbol"], timeframe=stream["timeframe"], kind="confirmed",
                                bar=deepcopy(stream["bars"][index]), available_at_ms=stream["closes"][index])
                           for index in range(start, stop))
            cursors.append(stop)
        self._cursors, self.observed_at_ms = cursors, observed_at_ms
        return updates

    def snapshot(self):
        return dict(contract=CONTRACT, source_hash=self.source_hash,
                    cursors=list(self._cursors), observed_at_ms=self.observed_at_ms)

    def empty_contexts(self):
        return [dict(symbol=stream["symbol"], timeframe=stream["timeframe"], bars=[],
                     **({"metadata": deepcopy(stream["metadata"])} if stream.get("metadata") else {}))
                for stream in self._streams]

    def window_history(self):
        return window_history(self._streams)

    def replay(self, observations):
        before = self.snapshot()
        try:
            for item in observations:
                if not isinstance(item, dict) or set(item) != {"observed_at_ms", "updates"}:
                    raise ValueError("PINE_REQUEST_UPDATE_INVALID: malformed requested transcript")
                if self.advance(item["observed_at_ms"]) != item["updates"]:
                    raise ValueError("PINE_REQUEST_UPDATE_INVALID: requested transcript differs from frozen source")
        except Exception:
            self.restore(before)
            raise

    def restore(self, value):
        if (not isinstance(value, dict) or set(value) != {"contract", "source_hash", "cursors", "observed_at_ms"}
                or value["contract"] != CONTRACT or value["source_hash"] != self.source_hash):
            raise ValueError("PINE_REQUEST_UPDATE_INVALID: frozen requested source identity differs")
        observed, cursors = value["observed_at_ms"], value["cursors"]
        if ((observed is not None and type(observed) is not int) or not isinstance(cursors, list)
                or len(cursors) != len(self._streams) or any(type(cursor) is not int for cursor in cursors)):
            raise ValueError("PINE_REQUEST_UPDATE_INVALID: malformed observation checkpoint")
        expected = [0 if observed is None else bisect_right(stream["closes"], observed) for stream in self._streams]
        if cursors != expected:
            raise ValueError("PINE_REQUEST_UPDATE_INVALID: checkpoint cursor differs from its observation")
        self._cursors, self.observed_at_ms = list(cursors), observed
