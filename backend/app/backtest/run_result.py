"""One result shape for every strategy run (ADR-BACKTEST-015 §3.7, step P1).

Each execution path keeps its own report; these adapters only *project* it into
``candlescope.run-result/1`` for the chart overlay and result views. Nothing
here re-matches orders or recomputes money: fills, trades and equity are copied
from the engine that owns the account, and ``authority`` says which one that is.

Two normalisations make paths comparable:

- times are milliseconds, and every fill, trade end and equity point also carries
  ``bar_time_ms``, the open time of the bar it belongs to (host kernels stamp the
  bar's close event, the native engine stamps the bar's open in seconds);
- money and quantities are plain decimal strings without exponent or trailing
  zeros (``"107.0"`` and ``107.0`` both become ``"107"``).
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.data_engine.interval_policy import parse_interval_ms

from .reports import build_round_trip_trades

SCHEMA = "candlescope.run-result/1"
DAY_MS = 86_400_000
WORKING_HOST_STATUSES = frozenset({"OPEN", "PARTIAL"})


def decimal_text(value: object) -> str | None:
    """Canonical decimal string, or None for missing and non-finite values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    if number == 0:
        return "0"
    text = format(number.normalize(), "f")
    return text


class BarAnchorRequired(ValueError):
    """The interval does not align with UTC days, so the run's bar open times are needed."""


class BarAnchor:
    """Map an engine timestamp to the open time of the bar containing it."""

    def __init__(self, interval: str, bar_open_times_ms: Sequence[int] | None = None) -> None:
        self.interval = interval
        self._opens = sorted(int(value) for value in bar_open_times_ms) if bar_open_times_ms else None
        width = parse_interval_ms(interval)
        # Flooring by width is only exact when bars align with UTC days.
        self._width = width if width and width <= DAY_MS and DAY_MS % width == 0 else None
        if self._opens is None and self._width is None:
            raise BarAnchorRequired(f"bar open times are required to anchor {interval!r} results")

    def __call__(self, time_ms: int | None) -> int | None:
        if time_ms is None:
            return None
        if self._opens is not None:
            index = bisect_right(self._opens, time_ms) - 1
            return self._opens[index] if index >= 0 else None
        assert self._width is not None
        return time_ms - time_ms % self._width


def _ms(value: object) -> int | None:
    """Engine milliseconds (int) or None."""
    if value is None or isinstance(value, bool):
        return None
    return int(Decimal(str(value)))


def _seconds_ms(value: object) -> int | None:
    """Engine seconds (int or float) to milliseconds, rounded to the nearest ms."""
    if value is None or isinstance(value, bool):
        return None
    return int((Decimal(str(value)) * 1000).to_integral_value())


def _summary(equity: list[dict[str, Any]], trades: list[dict[str, Any]], fills: list[dict[str, Any]]) -> dict[str, Any]:
    initial = Decimal(equity[0]["equity"]) if equity else None
    final = Decimal(equity[-1]["equity"]) if equity else None
    return {
        "initial_equity": decimal_text(initial),
        "final_equity": decimal_text(final),
        "net_profit": decimal_text(final - initial) if initial is not None and final is not None else None,
        "fill_count": len(fills),
        "trade_count": len(trades),
        "winning_trades": sum(1 for trade in trades if Decimal(trade["net_pnl"] or "0") > 0),
    }


def _result(*, source: str, authority: str, clock_policy: str, fidelity: str | None, interval: str,
            fills: list[dict[str, Any]], trades: list[dict[str, Any]], open_position: dict[str, Any] | None,
            pending_orders: list[dict[str, Any]], equity: list[dict[str, Any]],
            plots: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "source": source,
        "authority": authority,
        "clock_policy": clock_policy,
        "fidelity": fidelity,
        "interval": interval,
        "fills": fills,
        "trades": trades,
        "open_position": open_position,
        "pending_orders": pending_orders,
        "equity": equity,
        "plots": plots,
        "summary": _summary(equity, trades, fills),
    }


def _open_position(qty: object, avg_price: object) -> dict[str, Any] | None:
    size = Decimal(str(qty or "0"))
    if size == 0:
        return None
    return {"side": "LONG" if size > 0 else "SHORT", "qty": decimal_text(abs(size)),
            "avg_price": decimal_text(avg_price)}


def _host_fill(fill: Mapping[str, Any], anchor: BarAnchor) -> dict[str, Any]:
    time_ms = _ms(fill.get("event_time_ms"))
    return {
        "time_ms": time_ms,
        "bar_time_ms": anchor(time_ms),
        "side": str(fill["side"]).upper(),
        "qty": decimal_text(fill.get("qty")),
        "price": decimal_text(fill.get("price")),
        "fee": decimal_text(fill.get("fee")),
        "order_id": str(fill["order_id"]) if fill.get("order_id") is not None else None,
        "tag": fill.get("script_order_id") or fill.get("client_tag"),
    }


def _host_pending(orders: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "order_id": str(order.get("order_id")),
        "side": str(order.get("side")).upper(),
        "type": str(order.get("type")).upper(),
        "qty": decimal_text(order.get("qty")),
        "limit_price": decimal_text(order.get("limit_price")),
        "stop_price": decimal_text(order.get("stop_price")),
        "tag": order.get("script_order_id"),
    } for order in orders if str(order.get("status")).upper() in WORKING_HOST_STATUSES]


def from_host_result(result: Mapping[str, Any], *, interval: str, fidelity: str,
                     clock_policy: str = "FIXED", bar_open_times_ms: Sequence[int] | None = None,
                     source: str = "host-kernel") -> dict[str, Any]:
    """Project a host-kernel result: a service run's ``result`` or a continuous kernel result."""
    anchor = BarAnchor(interval, bar_open_times_ms)
    raw_fills = [dict(fill) for fill in result.get("fills") or ()]
    fills = [_host_fill(fill, anchor) for fill in raw_fills]
    trades = []
    for trade in build_round_trip_trades(raw_fills):
        entry, exit_ = _ms(trade["entry_time_ms"]), _ms(trade["exit_time_ms"])
        trades.append({
            "id": trade["trade_id"], "side": trade["side"], "qty": decimal_text(trade["qty"]),
            "entry_time_ms": entry, "entry_bar_time_ms": anchor(entry), "entry_price": decimal_text(trade["entry_price"]),
            "exit_time_ms": exit_, "exit_bar_time_ms": anchor(exit_), "exit_price": decimal_text(trade["exit_price"]),
            "fees": decimal_text(trade["fees"]), "net_pnl": decimal_text(trade["net_pnl"]),
        })
    account = (result.get("ledger") or {}).get("account") or {}
    equity = []
    for point in result.get("equity_curve") or ():
        time_ms = _ms(point.get("event_time_ms"))
        equity.append({"time_ms": time_ms, "bar_time_ms": anchor(time_ms), "equity": decimal_text(point.get("equity"))})
    return _result(source=source, authority="HOST", clock_policy=clock_policy, fidelity=fidelity, interval=interval,
                   fills=fills, trades=trades,
                   open_position=_open_position(account.get("position_qty"), account.get("entry_price")),
                   pending_orders=_host_pending(result.get("orders") or ()), equity=equity, plots=[])


def _plots(graphics: Sequence[Mapping[str, Any]], bar_open_times_ms: Sequence[int]) -> list[dict[str, Any]]:
    """Pine plot series aligned to the report's bars; ``None`` marks a gap."""
    plots = []
    for graphic in graphics:
        values = list(graphic.get("values") or ())
        points = [[bar_open_times_ms[index], value if isinstance(value, (int, float)) and not isinstance(value, bool) else None]
                  for index, value in enumerate(values[:len(bar_open_times_ms)])]
        plots.append({"id": str(graphic.get("id")), "title": graphic.get("title"), "kind": "line",
                      "pane": str(graphic.get("pane") or "main"), "points": points})
    return plots


def _report_bars(report: Mapping[str, Any]) -> list[int]:
    return [_seconds_ms(bar["time"]) for bar in report.get("bars") or ()]


def from_native_report(report: Mapping[str, Any], *, interval: str) -> dict[str, Any]:
    """Project a native Pine report. The engine owns the account (SCRIPT authority)."""
    bar_opens = _report_bars(report)
    anchor = BarAnchor(interval, bar_opens or None)
    fills, position = [], Decimal("0")
    for order in report.get("orders") or ():
        qty = Decimal(str(order.get("qty") or "0"))
        direction = str(order.get("direction"))
        if direction == "strategy.long":
            side = "BUY"
        elif direction == "strategy.short":
            side = "SELL"
        elif direction == "strategy.close":
            side = "SELL" if position > 0 else "BUY"
        else:
            raise ValueError(f"unknown native order direction {direction!r}")
        position += qty if side == "BUY" else -qty
        time_ms = _seconds_ms(order.get("time"))
        fills.append({"time_ms": time_ms, "bar_time_ms": anchor(time_ms), "side": side, "qty": decimal_text(qty),
                      "price": decimal_text(order.get("price")), "fee": None, "order_id": None, "tag": order.get("id")})
    trades = []
    for index, trade in enumerate(report.get("trades") or (), start=1):
        size = Decimal(str(trade.get("qty") or "0"))
        entry, exit_ = _seconds_ms(trade.get("entryTime")), _seconds_ms(trade.get("exitTime"))
        trades.append({
            "id": f"trade-{index}", "side": "LONG" if size >= 0 else "SHORT", "qty": decimal_text(abs(size)),
            "entry_time_ms": entry, "entry_bar_time_ms": anchor(entry), "entry_price": decimal_text(trade.get("entryPrice")),
            "exit_time_ms": exit_, "exit_bar_time_ms": anchor(exit_), "exit_price": decimal_text(trade.get("exitPrice")),
            "fees": None, "net_pnl": decimal_text(trade.get("profit")),
        })
    history = list(report.get("position") or ())
    last = history[-1] if history else {}
    equity = []
    for point in report.get("equity") or ():
        time_ms = _seconds_ms(point.get("time"))
        equity.append({"time_ms": time_ms, "bar_time_ms": anchor(time_ms), "equity": decimal_text(point.get("value"))})
    return _result(source="native-pine", authority="SCRIPT", clock_policy="FIXED", fidelity=None, interval=interval,
                   fills=fills, trades=trades, open_position=_open_position(last.get("size"), last.get("avgPrice")),
                   pending_orders=[], equity=equity, plots=_plots(report.get("graphics") or (), bar_opens))


def from_external_report(report: Mapping[str, Any], *, interval: str) -> dict[str, Any]:
    """Project Pine decisions matched by CandleScope. The host kernel owns the account."""
    bar_opens = _report_bars(report)
    anchor = BarAnchor(interval, bar_opens or None)
    fills = [_host_fill(fill, anchor) for fill in report.get("trades") or ()]
    trades = []
    for index, trade in enumerate(report.get("closed_trades") or (), start=1):
        entry, exit_ = _seconds_ms(trade.get("entryTime")), _seconds_ms(trade.get("exitTime"))
        trades.append({
            "id": f"trade-{index}", "side": str(trade.get("side") or "long").upper(), "qty": decimal_text(trade.get("qty")),
            "entry_time_ms": entry, "entry_bar_time_ms": anchor(entry), "entry_price": decimal_text(trade.get("entryPrice")),
            "exit_time_ms": exit_, "exit_bar_time_ms": anchor(exit_), "exit_price": decimal_text(trade.get("exitPrice")),
            "fees": None, "net_pnl": decimal_text(trade.get("profit")),
        })
    account = report.get("position") or {}
    equity = []
    for point in report.get("equity") or ():
        time_ms = _seconds_ms(point.get("time"))
        equity.append({"time_ms": time_ms, "bar_time_ms": anchor(time_ms), "equity": decimal_text(point.get("value"))})
    fidelity = report.get("fidelity")
    return _result(source="external-pine", authority="HOST", clock_policy="FIXED",
                   fidelity=str(fidelity) if fidelity else None, interval=interval, fills=fills, trades=trades,
                   open_position=_open_position(account.get("position_qty"), account.get("entry_price")),
                   pending_orders=_host_pending(report.get("orders") or ()), equity=equity,
                   plots=_plots(report.get("graphics") or (), bar_opens))


def from_native_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project a completed ``/backtests/native`` or ``/backtests/external`` run record."""
    from .errors import BacktestError

    if record.get("state") != "COMPLETED" or not isinstance(record.get("result"), Mapping):
        raise BacktestError("IDENTITY_MUTATION", "strategy run result is not ready")
    interval = str((record.get("config") or {}).get("interval") or "")
    mode = record.get("execution_mode")
    if mode == "NATIVE":
        return from_native_report(record["result"], interval=interval)
    if mode == "CANDLESCOPE":
        return from_external_report(record["result"], interval=interval)
    raise BacktestError("NATIVE_INPUT_UNSUPPORTED", f"unknown strategy execution mode {mode!r}")
