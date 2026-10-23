"""Detached complete replay views, reused while the stored result is unchanged."""
from collections import OrderedDict
import json

from .native import MAX_BYTES, digest, encoded


class ResultViews:
    """Keep at most two views and 64 MiB of encoded JSON, not unbounded history."""
    def __init__(self, *, max_bytes=MAX_BYTES, capacity=2):
        self.max_bytes = max_bytes
        self.capacity = capacity
        self.entries = OrderedDict()
        self.bytes = 0

    def discard(self, replay_id=None):
        for key in list(self.entries):
            if replay_id is None or key[0] == replay_id:
                _, raw = self.entries.pop(key)
                self.bytes -= len(raw)

    def read(self, key, body, bars):
        cached = self.entries.get(key)
        if cached is not None and cached[0] is body:
            self.entries.move_to_end(key)
            return json.loads(cached[1])
        if cached is not None:
            self.bytes -= len(self.entries.pop(key)[1])
        value = {**body, "bars": bars}
        value["report_hash"] = digest(value)
        raw = encoded(value).encode("utf-8")
        if len(raw) <= self.max_bytes and self.capacity > 0:
            while self.entries and (len(self.entries) >= self.capacity or self.bytes + len(raw) > self.max_bytes):
                _, (_, removed) = self.entries.popitem(last=False)
                self.bytes -= len(removed)
            self.entries[key] = (body, raw)
            self.bytes += len(raw)
        # Decode on every read so a caller cannot mutate the journal or another
        # caller's view. No unchanged arrays are walked and hashed again.
        return json.loads(raw)
