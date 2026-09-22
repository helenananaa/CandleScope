"""Resolve declared strategy warmup using the consumer's real interval grid."""
import json

from app.data_engine.interval_policy import IntervalAlignment

from .models import PreparationError


def strategy_warmup(runtime, revision_id, parameters):
    row = runtime.service.repository.get_strategy_revision(revision_id)
    if row is None or row["archived_at_ms"] is not None:
        raise PreparationError("STRATEGY_REVISION_UNAVAILABLE", "Select an active compiled strategy revision")
    capabilities = json.loads(row["capabilities_json"])
    requirement = capabilities.get("warmup_requirement") or {}
    if row["language"] == "PYNE_CHART_V1":
        from app.backtest.strategy.chart_pyne import compile_chart_pyne
        count = compile_chart_pyne(row["source_text"]).max_lookback
    else:
        schema = json.loads(row["parameter_schema_json"])
        registry = runtime.service.strategy_registry
        if not requirement and row["base_revision_id"] in registry.revision_ids():
            descriptor = registry.require(row["base_revision_id"]).to_wire()
            requirement = descriptor.get("warmup_requirement") or {}
            schema = schema or descriptor["parameter_schema"]
        if not requirement:
            return 0
        defaults = {item["name"]: item.get("default") for item in schema}
        if requirement.get("kind") == "PARAMETER_PLUS_ROWS":
            value = parameters.get(requirement["parameter"], defaults.get(requirement["parameter"]))
            if type(value) is not int:
                raise PreparationError("WARMUP_PARAMETER_INVALID", "Warmup requires a whole-number strategy parameter")
            count = max(requirement.get("minimum", 0), value + requirement.get("offset", 0))
        elif requirement.get("kind") == "PARAMETER_MAX":
            names = requirement.get("parameters") or []
            values = [parameters.get(name, defaults.get(name)) for name in names]
            if not values or any(type(value) is not int or value < 0 for value in values):
                raise PreparationError("WARMUP_PARAMETER_INVALID", "Warmup requires nonnegative whole-number parameters")
            count = max(values)
        elif requirement.get("kind") == "FIXED_BARS" and type(requirement.get("bars")) is int:
            count = requirement["bars"]
        else:
            raise PreparationError("WARMUP_UNSUPPORTED", "The provider warmup declaration cannot be resolved automatically")
    if type(count) is not int or not 0 <= count <= runtime.settings.max_warmup_bars:
        raise PreparationError("WARMUP_BUDGET", "Required warmup exceeds the strategy runtime limit")
    return count


def warmup_start(interval, start_ms, bars):
    if interval.alignment == IntervalAlignment.CALENDAR_MONTH:
        for _ in range(bars):
            start_ms = interval.previous_ms(start_ms)
    else:
        start_ms -= bars * interval.nominal_ms
    if start_ms < 0:
        raise PreparationError("WARMUP_RANGE_UNAVAILABLE", "Required warmup precedes available history")
    return start_ms
