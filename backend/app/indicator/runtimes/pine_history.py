"""Conservative history planning for hosted Pine-compatible indicators.

The native runtime executes the bars supplied by the host.  A viewport-sized
slice is therefore not a safe seed for cumulative, recursive, or otherwise
stateful scripts.  This module classifies scripts into two host execution
models:

``bounded``
    The result only needs a finite number of bars before the requested range.

``available-history``
    Execution must start at CandleScope's earliest locally available bar for
    the chart series.  This keeps results stable across viewport/range loads;
    a later session/checkpoint contract can extend the same model beyond the
    current per-run bar limit.

The planner deliberately prefers extra history over an under-sized seed.  It
uses native compatibility/input metadata when available and has a source-only
fallback for startup/error paths.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import math
import re
from typing import Any, Iterable


PINE_HISTORY_PLAN_SCHEMA_VERSION = 1
PINE_HISTORY_MODE_BOUNDED = "bounded"
PINE_HISTORY_MODE_AVAILABLE = "available-history"


@dataclass(frozen=True, slots=True)
class PineHistoryPlan:
    """Host-side seed-history requirements for one Pine script/param set."""

    mode: str
    warmup_bars: int = 0
    max_constant_offset: int = 0
    has_dynamic_offsets: bool = False
    reasons: tuple[str, ...] = ()
    features: tuple[str, ...] = ()

    @property
    def requires_available_history(self) -> bool:
        return self.mode == PINE_HISTORY_MODE_AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": PINE_HISTORY_PLAN_SCHEMA_VERSION,
            "mode": self.mode,
            "warmupBars": max(0, int(self.warmup_bars)),
            "maxConstantOffset": max(0, int(self.max_constant_offset)),
            "hasDynamicOffsets": bool(self.has_dynamic_offsets),
            "requiresAvailableHistory": self.requires_available_history,
            "historyScope": (
                "local-available-history"
                if self.requires_available_history
                else "bounded-lookback"
            ),
            "reasons": list(self.reasons),
            "features": list(self.features),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PineHistoryPlan":
        if int(value.get("schemaVersion") or 0) != PINE_HISTORY_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported Pine history plan schema")
        mode = str(value.get("mode") or "")
        if mode not in {PINE_HISTORY_MODE_BOUNDED, PINE_HISTORY_MODE_AVAILABLE}:
            raise ValueError("unsupported Pine history plan mode")
        return cls(
            mode=mode,
            warmup_bars=max(0, int(value.get("warmupBars") or 0)),
            max_constant_offset=max(0, int(value.get("maxConstantOffset") or 0)),
            has_dynamic_offsets=bool(value.get("hasDynamicOffsets")),
            reasons=tuple(str(item) for item in value.get("reasons") or [] if str(item)),
            features=tuple(str(item) for item in value.get("features") or [] if str(item)),
        )


# These functions retain state from the start of the supplied dataset, either
# directly or through recursive smoothing.  A finite "N times the length"
# heuristic is visually useful but is not an exact host contract.
_STATEFUL_TA_FEATURES = frozenset({
    "ta.accdist",
    "ta.atr",
    "ta.barssince",
    "ta.cum",
    "ta.dema",
    "ta.dmi",
    "ta.ema",
    "ta.kc",
    "ta.kcw",
    "ta.macd",
    "ta.max",
    "ta.min",
    "ta.nvi",
    "ta.obv",
    "ta.pvi",
    "ta.pvt",
    "ta.rma",
    "ta.rsi",
    "ta.sar",
    "ta.supertrend",
    "ta.tema",
    "ta.tsi",
    "ta.valuewhen",
    "ta.vwap",
})


# Positive positional indexes identify length-like arguments.  Negative
# indexes count from the end and cover overloads with an optional source.
_BOUNDED_TA_LENGTH_ARGS: dict[str, tuple[tuple[int, ...], tuple[str, ...], int | None]] = {
    "ta.alma": ((1,), ("length",), None),
    "ta.bb": ((1,), ("length",), None),
    "ta.bbw": ((1,), ("length",), None),
    "ta.cci": ((-1,), ("length",), None),
    "ta.change": ((1,), ("length",), 1),
    "ta.cmo": ((-1,), ("length",), None),
    "ta.cog": ((-1,), ("length",), None),
    "ta.correlation": ((2,), ("length",), None),
    "ta.covariance": ((2,), ("length",), None),
    "ta.dev": ((1,), ("length",), None),
    "ta.falling": ((1,), ("length",), None),
    "ta.highest": ((-1,), ("length",), None),
    "ta.highestbars": ((-1,), ("length",), None),
    "ta.hma": ((1,), ("length",), None),
    "ta.linreg": ((1,), ("length",), None),
    "ta.lowest": ((-1,), ("length",), None),
    "ta.lowestbars": ((-1,), ("length",), None),
    "ta.median": ((1,), ("length",), None),
    "ta.mfi": ((-1,), ("length",), None),
    "ta.mode": ((1,), ("length",), None),
    "ta.mom": ((1,), ("length",), None),
    "ta.percentile_linear_interpolation": ((1,), ("length",), None),
    "ta.percentile_nearest_rank": ((1,), ("length",), None),
    "ta.percentrank": ((1,), ("length",), None),
    "ta.pivothigh": ((-2, -1), ("leftbars", "rightbars"), None),
    "ta.pivotlow": ((-2, -1), ("leftbars", "rightbars"), None),
    "ta.range": ((1,), ("length",), None),
    "ta.rising": ((1,), ("length",), None),
    "ta.roc": ((1,), ("length",), None),
    "ta.sma": ((1,), ("length",), None),
    "ta.stdev": ((1,), ("length",), None),
    "ta.stoch": ((-1,), ("period", "length"), None),
    "ta.sum": ((1,), ("length",), None),
    "ta.variance": ((1,), ("length",), None),
    "ta.vwma": ((1,), ("length",), None),
    "ta.wma": ((1,), ("length",), None),
    "ta.wpr": ((-1,), ("length",), None),
}


_BOUNDED_TA_FIXED_WARMUP = {
    "ta.ao": 34,
    "ta.bop": 0,
    "ta.cross": 1,
    "ta.crossover": 1,
    "ta.crossunder": 1,
    "ta.iii": 0,
    "ta.swma": 4,
    "ta.tr": 1,
    "ta.wvad": 0,
}


def _mask_non_code(source: str) -> str:
    """Replace strings/comments with spaces while preserving source layout."""

    chars = list(source)
    index = 0
    state = "code"
    quote = ""
    while index < len(chars):
        current = chars[index]
        next_char = chars[index + 1] if index + 1 < len(chars) else ""
        if state == "code":
            if current in {'"', "'"}:
                quote = current
                chars[index] = " "
                state = "string"
            elif current == "/" and next_char == "/":
                chars[index] = chars[index + 1] = " "
                index += 1
                state = "line-comment"
            elif current == "/" and next_char == "*":
                chars[index] = chars[index + 1] = " "
                index += 1
                state = "block-comment"
        elif state == "string":
            if current == "\\":
                chars[index] = " "
                if index + 1 < len(chars):
                    index += 1
                    if chars[index] != "\n":
                        chars[index] = " "
            elif current == quote:
                chars[index] = " "
                state = "code"
            elif current != "\n":
                chars[index] = " "
        elif state == "line-comment":
            if current == "\n":
                state = "code"
            else:
                chars[index] = " "
        else:
            if current == "*" and next_char == "/":
                chars[index] = chars[index + 1] = " "
                index += 1
                state = "code"
            elif current != "\n":
                chars[index] = " "
        index += 1
    return "".join(chars)


def _matching_delimiter(source: str, start: int, opening: str, closing: str) -> int | None:
    depth = 0
    for index in range(start, len(source)):
        current = source[index]
        if current == opening:
            depth += 1
        elif current == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _history_offsets(source: str) -> tuple[int, bool]:
    max_offset = 0
    dynamic = False
    for index, current in enumerate(source):
        if current != "[":
            continue
        previous = index - 1
        while previous >= 0 and source[previous] in " \t\r":
            previous -= 1
        # Tuple declarations/literals begin a new expression.  A Pine history
        # reference follows an existing expression such as close[1] or foo()[1].
        if previous < 0 or source[previous] in "=({,:;\n":
            continue
        end = _matching_delimiter(source, index, "[", "]")
        if end is None:
            continue
        value = source[index + 1:end].strip()
        if re.fullmatch(r"\+?\d+", value):
            max_offset = max(max_offset, int(value))
        elif value:
            dynamic = True
    return max_offset, dynamic


def _safe_int_expression(expression: str, constants: dict[str, int]) -> int | None:
    try:
        node = ast.parse(expression.strip(), mode="eval").body
    except (SyntaxError, ValueError):
        return None

    def _value(item: ast.AST) -> int | None:
        if isinstance(item, ast.Constant) and isinstance(item.value, int) and not isinstance(item.value, bool):
            return int(item.value)
        if isinstance(item, ast.Name):
            return constants.get(item.id)
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, (ast.UAdd, ast.USub)):
            operand = _value(item.operand)
            if operand is None:
                return None
            return operand if isinstance(item.op, ast.UAdd) else -operand
        if isinstance(item, ast.BinOp):
            left = _value(item.left)
            right = _value(item.right)
            if left is None or right is None:
                return None
            try:
                if isinstance(item.op, ast.Add):
                    result = left + right
                elif isinstance(item.op, ast.Sub):
                    result = left - right
                elif isinstance(item.op, ast.Mult):
                    result = left * right
                elif isinstance(item.op, ast.FloorDiv) and right:
                    result = left // right
                elif isinstance(item.op, ast.Div) and right and left % right == 0:
                    result = left // right
                elif isinstance(item.op, ast.Mod) and right:
                    result = left % right
                else:
                    return None
            except ArithmeticError:
                return None
            return result if abs(result) <= 10_000_000 else None
        return None

    return _value(node)


def _split_top_level(source: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    for index, current in enumerate(source):
        if current in depths:
            depths[current] += 1
        elif current in closing:
            depths[closing[current]] = max(0, depths[closing[current]] - 1)
        elif current == "," and not any(depths.values()):
            parts.append(source[start:index].strip())
            start = index + 1
    parts.append(source[start:].strip())
    return [part for part in parts if part]


def _named_argument(argument: str) -> tuple[str | None, str]:
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    for index, current in enumerate(argument):
        if current in depths:
            depths[current] += 1
        elif current in closing:
            depths[closing[current]] = max(0, depths[closing[current]] - 1)
        elif current == "=" and not any(depths.values()):
            previous = argument[index - 1] if index else ""
            following = argument[index + 1] if index + 1 < len(argument) else ""
            if previous not in "<>!=" and following != "=":
                name = argument[:index].strip()
                if re.fullmatch(r"[A-Za-z_]\w*", name):
                    return name, argument[index + 1:].strip()
    return None, argument.strip()


def _iter_calls(source: str, names: Iterable[str]) -> Iterable[tuple[str, int, int, str]]:
    matches: list[tuple[int, str, int]] = []
    for name in set(names):
        pattern = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(name)}\s*\(")
        for match in pattern.finditer(source):
            matches.append((match.start(), name, match.end() - 1))
    for _, name, opening in sorted(matches):
        closing = _matching_delimiter(source, opening, "(", ")")
        if closing is not None:
            yield name, opening, closing, source[opening + 1:closing]


def _input_constants(
    source: str,
    analysis: dict[str, Any] | None,
    params: dict[str, Any] | None,
) -> dict[str, int]:
    constants: dict[str, int] = {}
    inputs = [item for item in (analysis or {}).get("inputs") or [] if isinstance(item, dict)]
    input_calls = list(_iter_calls(source, ("input", "input.int", "input.float")))
    for ordinal, (_, opening, _, body) in enumerate(input_calls):
        call_start = source.rfind("input", 0, opening + 1)
        line_start = source.rfind("\n", 0, max(call_start, 0)) + 1
        prefix = source[line_start:max(call_start, 0)]
        assignment = re.search(
            r"(?:(?:const|simple|input|series)\s+)?(?:(?:int|float)\s+)?"
            r"([A-Za-z_]\w*)\s*=\s*$",
            prefix,
        )
        if assignment is None:
            continue
        metadata = inputs[ordinal] if ordinal < len(inputs) else {}
        default = metadata.get("default")
        if default is None:
            arguments = [_named_argument(item) for item in _split_top_level(body)]
            named = {name: value for name, value in arguments if name}
            positional = [value for name, value in arguments if name is None]
            default_expr = named.get("defval") or (positional[0] if positional else "")
            default = _safe_int_expression(str(default_expr), constants)
        call_site_id = metadata.get("callSiteId")
        override = None
        if params and call_site_id is not None:
            override = params.get(str(call_site_id), params.get(call_site_id))
        effective = default if override is None else override
        if isinstance(effective, int) and not isinstance(effective, bool):
            constants[assignment.group(1)] = int(effective)

    # Resolve simple constant aliases/arithmetic in source order.  Stateful
    # declarations are intentionally ignored; they force available-history.
    assignment_pattern = re.compile(
        r"(?m)^\s*(?:(?:const|simple)\s+)?(?:int\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*([^\n]+?)\s*$"
    )
    for _ in range(3):
        changed = False
        for match in assignment_pattern.finditer(source):
            name, expression = match.groups()
            if name in constants or "input" in expression or ":=" in expression:
                continue
            value = _safe_int_expression(expression, constants)
            if value is not None:
                constants[name] = value
                changed = True
        if not changed:
            break
    return constants


def _supported_features(analysis: dict[str, Any] | None, source: str) -> set[str]:
    supported = (analysis or {}).get("compatibility")
    supported = supported if isinstance(supported, dict) else {}
    features = {
        str(item.get("feature") or "").strip().lower()
        for item in supported.get("supported") or []
        if isinstance(item, dict) and str(item.get("feature") or "").strip()
    }
    if not features:
        features.update(
            match.group(0).replace(" ", "").lower()
            for match in re.finditer(r"\bta\s*\.\s*[A-Za-z_]\w*", source)
        )
    return features


def _source_names_for_feature(feature: str, analysis: dict[str, Any] | None) -> set[str]:
    names = {feature}
    compatibility = (analysis or {}).get("compatibility")
    compatibility = compatibility if isinstance(compatibility, dict) else {}
    for item in compatibility.get("legacyTranslations") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("canonicalFeature") or "").strip().lower() == feature:
            source_feature = str(item.get("sourceFeature") or "").strip()
            if source_feature:
                names.add(source_feature)
    return names


def _bounded_ta_call_warmup(
    feature: str,
    body: str,
    constants: dict[str, int],
) -> int | None:
    if feature in _BOUNDED_TA_FIXED_WARMUP:
        return _BOUNDED_TA_FIXED_WARMUP[feature]
    spec = _BOUNDED_TA_LENGTH_ARGS.get(feature)
    if spec is None:
        return None
    positions, names, default = spec
    parsed = [_named_argument(item) for item in _split_top_level(body)]
    named = {name.lower(): value for name, value in parsed if name}
    positional = [value for name, value in parsed if name is None]
    values: list[int] = []
    for offset, argument_name in zip(positions, names):
        expression = named.get(argument_name.lower())
        if expression is None:
            index = offset if offset >= 0 else len(positional) + offset
            expression = positional[index] if 0 <= index < len(positional) else None
        value = _safe_int_expression(expression, constants) if expression is not None else default
        if value is None or value <= 0:
            return None
        values.append(value)
    if not values and default is not None:
        values.append(default)
    if not values:
        return None
    # HMA first builds full/half-length WMAs, then smooths their difference
    # over round(sqrt(length)) bars.  ``length`` alone would leave the first
    # requested bars as ``na`` even though a full-history execution has values.
    if feature == "ta.hma":
        length = values[0]
        smooth_length = max(1, int(math.sqrt(length) + 0.5))
        return length + smooth_length
    return sum(values)


def plan_pine_history(
    script: str,
    *,
    analysis: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> PineHistoryPlan:
    """Build a conservative, deterministic Pine seed-history plan."""

    code = _mask_non_code(str(script or ""))
    max_offset, dynamic_offset = _history_offsets(code)
    declared_values = [
        int(value)
        for value in re.findall(r"\bmax_bars_back\s*=\s*(\d+)", code)
    ]
    declared_max = max(declared_values, default=0)

    native_history = (analysis or {}).get("historyRequirements")
    native_history = native_history if isinstance(native_history, dict) else {}
    try:
        max_offset = max(max_offset, int(native_history.get("maxConstantOffset") or 0))
    except (TypeError, ValueError):
        pass
    dynamic_offset = dynamic_offset or bool(native_history.get("hasDynamicOffsets"))

    reasons: set[str] = set()
    origin_features: set[str] = set()
    if dynamic_offset:
        reasons.add("dynamic-history-offset")
    if re.search(r"\b(?:var|varip)\b", code):
        reasons.add("persistent-state")
    if re.search(r":=|\+=|-=|\*=|/=|%=", code):
        reasons.add("series-reassignment")
    if re.search(r"\b(?:bar_index|last_bar_index)\b", code):
        reasons.add("dataset-index")
    if re.search(r"\bbarstate\s*\.\s*isfirst\b", code):
        reasons.add("dataset-origin")
    if re.search(r"\bfixnan\s*\(", code):
        reasons.add("stateful-core")

    features = _supported_features(analysis, code)
    ta_features = {feature for feature in features if feature.startswith("ta.")}
    constants = _input_constants(code, analysis, params)
    bounded_ta_warmup = 0
    for feature in sorted(ta_features):
        if feature in _STATEFUL_TA_FEATURES:
            origin_features.add(feature)
            continue
        if feature in _BOUNDED_TA_FIXED_WARMUP:
            bounded_ta_warmup += _BOUNDED_TA_FIXED_WARMUP[feature]
            continue
        if feature not in _BOUNDED_TA_LENGTH_ARGS:
            origin_features.add(feature)
            continue
        calls = list(_iter_calls(code, _source_names_for_feature(feature, analysis)))
        if not calls:
            origin_features.add(feature)
            continue
        for _, _, _, body in calls:
            call_warmup = _bounded_ta_call_warmup(feature, body, constants)
            if call_warmup is None:
                origin_features.add(feature)
                break
            bounded_ta_warmup += call_warmup

    if origin_features:
        reasons.add("stateful-or-dynamic-ta")
    if bool(native_history.get("requiresFullHistory")):
        reasons.add("runtime-full-history")

    requires_origin = bool(reasons)
    finite_warmup = max(declared_max, max_offset + bounded_ta_warmup)
    return PineHistoryPlan(
        mode=(PINE_HISTORY_MODE_AVAILABLE if requires_origin else PINE_HISTORY_MODE_BOUNDED),
        warmup_bars=finite_warmup,
        max_constant_offset=max_offset,
        has_dynamic_offsets=dynamic_offset,
        reasons=tuple(sorted(reasons)),
        features=tuple(sorted(origin_features)),
    )


__all__ = [
    "PINE_HISTORY_MODE_AVAILABLE",
    "PINE_HISTORY_MODE_BOUNDED",
    "PINE_HISTORY_PLAN_SCHEMA_VERSION",
    "PineHistoryPlan",
    "plan_pine_history",
]
