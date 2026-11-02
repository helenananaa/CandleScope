"""Static declarations and strict values for python.indicator.batch/1.

Analysis never executes an author's module. Execution belongs to a fresh worker,
not this module or the host backend. Columns are position-aligned to the exact
input snapshot; no timestamp guessing or automatic future-dependency detection.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping

SCHEMA = "python.indicator.batch/1"
MAX_SOURCE_BYTES = 128 * 1024
MAX_BARS = 10000
MAX_OUTPUTS = 16
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
OUTPUT_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")


class AuthorError(ValueError):
    def __init__(self, message, *, line=None, column=None):
        super().__init__(message)
        self.line, self.column = line, column


def only_keys(value, allowed, label):
    if not isinstance(value, dict) or set(value) - allowed:
        raise AuthorError(f"{label} must be an object with supported fields only")


@dataclass(frozen=True)
class Declaration:
    name: str
    overlay: bool
    window: int
    parameters: tuple[dict, ...]
    outputs: tuple[dict, ...]

    def to_wire(self):
        return dict(schema=SCHEMA, name=self.name, overlay=self.overlay, window=self.window,
                    parameters=[dict(p) for p in self.parameters],
                    outputs=[dict(p) for p in self.outputs],
                    execution="fresh-process-batch", dependencyProfile="stdlib",
                    causality="unverified", recovery="reseed")


def analyze(source: str) -> Declaration:
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise AuthorError("Source exceeds 128 KiB")
    try:
        tree = ast.parse(source, filename="indicator.py")
    except SyntaxError as exc:
        raise AuthorError(exc.msg, line=exc.lineno, column=exc.offset) from exc
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "compute"]
    if len(functions) != 1:
        raise AuthorError("Define exactly one ordinary compute(bars, params) function")
    function = functions[0]
    args = function.args
    if (isinstance(function, ast.AsyncFunctionDef) or function.decorator_list
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults
            or [arg.arg for arg in args.args] != ["bars", "params"]):
        raise AuthorError("Use the undecorated signature compute(bars, params)", line=function.lineno)
    declarations = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "INDICATOR" for t in node.targets):
            if len(node.targets) != 1:
                raise AuthorError("INDICATOR must have its own literal assignment", line=node.lineno)
            declarations.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "INDICATOR":
            declarations.append(node)
    if len(declarations) > 1:
        raise AuthorError("Duplicate INDICATOR declaration")
    try:
        meta = ast.literal_eval(declarations[0].value) if declarations else {}
    except (ValueError, TypeError, SyntaxError, RecursionError) as exc:
        raise AuthorError("INDICATOR must be literal data; analysis does not execute Python") from exc
    only_keys(meta, {"name", "overlay", "window", "parameters", "outputs"}, "INDICATOR")
    name, overlay, window = meta.get("name", "Python Indicator"), meta.get("overlay", True), meta.get("window", 500)
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise AuthorError("Indicator name must contain 1..128 characters")
    if type(overlay) is not bool or type(window) is not int or not 1 <= window <= MAX_BARS:
        raise AuthorError("overlay must be boolean and window must be 1..10000")
    parameters = meta.get("parameters", [])
    outputs = meta.get("outputs", [{"id": "main", "title": "Value", "type": "line"}])
    if not isinstance(parameters, list) or len(parameters) > 32:
        raise AuthorError("At most 32 parameters are supported")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= MAX_OUTPUTS:
        raise AuthorError("Declare 1..16 outputs")
    seen = set()
    for param in parameters:
        only_keys(param, {"name", "title", "type", "default", "min", "max", "step"}, "parameter")
        key, kind = param.get("name"), param.get("type")
        if not isinstance(key, str) or not IDENTIFIER.fullmatch(key) or key in seen:
            raise AuthorError("Parameter names must be unique identifiers")
        seen.add(key)
        if kind not in {"int", "float", "bool", "string"} or "default" not in param:
            raise AuthorError("Parameter requires a supported type and default")
        for field in ("min", "max", "step"):
            if field in param and (kind not in {"int", "float"} or not finite(param[field])):
                raise AuthorError("Numeric parameter bounds must be finite numbers")
        if "min" in param and "max" in param and param["min"] > param["max"]:
            raise AuthorError("Parameter min exceeds max")
        if "step" in param and param["step"] <= 0:
            raise AuthorError("Parameter step must be positive")
        validate_parameter(param, param["default"])
    seen = set()
    for output in outputs:
        only_keys(output, {"id", "title", "type", "color"}, "output")
        key = output.get("id")
        if not isinstance(key, str) or not OUTPUT_ID.fullmatch(key) or key in seen:
            raise AuthorError("Output IDs must be unique lowercase public render identifiers")
        seen.add(key)
        if output.get("type", "line") not in {"line", "histogram"}:
            raise AuthorError("Output type must be line or histogram")
        if "title" in output and (not isinstance(output["title"], str) or len(output["title"]) > 128):
            raise AuthorError("Output title must be a short string")
        if "color" in output and (not isinstance(output["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", output["color"])):
            raise AuthorError("Output color must be #RRGGBB")
    return Declaration(name, overlay, window, tuple(dict(p) for p in parameters), tuple(dict(p) for p in outputs))


def finite(value):
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


def validate_parameter(spec, value):
    kind = spec["type"]
    valid = ((kind == "int" and type(value) is int)
             or (kind == "float" and finite(value))
             or (kind == "bool" and type(value) is bool)
             or (kind == "string" and isinstance(value, str) and len(value) <= 1024))
    if not valid or (kind == "int" and not -(2**53) < value < 2**53):
        raise AuthorError(f"Invalid value for parameter {spec['name']}")
    if kind in {"int", "float"}:
        if ("min" in spec and value < spec["min"]) or ("max" in spec and value > spec["max"]):
            raise AuthorError(f"Parameter {spec['name']} is outside declared bounds")
    return value


def parameters(declaration, values):
    if not isinstance(values, dict) or set(values) - {p["name"] for p in declaration.parameters}:
        raise AuthorError("Unknown parameter fields")
    return MappingProxyType({p["name"]: validate_parameter(p, values.get(p["name"], p["default"]))
                             for p in declaration.parameters})


def columns(rows):
    if not isinstance(rows, (tuple, list)) or len(rows) > MAX_BARS:
        raise AuthorError("Input exceeds 10000 bars")
    previous = None
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("time")) is not int
                or (previous is not None and row["time"] <= previous)
                or any(not finite(row.get(k)) for k in ("open", "high", "low", "close", "volume"))
                or type(row.get("isClosed", True)) is not bool):
            raise AuthorError("Input requires strictly ordered unique standard OHLCV bars")
        previous = row["time"]
    return MappingProxyType({k: tuple(row.get(k, True) for row in rows)
                             for k in ("time", "open", "high", "low", "close", "volume", "isClosed")})


def output_columns(declaration, result, length):
    if not isinstance(result, Mapping) or set(result) != {"lines"} or not isinstance(result["lines"], Mapping):
        raise AuthorError("Return {'lines': {output_id: aligned_values}}")
    values = result["lines"]
    if set(values) != {o["id"] for o in declaration.outputs}:
        raise AuthorError("Returned output IDs differ from declarations")
    normalized = {}
    for key, data in values.items():
        if not isinstance(data, (tuple, list)) or len(data) != length:
            raise AuthorError("Every output must align exactly to input length")
        if any(value is not None and not finite(value) for value in data):
            raise AuthorError("Output values must be finite numbers or None for warmup")
        normalized[key] = list(data)
    return normalized
