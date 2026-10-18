"""Bounded tape-chart context from already verified immutable market indexes."""

from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.replay.bars.trade_builder import _decimal_string
from app.replay.dataset import ReplayBar

from .errors import TrainingRunError

MAX_CONTEXT_MINUTES = 32_768


def select_indexed_closes(history, start, stop, times, cancelled):
    reader = getattr(history.arguments["repository"], "tape_indicator_closes_at_revision", None)
    snapshot, config = history.snapshot, history.config
    delta = int(history.arguments["binding"]["history_policy"]["actual_replay_start_ms"]) - snapshot.replay_start_ms
    if (not callable(reader) or config.base_interval != "1m"
        or not snapshot.provenance.source_revision or delta % 60_000
        or start < history.origin_ms or stop > snapshot.replay_start_ms):
        return None
    try:
        return reader(
            snapshot.provenance.source_revision, config.symbol, config.base_interval,
            start_ms=start + delta, end_ms=stop + delta,
            close_times=[at + delta for at in times], exchange=config.exchange,
            market_type=config.market_type, cancelled=cancelled,
        )
    except (InterruptedError, TrainingRunError):
        raise
    except Exception as error:
        raise TrainingRunError(
            "HISTORY_SOURCE_UNAVAILABLE", "replay indicator history could not be read",
            status_code=503, details={"retryable": getattr(error, "retryable", False) is True},
        ) from error


def select_indexed_context(history, start, stop, cancelled):
    repository = history.arguments["repository"]
    reader = getattr(repository, "tape_context_market_at_revision", None)
    snapshot, config = history.snapshot, history.config
    if (
        not callable(reader)
        or config.base_interval != "1m"
        or not snapshot.provenance.source_revision
    ):
        return None
    delta = (
        int(history.arguments["binding"]["history_policy"]["actual_replay_start_ms"])
        - snapshot.replay_start_ms
    )
    if delta % 60_000 or start < history.origin_ms or stop > snapshot.replay_start_ms:
        return None
    stop = min(stop, start + MAX_CONTEXT_MINUTES * 60_000)
    if cancelled.is_set():
        raise InterruptedError("indexed tape context cancelled")
    try:
        market = reader(
            snapshot.provenance.source_revision,
            config.symbol,
            config.base_interval,
            exchange=config.exchange,
            market_type=config.market_type,
            start_ms=start + delta,
            end_ms=stop + delta,
            offset_ms=-delta,
            cancelled=cancelled,
        )
    except (InterruptedError, TrainingRunError):
        raise
    except Exception as error:
        raise TrainingRunError(
            "HISTORY_SOURCE_UNAVAILABLE",
            "replay indexed history could not be read",
            status_code=503,
            details={"retryable": getattr(error, "retryable", False) is True},
        ) from error
    if market is None:
        return None
    coverage = market.display_summary(0, market.count)
    # Only a complete continuous minute range admits arithmetic bucket offsets.
    # Missing rows retain the ordinary reader's declared-gap/error semantics.
    if (
        coverage is None
        or not coverage[12]
        or coverage[10] != start
        or coverage[11] + 60_000 != stop
        or coverage[9] != (stop - start) // 60_000
    ):
        return None
    return stop, market


def read_indexed_context(history, start, stop, interval, cancelled, *, include_auxiliary=True):
    selected = select_indexed_context(history, start, stop, cancelled)
    if selected is None:
        return None
    stop, market = selected
    width = parse_interval_ms(interval)
    summaries, cursor = [], start
    while cursor < stop:
        if cancelled.is_set():
            raise InterruptedError("indexed tape context cancelled")
        bucket = compute_bucket_start_ms(cursor, width, interval=interval)
        end = min(stop, compute_bucket_end_ms(bucket, width, interval=interval))
        fields = market.display_summary(
            (cursor - start) // 60_000, (end - start) // 60_000,
            include_auxiliary=include_auxiliary,
        )
        # Scalar tape sums use precision 60. This ordinary market-value domain
        # leaves ample headroom for every prefix and cross-page merge within
        # the supported timestamp range; unusual decimals keep scalar order.
        numeric = [fields[i] for i in (0, 1, 2, 3, 4, 5, 7, 8) if fields[i] is not None]
        if any(v.adjusted() > 18 or v.as_tuple().exponent < -18 for v in numeric):
            return None
        values = {
            name: None if fields[i] is None else _decimal_string(fields[i], name)
            for i, name in enumerate(
                ("open", "high", "low", "close", "volume", "quote_volume")
            )
        }
        values.update(
            trades=fields[6],
            taker_buy_base=None
            if fields[7] is None
            else _decimal_string(fields[7], "taker_buy_base"),
            taker_buy_quote=None
            if fields[8] is None
            else _decimal_string(fields[8], "taker_buy_quote"),
        )
        bar = ReplayBar(
            open_time_ms=cursor,
            close_time_ms=end - 1,
            source="replay_context",
            **values,
        )
        summaries.append((bar, fields[11], fields[9]))
        cursor = end
    return stop, tuple(summaries)
