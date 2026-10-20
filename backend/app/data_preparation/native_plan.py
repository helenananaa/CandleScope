"""Frozen native input planning; execution/account ownership stays in the plugin."""
from __future__ import annotations

import ast
import re

from app.data_engine.interval_policy import parse_interval_spec
from app.backtest.native import timeframe

from .models import PreparationError, Requirement

_TOKENS = re.compile(r'''//[^\n]*|\#[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_]\w*|\d+|[^\s]''')


def _request_calls(source):
    tokens = [match.group() for match in _TOKENS.finditer(source)
              if not match.group().startswith(("//", "#", "/*"))]
    for index in range(len(tokens) - 4):
        if tokens[index:index + 2] != ["request", "."] or tokens[index + 2] not in {"security", "security_lower_tf"} or tokens[index + 3] != "(":
            continue
        arguments, current, depth = [], [], 0
        for token in tokens[index + 4:]:
            if token in {"(", "[", "{"}:
                depth += 1
            elif token in {")", "]", "}"}:
                if depth == 0:
                    arguments.append(current)
                    break
                depth -= 1
            if token == "," and depth == 0:
                arguments.append(current)
                current = []
            else:
                current.append(token)
        yield arguments


def requested_contexts(source, *, symbol, interval, explicit=False):
    """Recognize literal request.security contexts without executing source."""
    found = []
    for arguments in _request_calls(source):
        values = []
        for argument, default, alias in zip(arguments, (symbol, timeframe(interval)),
                                            (["syminfo", ".", "tickerid"], ["timeframe", ".", "period"])):
            if argument == alias:
                values.append(default)
            elif len(argument) == 1 and argument[0].startswith(('"', "'")):
                try:
                    values.append(ast.literal_eval(argument[0]) or default)
                except (ValueError, SyntaxError) as exc:
                    raise PreparationError("INVALID_DEPENDENCY", "Requested context contains an invalid string literal") from exc
            else:
                values.append(None)
        if len(values) != 2 or None in values:
            if explicit:
                continue
            raise PreparationError("DYNAMIC_DEPENDENCY_REQUIRED", "Declare symbol/timeframe inputs for dynamic request.security calls")
        requested_symbol, requested_timeframe = values
        if not isinstance(requested_symbol, str) or not isinstance(requested_timeframe, str):
            raise PreparationError("INVALID_DEPENDENCY", "Requested contexts must have string identities")
        pair = (requested_symbol, requested_timeframe)
        if pair not in found:
            found.append(pair)
    return found


def requested_lookbacks(source, *, symbol, interval, explicit=False):
    from .native_lookback import expression_lookback
    found = {}
    for arguments in _request_calls(source):
        call = "request.security(" + ",".join(" ".join(arg) for arg in arguments[:2]) + ",close)"
        pairs = requested_contexts(call, symbol=symbol, interval=interval, explicit=explicit)
        if not pairs:
            continue
        pair = pairs[0]
        count = expression_lookback(" ".join(arguments[2])) if len(arguments) >= 3 else None
        previous = found.get(pair, 0)
        found[pair] = None if previous is None or count is None else max(previous, count)
    return found


def chart_interval(value):
    if re.fullmatch(r"[1-9]\d*", value):
        interval = value + "m"
    else:
        match = re.fullmatch(r"([1-9]\d*)?([SDWM])", value)
        if match is None:
            raise PreparationError("DEPENDENCY_INTERVAL_UNSUPPORTED", f"Unsupported requested timeframe: {value}")
        interval = (match[1] or "1") + {"S": "s", "D": "d", "W": "w", "M": "M"}[match[2]]
    spec = parse_interval_spec(interval)
    if spec is None or spec.nominal_ms < 60_000:
        raise PreparationError("DEPENDENCY_INTERVAL_UNSUPPORTED", "Automatic native inputs require minute or coarser bars")
    return spec.canonical


def plan_inputs(context, dependencies):
    """Deduplicate physical minute-bar acquisition across logical intervals."""
    from app.backtest.chart_context import ChartContextRequest
    bindings, physical = [], {}
    primary_start, primary_end = context["start_time_ms"], context["end_time_ms"] + 1
    for index, dependency in enumerate([context, *dependencies]):
        market = ChartContextRequest.from_mapping(dependency)
        spec = parse_interval_spec(dependency["interval"])
        if spec is None or spec.nominal_ms < 60_000:
            raise PreparationError("DEPENDENCY_INTERVAL_UNSUPPORTED", "Native input cannot be constructed from minute bars")
        start = spec.floor_ms(primary_start)
        end = spec.floor_ms(primary_end)
        if index:
            from .dependency_plan import warmup_start
            warmup = dependency.get("warmup_bars", 1)
            if type(warmup) is not int or not 0 <= warmup <= 5000:
                raise PreparationError("WARMUP_BUDGET", "Requested-context warmup must be between 0 and 5000 prior bars")
            start = warmup_start(spec, start, max(1, warmup))
        if end <= start or start < 0:
            raise PreparationError("DEPENDENCY_RANGE_UNAVAILABLE", "No complete historical bars cover the requested input")
        # Publication and subsequent context resolution must use the same
        # canonical market identity, including aliases such as usdm -> futures.
        binding = {"exchange": market.exchange, "market_type": market.market_type,
            "symbol": market.symbol, "interval": spec.canonical,
            "binding_symbol": dependency.get("binding_symbol", f"{market.exchange.upper()}:{market.symbol}"),
            "range_mode": "CUSTOM", "fidelity_preference": "FAST", "start_time_ms": start, "end_time_ms": end - 1}
        bindings.append(binding)
        identity = (binding["exchange"], binding["market_type"], binding["symbol"])
        previous = physical.get(identity)
        physical[identity] = Requirement(exchange=identity[0], market_type=identity[1], symbol=identity[2],
            start_ms=min(start, previous.start_ms) if previous else start,
            end_ms=max(end, previous.end_ms) if previous else end)
    return list(physical.values()), bindings


def freeze_bindings(runtime, bindings):
    inputs = []
    for binding in bindings:
        context = {key: value for key, value in binding.items() if key != "binding_symbol"}
        resolved = runtime.chart_context.resolve(context)
        if resolved["status"] != "READY":
            raise PreparationError("DEPENDENCY_NOT_READY", f"History is incomplete for {binding['binding_symbol']} {binding['interval']}")
        inputs.append({"dataset_id": resolved["dataset_id"], "data_epoch": resolved["data_epoch"],
            "snapshot_hash": resolved["snapshot_hash"], "start_time_ms": binding["start_time_ms"],
            "end_time_ms": binding["end_time_ms"], "interval": binding["interval"],
            "exchange": binding["exchange"], "market_type": binding["market_type"],
            "symbol": binding["binding_symbol"], "timeframe": timeframe(binding["interval"])})
    return inputs


def launch(runtime, intent, inputs, job_id):
    from app.backtest.native_contracts import NativeRunRequest, ExternalRunRequest
    if "frozen_payload" in intent:
        payload = ExternalRunRequest.model_validate(intent["frozen_payload"]).model_dump()
        return runtime.native.create(payload, f"preparation:{job_id}")
    main, *contexts = inputs
    payload = {key: value for key, value in main.items() if key not in {"symbol", "timeframe"}}
    payload.update(language=intent["language"], source=intent["source"], parameters=intent["parameters"],
        libraries=intent["libraries"], contexts=contexts,
        context={"symbol": main["symbol"], "timeframe": main["timeframe"],
                 **({"metadata": intent["chart_metadata"]} if intent.get("chart_metadata") else {})})
    if intent.get("currency_rates") is not None:
        payload["currency_rates"] = intent["currency_rates"]
    contract = NativeRunRequest
    if intent.get("execution") is not None:
        contract = ExternalRunRequest
        payload.update(intent["execution"], execution_mode="CANDLESCOPE")
    return runtime.native.create(contract.model_validate(payload).model_dump(), f"preparation:{job_id}")


def validate_frozen_external(runtime, payload):
    """Reject stale or mismatched signal inputs before acquiring any prints."""
    from app.backtest.errors import BacktestError
    from app.market_dataset.snapshot import MarketDatasetError
    if payload["execution_fidelity"] != "TRADE_TAPE" or payload.get("execution_data") is not None:
        raise PreparationError("INPUT_UNSUPPORTED", "Automatic frozen execution requires archive TRADE_TAPE")
    if payload.get("magnifier"):
        raise PreparationError("EXTERNAL_UNSUPPORTED", "Host matching requires execution events instead of native Magnifier")
    keys = set()
    for index, item in enumerate([payload, *payload.get("contexts", [])]):
        metadata = payload["context"] if index == 0 else item
        pair = (metadata["symbol"], metadata["timeframe"])
        if index and pair in keys:
            raise PreparationError("INPUT_INVALID", "Duplicate requested context")
        if index:
            keys.add(pair)
        try:
            manifest = runtime._manifest(item["dataset_id"])
            runtime.native._freeze(item)
        except (BacktestError, MarketDatasetError) as exc:
            raise PreparationError(exc.code, str(exc)) from exc
        if pair[0].split(":")[-1] != manifest["symbol"] or pair[1] != timeframe(item["interval"]):
            raise PreparationError("DATA_SNAPSHOT_MISMATCH", "Signal metadata differs from frozen dataset")
