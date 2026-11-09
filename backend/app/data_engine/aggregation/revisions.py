"""Readonly B130 adapter for the existing D126 durable revision store."""
from __future__ import annotations

from uuid import uuid4

from .blocks import BlockRevisionChanged, BlockRevisionRanges
from .core import InputRevision


def _series(row):
    from app.data_engine.data_manager.models import SeriesKey
    return SeriesKey(**{name: row[name] for name in (
        "symbol", "interval", "exchange", "market_type", "provider_id", "venue",
        "asset_class", "series_variant", "price_adjustment", "session_variant",
        "volume_semantics")})


def _disjoint_spans(receipts):
    bounds = [(row["start_ms"], row["end_ms"]) for row in receipts]
    if any(type(start) is not int or type(end) is not int or end < start for start, end in bounds):
        return ()
    spans = []
    for start, end in sorted(bounds):
        if spans and start <= spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))
    return tuple(spans)


class DurableBlockRevisions:
    def __init__(self, store):
        self.store = store
        # Cache values never cross process/storage replacement boundaries.
        self.domain = "d126:" + uuid4().hex
        self.revision = 0

    def validate_detached(self, revisions, *, acquisition_revision, read_scope=None):
        """Validate an immutable consumer value in one existing D126 read.

        This does not acquire blocks or consume the shared invalidation cursor.
        A detached prefix needs its source versions, not a new B130 lease/view
        with two global change polls for every live input.
        """
        if not 1 <= len(revisions) <= 32 or any(r.domain != self.domain for r in revisions):
            raise BlockRevisionChanged('detached source revision domain changed')
        keys = [(r.series.exchange, r.series.market_type, r.series.symbol, r.series.interval,
                 *r.series.identity.storage_values) for r in revisions]
        reader = read_scope if read_scope is not None and read_scope.store is self.store else self.store
        head, versions = reader.read_versions(keys)
        if (head < acquisition_revision or head < self.revision
                or tuple(versions) != tuple(r.version for r in revisions)):
            raise BlockRevisionChanged('detached source revision expired')

    def read(self, series, *, acquired_at=None):
        # Called serially by the manager, outside its state lock.
        keys = [(key.exchange, key.market_type, key.symbol, key.interval,
                 *key.identity.storage_values) for key in series]
        head, versions, rows, reset, receipts = self.store.read_block_changes(self.revision, keys)
        if acquired_at is not None and (head < acquired_at or any(v > acquired_at for v in versions)):
            raise BlockRevisionChanged("source changed since the initiating acquisition")
        by_series = {}
        for row in receipts:
            by_series.setdefault(_series(row), []).append(row)
        changes = []
        for row in rows:
            key, version = _series(row), row["revision"]
            precise = by_series.get(key, ())
            # The journal may be empty during migration, after a large commit,
            # or when an older writer installed triggers without footprints.
            # Check the chain from the old token through the coalesced head.
            if (precise and precise[-1]["revision"] == version
                    and precise[0]["previous_revision"] <= self.revision
                    and all(left["revision"] == right["previous_revision"]
                            for left, right in zip(precise, precise[1:]))):
                spans = _disjoint_spans(precise)
                if spans:
                    changes.append(BlockRevisionRanges(
                        InputRevision(key, self.domain, precise[0]["previous_revision"]),
                        InputRevision(key, self.domain, version), spans))
                    continue
            changes.append((key, self.domain, version))
        self.revision = head
        return (tuple(InputRevision(key, self.domain, version) for key, version in zip(series, versions)),
                changes, reset)
