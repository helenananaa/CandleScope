"""Pine compilation and external decisions for the chart strategy workspace."""

import sys

import pine_compat
from candlescope_plugin_sdk.native_strategy import identity, serve, serve_evaluator

from .external_strategy import execute as evaluate
from .external_strategy import prepare
from .prefix_transport import CONTRACT as PREFIX_CONTRACT, PASSES_CONTRACT, CLOCKS_CONTRACT
from .libraries import library_sources
from .entry_risk import CONTRACT as RISK_CONTRACT, available as risk_available
from .entry_risk import STOP_CONTRACT
from .execution_schedule import capabilities as schedule_capabilities
from .request_updates import CONTRACT as REQUEST_UPDATE_CONTRACT, capabilities as request_update_capabilities, eligible as request_updates_eligible
from .external_stream import capabilities as stream_capabilities


def describe():
    return {
        **identity("candlescope-plugin-pine-compat", "pine-compat-runtime", adapter="pine-chart/9"),
        **({"order_metadata_contract": "candlescope.pine-order-metadata/1"}
           if getattr(pine_compat, "EXTERNAL_ORDER_METADATA_SCHEMA_VERSION", 0) == 1 else {}),
        **schedule_capabilities(),
        **stream_capabilities(),
        **request_update_capabilities(),
        "external_orders": getattr(pine_compat, "EXTERNAL_ORDER_SCHEMA_VERSION", 1),
        "external_sizing": getattr(pine_compat, "EXTERNAL_SIZING_SCHEMA_VERSION", 0),
        "contract_metadata_schema": getattr(pine_compat, "CONTRACT_METADATA_SCHEMA_VERSION", 0),
        **({"entry_risk_contract": RISK_CONTRACT} if risk_available() else {}),
        **({"risk_stop_contract": STOP_CONTRACT} if risk_available() else {}),
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
        scheduled=bool(stream_capabilities()) and any(requirements["execution"].get(name)
            for name in ("calcOnEveryTick","calcOnEveryHistoryTick"))
        try:
            profile = program.run_external([], [], **({"risk_rules": True} if risk_available() else {}), **({"closing_ticks": True} if requirements["execution"].get("processOrdersOnClose") and getattr(pine_compat,"EXTERNAL_CLOSING_TICK_SCHEMA_VERSION",0)==1 else {}), **({"execution_schedule":[]} if scheduled else {"execution_passes": []} if requirements["execution"].get("calcOnOrderFills") else {}))
        except ValueError as exc:
            profile = {"profileError": str(exc)}
        return {
            "analysis": analysis,
            "requirements": requirements,
            "pyramiding": profile.get("pyramiding", 1),
            "profileError": profile.get("profileError"),
            **({"request_update_contract": REQUEST_UPDATE_CONTRACT} if request_updates_eligible(analysis) else {}),
        }
    return evaluate(request)


if __name__ == "__main__":
    raise SystemExit((serve_evaluator if "--worker" in sys.argv else serve)(describe, execute))
