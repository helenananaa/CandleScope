"""Small, rebuildable calculation checkpoints; no account or chart-window state."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import deque
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from app.indicator.base import Indicator
from app.indicator.indicators.atr import ATRIndicator
from app.indicator.indicators.boll import BOLLIndicator
from app.indicator.indicators.ema import EMAIndicator
from app.indicator.indicators.ma import MAIndicator
from app.indicator.indicators.macd import MACDIndicator
from app.indicator.indicators.rsi import RSIIndicator
from app.indicator.indicators.vol import VOLIndicator
from app.indicator.script_identity import object_source_hash
from app.indicator.window_math import window_mean
from app.replay.canonical import canonical_sha256

BUILTINS = {
    "MA": MAIndicator,
    "EMA": EMAIndicator,
    "RSI": RSIIndicator,
    "ATR": ATRIndicator,
    "MACD": MACDIndicator,
    "BOLL": BOLLIndicator,
    "VOL": VOLIndicator,
}
# Constructor configuration always comes from the requested, keyed parameters.
# Persist only recursive/rolling mathematical state, never arbitrary attributes.
FIELDS = {
    "MA": ("_window",),
    "EMA": ("_ema", "_count", "_sum"),
    "RSI": (
        "_avg_gain",
        "_avg_loss",
        "_prev_val",
        "_count",
        "_init_gains",
        "_init_losses",
    ),
    "ATR": ("_atr", "_prev_close", "_count", "_tr_sum"),
    "MACD": (
        "_fast_ema",
        "_slow_ema",
        "_signal_ema",
        "_count",
        "_fast_sum",
        "_slow_sum",
        "_signal_count",
        "_signal_sum",
    ),
    "BOLL": ("_window",),
    "VOL": (),
}
SCHEMA = "replay.indicator-checkpoint.v1"


def normalized_parameters(name: str, params: dict) -> dict:
    spec = BUILTINS[name].get_spec()
    schema = {field.key: field for field in spec.param_schema}
    if not isinstance(params, dict) or set(params) - schema.keys():
        raise ValueError("unsupported canonical indicator parameters")
    values = {**spec.default_params, **params}
    for key, field in schema.items():
        value = values.get(key, field.default)
        if field.type in {"int", "float"}:
            _number(value)
            if field.type == "int":
                if value != int(value):
                    raise ValueError("indicator period must be an integer")
                value = int(value)
            else:
                value = float(value)
            if (field.min is not None and value < field.min) or (
                field.max is not None and value > field.max
            ):
                raise ValueError("indicator parameter is out of range")
        elif field.type in {"string", "color"}:
            if not isinstance(value, str) or len(value) > 512:
                raise ValueError("invalid indicator text parameter")
        if field.options is not None and value not in field.options:
            raise ValueError("invalid indicator parameter option")
        values[key] = value
    return values


def new_indicator(name: str, params: dict) -> Indicator:
    instance = BUILTINS[name](dict(params))
    # Prefix calculation retains one output solely for the builtin lifecycle;
    # its mathematical state is independent of that bounded render history.
    instance.retain_outputs(1)
    instance.init([])
    return instance


def checkpoint_key(identity: dict, name: str, params: dict) -> str:
    return canonical_sha256(
        {
            "schema": SCHEMA,
            "source": identity,
            "name": name,
            "params": {
                key: Decimal(str(value)) if type(value) is float else value
                for key, value in params.items()
            },
            "implementation": object_source_hash(BUILTINS[name], length=64),
            "base_implementation": object_source_hash(Indicator, length=64),
            **({"window_implementation": object_source_hash(window_mean, length=64)}
               if name in {"MA", "BOLL"} else {}),
        }
    )


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("invalid indicator checkpoint number")
    return value


def dump_state(instance: Indicator) -> dict:
    fields = {}
    for field in (*FIELDS[instance.name], "_bar_count"):
        value = getattr(instance, field)
        if isinstance(value, (list, deque)):
            fields[field] = [_number(item) for item in value]
        else:
            fields[field] = None if value is None else _number(value)
    return fields


def restore_state(name: str, params: dict, fields: dict) -> Indicator:
    instance = new_indicator(name, params)
    if set(fields) != {*FIELDS[name], "_bar_count"}:
        raise ValueError("indicator checkpoint fields changed")
    for field, value in fields.items():
        fresh = getattr(instance, field)
        if isinstance(fresh, (list, deque)):
            limit = int(getattr(instance, "_period", 500))
            if not isinstance(value, list) or len(value) > limit:
                raise ValueError("indicator checkpoint window is invalid")
            values = [_number(item) for item in value]
            value = (
                deque(values, maxlen=fresh.maxlen)
                if isinstance(fresh, deque)
                else values
            )
        elif value is None:
            if fresh is not None:
                raise ValueError("indicator checkpoint accumulator is missing")
        else:
            _number(value)
            if type(fresh) is int and (type(value) is not int or value < 0):
                raise ValueError("indicator checkpoint count is invalid")
        setattr(instance, field, value)
    return instance


def discard_prefix_graphics(instance: Indicator) -> None:
    """Color histories are auxiliary lists in the builtin implementations."""
    for field in ("_hist_color_data", "_color_data"):
        if hasattr(instance, field):
            getattr(instance, field).clear()


class IndicatorCheckpointStore:
    """A separate bounded derived-data database, safe to discard and rebuild.

    Each operation uses its own connection. No replay account writer, live
    actor, or transaction is held during history reads or indicator evaluation.
    """

    def __init__(self, path: Path, *, max_entries: int = 512) -> None:
        self.path = path
        self.max_entries = max(1, max_entries)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                identity TEXT NOT NULL, before_ms INTEGER NOT NULL,
                body TEXT NOT NULL, touched_ns INTEGER NOT NULL,
                PRIMARY KEY (identity, before_ms))""")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def load(self, identity: str, before_ms: int, origin_ms: int):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT before_ms, body FROM checkpoints WHERE identity=? AND before_ms<=? AND before_ms>=? ORDER BY before_ms DESC LIMIT 1",
                (identity, before_ms, origin_ms),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE checkpoints SET touched_ns=? WHERE identity=? AND before_ms=?",
                (time.time_ns(), identity, row[0]),
            )
        try:
            body = json.loads(row[1])
            if not isinstance(body, dict) or set(body) != {
                "schema",
                "identity",
                "before_ms",
                "last_close_ms",
                "state",
            }:
                raise ValueError("invalid checkpoint envelope")
            if (
                body["schema"] != SCHEMA
                or body["identity"] != identity
                or body["before_ms"] != row[0]
            ):
                raise ValueError("invalid checkpoint identity")
            last = body["last_close_ms"]
            if last is not None and (
                type(last) is not int or last < origin_ms or last >= row[0]
            ):
                raise ValueError("invalid checkpoint boundary")
            return body
        except (ValueError, TypeError):
            self.discard(identity, row[0])
            return None

    def save(
        self, identity: str, before_ms: int, last_close_ms: int | None, state: dict
    ) -> None:
        body = json.dumps(
            {
                "schema": SCHEMA,
                "identity": identity,
                "before_ms": before_ms,
                "last_close_ms": last_close_ms,
                "state": state,
            },
            allow_nan=False,
            separators=(",", ":"),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?, ?)",
                (identity, before_ms, body, time.time_ns()),
            )
            conn.execute(
                "DELETE FROM checkpoints WHERE rowid IN (SELECT rowid FROM checkpoints ORDER BY touched_ns DESC LIMIT -1 OFFSET ?)",
                (self.max_entries,),
            )

    def discard(self, identity: str, before_ms: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM checkpoints WHERE identity=? AND before_ms=?",
                (identity, before_ms),
            )
