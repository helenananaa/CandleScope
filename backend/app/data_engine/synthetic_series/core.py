"""Pure close-source Renko and Heikin Ashi transforms.

All state belongs to one kernel. Preview is calculated from confirmed state;
it never advances that state. No network, database, React or chart dependency.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from decimal import Decimal
import math


MAX_SOURCE_ROWS = 10_000
MAX_OUTPUT_ROWS = 50_000
MAX_BRICKS_PER_SOURCE = 10_000
ALGORITHM_VERSION = "close-source/1"


class SyntheticError(ValueError):
    pass


def _positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise SyntheticError(f"{name} must be positive and finite")
    return value


def _round(value):
    # Match ECMAScript Math.round, including negative half-ticks.
    if not math.isfinite(value) or abs(value) > 2**53 - 1:
        raise SyntheticError("price exceeds safe integer tick range")
    return math.floor(value + 0.5)


@dataclass(frozen=True)
class SyntheticConfig:
    transform: str
    semantics: str = "display-window/1"
    mode: str = "traditional"
    box_size: float = 1.0
    min_tick: float | None = None
    atr_length: int = 14

    def __post_init__(self):
        if self.transform not in {"renko", "heikin-ashi"}:
            raise SyntheticError("unsupported synthetic transform")
        if self.semantics not in {"display-window/1", "anchored/1"}:
            raise SyntheticError("unsupported synthetic semantics")
        if self.mode not in {"traditional", "atr"}:
            raise SyntheticError("unsupported box size mode")
        object.__setattr__(self, "box_size", _positive(self.box_size, "box_size"))
        if self.min_tick is not None:
            object.__setattr__(self, "min_tick", _positive(self.min_tick, "min_tick"))
        if not 2 <= self.atr_length <= 500:
            raise SyntheticError("atr_length must be between 2 and 500")
        if self.semantics == "anchored/1" and self.transform == "renko":
            if self.mode != "traditional" or self.min_tick is None:
                raise SyntheticError("anchored Renko requires fixed box_size and min_tick")

    def to_dict(self):
        return {**asdict(self), "algorithm": ALGORITHM_VERSION}


def normalize_source(row):
    values = {name: float(row[name]) for name in ("time", "open", "high", "low", "close")}
    if any(not math.isfinite(value) for value in values.values()):
        raise SyntheticError("source OHLC/time must be finite")
    if values["time"] < 0 or not values["time"].is_integer():
        raise SyntheticError("source time must be non-negative Unix seconds")
    if values["high"] < max(values["open"], values["close"], values["low"]) or values["low"] > min(values["open"], values["close"]):
        raise SyntheticError("source OHLC is invalid")
    values["time"] = int(values["time"])
    if "volume" in row and row["volume"] is not None:
        volume = float(row["volume"])
        if not math.isfinite(volume) or volume < 0:
            raise SyntheticError("source volume is invalid")
        values["volume"] = volume
    if not isinstance(row.get("is_closed"), bool):
        raise SyntheticError("source finality must be explicit")
    values["is_closed"] = row["is_closed"]
    return values


def resolve_options(config, rows):
    if config.transform == "heikin-ashi":
        return {}
    precision = 0
    for value in [config.box_size, *(row[field] for row in rows for field in ("open", "high", "low", "close"))]:
        if value > 0:
            precision = max(precision, min(8, max(0, -Decimal(str(value)).normalize().as_tuple().exponent)))
    tick = config.min_tick or 10 ** -precision
    box = config.box_size
    if config.mode == "atr":
        ranges, previous = [], None
        for row in rows:
            ranges.append(max(abs(row["high"] - row["low"]),
                abs(row["high"] - previous) if previous is not None else 0,
                abs(row["low"] - previous) if previous is not None else 0))
            previous = row["close"]
        length = min(config.atr_length, len(ranges))
        atr = sum(ranges[:length]) / length if length else 0
        for value in ranges[length:]:
            atr = (atr * (config.atr_length - 1) + value) / config.atr_length
        box = atr or max(tick, (previous or config.box_size) * 0.005)
    ratio = box / tick
    ticks = max(1, _round(ratio))
    if config.semantics == "anchored/1" and abs(ratio - ticks) > math.ulp(1.0) * max(16, abs(ratio) * 16):
        raise SyntheticError("box_size must be an integer multiple of min_tick")
    return {"min_tick": tick, "box_ticks": ticks, "box_size": round(ticks * tick, 8)}


class SyntheticKernel:
    """Bounded, serial owner. A failed operation never partially commits."""

    def __init__(self, config: SyntheticConfig):
        self.config = config
        self.source = []
        self.output = []
        self.options = {}
        self._state = {}
        self._confirmed_output = []
        self._confirmed_count = 0

    def _initial(self):
        return {"last": None, "direction": None, "pending": None, "order": 0}

    def _step(self, state, row, provisional):
        time = row["time"]
        if self.config.transform == "heikin-ashi":
            close = sum(row[name] for name in ("open", "high", "low", "close")) / 4
            previous = state["last"]
            opening = (previous[0] + previous[1]) / 2 if previous else (row["open"] + row["close"]) / 2
            state["last"] = (opening, close)
            point = {"time": time, "open": opening, "close": close,
                "high": max(row["high"], opening, close), "low": min(row["low"], opening, close)}
            if "volume" in row:
                point["volume"] = row["volume"]
            points = [point]
        else:
            tick, box = self.options["min_tick"], self.options["box_ticks"]
            price = _round(row["close"] / tick)
            if state["last"] is None:
                state["last"] = math.floor(price / box) * box
                state["pending"] = time
            last, direction = state["last"], state["direction"]
            points = []
            ordinal = 0

            def emit(sign, opening):
                nonlocal ordinal
                if ordinal >= MAX_BRICKS_PER_SOURCE:
                    raise SyntheticError("source row exceeds brick budget")
                closing = opening + sign * box
                point = {"time": {"order": state["order"], "sourceTime": time, "sourceOrdinal": ordinal},
                    "open": round(opening * tick, 8), "close": round(closing * tick, 8)}
                point.update(high=max(point["open"], point["close"]), low=min(point["open"], point["close"]))
                point["customValues"] = {"renko": {"direction": "up" if sign == 1 else "down",
                    "boxSize": self.options["box_size"], "source": "close", "wickPolicy": "none"},
                    "chartProjection": {"sourceFromTime": state["pending"], "sourceOrdinal": ordinal}}
                points.append(point)
                state.update(last=closing, direction=sign, pending=time, order=state["order"] + 1)
                ordinal += 1

            sign = 1 if price >= last + box else -1 if price <= last - box else 0
            if sign and direction and sign != direction:
                if abs(price - last) >= 2 * box:
                    emit(sign, last + sign * box)
                else:
                    sign = 0
            if sign:
                while (price - state["last"]) * sign >= box:
                    emit(sign, state["last"])
        for point in points:
            custom = point.setdefault("customValues", {})
            metadata = custom.setdefault("chartProjection", {})
            metadata.update(projectorId=self.config.transform, sourceToTime=time,
                synthetic=True, provisional=provisional)
            metadata.setdefault("sourceFromTime", time)
            metadata.setdefault("sourceOrdinal", 0)
        return points

    def _calculate(self, rows, *, reset):
        state = self._initial() if reset else deepcopy(self._state)
        confirmed = [] if reset else list(self._confirmed_output)
        count = 0 if reset else self._confirmed_count
        for row in rows[count:]:
            if not row["is_closed"]:
                break
            confirmed.extend(self._step(state, row, False))
            count += 1
            if len(confirmed) > MAX_OUTPUT_ROWS:
                raise SyntheticError("synthetic output budget exceeded")
        output = list(confirmed)
        if count < len(rows):
            output.extend(self._step(deepcopy(state), rows[count], True))
        if len(output) > MAX_OUTPUT_ROWS:
            raise SyntheticError("synthetic output budget exceeded")
        return state, confirmed, count, output

    def replace(self, rows):
        if len(rows) > MAX_SOURCE_ROWS:
            raise SyntheticError("synthetic source budget exceeded")
        source = [normalize_source(row) for row in rows]
        if any(left["time"] >= right["time"] for left, right in zip(source, source[1:])):
            raise SyntheticError("source times must be strictly increasing")
        if any(not row["is_closed"] for row in source[:-1]):
            raise SyntheticError("only the source tail may be forming")
        options = resolve_options(self.config, source)
        previous_options = self.options
        self.options = options
        try:
            result = self._calculate(source, reset=True)
        except BaseException:
            self.options = previous_options
            raise
        self.source, self.output = source, result[3]
        self._state, self._confirmed_output, self._confirmed_count = result[:3]
        return self.output

    def apply(self, row):
        row = normalize_source(row)
        source = list(self.source)
        if not source or row["time"] > source[-1]["time"]:
            source.append(row)
        else:
            index = next((i for i, item in enumerate(source) if item["time"] == row["time"]), None)
            if index is None:
                return self.replace(sorted([*source, row], key=lambda item: item["time"]))
            if source[index] == row:
                return self.output
            if source[index]["is_closed"] and not row["is_closed"]:
                return self.output
            source[index] = row
            if index < self._confirmed_count:
                return self.replace(source)
        if len(source) > MAX_SOURCE_ROWS:
            raise SyntheticError("synthetic source budget exceeded")
        if any(not item["is_closed"] for item in source[:-1]):
            raise SyntheticError("missing source confirmation")
        # Window ATR/tick inference explicitly permits historical redraw.
        if resolve_options(self.config, source) != self.options:
            return self.replace(source)
        result = self._calculate(source, reset=False)
        self.source, self.output = source, result[3]
        self._state, self._confirmed_output, self._confirmed_count = result[:3]
        return self.output
