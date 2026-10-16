"""Paged, revealed-only aggregation over immutable minute repositories."""

from collections import OrderedDict
from threading import RLock
from weakref import WeakKeyDictionary

_closed_buckets = WeakKeyDictionary()
_cache_guard = RLock()
_CLOSED_BUCKET_CACHE_LIMIT = 1024


def _cached_bucket(repository, key):
    with _cache_guard:
        cache = _closed_buckets.get(repository)
        if cache is None or key not in cache:
            return None
        cache.move_to_end(key)
        return dict(cache[key])


def _remember_bucket(repository, key, group):
    # Market-only summaries belong to the immutable repository, not an
    # account or a run. An earlier reveal boundary never uses a later bucket.
    with _cache_guard:
        cache = _closed_buckets.setdefault(repository, OrderedDict())
        cache[key] = dict(group)
        cache.move_to_end(key)
        while len(cache) > _CLOSED_BUCKET_CACHE_LIMIT:
            cache.popitem(last=False)

def query_source_bucket_projection(repository, revision, symbol, base_interval, display_interval, *,
        actual_start_ms, actual_end_ms, actual_replay_start_ms, public_replay_start_ms, limit,
        include_partial=False, source_bucket_anchor_ms=None, exchange=None, market_type=None,
        max_base_rows=None):
    from decimal import Decimal

    from .display_time import SourceBucketTimeMapper
    from .models import normalize_decimal_string
    if base_interval != "1m":
        raise ValueError("source-bucket reducer requires immutable minute bars")
    mapper = SourceBucketTimeMapper.create(interval=display_interval,
        actual_replay_start_ms=actual_replay_start_ms, public_replay_start_ms=public_replay_start_ms,
        source_bucket_anchor_ms=source_bucket_anchor_ms)
    last_bucket = mapper.actual_containing_bucket_open(actual_end_ms - 1)
    first_bucket = mapper.actual_bucket_open(mapper.actual_bucket_ordinal(last_bucket) - limit - 2)
    first = max(actual_start_ms, first_bucket)
    if max_base_rows is not None:
        if isinstance(max_base_rows, bool) or not isinstance(max_base_rows, int) or max_base_rows < 1:
            raise ValueError("source-bucket page budget must be a positive integer")
        # A remote minute archive must not materialize 500 days merely because
        # a chart requested 500 daily candles. Return a recent, complete page
        # and let its oldest candle be the next cursor. Never split a bucket:
        # one calendar bucket may itself exceed this soft source-row budget.
        if actual_end_ms - first > max_base_rows * 60_000:
            cutoff = actual_end_ms - max_base_rows * 60_000
            bounded_first = mapper.actual_containing_bucket_open(cutoff)
            if bounded_first < cutoff:
                bounded_first = mapper.actual_bucket_end(bounded_first)
            first = max(first, min(last_bucket, bounded_first))
    groups = {}
    cursor = first
    optional = ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
    # Stream bounded base pages, retaining only bucket summaries. Calendar
    # months use the mapper's actual exchange grid before time disclosure.
    while cursor < actual_end_ms:
        current_bucket = mapper.actual_containing_bucket_open(cursor)
        current_end = mapper.actual_bucket_end(current_bucket)
        key = (revision, symbol, base_interval, display_interval, exchange, market_type,
               current_bucket, current_end)
        cached = (_cached_bucket(repository, key)
                  if cursor == current_bucket and current_end <= actual_end_ms else None)
        if cached is not None:
            groups[current_bucket] = cached
            cursor = current_end
            continue
        stop = min(actual_end_ms, current_end, cursor + 4096 * 60_000)
        rows = repository.query_bars_at_revision(revision, symbol, base_interval,
            start_ms=cursor, end_ms=stop - 1, limit=4096, order="ASC",
            exchange=exchange, market_type=market_type)
        for row in rows:
            timestamp = int(row["open_time"])
            if not cursor <= timestamp < stop:
                raise ValueError("source-bucket row exceeds revealed read range")
            bucket = mapper.actual_containing_bucket_open(timestamp)
            values = {key: None if row.get(key) is None else Decimal(str(row[key]))
                      for key in ("open", "high", "low", "close", "volume", *optional)}
            group = groups.get(bucket)
            if group is None:
                group = {**values, "first": timestamp, "last": timestamp, "count": 1, "contiguous": True}
                groups[bucket] = group
            else:
                group["contiguous"] = group["contiguous"] and timestamp == group["last"] + 60_000
                group["last"], group["count"] = timestamp, group["count"] + 1
                group["high"] = max(group["high"], values["high"])
                group["low"] = min(group["low"], values["low"])
                group["close"] = values["close"]
                group["volume"] += values["volume"]
                for key in optional:
                    group[key] = None if group[key] is None or values[key] is None else group[key] + values[key]
        cursor = stop
    bars = []
    public_revealed = public_replay_start_ms + actual_end_ms - actual_replay_start_ms - 1
    for bucket, group in sorted(groups.items()):
        bucket_end = mapper.actual_bucket_end(bucket)
        expected = (bucket_end - bucket) // 60_000
        complete = group["count"] == expected and group["last"] + 60_000 == bucket_end
        partial = include_partial and group["count"] < expected and group["last"] + 60_000 == actual_end_ms
        if not group["contiguous"] or group["first"] != bucket or not (complete or partial):
            continue
        if complete:
            _remember_bucket(repository,
                (revision, symbol, base_interval, display_interval, exchange, market_type, bucket, bucket_end),
                group)
        public = mapper.public_from_actual(bucket)
        public_end = mapper.public_bucket_end(public)
        last_base = min(public_end - 60_000, public + (group["count"] - 1) * 60_000, public_revealed)
        if public < 0 or last_base < public:
            continue
        result = {key: None if group[key] is None else normalize_decimal_string(format(group[key], "f"), field_name=key)
                  for key in ("open", "high", "low", "close", "volume", *optional)}
        result["trades"] = None if group["trades"] is None else int(group["trades"])
        bars.append({**result, "open_time_ms": public, "close_time_ms": public_end - 1,
            "first_base_open_ms": public, "last_base_open_ms": last_base,
            "component_count": group["count"], "expected_components": expected,
            "is_closed": complete, "synthetic": False})
    return {"bars": bars[-(limit + 1):], "has_more": first > actual_start_ms or len(bars) > limit}
