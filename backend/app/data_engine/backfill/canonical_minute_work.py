"""Coordinate native minute coverage through SQLite commit, not just HTTP receipt."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from itertools import groupby
import time

from app.core.executors import run_storage
from app.data_engine.series_identity import identity_from_metadata
from app.data_engine.storage.revisions import StaleAcquisition, current_acquisition, series_values

from .mixed_plan import reusable_component

STEP = 60_000
FIELDS = ("open", "high", "low", "close", "volume",
          "quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
MAX_SLOTS = 32_768


def _windows(task):
    return task.metadata.get("mixed_fetch_windows", ((task.start_ms, task.end_ms),))


class CanonicalMinuteWork:
    def __init__(self):
        self._active = {}

    async def claim(self, key, windows):
        """Acquire atomically so overlapping batches cannot wait on each other.

        Claims are bounded by active runs. A completion event is only a wakeup,
        including after failure/cancellation; consumers check the database.
        """
        while True:
            active = self._active.setdefault(key, {})
            overlap = tuple(event for event, spans in active.items()
                            if any(first <= end and start <= last
                                   for start, end in spans for first, last in windows))
            if not overlap:
                event = asyncio.Event()
                active[event] = windows
                return key, event
            await asyncio.gather(*(event.wait() for event in overlap))

    def release(self, claim):
        key, event = claim
        active = self._active[key]
        del active[event]
        if not active:
            del self._active[key]
        event.set()


def eligible_tasks(engine, plan):
    if (not plan.custom_intervals or len(plan.decompositions) != 1
            or engine._cfg.alignment_epoch_ms or engine._cfg.custom_alignment_mode != 'epoch'
            or engine.reconciler._custom_aggregator is not None
            or engine.reconciler._custom_dedup_fn is not None
            or not callable(getattr(engine._storage, 'query_canonical_page', None))
            or current_acquisition() is None
            or not (plan.mixed_binding or all(t.interval == '1m' for t in plan.tasks))):
        return []
    target = plan.custom_intervals[0]
    now_ms = int(time.time()*1000)
    tasks = [t for t in plan.tasks
             if (t.exchange, t.market_type, t.interval) == ('binance', 'futures', '1m')
             and t.metadata.get('custom_interval') == target
             and 0 <= t.start_ms <= t.end_ms and not (t.start_ms % STEP or t.end_ms % STEP)
             and t.end_ms + STEP <= now_ms
             and ((identity := identity_from_metadata(t.exchange, t.metadata)) is None
                  or identity.is_legacy_default_for(t.exchange))]
    if not tasks or len({t.symbol for t in tasks}) != 1:
        return []
    if not plan.mixed_binding and (len(tasks) != len(plan.tasks) or plan.derived_source_windows):
        return []
    if sum((t.end_ms-t.start_ms)//STEP+1 for t in tasks) > MAX_SLOTS:
        return []
    return tasks


async def reuse_committed_minutes(storage, plan, tasks, key):
    """Recheck a queued plan before network I/O; keep the reducer's full cover."""
    scope = current_acquisition()
    head, (version,) = await run_storage(storage.revision_store.read_versions, (key,))
    if version <= scope.revision:
        return 0
    now_ms = int(time.time()*1000)
    replacements = {}
    reused = 0
    for task in tasks:
        missing = []
        for first, last in _windows(task):
            cursor = first
            trusted = set()
            while cursor <= last:
                rows = await storage.query_canonical_page(task.symbol, '1m', cursor, last,
                    exchange=task.exchange, market_type=task.market_type)
                if not rows:
                    break
                opens = [row.get('open_time') for row in rows]
                if (len(opens) > 256 or any(type(at) is not int or not cursor <= at <= last for at in opens)
                        or any(a >= b for a, b in zip(opens, opens[1:]))):
                    raise StaleAcquisition('minute coverage read differs from its bounded source window')
                trusted.update(r['open_time'] for r in rows if reusable_component(r, STEP, now_ms, FIELDS))
                if len(rows) < 256:
                    break
                cursor = opens[-1]+1
            for present, slots in groupby(range(first, last+1, STEP), trusted.__contains__):
                if present:
                    reused += sum(1 for _ in slots)
                else:
                    pending = list(slots)
                    missing.append((pending[0], pending[-1]))
        if missing == list(_windows(task)):
            continue
        if not missing:
            replacements[id(task)] = None
            continue
        first, last = missing[0][0], missing[-1][1]
        metadata = {**task.metadata, 'ledger_range': {'start_ms': first, 'end_ms': last},
                    'mixed_fetch_windows': missing}
        replacements[id(task)] = replace(task, start_ms=first, end_ms=last,
                                         estimated_bars=(last-first)//STEP+1, metadata=metadata)
    if not reused:
        return 0
    if not plan.mixed_binding:
        plan.derived_source_windows = list(tasks)
    plan.tasks = [item for task in plan.tasks if (item := replacements.get(id(task), task)) is not None]
    plan.estimated_bars = sum(task.estimated_bars for task in plan.tasks)
    plan.estimated_requests = len(plan.tasks)
    # Only this minute source may use the new read head. Target and coarser
    # inputs retain their original checks and deletion permission is unchanged.
    # The reducer re-reads canonical rows, including mixed precedence checks.
    scope.minute_read_heads[key] = head
    return reused


def minute_key(task):
    return series_values(task.symbol, '1m', task.exchange, task.market_type)


def claimed_windows(tasks):
    return tuple(window for task in tasks for window in _windows(task))
