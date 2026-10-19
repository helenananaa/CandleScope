"""Pine compilation and external decisions for the chart strategy workspace."""

import sys

import pine_compat
from candlescope_plugin_sdk.native_strategy import identity, serve, serve_evaluator

from .external_strategy import execute as evaluate
from .external_strategy import prepare
from .prefix_transport import CONTRACT as PREFIX_CONTRACT, PASSES_CONTRACT, CLOCKS_CONTRACT
from .libraries import library_sources
from .entry_risk import CONTRACT as RISK_CONTRACT, available as risk_available


def describe():
    return {
        **identity("candlescope-plugin-pine-compat", "pine-compat-runtime", adapter="pine-chart/4"),
        "external_orders": getattr(pine_compat, "EXTERNAL_ORDER_SCHEMA_VERSION", 1),
        **({"entry_risk_contract": RISK_CONTRACT} if risk_available() else {}),
        "fill_callbacks": "candlescope.pine-fill-callbacks/1",
        "closing_tick_contract": "candlescope.pine-closing-tick/1" if getattr(pine_compat,"EXTERNAL_CLOSING_TICK_SCHEMA_VERSION",0)==1 else None,
        "prefix_append": PREFIX_CONTRACT,
        "prefix_passes": PASSES_CONTRACT,
        "prefix_clocks": CLOCKS_CONTRACT,
        "external_execution_times": getattr(pine_compat, "EXTERNAL_CLOCK_SCHEMA_VERSION", 0) == 1,
        "external_incremental": callable(getattr(pine_compat.Program, "external_session", None)),
    }


def execute(request):
    if request.get("operation") == "analyze":
        program, analysis = prepare(request["source"], library_sources({"pineLibrarySources": request.get("libraries", {})}))
        requirements = program.host_requirements()
        # The empty prefix exposes declared broker settings without making trades.
        try:
            profile = program.run_external([], [], **({"risk_rules": True} if risk_available() else {}), **({"closing_ticks": True} if requirements["execution"].get("processOrdersOnClose") and getattr(pine_compat,"EXTERNAL_CLOSING_TICK_SCHEMA_VERSION",0)==1 else {}), **({"execution_passes": []} if requirements["execution"].get("calcOnOrderFills") else {}))
        except ValueError as exc:
            profile = {"profileError": str(exc)}
        return {
            "analysis": analysis,
            "requirements": requirements,
            "pyramiding": profile.get("pyramiding", 1),
            "profileError": profile.get("profileError"),
        }
    return evaluate(request)


if __name__ == "__main__":
    raise SystemExit((serve_evaluator if "--worker" in sys.argv else serve)(describe, execute))
