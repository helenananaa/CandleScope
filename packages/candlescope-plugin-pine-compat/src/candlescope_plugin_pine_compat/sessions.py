"""Bounded native sessions behind the existing full-snapshot transport.

The host supplies a subscription identity; HTTP computations remain independent.
Changed history is replayed, never mistaken for a realtime append.
"""

from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any
import hashlib
import json
from .session_journal import SessionJournal, encode
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


def digest(value):
    return hashlib.sha256(encode(value, sort_keys=True).encode()).hexdigest()


def has_time(rows, time):
    index = bisect_left(rows, time, key=lambda row: row["time"])
    return index < len(rows) and rows[index]["time"] == time


class RecordedSession:
    """Record only mutating core calls, preserving their exact observation order."""
    MUTATIONS = {"seed_state", "apply_confirmed", "apply_forming", "apply_request_confirmed", "apply_request_feed_updates"}
    # Schema 1 journals recorded the calls that also built a discarded result.
    LEGACY = {"seed": "seed_state", "update_confirmed": "apply_confirmed", "update_forming": "apply_forming"}

    def __init__(self, native, operations):
        self.native, self.operations = native, operations

    def __getattr__(self, name):
        method = getattr(self.native, name)
        if name not in self.MUTATIONS or self.operations is None:
            return method
        def invoke(*args, **kwargs):
            result = method(*args, **kwargs)
            # Arguments belong to the current request and are encoded when it commits.
            self.operations.append([name, args, kwargs])
            return result
        return invoke


@dataclass
class Session:
    identity: Any
    native: Any
    confirmed: list[dict] = field(default_factory=list)
    forming_time: int | None = None
    clocks: list[int] | None = None
    history_start: int = 0
    requested: dict | None = None
    observed_at: int | None = None
    providers: dict = field(default_factory=dict)
    # Append-only indexes over ``confirmed``: engine time -> position, host seconds.
    positions: dict = field(default_factory=dict)
    times: list[int] = field(default_factory=list)
    header: dict | None = None
    pending: list | None = None
    seq: int = 0
    observation: Any = None
    last_observation: str | None = None

    def confirm(self, rows, clocks=None):
        for row in rows:
            self.positions[row["time"]] = len(self.confirmed)
            self.times.append(row["time"] // 1000)
            self.confirmed.append(dict(row))
        if self.clocks is not None and clocks is not None:
            self.clocks.extend(clocks)

    def extend_requested(self, incoming):
        """Append newly observed requested rows and return exactly those rows."""
        fresh = self.requested is None
        if fresh:
            self.requested = {key: [] for key in incoming}
        appended = {key: list(rows[len(self.requested[key]):]) for key, rows in incoming.items()
                    if fresh or len(rows) > len(self.requested[key])}
        for key, rows in appended.items():
            self.requested[key].extend(dict(row) for row in rows)
        return appended


class PineSessions:
    def __init__(self, capacity: int = 8, journal_path=None) -> None:
        self.capacity = capacity
        self.journal = SessionJournal(journal_path)
        self.entries: OrderedDict[str, Session] = OrderedDict()

    def clear(self) -> None:
        self.entries.clear()

    def commit(self, key):
        entry = self.entries.get(key) if key else None
        if entry is None or entry.pending is None:
            return
        try:
            observation = digest(entry.observation)
            state = encode({"formingTime": entry.forming_time, "observedAt": entry.observed_at, "observation": observation})
            header = None if entry.header is None else encode({"schema": 2, **entry.header})
            self.journal.append(key, header, state, [encode(op) for op in entry.pending], entry.seq)
        except Exception:
            # The journal still holds the previous commit; never continue past it.
            self.entries.pop(key, None)
            raise
        entry.seq += len(entry.pending)
        entry.pending.clear()
        entry.header, entry.last_observation = None, observation

    def release(self, key):
        self.entries.pop(key, None)
        if key:
            self.journal.delete(key)

    def _restore(self, engine, record):
        if record.get("schema") == 1:
            # The whole transcript stays pending until its first commit migrates it.
            header = {"source": record["source"], "options": record["options"], "identity": record["identity"],
                      "historyStart": record["history_start"], "clocked": record["clocks"] is not None}
            state = {"formingTime": record["forming_time"], "observedAt": record["observed_at"],
                     "observation": digest(record["lastObservation"]) if "lastObservation" in record else None}
            operations = [[RecordedSession.LEGACY.get(name, name), args, kwargs] for name, args, kwargs in record["operations"]]
            if record.get("requested") is not None:
                operations.append(["$requested", [record["requested"]], {}])
            if record.get("providers"):
                operations.append(["$providers", [{key: {"seed": value["bars"], "bars": [], "forming": value["forming"]}
                                                   for key, value in record["providers"].items()}], {}])
            pending, seq = operations, 0
        elif record.get("schema") == 2:
            header, state, operations = record["header"], record["state"], record["operations"]
            pending, seq = [], len(operations)
        else:
            raise ValueError("PINE_SESSION_JOURNAL_INVALID: unsupported observation journal")
        native = engine.create_realtime_session(header["source"], **header["options"])
        entry = Session(header["identity"], RecordedSession(native, pending), clocks=[] if header["clocked"] else None,
                        history_start=header["historyStart"], forming_time=state["formingTime"],
                        observed_at=state["observedAt"], header=header if seq == 0 else None,
                        pending=pending, seq=seq, last_observation=state["observation"])
        providers = {}
        for name, args, kwargs in operations:
            if name == "$requested":
                entry.requested = {} if entry.requested is None else entry.requested
                for key, rows in args[0].items():
                    entry.requested.setdefault(key, []).extend(rows)
            elif name == "$providers":
                for key, change in args[0].items():
                    rows = {row["time"]: row for row in change["seed"]} if "seed" in change else providers[key][0]
                    rows.update((row["time"], row) for row in change["bars"])
                    providers[key] = rows, change["forming"]
            elif name in RecordedSession.MUTATIONS:
                getattr(native, name)(*args, **kwargs)
                if name == "seed_state":
                    entry.confirm(args[0], kwargs.get("execution_times"))
                elif name == "apply_confirmed":
                    entry.confirm(args[:1], [kwargs["execution_time"]] if "execution_time" in kwargs else None)
            else:
                raise ValueError("PINE_SESSION_JOURNAL_INVALID: unknown operation")
        entry.providers = {key: {"bars": sorted(rows.values(), key=lambda row: row["time"]), "forming": forming}
                           for key, (rows, forming) in providers.items()}
        return entry

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
            record = self.journal.read(session_id)
            if record is not None:
                entry = self._restore(engine, record)
                recovered = True
        # A sliding UI window may omit an immutable retained prefix. The host
        # forwards no correction marker: a corrected bar is only a changed row,
        # so every retained row the window repeats is compared.
        offset = 0
        if entry is not None and confirmed and entry.confirmed:
            offset = entry.positions.get(confirmed[0]["time"], -1)
        retained = len(entry.confirmed) - max(0, offset) if entry else 0
        overlap = min(len(confirmed), retained)
        reset = (
            entry is None
            or entry.identity != identity
            or (execution_times is None) != (entry.clocks is None)
            or (verify_history_clocks and execution_times is not None and execution_times[:overlap] != entry.clocks[offset:offset+overlap])
            or (observed_at is not None and not session_requests.immutable_prefix(entry.requested, incoming))
            # A shortened tail is replayed, never truncated beneath the native session.
            or offset < 0 or overlap < retained or confirmed[:overlap] != entry.confirmed[offset:]
            or (entry.forming_time is not None and not has_time(bars, entry.forming_time))
        )
        if not reset and observed_at is not None and observed_at < entry.observed_at:
            raise ValueError("PINE_REQUEST_DATA_INVALID: requested observation clock regressed")
        try:
            if reset:
                pending = [] if session_id else None
                native = RecordedSession(engine.create_realtime_session(source, **native_options), pending)
                if observed_at is not None:
                    # Preflight the complete observed snapshot, including rows
                    # in the static seed, before any chart execution.
                    session_requests.FeedPlan(native, incoming, {}, observed_at)
                    if confirmed and session_requests.chart_cutoff(native, options, confirmed[-1]) > observed_at:
                        raise ValueError("PINE_REQUEST_DATA_INVALID: chart confirmation is ahead of the observation")
                clocks = execution_times[:len(confirmed)] if execution_times is not None else None
                native.seed_state(confirmed, **({"execution_times": clocks} if clocks is not None else {}))
                entry = Session(identity, native, clocks=None if clocks is None else [], pending=pending,
                                history_start=calculation_skip(engine, source, confirmed, native_options, clocks,
                                    native.result() if calculation_bars_count and confirmed else None, calculation_bars_count))
                entry.confirm(confirmed, clocks)
                entry.header = {"source": source, "options": native_options, "identity": identity,
                                "historyStart": entry.history_start, "clocked": clocks is not None}
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
                    entry.native.apply_confirmed(confirmed[index], **(
                        {"execution_time": execution_times[index]} if execution_times is not None else {}))
                entry.confirm(confirmed[overlap:], execution_times[overlap:len(confirmed)] if execution_times is not None else None)
                entry.forming_time = None
                if feed is not None:
                    if forming:
                        feed.advance(entry.native, observed_at)
                    feed.complete()
            if providers and observed_at is None:
                known = {key: value["forming"] for key, value in entry.providers.items()}
                updates, changes = [], {}
                for provider in providers:
                    key = f"{provider['symbol']}:{provider['timeframe']}"
                    previous = entry.providers.get(key, {"bars": options.get("request_bars", {}).get(key, []), "forming": False})
                    change = changes.setdefault(key, {"bars": []} if key in known else {"seed": previous["bars"], "bars": []})
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
                        change["bars"].append(row)
                    entry.providers[key] = {"bars": sorted(old.values(), key=lambda row: row["time"]), "forming": bool(provider.get("forming"))}
                    change["forming"] = entry.providers[key]["forming"]
                if updates:
                    entry.native.apply_request_feed_updates(updates)
                changes = {key: change for key, change in changes.items()
                           if "seed" in change or change["bars"] or change["forming"] != known[key]}
                if changes and entry.pending is not None:
                    entry.pending.append(["$providers", [changes], {}])
            observation = {"bar": bars[-1] if bars else None, "forming": forming,
                "providers": list(providers), "clock": execution_times[-1] if execution_times else None,
                "requested": request_observation}
            duplicate_recovery = recovered and not reset and entry.last_observation == digest(observation)
            if duplicate_recovery and forming:
                entry.forming_time = bars[-1]["time"]
            if forming and not duplicate_recovery:
                # A subscription may begin midway through an already open bar.
                entry.native.apply_forming(bars[-1], opening_update=False if reset else None, **(
                    {"execution_time": execution_times[-1]} if execution_times is not None else {}))
                entry.forming_time = bars[-1]["time"]
            raw = entry.native.result()
            entry.observation = observation
            if len(entry.confirmed) > 100_000:
                raise ValueError("PINE_SESSION_HISTORY_LIMIT: explicitly restart the indicator")
            if observed_at is not None:
                appended = entry.extend_requested(incoming)
                if entry.pending is not None and (reset or appended):
                    entry.pending.append(["$requested", [appended], {}])
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
                         # Rows and host seconds the native session retains before a slid window.
                         **({"hostPrefix": (entry.confirmed[:offset], entry.times[:offset])} if offset > 0 and not reset else {}),
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
