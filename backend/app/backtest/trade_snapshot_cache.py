"""Worker-owned bounded preparation cache, keyed by full frozen archive identity.

Only internally generated pickle bytes are retained, never disk or wire input.
Each borrower gets independent mutable MarketEvents. Archive pins still validate
the source on every borrow; runtime must also freeze and check run identity first.
"""
from collections import OrderedDict
from concurrent.futures import Future
import io
import pickle
import threading

from app.market_dataset.snapshot import MarketDatasetError
from .spawn_events import pack_events


class _TooLarge(Exception):
    pass


class _BoundedBuffer(io.BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def write(self, value):
        if self.tell() + len(value) > self.limit:
            raise _TooLarge()
        return super().write(value)


class TradeSnapshotCache:
    def __init__(self, max_bytes, max_entries=2):
        self.max_bytes = max(0, int(max_bytes))
        self.max_entries = max(0, int(max_entries))
        self._lock = threading.Lock()
        self._entries = OrderedDict()
        self._pending = {}
        self._bytes = 0
        self._hits = self._misses = self._waits = 0

    @property
    def stats(self):
        with self._lock:
            return dict(hits=self._hits, misses=self._misses, waits=self._waits,
                        bytes=self._bytes, entries=len(self._entries))

    def close(self):
        with self._lock:
            self.max_bytes = 0
            self._entries.clear()
            self._bytes = 0

    def read(self, archive, dataset, *, max_events, loader):
        if dataset.row_count > max_events:
            raise MarketDatasetError("aggregate-trade event count exceeds frozen ceiling", code="BUDGET_EXCEEDED")
        if not self.max_bytes or not self.max_entries:
            return loader()
        token = archive.pin_dataset(dataset)
        try:
            key = (archive, dataset)
            with self._lock:
                raw = self._entries.get(key)
                if raw is not None:
                    self._hits += 1
                    self._entries.move_to_end(key)
                    future, owner = None, False
                else:
                    future = self._pending.get(key)
                    owner = future is None
                    if owner:
                        self._misses += 1
                        future = self._pending[key] = Future()
                    else:
                        self._waits += 1
            if raw is not None:
                return pickle.loads(raw)
            if not owner:
                raw = future.result()
                return loader() if raw is None else pickle.loads(raw)
            try:
                events = loader()
                with _BoundedBuffer(self.max_bytes) as buffer:
                    try:
                        pickle.Pickler(buffer, protocol=5).dump(pack_events(events))
                        raw = buffer.getvalue()
                    except _TooLarge:
                        raw = None
                if raw is not None:
                    with self._lock:
                        if len(raw) <= self.max_bytes:
                            while self._entries and (len(self._entries) >= self.max_entries
                                    or self._bytes + len(raw) > self.max_bytes):
                                _, removed = self._entries.popitem(last=False)
                                self._bytes -= len(removed)
                            self._entries[key] = raw
                            self._bytes += len(raw)
                future.set_result(raw)
                return events
            except BaseException as exc:
                future.set_exception(exc)
                raise
            finally:
                with self._lock:
                    self._pending.pop(key, None)
        finally:
            archive.release_dataset(token)
