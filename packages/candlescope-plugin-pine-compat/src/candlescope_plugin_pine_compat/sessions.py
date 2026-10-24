"""Bounded native sessions behind the existing full-snapshot transport.

The host supplies a subscription identity; HTTP computations remain independent.
Changed history is replayed, never mistaken for a realtime append.
"""

from collections import OrderedDict
from dataclasses import dataclass
from copy import deepcopy
from typing import Any

from . import session_requests


def requested_tail(options, forming_time):
    """Seed prior history, then feed observed confirmed intrabars in order.

    These rows have already been clipped by the host's observation boundary.
    Keeping them out of the static seed lets the core distinguish an observed
    intrabar from unobserved historical data in a forming chart period.
    """
    supplied = options.get("request_bars")
    if forming_time is None or not supplied:
        return options, []
    history, updates = {}, []
    for key, rows in supplied.items():
        if key.startswith("$"):
            history[key] = rows
            continue
        symbol, timeframe = key.rsplit(":", 1)
        history[key] = [row for row in rows if row["time"] < forming_time]
        updates.extend((symbol, timeframe, row) for row in rows if row["time"] >= forming_time)
    return {**options, "request_bars": history}, updates


@dataclass
class Session:
    identity: Any
    native: Any
    confirmed: list[dict]
    forming_time: int | None = None
    clocks: list[int] | None = None
    history_start: int = 0
    requested: dict | None = None
    observed_at: int | None = None


class PineSessions:
    def __init__(self, capacity: int = 8) -> None:
        self.capacity = capacity
        self.entries: OrderedDict[str, Session] = OrderedDict()

    def clear(self) -> None:
        self.entries.clear()

    def execute(self, engine, source, bars, options, *, session_id, forming, execution_times=None, calculation_bars_count=None, request_observation=None):
        native_options, request_updates = requested_tail(options, bars[-1]["time"] if forming else None)
        observed_at = session_requests.observation_clock(engine, request_observation)
        identity = session_requests.identity(source, options, native_options, observed_at)
        incoming = session_requests.requested_rows(options) if observed_at is not None else None
        if observed_at is not None and bars and observed_at < bars[-1]["time"]:
            raise ValueError("PINE_REQUEST_DATA_INVALID: chart begins after the requested observation")
        confirmed = bars[:-1] if forming else bars
        entry = self.entries.get(session_id) if session_id else None
        reset = (
            entry is None
            or entry.identity != identity
            or (observed_at is not None and not session_requests.immutable_prefix(entry.requested, incoming))
            or confirmed[:len(entry.confirmed)] != entry.confirmed
            or (entry.forming_time is not None and (
                len(bars) <= len(entry.confirmed)
                or bars[len(entry.confirmed)]["time"] != entry.forming_time
            ))
        )
        if not reset and observed_at is not None and observed_at < entry.observed_at:
            raise ValueError("PINE_REQUEST_DATA_INVALID: requested observation clock regressed")
        try:
            if reset:
                native = engine.create_realtime_session(source, **native_options)
                if observed_at is not None:
                    # Preflight the complete observed snapshot, including rows
                    # in the static seed, before any chart execution.
                    session_requests.FeedPlan(native, incoming, {}, observed_at)
                    if confirmed and session_requests.chart_cutoff(native, options, confirmed[-1]) > observed_at:
                        raise ValueError("PINE_REQUEST_DATA_INVALID: chart confirmation is ahead of the observation")
                native.seed(confirmed, **({"execution_times": execution_times[:len(confirmed)]}
                                         if execution_times is not None else {}))
                entry = Session(identity, native, deepcopy(confirmed),
                                history_start=max(0, len(confirmed) - calculation_bars_count) if calculation_bars_count else 0,
                                clocks=execution_times[:len(confirmed)] if execution_times is not None else None)
                if observed_at is not None:
                    native.apply_request_feed_updates([{"symbol": symbol, "timeframe": timeframe,
                        "bar": row, "kind": "confirmed"} for symbol, timeframe, row in request_updates])
                else:
                    for symbol, timeframe, row in request_updates:
                        native.apply_request_confirmed(symbol, timeframe, row)
            else:
                feed = (session_requests.FeedPlan(entry.native, incoming, entry.requested, observed_at)
                        if observed_at is not None else None)
                for index in range(len(entry.confirmed), len(confirmed)):
                    if feed is not None:
                        cutoff = session_requests.chart_cutoff(entry.native, options, confirmed[index])
                        if cutoff > observed_at:
                            raise ValueError("PINE_REQUEST_DATA_INVALID: chart confirmation is ahead of the observation")
                        feed.advance(entry.native, cutoff)
                    entry.native.update_confirmed(confirmed[index], **(
                        {"execution_time": execution_times[index]} if execution_times is not None else {}))
                    if entry.clocks is not None and execution_times is not None:
                        entry.clocks.append(execution_times[index])
                entry.confirmed = deepcopy(confirmed)
                entry.forming_time = None
                if feed is not None:
                    if forming:
                        feed.advance(entry.native, observed_at)
                    feed.complete()
            if forming:
                # A subscription may begin midway through an already open bar.
                entry.native.update_forming(bars[-1], opening_update=False if reset else None, **(
                    {"execution_time": execution_times[-1]} if execution_times is not None else {}))
                entry.forming_time = bars[-1]["time"]
            raw = entry.native.result()
            if observed_at is not None:
                entry.requested = deepcopy({key: list(rows) for key, rows in incoming.items()})
                entry.observed_at = observed_at
            if session_id:
                self.entries[session_id] = entry
                self.entries.move_to_end(session_id)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
            return raw, {"sessionReset": reset, "executionMode": "realtime-session",
                         "incremental": not reset, "formingBar": forming,
                         "sessionRetained": bool(session_id), **({"historyStartIndex": entry.history_start} if entry.history_start else {}),
                         **({"requestedObservationContract": session_requests.CONTRACT,
                             "requestedObservedAtMs": observed_at} if observed_at is not None else {}),
                         **({"executionTimesMs": entry.clocks + ([execution_times[-1]] if forming else [])}
                            if entry.clocks is not None and execution_times is not None else {})}
        except Exception:
            # A multi-bar update can fail after an earlier bar committed. Never
            # reuse that partially advanced session for the next request.
            self.entries.pop(session_id, None)
            raise
