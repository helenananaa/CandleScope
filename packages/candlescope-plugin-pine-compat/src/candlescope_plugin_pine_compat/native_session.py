"""Fixed-horizon Pine state with frozen request and magnifier data."""
from candlescope_plugin_sdk.native_strategy import serve_session
from .native_strategy import describe, prepare, pack
from .strategy_time import engine_bars, engine_magnifier


class Session:
    def __init__(self, request):
        self.request = request
        program, overrides, self.requirements, self.uses_magnifier = prepare(request)
        self.engine = program.historical_session(engine_bars(request["bars"]), input_overrides=overrides or None,
            chart_symbol=request["context"]["symbol"], chart_timeframe=request["context"]["timeframe"],
            request_bars={f"{item['symbol']}:{item['timeframe']}": engine_bars(item["bars"]) for item in request.get("contexts", [])} or None,
            magnifier_bars=engine_magnifier(request.get("magnifier")))
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
        return pack(self.request, output, self.requirements, self.uses_magnifier)


def factory(request):
    return Session(request)


if __name__ == "__main__":
    raise SystemExit(serve_session(describe, factory))
