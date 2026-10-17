"""Bounded immutable price columns for selected indicator input reads.

The existing verified market object remains the authority and fallback. Read
only ordinary float64 Parquet objects with a bounded row count; never persist
account state, open Parquet handles or a chart's mutable observations here.
"""

from collections import OrderedDict
from threading import RLock

MAX_COLUMN_ROWS = 65_536
MAX_COLUMN_BYTES = 32 * 1024 * 1024
MAX_COLUMN_OBJECTS = 4096
_lock = RLock()
_columns = OrderedDict()
_bytes = 0


def selected_closes(obj, offsets, cancelled):
    global _bytes
    if obj.count > MAX_COLUMN_ROWS:
        return None
    if cancelled.is_set():
        raise InterruptedError("indicator column read cancelled")
    key = (
        obj.source_path,
        obj.object_hash,
        obj.metadata["source_size"],
        obj.metadata["source_mtime"],
        obj.count,
    )
    with _lock:
        column = _columns.get(key)
        if column is not None:
            _columns.move_to_end(key)
    if column is None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            return None

        try:
            with pq.ParquetFile(obj.source_path) as source:
                if (
                    source.metadata.num_rows != obj.count
                    or source.schema_arrow.field("close").type != pa.float64()
                ):
                    return None
                column = source.read(columns=["close"]).column(0)
        except (OSError, pa.ArrowException, KeyError):
            # Legacy/unsupported objects retain the already-verified block
            # index path. No source repair or download is triggered here.
            return None
        if column.null_count or column.nbytes > MAX_COLUMN_BYTES:
            return None
        if cancelled.is_set():
            raise InterruptedError("indicator column read cancelled")
        with _lock:
            existing = _columns.get(key)
            if existing is None:
                _columns[key] = column
                _bytes += column.nbytes
                while _bytes > MAX_COLUMN_BYTES or len(_columns) > MAX_COLUMN_OBJECTS:
                    _, old = _columns.popitem(last=False)
                    _bytes -= old.nbytes
            else:
                column = existing
                _columns.move_to_end(key)
    if cancelled.is_set():
        raise InterruptedError("indicator column read cancelled")
    # Float64 values are the source type used by the archive writer. The index
    # normalizes those same values through decimal strings; float conversion
    # by close-source indicator math therefore has the identical result.
    return [
        str(0 if value == 0 else value) for value in column.take(offsets).to_pylist()
    ]
