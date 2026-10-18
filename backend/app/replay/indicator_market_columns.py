"""Verified close inputs without building account range trees on first access.

Only bounded, continuous float64 minute objects admit this path. Keep the
original scalar/indexed reader for other schemas, gaps or unusual values.
The cache contains immutable market columns, never indicator or account state.
"""

from collections import OrderedDict
from threading import RLock

MAX_ROWS = 65_536
MAX_BYTES = 32 * 1024 * 1024
MAX_OBJECTS = 128
_cache = OrderedDict()
_lock = RLock()
_bytes = 0
MINUTE = 60_000


def _column(repository, manifest, item, cancelled):
    global _bytes
    from .history_archive import _load_pyarrow

    path = repository._object_path(item)
    repository._verify_object(manifest, item, path)
    stat = path.stat()
    key = (str(path), item.object_sha256, stat.st_size, stat.st_mtime_ns)
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    if cancelled.is_set():
        raise InterruptedError("indicator column preparation cancelled")
    pa, pq = _load_pyarrow()
    import pyarrow.compute as pc

    with pq.ParquetFile(path) as source:
        count = source.metadata.num_rows
        if not 0 < count <= MAX_ROWS:
            return None
        prices = ("open", "high", "low", "close", "volume")
        auxiliary = ("quote_volume", "taker_buy_base", "taker_buy_quote")
        fields = (*prices, *auxiliary, "open_time", "close_time", "trades")
        for name in fields:
            expected = pa.int64() if name in {"open_time", "close_time", "trades"} else pa.float64()
            if source.schema_arrow.field(name).type != expected:
                return None
        table = source.read(columns=list(fields))
    if cancelled.is_set():
        raise InterruptedError("indicator column preparation cancelled")
    # A strict ordinary subset keeps unsupported domains on the existing
    # validator. No sums or changed precision enter the recursive math here.
    for name in (*prices, *auxiliary):
        values = table[name]
        if name in prices and values.null_count:
            return None
        valid = pc.drop_null(values)
        if len(valid) and (
            not pc.all(pc.is_finite(valid)).as_py()
            or pc.min(valid).as_py() < (1e-6 if name in prices[:4] else 0)
            or pc.max(valid).as_py() > 1e12
        ):
            return None
    if any(table[name].null_count for name in ("open_time", "close_time")):
        return None
    opens, closes = table["open_time"], table["close_time"]
    first = opens[0].as_py()
    if (
        first < 0 or first % MINUTE
        or not pc.all(pc.equal(pc.subtract(closes, opens), MINUTE - 1)).as_py()
        or (count > 1 and not pc.all(pc.equal(
            pc.subtract(opens.slice(1), opens.slice(0, count - 1)), MINUTE
        )).as_py())
        or first != item.first_open_ms
        or opens[-1].as_py() != item.last_open_ms
        or count != item.row_count
    ):
        return None
    for left, right in (("high", "open"), ("high", "close"), ("high", "low"),
                        ("open", "low"), ("close", "low")):
        if not pc.all(pc.greater_equal(table[left], table[right])).as_py():
            return None
    trades = pc.drop_null(table["trades"])
    if len(trades) and pc.min(trades).as_py() < 0:
        return None
    column = table["close"]
    result = (first, count, column)
    with _lock:
        existing = _cache.get(key)
        if existing is not None:
            return existing
        _cache[key] = result
        _bytes += column.nbytes
        while _bytes > MAX_BYTES or len(_cache) > MAX_OBJECTS:
            _, old = _cache.popitem(last=False)
            _bytes -= old[2].nbytes
    return result


def read_pinned_closes(repository, revision, identity, start, stop, times, cancelled):
    """Prove every minute of the selection, return only requested closes."""
    manifest = repository._manifest(
        identity.symbol, "1m", exchange=identity.exchange,
        market_type=identity.market_type, source_revision=revision,
    )
    if start % MINUTE or stop % MINUTE or any(
        at < start or at >= stop or at % MINUTE for at in times
    ) or times != sorted(set(times)):
        return None
    cursor, result = start, []
    for item in manifest.objects:
        if item.last_open_ms < cursor or item.first_open_ms >= stop:
            continue
        if cancelled.is_set():
            raise InterruptedError("indicator column preparation cancelled")
        selected = _column(repository, manifest, item, cancelled)
        if selected is None:
            return None
        first, count, column = selected
        end = min(stop, first + count * MINUTE)
        if first > cursor or end <= cursor:
            return None
        offsets = [(at - first) // MINUTE for at in times if cursor <= at < end]
        if offsets:
            result.extend(str(value) for value in column.take(offsets).to_pylist())
        cursor = end
    if cancelled.is_set():
        raise InterruptedError("indicator column preparation cancelled")
    return result if cursor == stop and len(result) == len(times) else None
