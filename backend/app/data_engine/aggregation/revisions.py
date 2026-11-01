"""Readonly B130 adapter for the existing D126 durable revision store."""
from __future__ import annotations

from uuid import uuid4

from .blocks import BlockRevisionChanged
from .core import InputRevision


class DurableBlockRevisions:
    def __init__(self, store):
        self.store = store
        # Cache values never cross process/storage replacement boundaries.
        self.domain = "d126:" + uuid4().hex
        self.revision = 0

    def read(self, series, *, acquired_at=None):
        # Called serially by the manager, outside its state lock. The change
        # receipt is coalesced by series; its range is not a precise edit log.
        from app.data_engine.data_manager.models import SeriesKey
        batch = self.store.changes_since(self.revision)
        keys = [(key.exchange, key.market_type, key.symbol, key.interval,
                 *key.identity.storage_values) for key in series]
        head, versions = self.store.read_versions(keys) if keys else (int(batch["revision"]), ())
        if acquired_at is not None and (head < acquired_at or any(v > acquired_at for v in versions)):
            raise BlockRevisionChanged("source changed since the initiating acquisition")
        changes = tuple((SeriesKey(**{name: row[name] for name in (
            "symbol", "interval", "exchange", "market_type", "provider_id", "venue",
            "asset_class", "series_variant", "price_adjustment", "session_variant",
            "volume_semantics")}), self.domain, int(row["revision"])) for row in batch["changes"])
        reset = batch["reset"] or head < self.revision
        self.revision = int(batch["revision"])
        return tuple(InputRevision(key, self.domain, version) for key, version in zip(series, versions)), changes, reset
