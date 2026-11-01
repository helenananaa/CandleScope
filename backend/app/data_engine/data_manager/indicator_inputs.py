"""Canonical numeric inputs; formulas and output sharing belong to indicators."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import time

from app.indicator.query_contracts import IndicatorInputUnavailable, IndicatorQuery
from .models import BarData


@dataclass(frozen=True, slots=True)
class CanonicalIndicatorInput:
    request: IndicatorQuery
    bars: tuple[BarData, ...]
    slots: int
    revision: int
    binding: tuple[object, object, object]
    version: dict
    fingerprint: str


class IndicatorInputPort:
    def __init__(self, manager):
        self.manager = manager

    def _query(self, request, *, auto_backfill):
        key = request.source
        # Count-based pagination must fill the recursive seed from storage.
        # A range query can correctly consider a lone cached forming bar a
        # complete requested range; that is not a complete N-row input window.
        frontier_ms = request.through_ms if request.through_ms is not None else int(time.time() * 1000)
        # The cache's exclusive cursor is second-granular, including native1s.
        before_ms = (frontier_ms // 1000 + 1) * 1000
        return self.manager.query_before(key.symbol, key.interval, before_ms=before_ms,
                          limit=request.source_slots, exchange=key.exchange, market_type=key.market_type,
                          series_identity=key.identity, min_revision=request.minimum_revision,
                          auto_backfill=auto_backfill,
                          backfill_reason='indicator_numeric_warmup' if auto_backfill else None,
                          backfill_requester='indicator_numeric')

    def warmup(self, request):
        return self._query(request, auto_backfill=True)

    def capture(self, request: IndicatorQuery) -> CanonicalIndicatorInput:
        dm, key = self.manager, request.source
        storage, consumer, policy = dm.query_engine.storage, dm.cache.revision_consumer, dm.query_engine.history_policy
        if storage is None or consumer is None:
            raise IndicatorInputUnavailable('durable_input_unavailable')
        result = self._query(request, auto_backfill=False)
        version = result.metadata.get('stream_version', {})
        revision = result.metadata.get('storage_revision')
        if (result.complete is not True or result.retryable or result.missing_ranges or result.has_tail_gap
                or type(revision) is not int or revision < request.minimum_revision
                or version.get('stable') is not True or not result.bars
                or (result.has_more and len(result.bars) < request.source_slots)):
            raise IndicatorInputUnavailable('canonical_history_pending')
        rows = tuple(deepcopy(result.bars[-request.source_slots:]))
        if request.expected_bar is not None:
            expected = request.expected_bar
            actual = next((bar for bar in rows if bar.time == expected.time), None)
            if actual is None or actual.is_closed != expected.is_closed:
                raise IndicatorInputUnavailable('event_frontier_superseded')
            if expected.is_closed and any(getattr(actual, field) != getattr(expected, field)
                    for field in ('open', 'high', 'low', 'close', 'volume')):
                raise IndicatorInputUnavailable('event_values_superseded')
        closed = tuple(bar for bar in rows if bar.is_closed)
        if not closed or any(not bar.trusted_final for bar in closed):
            raise IndicatorInputUnavailable('confirmed_history_unverified')
        value = {'seed_policy': request.seed_policy, 'source_slots': request.source_slots,
                 'slots': len(rows), 'bars': [bar.to_dict() for bar in closed]}
        fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                                allow_nan=False).encode()).hexdigest()
        captured = CanonicalIndicatorInput(request, closed, len(rows), revision,
                                           (storage, consumer, policy), deepcopy(version), fingerprint)
        self.validate(captured)
        return captured

    def validate(self, captured: CanonicalIndicatorInput) -> None:
        dm = self.manager
        storage, consumer, policy = captured.binding
        def bound():
            return (dm.query_engine.storage is storage and dm.cache.revision_consumer is consumer
                    and dm.query_engine.history_policy is policy and not dm.shared_blocks.snapshot()['closed'])
        if not bound():
            raise IndicatorInputUnavailable('input_binding_changed')
        consumer.sync(force=True)
        after = dm.event_bus.stream_versions.snapshot(captured.request.source)
        if (not bound() or consumer.conflicts(captured.revision, captured.request.source)
                or after.get('stable') is not True
                or any(after.get(field) != captured.version.get(field) for field in ('epoch', 'generation', 'barrier'))):
            raise IndicatorInputUnavailable('canonical_revision_changed')
