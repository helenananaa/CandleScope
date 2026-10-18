"""Versioned, forward-only callbacks with host-owned account feedback.

Only the historical horizon count is known in advance. Future prices and account
frames never enter the process. Batch and fill-pass scripts retain the explicit
prefix evaluator until they support this contract.
"""
from copy import deepcopy
import math

from pyne_runtime.barstate import PyneIncrementalBarState
from pyne_runtime.data import PyneData
from pyne_runtime.external import ACCOUNT_FIELDS, _IntentStrategy
from pyne_runtime.incremental import PyneIncrementalSession, is_incremental_pyne_script
from pyne_runtime.incremental._bar_admission import admit_bar
from pyne_runtime.security import enforce_input_limits

from .event_requests import FrozenProvider, closed_boundary, market_bars

CONTRACT = "pyne.host-fixed-history/1"
PREFIX = "historical-prefix/1"


class AppendProvider(FrozenProvider):
    def get_finalized_through(self, symbol, timeframe):
        rows = self._rows(symbol, timeframe)
        return rows[-1]["time"] if rows else None

    def append(self, streams, boundary):
        seen = set()
        for stream in streams:
            key = (stream["symbol"], stream["timeframe"])
            if key in seen or key not in self.contexts:
                raise ValueError("EXTERNAL_DELTA_INVALID: requested context changed")
            seen.add(key)
            previous = self.contexts[key]
            if stream["offset"] != len(previous):
                raise ValueError("EXTERNAL_DELTA_INVALID: context cursor changed")
            rows = stream["bars"]
            if rows:
                PyneData.from_ohlcv(rows)
                if (previous and rows[0]["time"] <= previous[-1]["time"]) or any(
                        closed_boundary(row, key[1]) > boundary for row in rows):
                    raise ValueError("EXTERNAL_DELTA_INVALID: noncausal requested bars")
                previous.extend(deepcopy(rows))
        self.events.clear()


class Session:
    def __init__(self, request, settings_for):
        self.horizon = request["evaluation"]["horizon"]
        if type(self.horizon) is not int or self.horizon < 1:
            raise ValueError("EXTERNAL_DELTA_INVALID: invalid horizon")
        self.cursor = 0
        self.frames = []
        self.context = deepcopy(request["context"])
        contexts = [{**item, "bars": []} for item in request.get("contexts", [])]
        keys = [(item["symbol"], item["timeframe"]) for item in contexts]
        primary = (self.context["symbol"], self.context["timeframe"])
        if len(set(keys)) != len(keys) or primary in keys:
            raise ValueError("EXTERNAL_DELTA_INVALID: duplicate primary/request context")
        self.provider = AppendProvider(contexts, {**request, "bars": []})
        frames = self.frames

        class EngineSession(PyneIncrementalSession):
            observer = None

            def _call_optional(self, func, ctx):
                if self.observer is None:
                    self.observer = _IntentStrategy(frames, ctx=ctx)
                    ctx.strategy = self.observer
                return super()._call_optional(func, ctx)

        self.engine = EngineSession(script=request["source"], params=request.get("parameters") or {},
                                    settings=settings_for(request, self.provider))
        enforce_input_limits(self.horizon, self.engine.policy)

    def advance(self, request):
        if (request["evaluation"] != {"contract": CONTRACT, "horizon": self.horizon, "cursor": self.cursor}
                or self.cursor >= self.horizon or len(request["bars"]) != 1 or len(request["accounts"]) != 1):
            raise ValueError("EXTERNAL_DELTA_INVALID: historical cursor changed")
        if self.cursor and set(request) != {"protocol", "identity", "evaluation", "bars", "accounts", "contexts"}:
            raise ValueError("EXTERNAL_DELTA_INVALID: frozen run configuration changed")
        row, frame = request["bars"][0], request["accounts"][0]
        if set(frame) != {"time", *ACCOUNT_FIELDS} or frame["time"] != row["time"]:
            raise ValueError("EXTERNAL_DELTA_INVALID: invalid account frame")
        for name in ACCOUNT_FIELDS:
            value = frame[name]
            if value is None and name == "position_avg_price" and frame["position_size"] == 0:
                continue
            if type(value) not in {int, float} or not math.isfinite(value):
                raise ValueError("EXTERNAL_DELTA_INVALID: nonfinite account feedback")
        bar = admit_bar(market_bars([row], self.context["timeframe"])[0])
        self.engine._validate_event_time(bar, preview=False)
        streams = request.get("contexts", [])
        if not self.cursor:
            streams = [{**item, "offset": 0} for item in streams]
        self.provider.append([*streams, {**self.context, "offset": self.cursor, "bars": [row]}],
                             closed_boundary(row, self.context["timeframe"]))
        self.frames.append(deepcopy(frame))
        if not self.cursor:
            self.engine.seed([])
        final = self.cursor == self.horizon - 1
        self.engine._run_bar(self.engine._ctx, bar, preview=False, bar_index=self.cursor,
                            last_bar_index=self.horizon - 1,
                            barstate=PyneIncrementalBarState(isfirst=self.cursor == 0, islast=final,
                                ishistory=True, isrealtime=False, isnew=True, isconfirmed=True,
                                islastconfirmedhistory=final))
        self.engine._ensure_healthy()
        observer = self.engine.observer
        if observer is None or not observer.declared:
            raise ValueError("PYNE_EXTERNAL_UNSUPPORTED: strategy declaration is required")
        intents = observer.intents
        if len(intents) > 64 or any(item["bar_index"] != self.cursor for item in intents):
            raise ValueError("EXTERNAL_DELTA_INVALID: at most 64 current-bar intents")
        observer.intents = []
        self.engine.last_closed_time = bar.time
        self.engine._closed_count = self.cursor + 1
        self.engine._commit_retention(bar.time)
        self.engine._portable_complete = False
        self.cursor += 1
        output, graphics = {}, []
        if final:
            result = self.engine.snapshot_result()
            if not result.ok or result.output.get("strategy"):
                raise ValueError("PYNE_EXTERNAL_UNSUPPORTED: invalid external result")
            output, graphics = result.output, result.lines
        return {"contract": "external-broker/1", "evaluation_contract": CONTRACT,
                "pyramiding": observer.pyramiding, "intents": intents, "graphics": graphics,
                "raw_output": output, "execution_mode": "CANDLESCOPE", "account_authority": "candlescope"}


class Evaluator:
    def __init__(self, execute, settings_for):
        self.execute, self.settings_for = execute, settings_for
        self.session = None
        self.started = False

    def __call__(self, request):
        if not self.started:
            self.started = True
            if (request.get("evaluation", {}).get("contract") == CONTRACT
                    and request.get("execution_passes") is None
                    and is_incremental_pyne_script(request["source"])):
                self.session = Session(request, self.settings_for)
        if self.session is not None:
            return self.session.advance(request)
        return {**self.execute(request), "evaluation_contract": PREFIX}
