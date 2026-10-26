"""Bounded native sessions behind the existing full-snapshot transport.

The host supplies a subscription identity; HTTP computations remain independent.
Changed history is replayed, never mistaken for a realtime append.
"""

from collections import OrderedDict
from dataclasses import dataclass
from copy import deepcopy
from typing import Any
import json
from .session_journal import SessionJournal
from .strategy_time import engine_bars
from .window_alignment import calculation_skip

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


class RecordedSession:
    """Record only mutating core calls, preserving their exact observation order."""
    MUTATIONS = {"seed", "update_confirmed", "update_forming", "apply_request_confirmed", "apply_request_feed_updates"}

    def __init__(self, native, operations):
        self.native, self.operations = native, operations

    def __getattr__(self, name):
        method = getattr(self.native, name)
        if name not in self.MUTATIONS:
            return method
        def invoke(*args, **kwargs):
            result = method(*args, **kwargs)
            self.operations.append([name, deepcopy(args), deepcopy(kwargs)])
            return result
        return invoke


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
    transcript: dict | None = None


class PineSessions:
    def __init__(self, capacity: int = 8, journal_path=None) -> None:
        self.capacity = capacity
        self.journal = SessionJournal(journal_path)
        self.entries: OrderedDict[str, Session] = OrderedDict()

    def clear(self) -> None:
        self.entries.clear()

    def commit(self, key):
        if key and key in self.entries:
            entry = self.entries[key]
            entry.transcript.update({name: deepcopy(getattr(entry, name)) for name in
                ("identity", "confirmed", "forming_time", "clocks", "history_start", "requested", "observed_at")})
            self.journal.write(key, entry.transcript)

    def release(self, key):
        self.entries.pop(key, None)
        self.journal.delete(key)

    def _restore(self, engine, transcript):
        if transcript.get("schema") != 1:
            raise ValueError("PINE_SESSION_JOURNAL_INVALID: unsupported observation journal")
        native = engine.create_realtime_session(transcript["source"], **transcript["options"])
        for name, args, kwargs in transcript["operations"]:
            if name not in RecordedSession.MUTATIONS:
                raise ValueError("PINE_SESSION_JOURNAL_INVALID: unknown operation")
            getattr(native, name)(*args, **kwargs)
        return Session(native=RecordedSession(native, transcript["operations"]), transcript=transcript,
            **{name: transcript[name] for name in ("identity", "confirmed", "forming_time", "clocks", "history_start", "requested", "observed_at")})

    def execute(self, engine, source, bars, options, *, session_id, forming, execution_times=None, calculation_bars_count=None, request_observation=None, epoch="0", providers=(), verify_history_clocks=False):
        native_options, request_updates = requested_tail(options, bars[-1]["time"] if forming else None)
        observed_at = session_requests.observation_clock(engine, request_observation)
        identity_options = options
        identity_native = native_options
        if providers and observed_at is None:
            def registry(value):
                return {**value, "request_bars": {key: rows if key.startswith("$") else [] for key, rows in value.get("request_bars", {}).items()}}
            identity_options, identity_native = registry(options), registry(native_options)
        identity = json.loads(json.dumps([session_requests.identity(source, identity_options, identity_native, observed_at), str(epoch)]))
        incoming = session_requests.requested_rows(options) if observed_at is not None else None
        if observed_at is not None and bars and observed_at < bars[-1]["time"]:
            raise ValueError("PINE_REQUEST_DATA_INVALID: chart begins after the requested observation")
        confirmed = bars[:-1] if forming else bars
        entry = self.entries.get(session_id) if session_id else None
        recovered = False
        if entry is None and session_id:
            transcript = self.journal.read(session_id)
            if transcript is not None:
                entry = self._restore(engine, transcript)
                recovered = True
        # A sliding UI window may omit an immutable retained prefix.
        offset = 0
        if entry is not None and confirmed and entry.confirmed:
            offset = next((i for i, row in enumerate(entry.confirmed) if row["time"] == confirmed[0]["time"]), -1)
        overlap = min(len(confirmed), len(entry.confirmed) - max(0, offset)) if entry else 0
        reset = (
            entry is None
            or entry.identity != identity
            or (execution_times is None) != (entry.clocks is None)
            or (verify_history_clocks and execution_times is not None and execution_times[:overlap] != entry.clocks[offset:offset+overlap])
            or (observed_at is not None and not session_requests.immutable_prefix(entry.requested, incoming))
            or offset < 0 or confirmed[:overlap] != entry.confirmed[offset:offset+overlap]
            or (entry.forming_time is not None and (
                not any(row["time"] == entry.forming_time for row in bars)
            ))
        )
        if not reset and observed_at is not None and observed_at < entry.observed_at:
            raise ValueError("PINE_REQUEST_DATA_INVALID: requested observation clock regressed")
        try:
            if reset:
                transcript = {"schema": 1, "source": source, "options": deepcopy(native_options), "operations": []}
                native = RecordedSession(engine.create_realtime_session(source, **native_options), transcript["operations"])
                if observed_at is not None:
                    # Preflight the complete observed snapshot, including rows
                    # in the static seed, before any chart execution.
                    session_requests.FeedPlan(native, incoming, {}, observed_at)
                    if confirmed and session_requests.chart_cutoff(native, options, confirmed[-1]) > observed_at:
                        raise ValueError("PINE_REQUEST_DATA_INVALID: chart confirmation is ahead of the observation")
                native.seed(confirmed, **({"execution_times": execution_times[:len(confirmed)]}
                                         if execution_times is not None else {}))
                entry = Session(identity, native, deepcopy(confirmed), transcript=transcript,
                                history_start=calculation_skip(engine, source, confirmed, native_options,
                                    execution_times[:len(confirmed)] if execution_times is not None else None, native.result(), calculation_bars_count),
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
                for index in range(overlap, len(confirmed)):
                    if feed is not None:
                        cutoff = session_requests.chart_cutoff(entry.native, options, confirmed[index])
                        if cutoff > observed_at:
                            raise ValueError("PINE_REQUEST_DATA_INVALID: chart confirmation is ahead of the observation")
                        feed.advance(entry.native, cutoff)
                    entry.native.update_confirmed(confirmed[index], **(
                        {"execution_time": execution_times[index]} if execution_times is not None else {}))
                    if entry.clocks is not None and execution_times is not None:
                        entry.clocks.append(execution_times[index])
                entry.confirmed = deepcopy(entry.confirmed[:offset] + confirmed)
                entry.forming_time = None
                if feed is not None:
                    if forming:
                        feed.advance(entry.native, observed_at)
                    feed.complete()
            if providers and observed_at is None:
                updates = []
                previous_providers = entry.transcript.setdefault("providers", {})
                for provider in providers:
                    key = f"{provider['symbol']}:{provider['timeframe']}"
                    previous = previous_providers.get(key, {"bars": options.get("request_bars", {}).get(key, []), "forming": False})
                    old = {bar["time"]: bar for bar in previous["bars"]}
                    old_forming = previous["bars"][-1]["time"] if previous["bars"] and previous["forming"] else None
                    for i, row in enumerate(engine_bars(provider["bars"])):
                        current_forming = bool(provider.get("forming")) and i == len(provider["bars"]) - 1
                        if row["time"] in old and row["time"] != old_forming:
                            if old[row["time"]] != row:
                                raise ValueError("PINE_REQUEST_HISTORY_CHANGED: requested confirmed history changed")
                            continue
                        if old.get(row["time"]) == row and row["time"] == old_forming and current_forming:
                            continue
                        updates.append({"symbol": provider["symbol"], "timeframe": provider["timeframe"], "kind": "forming" if current_forming else "confirmed", "bar": row})
                        old[row["time"]] = row
                    previous_providers[key] = {"bars": sorted(old.values(), key=lambda row: row["time"]), "forming": bool(provider.get("forming"))}
                if updates:
                    entry.native.apply_request_feed_updates(updates)
            observation = {"bar": bars[-1] if bars else None, "forming": forming,
                "providers": list(providers), "clock": execution_times[-1] if execution_times else None,
                "requested": request_observation}
            duplicate_recovery = recovered and not reset and entry.transcript.get("lastObservation") == observation
            if duplicate_recovery and forming:
                entry.forming_time = bars[-1]["time"]
            if forming and not duplicate_recovery:
                # A subscription may begin midway through an already open bar.
                entry.native.update_forming(bars[-1], opening_update=False if reset else None, **(
                    {"execution_time": execution_times[-1]} if execution_times is not None else {}))
                entry.forming_time = bars[-1]["time"]
            raw = entry.native.result()
            entry.transcript["lastObservation"] = deepcopy(observation)
            if len(entry.confirmed) > 100_000:
                raise ValueError("PINE_SESSION_HISTORY_LIMIT: explicitly restart the indicator")
            if observed_at is not None:
                entry.requested = deepcopy({key: list(rows) for key, rows in incoming.items()})
                entry.observed_at = observed_at
            if session_id:
                self.entries[session_id] = entry
                self.entries.move_to_end(session_id)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
            return raw, {"sessionReset": reset, "sessionRecovered": recovered and not reset,
                         "sessionResetReason": "inputs changed or no retained state" if reset else None, "executionMode": "realtime-session",
                         "incremental": not reset, "formingBar": forming,
                         "sessionRetained": bool(session_id),
                         "hostBars": entry.confirmed + ([bars[-1]] if forming else []),
                         **({"historyStartIndex": entry.history_start} if entry.history_start else {}),
                         **({"requestedObservationContract": session_requests.CONTRACT,
                             "requestedObservedAtMs": observed_at} if observed_at is not None else {}),
                         **({"executionTimesMs": entry.clocks + ([execution_times[-1]] if forming else [])}
                            if entry.clocks is not None and execution_times is not None else {})}
        except Exception:
            # A multi-bar update can fail after an earlier bar committed. Never
            # reuse that partially advanced session for the next request.
            self.release(session_id)
            raise
