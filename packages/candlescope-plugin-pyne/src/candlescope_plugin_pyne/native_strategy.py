"""Full native Pyne reports; no signal extraction or host rematching.

Pyne 0.4.1 has public equity accessors but no batch report equity array. The
version-pinned observer below reads those accessors without modifying source,
orders or execution order. Keep this seam covered by native parity tests.
"""
from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
import pyne_runtime as pn
from pyne_runtime.runtime import PyneRuntime
from pyne_runtime.incremental import PyneIncrementalSession, is_incremental_pyne_script
from candlescope_plugin_sdk.native_strategy import identity, serve
from .host_policy import host_settings
from .event_requests import FrozenProvider, market_bars


def describe():
    result = identity("candlescope-plugin-pyne", "pyne-runtime", adapter="pyne-native/1")
    if result["engine"]["version"] != "0.4.1":
        raise ValueError("NATIVE_VERSION_UNSUPPORTED: Pyne observer requires 0.4.1")
    result["historical_session"] = "fixed-history/1"
    return result


class ObservedBatch(PyneRuntime):
    strategy_observer = None

    def _build_namespace(self, services):
        namespace = super()._build_namespace(services)
        self.strategy_observer = namespace["strategy"]
        return namespace


class ObservedSession(PyneIncrementalSession):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.native_equity = []
        self.strategy_declared = False

    @contextmanager
    def observe_configuration(self, ctx):
        # In 0.4.1 configure() does not mark an otherwise empty strategy as
        # touched. Observe the actual successful call, not source text or an
        # invented order; restore the method before any engine snapshot.
        original = ctx.strategy.configure
        had_override = "configure" in vars(ctx.strategy)

        def configure(**settings):
            result = original(**settings)
            self.strategy_declared = True
            return result

        ctx.strategy.configure = configure
        try:
            yield
        finally:
            if had_override:
                ctx.strategy.configure = original
            else:
                del ctx.strategy.configure

    def _call_optional(self, func, ctx):
        with self.observe_configuration(ctx):
            return super()._call_optional(func, ctx)

    def _run_bar(self, ctx, bar, **kwargs):
        with self.observe_configuration(ctx):
            super()._run_bar(ctx, bar, **kwargs)
        if not kwargs["preview"]:
            self.native_equity.append({"time": bar.time, "value": ctx.strategy.equity})


def settings_for(request):
    if request.get("libraries"):
        raise ValueError("NATIVE_INPUT_UNSUPPORTED: Pyne does not accept Pine library sources")
    settings = replace(host_settings(security_mode="safe"), timeout_seconds=None,
                       data_provider=FrozenProvider(request.get("contexts", []), request))
    # Symbol/timeframe are provided explicitly, never inferred from engine defaults.
    from pyne_runtime.metadata import SymbolInfo, TimeframeInfo
    settings = replace(settings, syminfo=SymbolInfo.from_value(request["context"]["symbol"]),
                       timeframe=TimeframeInfo.from_value(request["context"]["timeframe"]))
    return settings


def execute(request):
    settings = settings_for(request)
    source = request["source"]
    bars = market_bars(request["bars"], request["context"]["timeframe"])
    if is_incremental_pyne_script(source):
        session = ObservedSession(script=source, params=request.get("parameters") or {}, settings=settings)
        result = session.seed(bars)
        equity = session.native_equity
        declared = session.strategy_declared or bool((result.output.get("strategy") or {}).get("summary"))
    else:
        runtime = ObservedBatch(settings=settings)
        result = runtime.execute(source, bars, request.get("parameters") or {})
        equity = [] if not result.ok else [
            {"time": bar["time"], "value": float(value)}
            for bar, value in zip(bars, runtime.strategy_observer.equity.values, strict=True)]
        declared = result.meta.get("script_type") == "strategy"
    return pack(result, equity, declared)


def pack(result, equity, declared):
    if not result.ok:
        raise ValueError(f"{result.code}: {result.error}")
    output = result.output
    strategy = output.get("strategy") or {}
    if not isinstance(strategy, dict) or not declared:
        raise ValueError("NATIVE_STRATEGY_REQUIRED: use a strategy declaration")
    return {"execution_mode": "NATIVE", "account_authority": "pyne-runtime",
            "fill_model": "pyne-native-standard-ohlcv", "raw_output": output,
            "trades": strategy.get("closedtrades", []), "orders": strategy.get("orders", []),
            "equity": equity, "position": strategy.get("position"),
            "graphics": result.lines, "parameter_schema": result.param_schema,
            "diagnostics": [*result.meta.get("requestDiagnostics", []), *([] if strategy else [{
                "severity": "warning", "code": "PYNE_EMPTY_NATIVE_REPORT",
                "message": "Pyne 0.4.1 emitted no strategy report for this no-order run; equity is its unmodified native series."}])]}


if __name__ == "__main__":
    raise SystemExit(serve(describe, execute))
