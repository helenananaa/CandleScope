"""Detached complete replay views, reused while the stored result is unchanged."""
from collections import OrderedDict
import json

from .native import MAX_BYTES, encoded
from .native_checkpoint import checkpoint_measure, detached_json


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
        value["report_hash"], source_bytes = checkpoint_measure(value)
        if self.capacity <= 0 or source_bytes > self.max_bytes:
            # Hashing already counted the complete body. An oversized value
            # cannot use this cache; avoid encoding a second full temporary
            # string before building the caller's independent containers.
            return detached_json(value, preserve_aliases=False)
        text = encoded(value)
        size = len(text)
        if self.capacity > 0 and size <= self.max_bytes:
            # Count non-ASCII UTF-8 in bounded chunks before deciding whether
            # to retain bytes. Oversized complete views decode the existing
            # text directly instead of holding a second full byte buffer.
            if not text.isascii():
                size = sum(len(text[start:start+65536].encode("utf-8"))
                           for start in range(0, len(text), 65536))
        if self.capacity > 0 and size <= self.max_bytes:
            raw = text.encode("utf-8")
            while self.entries and (len(self.entries) >= self.capacity or self.bytes + size > self.max_bytes):
                _, (_, removed) = self.entries.popitem(last=False)
                self.bytes -= len(removed)
            self.entries[key] = (body, raw)
            self.bytes += size
            return json.loads(text)
        # The journal and bars are normalized JSON. Oversized public reads need
        # independent containers, but can retain immutable scalar values instead
        # of holding full JSON text while decoding another complete graph.
        # Do not preserve aliases: mutating one occurrence must leave every
        # other occurrence, the journal and earlier callers unchanged.
        del text
        return detached_json(value, preserve_aliases=False)
