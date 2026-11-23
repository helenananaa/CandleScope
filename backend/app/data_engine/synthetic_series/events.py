"""Causal observations for special-chart strategies over observed prices.

Price-event charts advance on the actual observed path. HA retains a forming
source bar. No order/account/matching ownership belongs to this cursor.
"""

from copy import deepcopy
import math

from .core import (
    SyntheticKernel,
    SyntheticConfig,
    SyntheticError,
    normalize_source,
    resolve_options,
    _round,
)
from .signals import normalize_signal_chart, ChartSignalSeries

CONTRACT = "candlescope.chart-signal-events/1"


class ChartEventSeries:
    def __init__(self, definition):
        self.definition = normalize_signal_chart(definition)
        if self.definition is None:
            raise SyntheticError("chart event definition required")
        self.source = ChartSignalSeries(self.definition)
        self.kernel = SyntheticKernel(self.source.config)
        self.math = self.kernel._initial()
        self.tick = self.source.tick
        self.count = self.source_count = 0
        self.active = None
        self.column = None
        self.pending = []
        self.last_key = None
        self.last_time = None

    def _row(self, payload):
        return normalize_source(
            dict(
                time=int(payload["open_time_ms"]) // 1000,
                **{key: payload[key] for key in ("open", "high", "low", "close", "volume")},
                is_closed=True
            )
        )

    def _options(self, row):
        config = self.source.config
        if config.transform == "heikin-ashi":
            return
        if self.tick is None:
            self.tick = resolve_options(config, [row])["min_tick"]
        options = resolve_options(
            SyntheticConfig(
                **{
                    **{
                        k: self.definition[k]
                        for k in (
                            "transform",
                            "mode",
                            "box_size",
                            "min_tick",
                            "atr_length",
                            "reversal_amount",
                            "number_of_lines",
                        )
                    },
                    "mode": "traditional",
                    "min_tick": self.tick,
                }
            ),
            [row],
        )
        if config.mode == "atr" and config.transform != "line-break":
            tr = max(
                row["high"] - row["low"],
                (
                    abs(row["high"] - self.source.previous_close)
                    if self.source.previous_close is not None
                    else 0
                ),
                (
                    abs(row["low"] - self.source.previous_close)
                    if self.source.previous_close is not None
                    else 0
                ),
            )
            n = self.source.atr_count
            atr = (
                (self.source.atr_sum + tr) / (n + 1)
                if n < config.atr_length
                else (self.source.atr * (config.atr_length - 1) + tr) / config.atr_length
            )
            amount = atr or max(self.tick, row["close"] * 0.005)
            ticks = max(1, _round(amount / self.tick))
            options.update(box_ticks=ticks, box_size=round(ticks * self.tick, 8))
        self.kernel.options = options

    def _bar(self, point, time_ms, *, volume=0):
        return dict(
            open_time_ms=time_ms,
            **{k: str(point[k]) for k in ("open", "high", "low", "close")},
            volume=str(volume),
            is_closed=False
        )

    def _confirm(self, bar, at):
        self.pending.append(
            dict(
                ordinal=self.count,
                bar={**bar, "close_time_ms": at, "is_closed": True},
                confirmed=True,
                available_time_ms=at,
            )
        )
        self.count += 1
        self.active = None

    def update(self, payload, at, key, *, quantity):
        """Observe a market event once, including when fills reenter its clock."""
        if self.last_key == key:
            return
        if (
            type(key) is not int
            or (self.last_key is not None and key <= self.last_key)
            or type(at) is not int
            or (self.last_time is not None and at < self.last_time)
        ):
            raise SyntheticError("chart event clock moved backward")
        previous = self.snapshot()
        try:
            self._update(payload, at, key, quantity)
        except Exception:
            self.restore(previous)
            raise

    def _update(self, payload, at, key, quantity):
        row = self._row(payload)
        qty = float(quantity)
        if not math.isfinite(qty) or qty < 0 or row["time"] * 1000 > at:
            raise SyntheticError("invalid revealed chart event")
        self._options(row)
        transform = self.source.config.transform
        opened = self.active["open_time_ms"] if self.active is not None else at
        volume = (float(self.active["volume"]) if self.active else 0) + qty
        if transform == "heikin-ashi":
            point = self.kernel._step(deepcopy(self.math), row, True)[0]
            self.active = self._bar(point, payload["open_time_ms"], volume=row.get("volume", 0))
        else:
            # ATR uses the visible source prefix. Event-chart price steps consume
            # the actual observed close, without the eventual source OHLC path.
            price_row = {**row, "time": at // 1000}
            points = self.kernel._step(self.math, price_row, False)
            if transform in {"point-and-figure", "kagi"}:
                if points:
                    point = points[0]
                    column = point["time"]["order"]
                    if self.column is not None and column != self.column:
                        self._confirm(self.active, at)
                        opened, volume = at, qty
                    self.active = self._bar(point, opened, volume=volume)
                    self.column = column
                elif self.active is not None:
                    self.active = {**self.active, "volume": str(volume)}
            elif points:
                for point in points:
                    self._confirm(self._bar(point, opened, volume=volume / len(points)), at)
                    opened = at
                volume = 0
            if self.active is None:
                anchor = self.math["last"]
                opening = (
                    points[-1]["close"]
                    if points
                    else row["close"] if anchor is None else self.kernel._price(anchor)
                )
                self.active = self._bar(
                    dict(
                        open=opening,
                        high=max(opening, row["close"]),
                        low=min(opening, row["close"]),
                        close=row["close"],
                    ),
                    opened,
                    volume=volume,
                )
            elif transform not in {"point-and-figure", "kagi"}:
                self.active = {
                    **self.active,
                    "high": str(max(float(self.active["high"]), row["close"])),
                    "low": str(min(float(self.active["low"]), row["close"])),
                    "close": str(row["close"]),
                    "volume": str(volume),
                }
        self.last_key, self.last_time = key, at

    def close_source(self, payload, at):
        row = self._row(payload)
        if self.source.previous_time is not None and row["time"] <= self.source.previous_time:
            raise SyntheticError("chart source close revision/order changed")
        if int(payload["close_time_ms"]) > at:
            raise SyntheticError("source close is not revealed")
        if self.source.config.transform == "heikin-ashi":
            point = self.kernel._step(self.math, row, False)[0]
            self._confirm(
                self._bar(point, payload["open_time_ms"], volume=row.get("volume", 0)), at
            )
        tr = max(
            row["high"] - row["low"],
            (
                abs(row["high"] - self.source.previous_close)
                if self.source.previous_close is not None
                else 0
            ),
            (
                abs(row["low"] - self.source.previous_close)
                if self.source.previous_close is not None
                else 0
            ),
        )
        self.source.atr_count += 1
        length = self.source.config.atr_length
        if self.source.atr_count <= length:
            self.source.atr_sum += tr
            self.source.atr = self.source.atr_sum / self.source.atr_count
        else:
            self.source.atr = (self.source.atr * (length - 1) + tr) / length
        self.source.previous_time, self.source.previous_close = row["time"], row["close"]
        self.source.source_count += 1
        self.source_count += 1

    def observations(self, at, *, preview):
        pending, self.pending = self.pending, []
        yield from pending
        if preview and self.active is not None:
            yield dict(
                ordinal=self.count,
                bar={**self.active, "close_time_ms": at, "is_closed": False},
                confirmed=False,
                available_time_ms=at,
            )

    def snapshot(self):
        return deepcopy(
            dict(
                contract=CONTRACT,
                definition=self.definition,
                math=self.math,
                tick=self.tick,
                count=self.count,
                source_count=self.source_count,
                source=self.source.snapshot(),
                active=self.active,
                column=self.column,
                pending=self.pending,
                last_key=self.last_key,
                last_time=self.last_time,
            )
        )

    def restore(self, value):
        if (
            not isinstance(value, dict)
            or value.get("contract") != CONTRACT
            or value.get("definition") != self.definition
        ):
            raise SyntheticError("chart event checkpoint identity changed")
        if (
            type(value.get("count")) is not int
            or value["count"] < 0
            or not isinstance(value.get("pending"), list)
            or len(value["pending"]) > 10000
        ):
            raise SyntheticError("invalid chart event checkpoint")
        self.source.restore(value["source"])
        for name in (
            "math",
            "tick",
            "count",
            "source_count",
            "active",
            "column",
            "pending",
            "last_key",
            "last_time",
        ):
            setattr(self, name, deepcopy(value[name]))
