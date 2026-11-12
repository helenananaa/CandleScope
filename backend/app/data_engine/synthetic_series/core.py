"""Pure close-source synthetic transforms.

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
ALGORITHM_VERSION = "close-source/2"
TRANSFORMS = ("heikin-ashi", "renko", "point-and-figure", "kagi", "line-break")


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
    base = math.floor(value)
    return base + int(value - base >= 0.5)


@dataclass(frozen=True)
class SyntheticConfig:
    transform: str
    semantics: str = "display-window/1"
    mode: str = "traditional"
    box_size: float = 1.0
    min_tick: float | None = None
    atr_length: int = 14
    reversal_amount: float = 3
    number_of_lines: int = 3

    def __post_init__(self):
        if self.transform not in TRANSFORMS:
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
        object.__setattr__(self, "reversal_amount", _positive(self.reversal_amount, "reversal_amount"))
        if self.transform == "point-and-figure" and (
                not self.reversal_amount.is_integer() or self.reversal_amount > 100):
            raise SyntheticError("Point & Figure reversal_amount must be an integer between 1 and 100")
        if isinstance(self.number_of_lines, bool) or not isinstance(self.number_of_lines, int) or not 1 <= self.number_of_lines <= 50:
            raise SyntheticError("number_of_lines must be an integer between 1 and 50")
        if self.semantics == "anchored/1" and self.transform != "heikin-ashi":
            if self.mode != "traditional" or self.min_tick is None:
                raise SyntheticError("anchored synthetic series requires fixed parameters and min_tick")

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
    preferred = config.reversal_amount if config.transform == "kagi" else config.box_size
    values = ([row["close"] for row in rows] if config.transform == "line-break"
        else [preferred, *(row[field] for row in rows for field in ("open", "high", "low", "close"))])
    for value in values:
        if value > 0:
            precision = max(precision, min(8, max(0, -Decimal(str(value)).normalize().as_tuple().exponent)))
    tick = config.min_tick or 10 ** -precision
    if config.transform == "line-break":
        return {"min_tick": tick, "number_of_lines": config.number_of_lines}
    box = preferred
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
        box = atr or max(tick, (previous or preferred) * 0.005)
    ratio = box / tick
    ticks = max(1, _round(ratio))
    if config.semantics == "anchored/1" and abs(ratio - ticks) > math.ulp(1.0) * max(16, abs(ratio) * 16):
        raise SyntheticError("box_size must be an integer multiple of min_tick")
    options = {"min_tick": tick, "box_ticks": ticks, "box_size": round(ticks * tick, 8)}
    if config.transform == "point-and-figure":
        options["reversal_amount"] = int(config.reversal_amount)
    return options


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
        self._snapshot_only = False

    def _initial(self):
        return {"last": None, "direction": None, "pending": None, "order": 0,
            "active": None, "style": "yin", "shoulder": None, "waist": None, "window": []}

    def _price(self, ticks):
        return round(ticks * self.options["min_tick"], 8)

    def _point(self, state, row, opening, close, values, field, *, order=None, source_from=None):
        return {"time": {"order": state["order"] if order is None else order,
            "sourceTime": row["time"], "sourceOrdinal": 0},
            "open": self._price(opening), "close": self._price(close),
            "high": self._price(max(opening, close)), "low": self._price(min(opening, close)),
            "customValues": {field: values, "chartProjection": {
                "sourceFromTime": row["time"] if source_from is None else source_from,
                "sourceOrdinal": 0}}}

    def _point_figure(self, state, row):
        price = _round(row["close"] / self.options["min_tick"])
        box = self.options["box_ticks"]
        if state["last"] is None:
            state.update(last=math.floor(price / box) * box, pending=row["time"])
            return []
        active = state["active"]
        direction = state["direction"]
        low = high = None
        new = False
        if active is None:
            if abs(price - state["last"]) < box:
                return []
            direction = "x" if price > state["last"] else "o"
            distance = math.floor(abs(price - state["last"]) / box) * box
            low, high = ((state["last"] + box, state["last"] + distance) if direction == "x"
                else (state["last"] - distance, state["last"] - box))
            new = True
        else:
            low, high = active["low"], active["high"]
            if direction == "x":
                if price >= high + box:
                    high += math.floor((price - high) / box) * box
                elif price <= high - self.options["reversal_amount"] * box:
                    low, high = high - math.floor((high - price) / box) * box, high - box
                    direction, new = "o", True
                else:
                    return []
            else:
                if price <= low - box:
                    low -= math.floor((low - price) / box) * box
                elif price >= low + self.options["reversal_amount"] * box:
                    low, high = low + box, low + math.floor((price - low) / box) * box
                    direction, new = "x", True
                else:
                    return []
        if (high - low) // box + 1 > MAX_BRICKS_PER_SOURCE:
            raise SyntheticError("Point & Figure column exceeds glyph budget")
        if new:
            active = {"order": state["order"], "from": active["time"] if active else state["pending"]}
            state["order"] += 1
        else:
            active = dict(active)
        active.update(low=low, high=high, time=row["time"])
        state.update(active=active, direction=direction)
        opening, closing = (low, high) if direction == "x" else (high, low)
        return [self._point(state, row, opening, closing,
            {"direction": direction, "boxSize": self.options["box_size"],
                "reversalAmount": self.options["reversal_amount"], "source": "close"},
            "pointAndFigure", order=active["order"], source_from=active["from"])]

    def _kagi_sections(self, state, active):
        opening, close, style = active["open"], active["close"], active["start_style"]
        boundary, next_style = None, style
        if state["direction"] == "up" and style == "yin" and state["shoulder"] is not None and close > state["shoulder"]:
            boundary, next_style = state["shoulder"], "yang"
        elif state["direction"] == "down" and style == "yang" and state["waist"] is not None and close < state["waist"]:
            boundary, next_style = state["waist"], "yin"
        if boundary is None:
            return [{"from": self._price(opening), "to": self._price(close), "style": style}], style
        sections = []
        if opening != boundary:
            sections.append({"from": self._price(opening), "to": self._price(boundary), "style": style})
        sections.append({"from": self._price(boundary), "to": self._price(close), "style": next_style})
        return sections, next_style

    def _kagi(self, state, row):
        price = _round(row["close"] / self.options["min_tick"])
        if state["last"] is None:
            state.update(last=price, pending=row["time"])
            return []
        active = state["active"]
        direction = state["direction"]
        kind, turn = None, None
        new = active is None
        if new:
            opening = state["last"]
            if abs(price - opening) < self.options["box_ticks"]:
                return []
            direction = "up" if price > opening else "down"
        else:
            opening = active["open"]
            closing = active["close"]
            extends = price > closing if direction == "up" else price < closing
            if not extends:
                if abs(price - closing) < self.options["box_ticks"]:
                    return []
                new, opening, turn = True, closing, closing
                if direction == "up":
                    state["shoulder"], direction, kind = turn, "down", "shoulder"
                else:
                    state["waist"], direction, kind = turn, "up", "waist"
        if new:
            active = {"order": state["order"], "open": opening,
                "from": active["time"] if active else state["pending"],
                "kind": kind, "turn": turn, "start_style": state["style"]}
            state["order"] += 1
        else:
            active = dict(active)
        active.update(close=price, time=row["time"])
        state.update(active=active, direction=direction)
        sections, style = self._kagi_sections(state, active)
        state["style"] = style
        return [self._point(state, row, active["open"], price,
            {"direction": direction, "state": style, "reversalKind": active["kind"],
                "turnPrice": self._price(active["turn"]) if active["turn"] is not None else None,
                "reversalAmount": self.options["box_size"], "reversalTicks": self.options["box_ticks"],
                "source": "close", "sections": sections}, "kagi",
            order=active["order"], source_from=active["from"])]

    def _line_break(self, state, row):
        price = _round(row["close"] / self.options["min_tick"])
        if state["last"] is None:
            state.update(last=price, pending=row["time"])
            return []
        window = state["window"]
        reference_high = max(item["high"] for item in window) if window else state["last"]
        reference_low = min(item["low"] for item in window) if window else state["last"]
        if price <= reference_high and price >= reference_low:
            return []
        direction = "up" if price > reference_high else "down"
        opening = (window[-1]["high"] if direction == "up" else window[-1]["low"]) if window else state["last"]
        point = self._point(state, row, opening, price,
            {"direction": direction, "numberOfLines": self.config.number_of_lines, "source": "close",
                "referenceHigh": self._price(reference_high), "referenceLow": self._price(reference_low)},
            "lineBreak", source_from=window[-1]["time"] if window else state["pending"])
        state["order"] += 1
        state["window"] = [*window, {"high": max(opening, price), "low": min(opening, price),
            "time": row["time"]}][-self.config.number_of_lines:]
        return [point]

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
        elif self.config.transform == "point-and-figure":
            points = self._point_figure(state, row)
        elif self.config.transform == "kagi":
            points = self._kagi(state, row)
        elif self.config.transform == "line-break":
            points = self._line_break(state, row)
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

    @staticmethod
    def _merge(output, points):
        for point in points:
            if (output and isinstance(point["time"], dict) and
                    point["time"]["order"] == output[-1]["time"]["order"]):
                output[-1] = point
            else:
                output.append(point)

    def _calculate(self, rows, *, reset):
        state = self._initial() if reset else deepcopy(self._state)
        confirmed = [] if reset else list(self._confirmed_output)
        count = 0 if reset else self._confirmed_count
        for row in rows[count:]:
            if not row["is_closed"]:
                break
            self._merge(confirmed, self._step(state, row, False))
            count += 1
            if len(confirmed) > MAX_OUTPUT_ROWS:
                raise SyntheticError("synthetic output budget exceeded")
        output = list(confirmed)
        if count < len(rows):
            self._merge(output, self._step(deepcopy(state), rows[count], True))
        if len(output) > MAX_OUTPUT_ROWS:
            raise SyntheticError("synthetic output budget exceeded")
        return state, confirmed, count, output

    def _with_volume(self, output, source):
        if self.config.transform == "heikin-ashi" or not output:
            return output
        # Source volume waits for the next emitted display group, then divides
        # evenly among that group's records. Never duplicate one candle's full
        # volume on every same-time brick. Unemitted trailing volume stays pending.
        groups = []
        for index, point in enumerate(output):
            time = point["customValues"]["chartProjection"]["sourceToTime"]
            if not groups or groups[-1][0] != time:
                groups.append([time, [index], 0.0])
            else:
                groups[-1][1].append(index)
        at = 0
        for row in source:
            while at < len(groups) and row["time"] > groups[at][0]:
                at += 1
            if at == len(groups):
                break
            groups[at][2] += row.get("volume", 0)
        result = list(output)
        for _, indexes, volume in groups:
            for index in indexes:
                result[index] = {**output[index], "volume": volume / len(indexes)}
        return result

    def replace_snapshot(self, rows):
        """Project a frozen display window, including historical partial buckets.

        A partial oldest tape bucket is immutable source data, not an unfinished
        live candle to discard or silently promote to a trusted close. This
        owner cannot subsequently accept live updates.
        """
        if len(rows) > MAX_SOURCE_ROWS:
            raise SyntheticError("synthetic source budget exceeded")
        source = [normalize_source(row) for row in rows]
        if any(left["time"] >= right["time"] for left, right in zip(source, source[1:])):
            raise SyntheticError("source times must be strictly increasing")
        options, previous_options = resolve_options(self.config, source), self.options
        self.options = options
        output, state = [], self._initial()
        try:
            for row in source:
                self._merge(output, self._step(state, row, not row["is_closed"]))
                if len(output) > MAX_OUTPUT_ROWS:
                    raise SyntheticError("synthetic output budget exceeded")
        except BaseException:
            self.options = previous_options
            raise
        self.source, self.output, self._snapshot_only = source, self._with_volume(output, source), True
        self._state, self._confirmed_output, self._confirmed_count = {}, [], 0
        return self.output

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
        self.source, self.output = source, self._with_volume(result[3], source)
        self._state, self._confirmed_output, self._confirmed_count = result[:3]
        self._snapshot_only = False
        return self.output

    def apply(self, row):
        if self._snapshot_only:
            raise SyntheticError("immutable snapshot kernel cannot accept live updates")
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
        self.source, self.output = source, self._with_volume(result[3], source)
        self._state, self._confirmed_output, self._confirmed_count = result[:3]
        return self.output
