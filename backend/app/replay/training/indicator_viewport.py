"""Bounded display-only math with durable, immutable overlap anchors.

Live display warmup budgets seed unseen windows. Once a window has been shown,
its mathematical anchors win over later left-edge initialization. Panning left
can add history but cannot rebase already displayed values. This store is a
separate derived table; execution/account indicators never read it.
"""

from __future__ import annotations

import json
import math
from time import monotonic

from app.data_engine.interval_policy import compute_bucket_start_ms, parse_interval_ms
from app.indicator.serialization import serialize_indicator_result
from app.indicator.types import IndicatorKey
from app.indicator.warmup import indicator_warmup_bars

from .indicator_checkpoint import (
    BUILTINS,
    checkpoint_key,
    discard_prefix_graphics,
    dump_state,
    new_indicator,
    normalized_parameters,
    restore_state,
)
from .indicator_history import IndicatorHistoryPreparing, validate_chunk
from .indicator_prefix import CloseIndicatorBar, indicator_bar, validated_render_bars

SCHEMA = "replay.viewport-indicator.v1"
ANCHOR_STRIDE = 128
MAX_PREFIX_CHUNK_BARS = 500


def math_parameters(name, params):
    styles = {
        p.key for p in BUILTINS[name].get_spec().param_schema if p.type == "color"
    }
    return {key: value for key, value in params.items() if key not in styles}


def preceding_boundary(history, before, count):
    interval = history.identity["identity"]["display_interval"]
    width = parse_interval_ms(interval)
    if not width:
        raise ValueError("invalid indicator display interval")
    cursor = before
    for _ in range(count):
        if cursor <= history.origin_ms:
            break
        cursor = compute_bucket_start_ms(cursor - 1, width, interval=interval)
    return max(history.origin_ms, cursor)


class DisplayIndicatorAnchors:
    def __init__(self, checkpoints):
        self.checkpoints = checkpoints
        with checkpoints._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS display_indicator_anchors (
                identity TEXT NOT NULL, before_ms INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(identity, before_ms))""")

    def between(self, identity, start, end, name, params):
        with self.checkpoints._connect() as conn:
            rows = conn.execute(
                "SELECT before_ms, body FROM display_indicator_anchors WHERE identity=? AND before_ms>=? AND before_ms<=? ORDER BY before_ms",
                (identity, start, end),
            ).fetchall()
        result = {}
        for at, raw in rows:
            body = json.loads(raw)
            restore_state(name, params, body["state"])
            last = body["last_close_ms"]
            if last is not None and (type(last) is not int or last >= at):
                raise ValueError("invalid display anchor boundary")
            result[at] = body
        return result

    def save(self, identity, anchors):
        if not anchors:
            return
        with self.checkpoints._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Never evict a seed behind a displayed window: reinitializing it
            # from a different left edge would change historical values.
            if (
                conn.execute(
                    "SELECT count(*) FROM display_indicator_anchors"
                ).fetchone()[0]
                + len(anchors)
                > 100_000
            ):
                raise ValueError("display indicator anchor budget exhausted")
            conn.executemany(
                "INSERT OR IGNORE INTO display_indicator_anchors VALUES (?, ?, ?)",
                [
                    (
                        identity,
                        at,
                        json.dumps(body, allow_nan=False, separators=(",", ":")),
                    )
                    for at, body in anchors.items()
                ],
            )


class ViewportReplayIndicators:
    def __init__(self, checkpoints, *, max_prefix_pages=64, max_prefix_seconds=0.5):
        self.anchors = DisplayIndicatorAnchors(checkpoints)
        self.max_prefix_pages = max_prefix_pages
        self.max_prefix_seconds = max_prefix_seconds

    def compute(self, *, history, name, params, rows, cancelled=None):
        params = normalized_parameters(name, params)
        render_bars = validated_render_bars(history, rows)
        before = rows[0].open_time_ms
        warmup = indicator_warmup_bars(name, params)
        lower = preceding_boundary(history, before, max(warmup, ANCHOR_STRIDE))
        identity = checkpoint_key(
            {**history.identity, "display_math": SCHEMA},
            name,
            math_parameters(name, params),
        )
        known = self.anchors.between(
            identity, lower, rows[-1].close_time_ms + 1, name, params
        )
        prior = [at for at in known if at <= before]
        cursor = max(prior) if prior else preceding_boundary(history, before, warmup)
        instance = new_indicator(name, params)
        last_close = None
        pending = {}

        def check_cancelled():
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError("indicator preparation cancelled")

        def restore_at(at, *, keep_outputs=False):
            nonlocal instance, last_close
            if at not in known:
                return
            outputs = instance._outputs
            aux = {
                f: getattr(instance, f)
                for f in ("_hist_color_data", "_color_data")
                if hasattr(instance, f)
            }
            instance = restore_state(name, params, known[at]["state"])
            if keep_outputs:
                instance.retain_outputs(len(rows))
                instance._outputs = outputs
                for field, value in aux.items():
                    setattr(instance, field, value)
            last_close = known[at]["last_close_ms"]

        def remember(at):
            if at not in known:
                pending[at] = {
                    "state": dump_state(instance),
                    "last_close_ms": last_close,
                }

        def reset_for_gap(at, *, keep_outputs=False):
            nonlocal instance
            if last_close is not None and at != last_close + 1:
                outputs = instance._outputs
                colors = {
                    field: getattr(instance, field)
                    for field in ("_hist_color_data", "_color_data")
                    if hasattr(instance, field)
                }
                instance = new_indicator(name, params)
                if keep_outputs:
                    instance.retain_outputs(len(rows))
                    instance._outputs = outputs
                    for field, value in colors.items():
                        setattr(instance, field, value)

        check_cancelled()
        deadline = monotonic() + self.max_prefix_seconds
        pages = read_rows = 0
        close_reader = (
            getattr(history, "read_closes", None)
            if name in {"MA", "EMA", "RSI", "MACD", "BOLL"}
            and params.get("source", "close") == "close"
            else None
        )
        while cursor < before:
            check_cancelled()
            restore_at(cursor)
            following = [at for at in known if cursor < at < before]
            stop = min(following) if following else before
            try:
                close_chunk = (
                    None if close_reader is None else close_reader(cursor, stop)
                )
                chunk = (
                    history.read(cursor, stop) if close_chunk is None else close_chunk
                )
            except IndicatorHistoryPreparing as preparing:
                remember(cursor)
                check_cancelled()
                self.anchors.save(identity, pending)
                return {
                    "status": "preparing",
                    "seed": history.identity,
                    "prepared_before_ms": cursor,
                    "target_before_ms": before,
                    "prefix_rows_read": read_rows,
                    "source_preparation": preparing.progress,
                    "display_math": SCHEMA,
                }
            if (
                chunk.start_ms != cursor
                or chunk.stop_ms > stop
                or len(chunk.bars) > MAX_PREFIX_CHUNK_BARS
            ):
                raise ValueError("indicator reader changed its display cursor")
            validate_chunk(chunk, history.revealed_boundary_ms)
            for bar in chunk.bars:
                reset_for_gap(bar.open_time_ms)
                value = (
                    indicator_bar(bar)
                    if close_chunk is None
                    else CloseIndicatorBar(bar.open_time_ms // 1000, float(bar.close))
                )
                # The ordinary builtin remains the mathematical authority.
                if close_chunk is not None and not math.isfinite(value.close):
                    raise ValueError("indicator close input is not finite")
                instance.update_closed(value)
                last_close = bar.close_time_ms
            if any(end == chunk.stop_ms - 1 for _, end in chunk.gaps):
                instance = new_indicator(name, params)
                last_close = None
            discard_prefix_graphics(instance)
            check_cancelled()
            cursor = chunk.stop_ms
            read_rows += len(chunk.bars)
            pages += 1
            if cursor < before and (
                pages >= self.max_prefix_pages or monotonic() >= deadline
            ):
                remember(cursor)
                self.anchors.save(identity, pending)
                return {
                    "status": "preparing",
                    "seed": history.identity,
                    "prepared_before_ms": cursor,
                    "target_before_ms": before,
                    "prefix_rows_read": read_rows,
                    "display_math": SCHEMA,
                }
        restore_at(before)
        reset_for_gap(before)
        remember(before)
        math_seed = {
            "schema": "replay.builtin-seed.v1",
            "name": name,
            "params": params,
            "before_ms": before,
            "state": dump_state(instance),
        }
        instance.retain_outputs(len(rows))
        for i, (row, bar) in enumerate(zip(rows, render_bars, strict=True)):
            check_cancelled()
            restore_at(row.open_time_ms, keep_outputs=True)
            reset_for_gap(row.open_time_ms, keep_outputs=True)
            instance.update_closed(bar)
            last_close = row.close_time_ms
            if row.is_closed and (
                (i + 1) % ANCHOR_STRIDE == 0
                or i == len(rows) - 1
                or not rows[i + 1].is_closed
            ):
                remember(row.close_time_ms + 1)
        market = history.identity["identity"]
        key = IndicatorKey(
            market["symbol"],
            market["display_interval"],
            name,
            params,
            exchange=market["exchange"],
            market_type=market["market_type"],
        )
        payload = serialize_indicator_result(instance.build_result(key))
        check_cancelled()
        self.anchors.save(identity, pending)
        return {
            "status": "ready",
            "seed": history.identity,
            "math_seed": math_seed,
            "payload": payload,
            "prefix_rows_read": read_rows,
            "checkpoint_before_ms": max(prior) if prior else None,
            "display_math": SCHEMA,
        }
