"""Incremental Python strategies keep their real fixed-history context."""
from pyne_runtime.historical import HistoricalSession
from pyne_runtime.incremental import is_incremental_pyne_script
from candlescope_plugin_sdk.native_strategy import serve_session
from .native_strategy import describe, settings_for, pack


class Session:
    def __init__(self, request):
        self.request = request
        self.saved = {}
        self.engine = self.new_engine()

    def new_engine(self):
        return HistoricalSession(self.request["source"], self.request["bars"],
            params=self.request.get("parameters"), settings=settings_for(self.request))

    def advance(self, target):
        if target < self.engine.cursor:
            eligible = [n for n in self.saved if n <= target]
            if eligible:
                self.engine.restore(self.saved[max(eligible)])
            else:
                self.engine = self.new_engine()
        result = self.engine.advance(target)
        try:
            self.saved[target] = self.engine.snapshot()
        except (TypeError, ValueError):
            # Some script-owned objects cannot be snapshotted. Rebuild on backward seek.
            self.saved.clear()
        while len(self.saved) > 8:
            del self.saved[next(iter(self.saved))]
        # This transport continues an already completed, validated native strategy run.
        # Before its first order, Pyne may omit strategy output. Preserve that native report.
        return pack(result, self.engine.equity, True)


def factory(request):
    if not is_incremental_pyne_script(request["source"]):
        return None
    return Session(request)


if __name__ == "__main__":
    raise SystemExit(serve_session(describe, factory))
