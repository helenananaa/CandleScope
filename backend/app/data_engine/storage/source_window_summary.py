"""Fold a selected-source read view without retaining its complete row set."""

from contextlib import closing
from dataclasses import replace

from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.aggregation.source_window import (
    MAX_SOURCE_SUMMARY_PARTS,
    SOURCE_SUMMARY_BYTES,
)
from app.data_engine.bar_aggregator.bar_state import ComponentSnapshotOHLCVMerge
from app.data_engine.bar_aggregator.component_accumulator import (
    _Summary,
    _combine,
    SourceWindowSummary,
)
from app.data_engine.market_data.kline_metrics import declared_enhanced_fields
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size
from . import kline_sources, klines_repo


def fold_source_window(key, start, end, width, incoming, cancel):
    """One finite worker, one pinned SQLite view, at most one decoded page.

    The original source journal remains the selection authority. A fresh
    post-transaction content fence rejects changes made while folding. No
    persistent cursor, cache, thread, writer or revision ledger is introduced.
    The caller owns decode/staging reservations through physical completion.
    """
    if key != kline_sources._json(
        [
            incoming.exchange,
            incoming.market_type,
            incoming.symbol,
            incoming.source_interval,
        ]
    ):
        raise BlockUnavailable(
            "source reconstruction identity does not match its incoming value"
        )
    version = kline_sources.capture_source_window(key, start, end, width)
    parts = []
    pages = count = 0
    found = False
    where, params, _ = klines_repo._series_where(
        exchange=incoming.exchange,
        market_type=incoming.market_type,
        symbol=incoming.symbol,
        interval=incoming.source_interval,
        series_identity=incoming.identity,
    )
    with closing(klines_repo._connect()) as conn:
        conn.execute("BEGIN")
        if not kline_sources.source_window_current(conn, version):
            raise BlockRevisionChanged("source changed before bounded reconstruction")
        position = start
        while position is not None:
            if cancel.is_set():
                raise BlockUnavailable("selected-source reconstruction cancelled")
            page = kline_sources.read_source_window_page(
                version,
                position,
                _connection=conn,
                _pinned=True,
            )
            pages += 1
            count += len(page.components)
            for component in page.components:
                data = component["data"]
                # SourceJournal-only evidence is valid. If a native canonical
                # value exists, however, an old source observation must not
                # overwrite a manual/canonical correction that it contradicts.
                canonical = conn.execute(
                    "SELECT "
                    + ",".join(kline_sources._VALUES)
                    + " FROM klines WHERE "
                    + " AND ".join(where)
                    + " AND open_time=?",
                    (*params, data["open_time"]),
                ).fetchone()
                mask = declared_enhanced_fields(
                    incoming.exchange, incoming.market_type, data
                )
                if canonical is not None and any(
                    canonical[name] != data.get(name)
                    for name in (
                        "open_time",
                        "close_time",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        *mask,
                    )
                ):
                    raise BlockRevisionChanged(
                        "canonical source differs from selected-source content"
                    )
                if data["open_time"] == incoming.open_time_ms:
                    if not incoming.is_closed:
                        raise BlockRevisionChanged(
                            "a forming input cannot replace a selected closed component"
                        )
                    if dict(component["ref"]) != dict(incoming.extra["source_ref"]):
                        raise BlockRevisionChanged(
                            "incoming source version was superseded"
                        )
                    expected = ComponentSnapshotOHLCVMerge._snapshot_from_input(
                        incoming
                    )
                    if mask != expected["enhanced_fields"] or any(
                        data.get(name) != expected[name]
                        for name in ("open", "high", "low", "close", "volume", *mask)
                    ):
                        raise BlockUnavailable(
                            "incoming value does not match selected source"
                        )
                    found = True
                    continue
                sibling = replace(
                    incoming,
                    open_time_ms=data["open_time"],
                    close_time_ms=data["close_time"],
                    enhanced_fields=declared_enhanced_fields(
                        incoming.exchange, incoming.market_type, data
                    ),
                    **{
                        name: data.get(name) if data.get(name) is not None else 0
                        for name in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "quote_volume",
                            "trades",
                            "taker_buy_base",
                            "taker_buy_quote",
                        )
                    },
                    extra={},
                )
                leaf = _Summary.leaf(
                    ComponentSnapshotOHLCVMerge._snapshot_from_input(sibling)
                )
                if parts and parts[-1].end == leaf.first:
                    parts[-1] = _combine(parts[-1], leaf)
                else:
                    if len(parts) >= MAX_SOURCE_SUMMARY_PARTS:
                        raise MemoryBudgetExceeded(
                            "selected-source reconstruction is too fragmented"
                        )
                    parts.append(leaf)
            position = page.next_position_ms
            page = None
            if retained_size((parts,))[0] > SOURCE_SUMMARY_BYTES - 4096:
                raise MemoryBudgetExceeded(
                    "selected-source summaries exceed staging allowance"
                )
    if (incoming.is_closed and not found) or count != version.closed_count:
        raise BlockRevisionChanged("selected-source read view is incomplete")
    with closing(klines_repo._connect()) as conn:
        conn.execute("BEGIN")
        if not kline_sources.source_window_current(conn, version):
            raise BlockRevisionChanged("source changed during bounded reconstruction")
        watermark = conn.execute("SELECT COALESCE(MAX(id),0) FROM kline_source_observations").fetchone()[0]
    result = SourceWindowSummary(version, tuple(parts), incoming.open_time_ms, pages, 0, observation_watermark=watermark)
    size = retained_size((result,))[0] + 64
    if size > SOURCE_SUMMARY_BYTES:
        raise MemoryBudgetExceeded("selected-source receipt exceeds staging allowance")
    return replace(result, estimated_bytes=size)
