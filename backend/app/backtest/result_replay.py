"""Reveal completed local spot strategy results from an immutable input prefix."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from decimal import Decimal
from itertools import groupby
import json
from math import isfinite

from app.data_engine.interval_policy import parse_interval_spec
from app.indicator.window_math import window_mean
from app.local_data.resampling import LocalResamplingError, resolve_local_resample_plan
from app.local_data.service import LocalDatasetError
from app.local_data.user_market_trades import USER_TRADE_SOURCE
from app.market_dataset.snapshot import MarketDatasetError
from app.simulation.closing_tick import REASON as CLOSING_TICK
from app.simulation.spot_cash_account import SpotCashAccount
from app.simulation.trade_bar_builder import TradeBarBuilder

from .errors import BacktestError
from .user_trade_input import open_user_trade_run_snapshot


DISPLAY_INTERVALS = ("1m", "5m", "15m", "1h")
MAX_REVEALED_BARS = 160
MAX_REVEALED_FILLS = 100


def _wire_bar(event, *, closed):
    payload = event.payload
    return {key: str(payload[key]) for key in ("open", "high", "low", "close")} | {
        "volume": None if payload["volume"] is None else str(payload["volume"]),
        "open_time_ms": payload["open_time_ms"], "close_time_ms": payload["close_time_ms"], "closed": closed,
    }


def _fill_cursor(fill, events, times, *, trade):
    if not trade:
        sequence = fill.get("source_sequence", fill["sequence"])
        if (type(sequence) is int and 1 <= sequence <= len(events)
                and fill.get("source_event_kind", "BAR") == "BAR"
                and fill.get("source_event_time_ms", fill["event_time_ms"]) == times[sequence - 1]):
            return sequence
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved fill does not identify a closed input bar")
    sequence = fill.get("source_sequence")
    source_time = fill.get("source_event_time_ms")
    if fill.get("reason") == CLOSING_TICK:
        # A simulated BAR-close fill is emitted by the first source event
        # beyond that close. The prior event's sequence is reused by the
        # matching engine, so that sequence alone cannot reveal this fill.
        position = bisect_right(times, int(fill["event_time_ms"])) + 1
        if position <= len(events):
            return position
    elif (type(sequence) is int and 1 <= sequence <= len(events)
          and source_time == events[sequence - 1].event_time_ms
          and fill.get("source_event_kind") == "AGG_TRADE"):
        return sequence
    raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved fill has no verifiable replay boundary")


def _display_tail(events, times, cursor, spec, limit):
    first_open = spec.floor_ms(events[cursor - 1].payload.get("open_time_ms", times[cursor - 1]))
    for _ in range(limit - 1):
        if first_open <= times[0]:
            break
        first_open = spec.previous_ms(first_open)
    return events[bisect_left(times, first_open):cursor]


def _display_bars(events, times, cursor, spec, *, trade, source_interval, limit):
    if cursor == 0:
        return []
    tail = _display_tail(events, times, cursor, spec, limit)
    if trade:
        builder = TradeBarBuilder(spec.canonical)
        bars = deque(maxlen=limit)
        for event in tail:
            bars.extend(_wire_bar(bar, closed=True) for bar in builder.push(event))
        bars.append(_wire_bar(builder.forming_bar(times[cursor - 1]), closed=False))
        return list(bars)
    if spec.canonical == source_interval:
        return [_wire_bar(event, closed=True) for event in tail]
    bars = []
    for opened, items in groupby(tail, key=lambda event: spec.floor_ms(event.payload["open_time_ms"])):
        parts = [event.payload for event in items]
        bars.append({
            "open_time_ms": opened, "close_time_ms": parts[-1]["close_time_ms"],
            "open": str(parts[0]["open"]), "close": str(parts[-1]["close"]),
            "high": str(max(Decimal(str(part["high"])) for part in parts)),
            "low": str(min(Decimal(str(part["low"])) for part in parts)),
            "volume": str(sum(Decimal(str(part["volume"])) for part in parts))
            if all(part["volume"] is not None for part in parts) else None,
            "closed": (parts[0]["open_time_ms"] == opened
                       and parts[-1]["close_time_ms"] + 1 == spec.next_ms(opened)
                       and all(right["open_time_ms"] == left["close_time_ms"] + 1
                               for left, right in zip(parts, parts[1:]))),
        })
    return bars


def _display_chart(events, times, cursor, spec, *, trade, source_interval, ma_period):
    # Extra input buckets warm the first visible point without extending
    # the display window or reading outside the run's revealed prefix.
    bars = _display_bars(
        events, times, cursor, spec, trade=trade, source_interval=source_interval,
        limit=MAX_REVEALED_BARS + (ma_period - 1 if ma_period else 0),
    )
    return _chart_from_bars(bars, ma_period)


def _chart_from_bars(bars, ma_period):
    chart = {"bars": bars[-MAX_REVEALED_BARS:]}
    if ma_period is None:
        return chart
    window = deque(maxlen=ma_period)
    points = []
    next_open = None
    first_visible = max(0, len(bars) - MAX_REVEALED_BARS)
    for index, bar in enumerate(bars):
        if bar["open_time_ms"] != next_open:
            window.clear()
        next_open = bar["close_time_ms"] + 1
        if not bar["closed"]:
            window.clear()
            continue
        window.append(float(bar["close"]))
        if index >= first_visible and len(window) == ma_period:
            value = window_mean(window)
            if isfinite(value):
                points.append({"open_time_ms": bar["open_time_ms"], "value": value})
    chart["ma"] = {"period": ma_period, "points": points}
    return chart


def _display_intervals(source_interval, alignment_offset_ms):
    available = []
    for candidate in dict.fromkeys((source_interval, *DISPLAY_INTERVALS)):
        try:
            resolve_local_resample_plan(source_interval, candidate, alignment_offset_ms=alignment_offset_ms)
        except LocalResamplingError:
            continue
        available.append(candidate)
    return available


def _comparison_dataset_chart(runtime, dataset, interval, boundary, ma_period):
    dataset_id, data_epoch = dataset
    try:
        manifest, rows = runtime.local_data.load_pinned_closed_bars(
            dataset_id, data_epoch=data_epoch, interval=interval, through_ms=boundary,
            limit=MAX_REVEALED_BARS + (ma_period - 1 if ma_period else 0),
        )
    except LocalResamplingError as exc:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", str(exc)) from exc
    except LocalDatasetError as exc:
        raise BacktestError(exc.code, str(exc)) from exc
    available = _display_intervals(manifest["interval"], int(manifest.get("alignment_offset_ms", 0)))
    if interval not in available:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "Unsupported comparison dataset interval")
    bars = [{
        key: str(row[key]) for key in ("open", "high", "low", "close")
    } | {
        "volume": None if row["volume"] is None else str(row["volume"]),
        "open_time_ms": row["open_time_ms"], "close_time_ms": row["close_time_ms"], "closed": True,
    } for row in rows]
    return {"interval": interval, "dataset_id": dataset_id, "data_epoch": data_epoch,
            "symbol": manifest["symbol"], "display_intervals": available, **_chart_from_bars(bars, ma_period)}


def project_result_replay(
    runtime, run_id: str, *, snapshot_hash: str, report_hash: str, cursor: int,
    interval: str, comparison_interval: str | None = None,
    ma_period: int | None = None, comparison_ma_period: int | None = None,
    comparison_dataset: tuple[str, str] | None = None,
) -> dict:
    if (comparison_ma_period is not None or comparison_dataset is not None) and comparison_interval is None:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "Comparison study requires a comparison chart")
    record = runtime.service.get_run(run_id)
    config = json.loads(str(record["config_json"]))
    trade = record["fidelity_mode"] == "AGG_TRADE_EXECUTION"
    if (record["state"] != "COMPLETED" or record["fidelity_mode"] not in {"BAR_APPROX", "AGG_TRADE_EXECUTION"}
            or config.get("exchange") != "local" or config.get("market_type") != "spot"
            or config.get("account_model") != "SPOT_CASH_V1"):
        raise BacktestError("FIDELITY_UNSUPPORTED", "Result replay requires a completed local spot run")
    if record["snapshot_hash"] != snapshot_hash:
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Result replay snapshot changed")
    if trade:
        if runtime._manifest(str(record["dataset_id"])).get("source") != USER_TRADE_SOURCE:
            raise BacktestError("FIDELITY_UNSUPPORTED", "This run does not use imported market trades")
        source_interval = str(config["signal_interval"])
        available = list(dict.fromkeys((*DISPLAY_INTERVALS, source_interval)))
        preview, events = open_user_trade_run_snapshot(
            runtime.local_data, record, config, max_events=runtime.settings.max_trade_events,
        )
        instrument = preview["identity"]["instrument"]
        symbol = instrument["base_asset"] + "/" + instrument["quote_asset"]
    else:
        try:
            manifest = runtime.local_data.revision_details(str(record["dataset_id"]), str(record["data_epoch"]))["manifest"]
        except LocalDatasetError as exc:
            raise BacktestError(exc.code, str(exc)) from exc
        if manifest.get("source") not in {"local_dataset", USER_TRADE_SOURCE}:
            raise BacktestError("FIDELITY_UNSUPPORTED", "This run does not use imported bars")
        source_interval = str(config.get("interval") or manifest["interval"])
        available = _display_intervals(source_interval, int(manifest.get("alignment_offset_ms", 0)))
        from .runtime import _bar_execution_events

        snapshot = runtime.open_saved_bar_snapshot(record, config, source_interval)
        try:
            events = _bar_execution_events(snapshot.events, interval_name=source_interval)
        finally:
            snapshot.close()
        if any(event.sequence != index for index, event in enumerate(events, start=1)):
            raise BacktestError("DATA_GAP_REJECTED", "Saved bar replay requires a contiguous input")
        instrument = manifest.get("instrument") or {}
        symbol = manifest["symbol"]
    spec = parse_interval_spec(interval)
    comparison_spec = parse_interval_spec(comparison_interval) if comparison_interval else None
    if spec is None or interval not in available or (comparison_interval and (
            comparison_spec is None or (comparison_dataset is None and
                (comparison_interval not in available or comparison_interval == interval)))):
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "Unsupported result replay display interval")
    if not 0 <= cursor <= len(events):
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "Result replay cursor is outside the frozen input")
    report = runtime.service.get_report(run_id)
    if report["hashes"]["report"] != report_hash:
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Result replay report changed")
    times = [event.event_time_ms for event in events]
    account = SpotCashAccount(quote_balance=Decimal(str(config["initial_balance"])))
    visible_fills = deque(maxlen=MAX_REVEALED_FILLS)
    visible_fill_count = 0
    last_fill_cursor = 0
    try:
        for fill in report["fills"]:
            reveal = _fill_cursor(fill, events, times, trade=trade)
            if reveal < last_fill_cursor:
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved fills are not ordered by their reveal boundary")
            last_fill_cursor = reveal
            if reveal > cursor:
                break
            account.apply_fill(side=fill["side"], price=Decimal(fill["price"]),
                               qty=Decimal(fill["qty"]), fee=Decimal(fill["fee"]))
            if account.position_qty != Decimal(fill["position_after"]):
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved fill position is inconsistent")
            # Explanations and full-order summaries are report views with their
            # own availability rules. Only sealed fields of this fill are shown.
            visible_fills.append({
                "cursor": reveal, "event_time_ms": fill["event_time_ms"],
                "order_id": fill["order_id"], "side": fill["side"], "price": fill["price"],
                "qty": fill["qty"], "fee": fill["fee"],
            })
            visible_fill_count += 1

        last = events[cursor - 1] if cursor else None
        if last is not None:
            account.mark = Decimal(str(last.payload["price" if trade else "close"]))
        if cursor == len(events):
            for field, value in (("quote_balance", account.quote_balance), ("position_qty", account.position_qty),
                                 ("equity", account.equity())):
                if Decimal(report["account"][field]) != value:
                    raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Replay account differs from the sealed result")
    except MarketDatasetError as exc:
        raise BacktestError(exc.code, str(exc)) from exc

    orders = report.get("order_events") or []
    # BAR order callbacks run on the closed input. Older trade reports can
    # instead carry the previous print time, which cannot establish visibility.
    order_boundaries = {time_ms: index for index, time_ms in enumerate(times, start=1)} if not trade else {}
    order_reveals = [row.get("reveal_sequence") if trade else order_boundaries.get(row.get("event_time_ms")) for row in orders]
    order_trace_available = all(type(reveal) is int for reveal in order_reveals)
    visible_orders = deque(maxlen=MAX_REVEALED_FILLS)
    if order_trace_available:
        for row, reveal in zip(orders, order_reveals):
            if not 1 <= reveal <= len(events):
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved order has an invalid replay boundary")
            if reveal <= cursor:
                visible_orders.append({key: row[key] for key in ("ordinal", "order_id", "state")} | {"reveal_sequence": reveal})
    signals = (report.get("strategy") or {}).get("replayClosedBarSignals")
    visible_signals = deque(maxlen=MAX_REVEALED_FILLS)
    if signals is not None:
        for signal in signals:
            reveal = signal["reveal_sequence"]
            if type(reveal) is not int or not 1 <= reveal <= len(events):
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "Saved signal has an invalid replay boundary")
            if reveal <= cursor:
                visible_signals.append(signal)
    comparison = None
    if comparison_spec and comparison_interval:
        if comparison_dataset is not None:
            comparison = _comparison_dataset_chart(
                runtime, comparison_dataset, comparison_interval, last.event_time_ms if last else None, comparison_ma_period,
            )
        else:
            comparison = {"interval": comparison_interval, **_display_chart(
                events, times, cursor, comparison_spec, trade=trade, source_interval=source_interval,
                ma_period=comparison_ma_period,
            )}
    return {
        "schema": "candlescope.user-trade-result-replay/1" if trade else "candlescope.local-bar-result-replay/1",
        "run_id": run_id, "snapshot_hash": snapshot_hash, "report_hash": report_hash,
        "symbol": symbol, "quote_asset": instrument.get("quote_asset", "USDT"), "interval": interval,
        "display_intervals": available, "signal_interval": source_interval, "cursor": cursor, "total": len(events),
        "time_ms": last.event_time_ms if last else None,
        "source_sequence": last.payload.get("source_sequence", last.sequence) if last else None,
        **_display_chart(events, times, cursor, spec, trade=trade, source_interval=source_interval, ma_period=ma_period),
        "comparison": comparison,
        "fills": list(visible_fills), "fill_count": visible_fill_count,
        "order_events": list(visible_orders), "order_trace_available": order_trace_available,
        "closed_bar_signals": list(visible_signals), "signal_trace_available": signals is not None,
        "notes": runtime.service.repository.result_replay_notes(run_id, snapshot_hash, report_hash, cursor),
        "cash": str(account.quote_balance), "position": str(account.position_qty), "equity": str(account.equity()),
    }
