"""Alert indicator fields mapped to public numeric definitions, without formulas.

``rsi``, ``macdHist`` and ``ma20`` are compatibility aliases. Any builtin
output can be referenced with a canonical key::

    ind:<NAME>:<output>:<param>=<value>,<param>=<value>

holding every calculation parameter in key order. Display-only colour
parameters are excluded, so restyling a chart line never changes an alert.
The numeric service evaluates these with the same convergence seed a chart
uses, so an alert sees exactly the value the chart shows (ADR-INDICATOR-001).
"""
from __future__ import annotations

import math

from app.data_engine.data_manager.models import SeriesKey
from app.indicator import registry
from app.indicator.query_contracts import BuiltinOutput, IndicatorQuery

INDICATOR_FIELD_PREFIX = "ind:"
# One numeric query serves a rule; the numeric contract accepts three outputs.
MAX_RULE_INDICATOR_OUTPUTS = 3


def _math_schema(name: str) -> tuple[dict, tuple[str, ...]]:
    spec = registry.get_spec(name)
    if spec is None or not getattr(spec, "is_builtin", False):
        raise ValueError(f"Unknown builtin indicator: {name or '<empty>'}")
    fields = {field.key: field for field in spec.param_schema if field.type != "color"}
    return fields, tuple(spec.output_specs)


def _format_value(value: int | float | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value)


def _normalize_params(name: str, params: dict) -> tuple[tuple[str, int | float | str], ...]:
    fields, _ = _math_schema(name)
    unknown = set(params) - set(fields)
    if unknown:
        raise ValueError(f"Unsupported {name} parameter: {sorted(unknown)[0]}")
    normalized = []
    for key in sorted(fields):
        field = fields[key]
        value = params.get(key, field.default)
        if field.type in {"int", "float"}:
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{name} {key} must be a number") from None
            if not math.isfinite(number):
                raise ValueError(f"{name} {key} must be finite")
            if field.type == "int":
                if not number.is_integer():
                    raise ValueError(f"{name} {key} must be an integer")
                value = int(number)
            else:
                value = int(number) if number.is_integer() else number
            if (field.min is not None and value < field.min) or (
                    field.max is not None and value > field.max):
                raise ValueError(f"{name} {key} is out of range")
        else:
            value = str(value)
            if field.options is not None and value not in field.options:
                raise ValueError(f"Unsupported {name} {key}: {value}")
        normalized.append((key, value))
    return tuple(normalized)


def builtin_output(name: str, params: dict, output: str) -> BuiltinOutput:
    name = str(name or "").upper().strip()
    _, outputs = _math_schema(name)
    if output not in outputs:
        raise ValueError(f"Unknown {name} output: {output or '<empty>'}")
    return BuiltinOutput(name, _normalize_params(name, params), output)


def indicator_field_key(output: BuiltinOutput) -> str:
    params = ",".join(f"{key}={_format_value(value)}" for key, value in output.params)
    return f"{INDICATOR_FIELD_PREFIX}{output.name}:{output.output_id}:{params}"


def parse_indicator_field(field: str) -> BuiltinOutput:
    """Parse a canonical ``ind:`` key; a non-canonical spelling is rejected."""
    if not isinstance(field, str) or not field.startswith(INDICATOR_FIELD_PREFIX):
        raise ValueError("Indicator field must start with ind:")
    parts = field[len(INDICATOR_FIELD_PREFIX):].split(":")
    if len(parts) != 3:
        raise ValueError("Indicator field must be ind:<NAME>:<output>:<params>")
    name, output, raw_params = parts
    params = {}
    for item in filter(None, raw_params.split(",")):
        key, separator, value = item.partition("=")
        if not separator or not key or key in params:
            raise ValueError(f"Invalid indicator parameter: {item}")
        params[key] = value
    parsed = builtin_output(name, params, output)
    if indicator_field_key(parsed) != field:
        raise ValueError(f"Indicator field is not canonical; expected {indicator_field_key(parsed)}")
    return parsed


ALIASES = {
    'rsi': builtin_output('RSI', {'period': 14, 'source': 'close'}, 'rsi'),
    'macdHist': builtin_output('MACD', {'fast': 12, 'slow': 26, 'signal': 9, 'source': 'close'}, 'hist'),
    'ma20': builtin_output('MA', {'period': 20, 'source': 'close'}, 'ma'),
}


def is_indicator_field(field: str) -> bool:
    return field in ALIASES or (isinstance(field, str) and field.startswith(INDICATOR_FIELD_PREFIX))


def output_for_field(field: str) -> BuiltinOutput:
    return ALIASES[field] if field in ALIASES else parse_indicator_field(field)


def rule_outputs(fields) -> tuple[BuiltinOutput, ...]:
    """Distinct numeric outputs for a rule's indicator fields, in stable order."""
    outputs = {}
    for field in sorted(field for field in fields if is_indicator_field(field)):
        output = output_for_field(field)
        outputs.setdefault(output, None)
    if len(outputs) > MAX_RULE_INDICATOR_OUTPUTS:
        raise ValueError(
            f"An alert can reference at most {MAX_RULE_INDICATOR_OUTPUTS} indicator outputs")
    return tuple(outputs)


def request_for(target, fields):
    return IndicatorQuery(SeriesKey(target['symbol'], target['interval'],
        exchange=target['exchange'], market_type=target['marketType']),
        rule_outputs(fields))


def empty_values(fields=()):
    """Trigger records always carry the alias keys, as before parameterised fields."""
    return {**dict.fromkeys(ALIASES), **dict.fromkeys(
        field for field in fields if is_indicator_field(field))}


def values_from(snapshot, fields):
    """Snapshot values keyed by the exact field strings the rule's expression uses."""
    values = dict(snapshot.values)
    return {**empty_values(), **{field: values.get(output_for_field(field))
            for field in fields if is_indicator_field(field)}}
