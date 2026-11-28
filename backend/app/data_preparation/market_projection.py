"""Pure display reduction of one closed-source bucket, with no actor history.

The general replay builder remains the fallback and test oracle. This reducer
does not create per-minute mutable builder states or execution-chain hashes.
"""

from decimal import Decimal

from app.replay.bars.builder import AGG_TRADE_SYNTHETIC_SOURCE, ReplayDisplayBar
from app.replay.dataset import validate_replay_repository_bar
from app.replay.models import normalize_decimal_string, validate_timestamp_ms


def project_bucket(rows, start, end, mapper, identity, *, include_active, fallback):
    bucket = mapper.actual_containing_bucket_open(start)
    if (
        not rows
        or start != bucket
        or mapper.monthly_count is not None
        or start % 60_000
        or end % 60_000
        or len(rows) != (end - start) // 60_000
        or end > mapper.actual_bucket_end(bucket)
        or any(row.get("source") == AGG_TRADE_SYNTHETIC_SOURCE for row in rows)
    ):
        return fallback(
            rows, start, end, mapper, identity, include_active=include_active
        )
    bucket_end = mapper.actual_bucket_end(bucket)
    validate_timestamp_ms(start, field_name="open_time_ms")
    validate_timestamp_ms(end - 1, field_name="close_time_ms")
    return _reduce(
        rows,
        [start + index * 60_000 for index in range(len(rows))],
        bucket,
        bucket_end,
        end,
        identity,
        expected_components=(bucket_end - bucket) // 60_000,
        complete=end == bucket_end,
        include_active=include_active,
    )


def project_session_bucket(rows, opens, bucket, bucket_end, now_ms, identity, *,
                           expected_components, include_active):
    """One display bucket of a session-calendar series (ADR-DATA-002 D2).

    ``opens`` are the calendar's traded minutes for ``rows``; closures are not
    components, so a bucket closes once it holds every minute it trades.
    """
    return _reduce(
        rows,
        opens,
        bucket,
        bucket_end,
        now_ms,
        identity,
        expected_components=expected_components,
        complete=len(rows) == expected_components,
        include_active=include_active,
    )


def _reduce(rows, opens, bucket, bucket_end, now_ms, identity, *,
            expected_components, complete, include_active):
    # Validate even an omitted active bucket. Missing/malformed data must not
    # become a successful empty projection merely because it is not rendered.
    first = last = None
    high = low = None
    totals = None
    trades = None
    fields = ("volume", "quote_volume", "taker_buy_base", "taker_buy_quote")
    for open_ms, row in zip(opens, rows, strict=True):
        bar = validate_replay_repository_bar(
            row,
            identity=identity,
            interval="1m",
            interval_ms=60_000,
            expected_open_ms=open_ms,
            now_ms=now_ms,
        )
        values = {
            name: None if getattr(bar, name) is None else Decimal(getattr(bar, name))
            for name in fields
        }
        if first is None:
            first, high, low, totals, trades = (
                bar,
                bar.high,
                bar.low,
                values,
                bar.trades,
            )
        else:
            high = high if Decimal(high) >= Decimal(bar.high) else bar.high
            low = low if Decimal(low) <= Decimal(bar.low) else bar.low
            for name in fields:
                totals[name] = (
                    None
                    if totals[name] is None or values[name] is None
                    else totals[name] + values[name]
                )
                if totals[name] is not None and not totals[name].is_finite():
                    raise ValueError(f"{name} must be finite")
            trades = (
                None if trades is None or bar.trades is None else trades + bar.trades
            )
        last = bar
    if not complete and not include_active:
        return ()
    normalized = {
        name: None
        if value is None
        else normalize_decimal_string(format(value, "f"), field_name=name)
        for name, value in totals.items()
    }
    return (
        ReplayDisplayBar(
            open_time_ms=bucket,
            close_time_ms=bucket_end - 1,
            open=first.open,
            high=high,
            low=low,
            close=last.close,
            **normalized,
            trades=trades,
            first_base_open_ms=first.open_time_ms,
            last_base_open_ms=last.open_time_ms,
            component_count=len(rows),
            expected_components=expected_components,
            is_closed=complete,
        ),
    )
