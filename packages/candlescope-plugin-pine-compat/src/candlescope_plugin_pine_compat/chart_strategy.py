"""Pine compilation and external decisions for the chart strategy workspace."""

import sys

import pine_compat
from candlescope_plugin_sdk.native_strategy import identity, serve, serve_evaluator

from .external_strategy import execute as evaluate
from .external_strategy import prepare
from .prefix_transport import CONTRACT as PREFIX_CONTRACT, PASSES_CONTRACT
from .libraries import library_sources


def describe():
    return {
        **identity("candlescope-plugin-pine-compat", "pine-compat-runtime", adapter="pine-chart/1"),
        "prefix_append": PREFIX_CONTRACT,
        "prefix_passes": PASSES_CONTRACT,
        "external_incremental": callable(getattr(pine_compat.Program, "external_session", None)),
    }


def execute(request):
    if request.get("operation") == "analyze":
        program, analysis = prepare(request["source"], library_sources({"pineLibrarySources": request.get("libraries", {})}))
        # The empty prefix exposes declared broker settings without making trades.
        try:
            profile = program.run_external([], [])
        except ValueError as exc:
            profile = {"profileError": str(exc)}
        return {
            "analysis": analysis,
            "requirements": program.host_requirements(),
            "pyramiding": profile.get("pyramiding", 1),
            "profileError": profile.get("profileError"),
        }
    return evaluate(request)


if __name__ == "__main__":
    raise SystemExit((serve_evaluator if "--worker" in sys.argv else serve)(describe, execute))
