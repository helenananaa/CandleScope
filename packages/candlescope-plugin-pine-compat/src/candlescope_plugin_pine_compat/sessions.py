"""Native realtime state with deterministic reconstruction after LRU/restart."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from .session_journal import SessionJournal
from .strategy_time import engine_bars
from .window_alignment import calculation_skip


@dataclass
class Session:
    identity: dict
    native: object
    confirmed: list
    transcript: dict
    forming_time: int | None = None


def _invoke(native, operation):
    method, value, options = operation
    return getattr(native, method)(value, **options)


class PineSessions:
    def __init__(self, capacity=8, journal_path=None):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.journal = SessionJournal(journal_path)

    def clear(self):
        self.entries.clear()

    def commit(self, key):
        if key and key in self.entries:
            self.journal.write(key, self.entries[key].transcript)

    def release(self, key):
        self.entries.pop(key, None)
        self.journal.delete(key)

    def _restore(self, engine, transcript):
        native = engine.create_realtime_session(transcript["source"], **transcript["options"])
        for operation in transcript["operations"]:
            _invoke(native, operation)
        return Session(transcript["identity"], native, transcript["confirmed"], transcript,
                       transcript.get("forming_time"))

    def execute(self, engine, source, bars, options, *, session_id, forming, execution_times=None, providers=(), epoch="0", calculation_bars_count=None):
        import json
        options = json.loads(json.dumps(options))
        identity_options = deepcopy(options)
        if "request_bars" in identity_options:
            identity_options["request_bars"] = {key: value if key.startswith("$") else True
                for key, value in identity_options["request_bars"].items()}
        identity = {"source": source, "options": identity_options, "epoch": str(epoch), "clocked": execution_times is not None}
        confirmed = bars[:-1] if forming else bars
        entry = self.entries.get(session_id) if session_id else None
        recovered = False
        if entry is None and session_id:
            transcript = self.journal.read(session_id)
            if transcript:
                entry = self._restore(engine, transcript)
                recovered = True
        reason = "initial"
        start = 0
        if entry is not None:
            reason = "inputsChanged" if entry.identity != identity else "historyChanged"
            if confirmed and entry.confirmed:
                start = next((i for i, row in enumerate(entry.confirmed) if row["time"] == confirmed[0]["time"]), -1)
            overlap = min(len(confirmed), len(entry.confirmed) - max(0, start))
            matches = start >= 0 and confirmed[:overlap] == entry.confirmed[start:start + overlap]
            if matches and execution_times is not None:
                matches = execution_times[:overlap] == entry.transcript.get("confirmed_clocks", [])[start:start + overlap]
            if (entry.identity == identity and matches and
                (entry.forming_time is None or any(row["time"] == entry.forming_time for row in bars))):
                reason = ""
        reset = entry is None or bool(reason)
        try:
            if reset:
                native = engine.create_realtime_session(source, **options)
                clock = {"execution_times": execution_times[:len(confirmed)]} if execution_times is not None else {}
                operation = ["seed", confirmed, clock]
                _invoke(native, operation)
                skip = calculation_skip(engine, source, confirmed, options,
                    execution_times[:len(confirmed)] if execution_times is not None else None,
                    native.result(), calculation_bars_count)
                transcript = {"source": source, "options": options, "identity": identity,
                              "operations": [operation], "confirmed": list(confirmed),
                              "confirmed_clocks": execution_times[:len(confirmed)] if execution_times is not None else None,
                              "calculation_skip": skip,
                              "providers": {key: {"bars": value, "forming": False}
                                  for key, value in options.get("request_bars", {}).items() if not key.startswith("$")}}
                entry = Session(identity, native, list(confirmed), transcript)
            else:
                entry.transcript = deepcopy(entry.transcript)
            updates = []
            for provider in providers:
                key = f"{provider['symbol']}:{provider['timeframe']}"
                previous = entry.transcript.setdefault("providers", {}).get(key, {"bars": [], "forming": False})
                old = {bar["time"]: bar for bar in previous["bars"]}
                old_forming = previous["bars"][-1]["time"] if previous["bars"] and previous["forming"] else None
                rows = engine_bars(provider["bars"])
                for i, row in enumerate(rows):
                    current_forming = bool(provider.get("forming")) and i == len(rows) - 1
                    if row["time"] in old and row["time"] != old_forming:
                        if old[row["time"]] != row:
                            raise ValueError("PINE_REQUEST_HISTORY_CHANGED: requested history was corrected; restart the indicator explicitly")
                        continue
                    if old.get(row["time"]) == row and row["time"] == old_forming and current_forming:
                        continue
                    updates.append({"symbol": provider["symbol"], "timeframe": provider["timeframe"],
                                    "kind": "forming" if current_forming else "confirmed", "bar": row})
                    old[row["time"]] = row
                entry.transcript["providers"][key] = {"bars": sorted(old.values(), key=lambda bar: bar["time"]), "forming": bool(provider.get("forming"))}
            if updates:
                operation = ["apply_request_feed_updates", updates, {}]
                _invoke(entry.native, operation)
                entry.transcript["operations"].append(operation)
            if not reset:
                for index, bar in enumerate(confirmed):
                    if entry.confirmed and bar["time"] <= entry.confirmed[-1]["time"]:
                        continue
                    kwargs = {"execution_time": execution_times[index]} if execution_times is not None else {}
                    operation = ["update_confirmed", bar, kwargs]
                    _invoke(entry.native, operation)
                    entry.transcript["operations"].append(operation)
                    entry.confirmed.append(bar)
                    if execution_times is not None:
                        entry.transcript["confirmed_clocks"].append(execution_times[index])
                entry.forming_time = None
            if len(entry.confirmed) > 100_000:
                raise ValueError("PINE_SESSION_HISTORY_LIMIT: retained input exceeds 100000 bars; restart the indicator explicitly")
            previous_observation = entry.transcript.get("lastObservation")
            observation = {"bar": bars[-1] if bars else None, "forming": forming,
                           "providers": list(providers), "clock": execution_times[-1] if execution_times else None}
            duplicate_recovery = recovered and not reset and previous_observation == observation
            if duplicate_recovery and forming:
                entry.forming_time = bars[-1]["time"]
            if forming and not duplicate_recovery:
                kwargs = {"opening_update": False if reset else None}
                if execution_times is not None:
                    kwargs["execution_time"] = execution_times[-1]
                operation = ["update_forming", bars[-1], kwargs]
                _invoke(entry.native, operation)
                entry.transcript["operations"].append(operation)
                entry.forming_time = bars[-1]["time"]
            raw = entry.native.result()
            entry.transcript.update(confirmed=entry.confirmed, forming_time=entry.forming_time, lastObservation=observation)
            if session_id:
                self.entries[session_id] = entry
                self.entries.move_to_end(session_id)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
            return raw, {"sessionReset": reset, "sessionResetReason": reason if reset else None,
                         "sessionRecovered": recovered and not reset,
                         "executionMode": "realtime-session", "incremental": not reset,
                         "formingBar": forming, "sessionRetained": bool(session_id),
                         "calculationSkip": entry.transcript.get("calculation_skip", 0),
                         "hostBars": entry.confirmed + ([bars[-1]] if forming else []),
                         "hostTimes": [row["time"] // 1000 for row in entry.confirmed] + ([bars[-1]["time"] // 1000] if forming else [])}
        except Exception:
            self.entries.pop(session_id, None)
            raise
