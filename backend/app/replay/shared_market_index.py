"""Account-independent range summaries beside immutable history objects.

Imported rows are normalized once. Queries read tree nodes and at most two
partial 256-row blocks, rather than decoding the whole future replay window.
This is a disposable index; original content-addressed Parquet remains authority.
"""

from bisect import bisect_left, bisect_right
from collections import OrderedDict, deque
from contextlib import closing
from decimal import Decimal, localcontext
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4
import zlib

VERSION = "shared-market.v1"
BLOCK = 256
FIELDS = (
    "open_time_ms",
    "close_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "source",
)
_readers = OrderedDict()
_lock = threading.RLock()


def pack(value):
    return zlib.compress(json.dumps(value, separators=(",", ":")).encode(), 1)


def unpack(value):
    return json.loads(zlib.decompress(value))


def merge(a, b, base_ms):
    if a is None:
        return b
    if b is None:
        return a
    with localcontext() as context:
        context.prec = 1000  # exact for the finite float64 archive domain
        left, right = a[0], b[0]
        sums = tuple(
            None if left[i] is None or right[i] is None else left[i] + right[i]
            for i in range(4, 9)
        )
        display = (
            left[0],
            max(left[1], right[1]),
            min(left[2], right[2]),
            right[3],
            *sums,
            left[9] + right[9],
            left[10],
            right[11],
            left[12] and right[12] and left[11] + base_ms == right[10],
        )
        down = max(a[3], b[3], (a[2], b[1]), key=lambda pair: pair[0] - pair[1])
        up = max(a[4], b[4], (a[1], b[2]), key=lambda pair: pair[1] - pair[0])
        return (
            display,
            min(a[1], b[1]),
            max(a[2], b[2]),
            down,
            up,
            min(a[5], b[5]),
            max(a[6], b[6]),
        )


def summarize(rows, base_ms):
    result = None
    for row in rows:
        prices = [Decimal(row[i]) for i in (2, 3, 4, 5)]
        close = prices[-1]
        display = (
            *prices,
            Decimal(row[6]),
            None if row[7] is None else Decimal(row[7]),
            row[8],
            None if row[9] is None else Decimal(row[9]),
            None if row[10] is None else Decimal(row[10]),
            1,
            row[0],
            row[0],
            True,
        )
        item = (
            display,
            close,
            close,
            (close, close),
            (close, close),
            close.as_tuple().exponent,
            close.adjusted(),
        )
        result = merge(result, item, base_ms)
    return result


def encode_summary(value):
    if value is None:
        return None
    display, low, high, down, up, scale, adjusted = value
    return [
        [str(v) if isinstance(v, Decimal) else v for v in display],
        str(low),
        str(high),
        list(map(str, down)),
        list(map(str, up)),
        scale,
        adjusted,
    ]


def decode_summary(value):
    if value is None:
        return None
    display = list(value[0])
    for i in (0, 1, 2, 3, 4, 5, 7, 8):
        if display[i] is not None:
            display[i] = Decimal(display[i])
    return (
        tuple(display),
        Decimal(value[1]),
        Decimal(value[2]),
        tuple(map(Decimal, value[3])),
        tuple(map(Decimal, value[4])),
        value[5],
        value[6],
    )


def index_path(source_path):
    source_path = Path(source_path)
    return source_path.parent / (source_path.stem + "." + VERSION + ".sqlite")


def repair_object(path, digest, *, stop=None):
    """Reconstruct missing/corrupt derived data from the pinned original."""
    from .history_archive import _load_pyarrow, _PARQUET_COLUMNS
    from .catalog import ReplaySeriesIdentity

    path = Path(path)
    with path.open("rb") as stream:
        actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        raise ValueError("frozen history object changed")
    _, pq = _load_pyarrow()
    table = pq.read_table(path, columns=list(_PARQUET_COLUMNS))
    meta = table.schema.metadata
    identity = ReplaySeriesIdentity(
        *(meta[key].decode() for key in (b"exchange", b"market_type", b"symbol"))
    )
    return build(
        path, digest, meta[b"interval"].decode(), identity, table.to_pylist(), stop=stop
    )


def build(source_path, object_hash, interval, identity, raw_rows, *, stop=None):
    from .dataset import validate_replay_repository_bar
    from app.data_engine.interval_policy import parse_interval_ms, is_monthly_interval

    base_ms = parse_interval_ms(interval)
    if base_ms is None or is_monthly_interval(interval):
        return None
    source_path = Path(source_path).resolve()
    target = index_path(source_path)
    temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
    rows = []
    for ordinal, raw in enumerate(raw_rows):
        if ordinal % BLOCK == 0 and stop is not None and stop.is_set():
            return None
        bar = validate_replay_repository_bar(
            raw,
            identity=identity,
            interval=interval,
            interval_ms=base_ms,
            expected_open_ms=int(raw["open_time"]),
            now_ms=int(raw["close_time"]) + 1,
        )
        rows.append([getattr(bar, name) for name in FIELDS])
    if not rows or any(a[0] >= b[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("shared market rows must be nonempty and ordered")
    size = 1
    count = (len(rows) + BLOCK - 1) // BLOCK
    while size < count:
        size *= 2
    nodes = [None] * (2 * size)
    directory = []
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.executescript(
                "CREATE TABLE metadata(value BLOB); CREATE TABLE blocks(id INTEGER PRIMARY KEY,value BLOB); CREATE TABLE nodes(id INTEGER PRIMARY KEY,value BLOB);"
            )
            for number, start in enumerate(range(0, len(rows), BLOCK)):
                if stop is not None and stop.is_set():
                    return None
                block = rows[start : start + BLOCK]
                directory.append([block[0][0], block[-1][0], len(block)])
                nodes[size + number] = summarize(block, base_ms)
                connection.execute(
                    "INSERT INTO blocks VALUES (?,?)", (number, pack(block))
                )
            for node in range(size - 1, 0, -1):
                nodes[node] = merge(nodes[node * 2], nodes[node * 2 + 1], base_ms)
            connection.executemany(
                "INSERT INTO nodes VALUES (?,?)",
                (
                    (i, pack(encode_summary(v)))
                    for i, v in enumerate(nodes)
                    if i and v is not None
                ),
            )
            stat = source_path.stat()
            metadata = {
                "version": VERSION,
                "object_hash": object_hash,
                "interval": interval,
                "base_ms": base_ms,
                "size": size,
                "count": len(rows),
                "directory": directory,
                "source_size": stat.st_size,
                "source_mtime": stat.st_mtime_ns,
            }
            connection.execute("INSERT INTO metadata VALUES (?)", (pack(metadata),))
            connection.commit()
        if stop is not None and stop.is_set():
            return None
        os.replace(temporary, target)
        with _lock:
            _readers.pop(str(target), None)
        return target
    finally:
        temporary.unlink(missing_ok=True)


class MarketObject:
    def __init__(self, source_path, object_hash):
        self.source_path = str(Path(source_path).resolve())
        self.path = index_path(self.source_path)
        self.metadata = unpack(self._fetch("metadata", None))
        stat = Path(self.source_path).stat()
        m = self.metadata
        if (
            m["version"] != VERSION
            or m["object_hash"] != object_hash
            or m["source_size"] != stat.st_size
            or m["source_mtime"] != stat.st_mtime_ns
        ):
            raise ValueError("shared market index does not match its frozen source")
        self.object_hash = object_hash
        self.base_ms = m["base_ms"]
        self.count = m["count"]
        self.firsts = tuple(row[0] for row in m["directory"])
        self.lasts = tuple(row[1] for row in m["directory"])
        self._blocks = OrderedDict()
        self._nodes = {}
        self._lock = threading.RLock()

    def _fetch(self, table, key):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as c:
            row = c.execute(
                "SELECT value FROM " + table + ("" if key is None else " WHERE id=?"),
                () if key is None else (key,),
            ).fetchone()
            if row is None:
                raise ValueError("shared market index entry is missing")
            return row[0]

    def block(self, number):
        with self._lock:
            if number not in self._blocks:
                self._blocks[number] = tuple(
                    tuple(row) for row in self._value("blocks", number)
                )
                if len(self._blocks) > 16:
                    self._blocks.popitem(last=False)
            return self._blocks[number]

    def row(self, index):
        if not 0 <= index < self.count:
            raise IndexError(index)
        return self.block(index // BLOCK)[index % BLOCK]

    def bound(self, time, right=False):
        block = bisect_left(self.lasts, time)
        if block == len(self.lasts):
            return self.count
        opens = [row[0] for row in self.block(block)]
        return block * BLOCK + (
            bisect_right(opens, time) if right else bisect_left(opens, time)
        )

    def node(self, number):
        with self._lock:
            if number not in self._nodes:
                self._nodes[number] = decode_summary(self._value("nodes", number))
            return self._nodes[number]

    def _value(self, table, key):
        try:
            return unpack(self._fetch(table, key))
        except (sqlite3.DatabaseError, OSError, ValueError, zlib.error):
            repair_object(self.source_path, self.object_hash)
            self._blocks.clear()
            self._nodes.clear()
            return unpack(self._fetch(table, key))

    def summary(self, start, end):
        if not 0 <= start <= end <= self.count:
            raise ValueError("shared market range is outside the object")
        if start == end:
            return None
        if start == 0 and end == self.count:
            return self.node(1)
        if start // BLOCK == (end - 1) // BLOCK:
            if start % BLOCK == 0 and (end - start == BLOCK or end == self.count):
                return self.node(self.metadata["size"] + start // BLOCK)
            return summarize(
                self.block(start // BLOCK)[start % BLOCK : (end - 1) % BLOCK + 1],
                self.base_ms,
            )
        result = tail = None
        if start % BLOCK:
            result = summarize(
                self.block(start // BLOCK)[start % BLOCK :], self.base_ms
            )
            start = (start // BLOCK + 1) * BLOCK
        if end % BLOCK:
            tail = (
                self.node(self.metadata["size"] + end // BLOCK)
                if end == self.count
                else summarize(self.block(end // BLOCK)[: end % BLOCK], self.base_ms)
            )
            end = end // BLOCK * BLOCK
        left, right = (
            start // BLOCK + self.metadata["size"],
            end // BLOCK + self.metadata["size"],
        )
        after = None
        while left < right:
            if left & 1:
                result = merge(result, self.node(left), self.base_ms)
                left += 1
            if right & 1:
                right -= 1
                after = merge(self.node(right), after, self.base_ms)
            left //= 2
            right //= 2
        return merge(merge(result, after, self.base_ms), tail, self.base_ms)


def open_object(path, object_hash):
    key = str(index_path(Path(path).resolve()))
    with _lock:
        result = _readers.get(key)
    if result is not None and result.object_hash != object_hash:
        raise ValueError("shared object digest changed")
    stat = Path(path).stat()
    if result is None or (
        result.metadata["source_size"],
        result.metadata["source_mtime"],
    ) != (stat.st_size, stat.st_mtime_ns):
        # Never hold the reader registry lock while backfilling an object.
        # An unrelated foreground range must remain readable during backfill.
        try:
            result = MarketObject(path, object_hash)
        except (sqlite3.DatabaseError, OSError, ValueError, zlib.error):
            if repair_object(path, object_hash) is None:
                raise ValueError("shared market index is unsupported")
            result = MarketObject(path, object_hash)
        with _lock:
            _readers[key] = result
            if len(_readers) > 128:
                _readers.popitem(last=False)
    return result


class BackgroundIndexBuilder:
    """One cancellable lane for remaining, already-local history objects."""

    def __init__(self):
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.pending = deque()
        self.seen = set()
        self.thread = None
        self.completed = self.failed = 0

    def submit(self, objects):
        with self.lock:
            if self.stop.is_set():
                return
            for path, digest in objects:
                if str(path) not in self.seen:
                    self.seen.add(str(path))
                    self.pending.append((path, digest))
            if self.pending and self.thread is None:
                self.thread = threading.Thread(
                    target=self._run, name="replay-market-index", daemon=True
                )
                self.thread.start()

    def _run(self):
        while True:
            with self.lock:
                if self.stop.is_set() or not self.pending:
                    self.thread = None
                    return
                path, digest = self.pending.popleft()
            try:
                if (
                    Path(path).is_file()
                    and not index_path(path).exists()
                    and repair_object(path, digest, stop=self.stop) is not None
                ):
                    self.completed += 1
            except Exception:
                # Background cache failure is not a failed trading action.
                # Foreground access retries against the immutable source and
                # reports any source error through the existing replay path.
                self.failed += 1

    def close(self, timeout=1.0):
        self.stop.set()
        with self.lock:
            self.pending.clear()
            thread = self.thread
        if thread is not None:
            thread.join(timeout)


class MarketRange:
    def __init__(self, parts, offset_ms=0):
        self.parts = parts
        self.offset_ms = offset_ms
        self.ends = []
        count = 0
        for obj, first, last in parts:
            count += last - first
            self.ends.append(count)
        self.count = count
        self.base_ms = parts[0][0].base_ms if parts else 60000

    def descriptor(self):
        return {
            "version": VERSION,
            "offset_ms": self.offset_ms,
            "parts": [
                [obj.source_path, obj.object_hash, first, last]
                for obj, first, last in self.parts
            ],
        }

    def reference(self):
        return {
            "version": VERSION,
            "offset_ms": self.offset_ms,
            "parts": [
                [obj.object_hash, first, last] for obj, first, last in self.parts
            ],
        }

    @classmethod
    def restore(cls, value):
        if value["version"] != VERSION:
            raise ValueError("unsupported shared market descriptor")
        return cls(
            [
                (open_object(path, digest), first, last)
                for path, digest, first, last in value["parts"]
            ],
            value["offset_ms"],
        )

    def row(self, index):
        if not 0 <= index < self.count:
            raise IndexError(index)
        part = bisect_right(self.ends, index)
        obj, first, _ = self.parts[part]
        before = 0 if part == 0 else self.ends[part - 1]
        row = obj.row(first + index - before)
        if self.offset_ms:
            row = [row[0] + self.offset_ms, row[1] + self.offset_ms, *row[2:]]
        return row

    def summary(self, start, end):
        if not 0 <= start <= end <= self.count:
            raise ValueError("shared market range is outside its view")
        result, before = None, 0
        for (obj, first, _), after in zip(self.parts, self.ends):
            a, b = max(start, before), min(end, after)
            if a < b:
                result = merge(
                    result,
                    obj.summary(first + a - before, first + b - before),
                    self.base_ms,
                )
            before = after
        if result is not None and self.offset_ms:
            display = list(result[0])
            display[10] += self.offset_ms
            display[11] += self.offset_ms
            result = (tuple(display), *result[1:])
        return result

    def first_touch(self, price, below, start, end):
        def find(a, b):
            value = self.summary(a, b)
            if value is None or (value[0][2] > price if below else value[0][1] < price):
                return end
            if b - a == 1:
                return a
            middle = (a + b) // 2
            hit = find(a, middle)
            return hit if hit != end else find(middle, b)

        return find(start, end)
