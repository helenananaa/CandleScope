"""DataManager-owned transactional provenance for a chart calculation.

Only bounded watch receipts live here. Market rows, SDK output and mathematical
history remain with the existing source/runtime. Old and candidate watches
overlap during an explicit full-origin generation replacement.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from app.core.executors import run_storage
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.interval_policy import compute_bucket_end_ms, parse_interval_ms
from app.data_engine.storage.prefix_watches import PrefixContinuityUnavailable
from app.data_engine.storage.revisions import StaleAcquisition
from .calculation_owner import CalculationOwnerError
from .series_reference import identity_for_meta


def _source_error(error):
    return CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_UNAVAILABLE'
        if isinstance(error,PrefixContinuityUnavailable) else 'INDICATOR_CALCULATION_SOURCE_CHANGED')


@dataclass
class _Watch:
    receipt: object
    latest: object
    clock: object


class ChartSource:
    def __init__(self, manager, owner_id, meta):
        self.api = getattr(getattr(manager,'bars',None),'prefixes',None)
        if self.api is None or any(not callable(getattr(self.api,name,None)) for name in
                ('register_family','prepare','query_proof','correction_cursor','inspect','commit','release')):
            raise CalculationOwnerError('INDICATOR_CALCULATION_SOURCE_UNAVAILABLE')
        self.owner_id = owner_id
        self.key = SeriesKey.create(meta['symbol'],meta['interval'],exchange=meta['exchange'],
            market_type=meta['market_type'],identity=identity_for_meta(meta))
        self.active = None
        self.watches = {}

    def end_ms(self, seconds):
        return compute_bucket_end_ms(seconds*1000,parse_interval_ms(self.key.interval),
                                     interval=self.key.interval)-1

    def needs_rebuild(self):
        if self.active is None: return True
        try:
            watch = self.active
            row = self.api.inspect(watch.receipt.owner)
            if row is None or row['incarnation'] != watch.receipt.incarnation:
                raise PrefixContinuityUnavailable('source watch continuity was lost')
            if row['version'] < watch.receipt.version or row['storage_revision'] < watch.receipt.storage_revision:
                raise PrefixContinuityUnavailable('source watch regressed')
            return (self.api.correction_cursor(self.key) != watch.clock or
                (row['version'] != watch.receipt.version and
                 (row['dirty_from_ms'] is None or row['dirty_from_ms'] <= watch.receipt.through_ms)))
        except StaleAcquisition as error:
            raise _source_error(error) from error

    async def acquire(self, *, start_ms, through_ms, rebuild, captured_open_ms=None):
        await self.retire_unused()
        watch = self.active
        try:
            clock = self.api.correction_cursor(self.key)
            if rebuild or watch is None:
                if len(self.watches) >= 2:
                    raise PrefixContinuityUnavailable('source cleanup still owns the watch budget')
                receipt = await run_storage(self.api.register_family,
                    'indicator:'+self.owner_id+':'+uuid4().hex,self.key,
                    from_ms=start_ms,committed_through_ms=start_ms-1)
                watch = _Watch(receipt,receipt,clock)
                self.watches[receipt.owner] = watch
            protected_through = max(through_ms, watch.latest.through_ms)
            if captured_open_ms is not None:
                # This slot comes from the ordered observation, not the query.
                # A previous acquisition may have watched its canonical value.
                protected_through = min(protected_through, captured_open_ms - 1)
            proof = await run_storage(self.api.prepare,watch.receipt,
                committed_through_ms=watch.receipt.through_ms,
                through_ms=protected_through)
            watch.latest = proof
            return SourceAcquisition(self,watch,proof,clock)
        except StaleAcquisition as error:
            raise _source_error(error) from error

    async def retire_unused(self):
        for key,watch in tuple(self.watches.items()):
            if watch is self.active: continue
            await self._release(watch)
            del self.watches[key]

    async def _release(self, watch):
        try:
            await run_storage(self.api.release,watch.latest)
        except PrefixContinuityUnavailable:
            # An externally removed watch has no remaining owned resource.
            # A replacement incarnation must never be released on its behalf.
            if await run_storage(self.api.inspect,watch.latest.owner) is not None:
                raise

    async def close(self):
        # The application owner drains all admitted work before this call.
        for key,watch in tuple(self.watches.items()):
            await self._release(watch)
            del self.watches[key]
        self.active = None


class SourceAcquisition:
    def __init__(self, source, watch, proof, clock):
        self.source,self.watch,self.proof,self.clock = source,watch,proof,clock
        self.acknowledged = watch.receipt.through_ms

    async def query_proof(self, result):
        try:
            self.proof = await run_storage(self.source.api.query_proof,self.proof,
                committed_through_ms=self.watch.receipt.through_ms,
                queried_revision=result.metadata.get('storage_revision'))
            self.watch.latest = self.proof
        except StaleAcquisition as error:
            raise _source_error(error) from error

    def closed(self, seconds):
        if seconds: self.acknowledged = self.source.end_ms(seconds)

    def commit(self, publish):
        # Only this short publication/acknowledgement holds the source fence.
        # There is no await, runtime call, serialization or history copy here.
        try:
            self.source.api.commit(self.proof,publish,committed_through_ms=self.acknowledged,
                series=self.source.key,source_cursor=self.clock)
            self.watch.receipt = replace(self.proof,through_ms=self.acknowledged)
            self.watch.clock = self.clock
            self.source.active = self.watch
        except StaleAcquisition as error:
            raise _source_error(error) from error
