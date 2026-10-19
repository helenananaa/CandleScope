"""External broker adapter. Never evaluates the native broker ledger."""

import re
from functools import lru_cache

import pine_compat
from candlescope_plugin_sdk.native_strategy import identity, serve, serve_evaluator

from .event_requests import run_with_event_requests
from .host_inputs import chart_metadata, native_request_bars, require_price_grid, require_quote_currency
from .libraries import library_sources
from .prefix_transport import CONTRACT as PREFIX_CONTRACT
from .prefix_transport import PASSES_CONTRACT, PrefixInput
from .strategy_time import engine_bars

_prefix = PrefixInput()
_session = None
_session_count = 0


def describe():
    if not hasattr(pine_compat.Program, "run_external"):
        raise ValueError("EXTERNAL_RUNTIME_UNAVAILABLE: install external-broker/1 runtime")
    return {
        **identity(
            "candlescope-plugin-pine-compat", "pine-compat-runtime", adapter="pine-external/6"
        ),
        "prefix_append": PREFIX_CONTRACT,
        "prefix_passes": PASSES_CONTRACT,
        "external_incremental": callable(getattr(pine_compat.Program, "external_session", None)),
    }


@lru_cache(maxsize=1)
def prepare(source, libraries=()):
    kwargs = {"library_sources": dict(libraries)} if libraries else {}
    return pine_compat.compile_script(source, **kwargs), pine_compat.analyze_script(source, **kwargs)


def execute(request):
    global _session, _session_count
    appending = request.get("operation") == "append_prefix"
    request = _prefix.decode(request)
    if not appending:
        _session = None
        _session_count = 0
    program, analysis = prepare(request["source"], library_sources({"pineLibrarySources": request.get("libraries", {})}))
    require_price_grid(analysis, request)
    require_quote_currency(analysis, program.host_requirements(), request, external=True)
    inputs = analysis.get("inputs", [])
    parameters = {}
    for name, value in request.get("parameters", {}).items():
        matches = [
            item for item in inputs if str(item["callSiteId"]) == name or item.get("title") == name
        ]
        if len(matches) != 1 or str(matches[0]["callSiteId"]) in parameters:
            raise ValueError("EXTERNAL_PARAMETER_INVALID: " + name)
        parameters[str(matches[0]["callSiteId"])] = value
    features = {
        item.get("feature", "") for item in analysis.get("compatibility", {}).get("supported", [])
    }
    endpoint_sensitive = any(
        feature
        in {"barstate.islast", "barstate.islastconfirmedhistory", "last_bar_index", "last_bar_time"}
        or feature.startswith("chart.")
        for feature in features
    ) or bool(re.search(r"\b(last_bar_index|last_bar_time|calc_bars_count)\b", request["source"]))
    # Growing historical prefixes change dataset-end builtins retroactively.
    # Only prefix-stable programs can reuse committed execution state.
    incremental = (
        callable(getattr(program, "external_session", None))
        and not endpoint_sensitive
        and not any(feature.startswith("ticker.") for feature in features)
    )
    start = _session_count if incremental and _session is not None else 0
    passes = request.get("execution_passes")
    if passes is not None:
        passes = [
            [
                {
                    **item,
                    "bar": engine_bars([item["bar"]])[0],
                    "account": {**item["account"], "time": item["account"]["time"] * 1000},
                    **(
                        {
                            "request_data": [
                                {**stream, "bars": engine_bars(stream["bars"])}
                                for stream in item["request_data"]
                            ]
                        }
                        if "request_data" in item
                        else {}
                    ),
                }
                for item in group
            ]
            for group in passes[start:]
        ]
    accounts = [{**item, "time": item["time"] * 1000} for item in request["accounts"][start:]]
    supplied = native_request_bars(
        request,
        {
            f"{item['symbol']}:{item['timeframe']}": engine_bars(item["bars"])
            for item in request.get("contexts", [])
        },
    )
    tick = request.get("host_settings", {}).get("price_tick")
    if tick is not None:
        grid = chart_metadata({"priceTickSize": tick})
        if "$chart" in supplied and any(
            supplied["$chart"][key] != grid[key] for key in ("minMove", "priceScale")
        ):
            raise ValueError(
                "EXTERNAL_UNSUPPORTED: context price grid differs from matching price_tick"
            )
        supplied["$chart"] = {**supplied.get("$chart", {}), **grid}
    try:
        if incremental:
            if _session is None:
                _session = program.external_session(
                    input_overrides=parameters or None,
                    chart_symbol=request["context"]["symbol"],
                    chart_timeframe=request["context"]["timeframe"],
                    request_bars=supplied,
                )
                _session_count = 0
            result = _session.append(
                engine_bars(request["bars"][start:]),
                accounts,
                **({"execution_passes": passes} if passes is not None else {}),
            )
            _session_count = len(request["bars"])
        else:
            _session = None
            result = run_with_event_requests(
                lambda request_bars: program.run_external(
                    engine_bars(request["bars"]),
                    accounts,
                    input_overrides=parameters or None,
                    chart_symbol=request["context"]["symbol"],
                    chart_timeframe=request["context"]["timeframe"],
                    execution_passes=passes,
                    request_bars=request_bars,
                ),
                request,
                supplied,
                engine_bars,
                pine_compat,
            )
    except Exception:
        _session = None
        _session_count = 0
        raise
    if result["output"].get("diagnostics"):
        raise ValueError(str(result["output"]["diagnostics"]))
    return {
        "contract": result["protocol"],
        "pyramiding": result.get("pyramiding", 1),
        "intents": result["intents"],
        "graphics": result["output"].get("plots", []),
        "raw_output": result["output"],
        "execution_mode": "CANDLESCOPE",
        "account_authority": "candlescope",
    }


if __name__ == "__main__":
    import sys

    raise SystemExit((serve_evaluator if "--worker" in sys.argv else serve)(describe, execute))
