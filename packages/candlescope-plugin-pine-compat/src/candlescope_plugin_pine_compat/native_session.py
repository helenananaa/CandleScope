"""Fixed-horizon Pine state with frozen request and magnifier data."""
from candlescope_plugin_sdk.native_strategy import serve_session
from .native_strategy import describe, prepare, pack
from .strategy_time import engine_bars, engine_magnifier
from .event_requests import run_with_event_requests
import pine_compat
from .host_inputs import native_inputs


class Session:
    def __init__(self, request):
        self.request = request
        program, overrides, self.requirements, self.uses_magnifier = prepare(request)
        bars = engine_bars(request["bars"])
        _libraries, options = native_inputs(request)
        supplied = options.pop("request_bars") or {}
        # Runtime ticker descriptors cannot be inferred from source text. Resolve
        # them against the immutable horizon once; the engine still reveals only
        # the event cohorts confirmed by each market bar as the session advances.
        if any(item.get("symbol", {}).get("kind") == "runtimeExpression"
               for item in self.requirements.get("requests", [])):
            run_with_event_requests(lambda request_bars: program.run(bars,
                input_overrides=overrides or None,
                chart_symbol=request["context"]["symbol"], chart_timeframe=request["context"]["timeframe"],
                request_bars=request_bars, magnifier_bars=engine_magnifier(request.get("magnifier")), **options),
                request, supplied, engine_bars, pine_compat)
        self.engine = program.historical_session(bars, input_overrides=overrides or None,
            chart_symbol=request["context"]["symbol"], chart_timeframe=request["context"]["timeframe"],
            request_bars=supplied or None,
            magnifier_bars=engine_magnifier(request.get("magnifier")), **options)
        self.saved = {0: self.engine.fork()}

    def advance(self, target):
        if target < self.engine.cursor:
            cursor = max(n for n in self.saved if n <= target)
            self.engine = self.saved[cursor].fork()
        output = self.engine.advance(target)
        # Bounded process-local snapshots. Durable host checkpoints rebuild if evicted.
        self.saved[target] = self.engine.fork()
        while len(self.saved) > 8:
            del self.saved[next(n for n in self.saved if n != 0)]
        return pack(self.request, output, self.requirements, self.uses_magnifier, cursor=target)


def factory(request):
    return Session(request)


if __name__ == "__main__":
    raise SystemExit(serve_session(describe, factory))
