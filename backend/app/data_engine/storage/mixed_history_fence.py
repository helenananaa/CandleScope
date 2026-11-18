"""Range proof for qualified mixed canonical reductions, using D126 receipts.

Capture the target before fetching. After native commits, capture a computation
head before any canonical read/precedence check. The final writer rejects every
intersecting source/target mutation since that head, including finer insertions.
Unrelated live tail writes require a complete receipt suffix or the exact dense
canonical inputs consumed by the qualified built-in 1m reducer.
"""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable

from app.data_engine.interval_resolution import IntervalResolver
from app.data_engine.interval_policy import parse_interval_spec
from .range_changes import check_range_since
from .derived_history_fence import check_deletions
from .native_history_fence import fingerprint, fingerprint_rows, NativeHistoryView, MAX_SLOTS
from .revisions import (
    IDENTITY_COLUMNS,
    StaleAcquisition,
    block_change_receipts,
    current_revision,
    series_change,
    series_range_spans,
    series_values,
    span_overlaps_half_open,
)

_current = ContextVar('mixed_canonical_computation', default=())


@dataclass
class MixedTarget:
    key: tuple
    dependencies: tuple
    start: int
    end: int
    duration: int
    digest: bytes

    def check(self, conn, scope):
        check_deletions(conn, scope, self.key, *self.dependencies)
        if fingerprint(conn, self.key, self.start, self.end) != self.digest:
            raise StaleAcquisition('mixed target changed during acquisition', details={
                'reason': 'target_window_changed', 'acquisition_revision': scope.revision,
                'head_revision': current_revision(conn), 'interval': self.key[3],
                'start_ms': self.start, 'end_ms': self.end})


@dataclass
class MixedComputation:
    target: MixedTarget
    revision: int
    canonical_input: NativeHistoryView | None = None
    input_owner_check: Callable[[], None] | None = None

    def check(self, conn, scope):
        if self.canonical_input is not None and self.input_owner_check is not None:
            self.input_owner_check()
        self.target.check(conn, scope)
        if self.canonical_input is not None:
            # This is the digest of the exact dense rows actually consumed,
            # not a fresh post-compute snapshot that could bless stale output.
            self.canonical_input.check(conn, scope)
            return
        head = current_revision(conn)
        keys = (*self.target.dependencies, self.target.key)
        changed = [key for key in keys if (row := series_change(conn, key)) is not None
                   and row['revision'] > self.revision]
        if not changed:
            return
        receipts = block_change_receipts(conn, self.revision, head)
        if receipts:
            changed_set = set(changed)
            for receipt in receipts:
                key = tuple(receipt[name] for name in IDENTITY_COLUMNS)
                if key == self.target.key and receipt['revision'] <= scope.accepted.get(key, self.revision):
                    continue  # A previously checked transaction of this computation.
                if (key in changed_set
                        and receipt['start_ms'] < self.target.end + self.target.duration
                        and receipt['end_ms'] >= self.target.start):
                    raise StaleAcquisition('mixed canonical inputs or target changed during computation', details={
                        'reason': 'mixed_overlapping_change', 'acquisition_revision': scope.revision,
                        'base_revision': self.revision, 'head_revision': head,
                        'change_revision': receipt['revision'], 'change_start_ms': receipt['start_ms'],
                        'change_end_ms': receipt['end_ms']})
            return
        stop_ms = self.target.end + self.target.duration
        for key in changed:
            spans = series_range_spans(conn, key, self.revision, head)
            if spans is None:
                raise StaleAcquisition('mixed computation receipt suffix is unavailable', details={
                    'reason': 'mixed_receipt_suffix_unavailable', 'acquisition_revision': scope.revision,
                    'base_revision': self.revision, 'head_revision': head,
                    'start_ms': self.target.start, 'end_ms': stop_ms})
            accepted_rev = scope.accepted.get(key, self.revision)
            for span in spans:
                if key == self.target.key and int(span['last_revision']) <= accepted_rev:
                    continue
                if span_overlaps_half_open(span, self.target.start, stop_ms):
                    raise StaleAcquisition('mixed canonical inputs or target changed during computation', details={
                        'reason': 'mixed_overlapping_change', 'acquisition_revision': scope.revision,
                        'base_revision': self.revision, 'head_revision': head,
                        'change_revision': int(span['last_revision']), 'change_start_ms': int(span['start_ms']),
                        'change_end_ms': int(span['end_ms'])})


def _check_initial_range(conn, scope, keys, start, stop):
    by_head = {}
    for key in keys:
        by_head.setdefault(scope.minute_read_heads.get(key, scope.revision), set()).add(key)
    for revision, grouped in by_head.items():
        check_range_since(conn, grouped, start, stop, revision)


def capture_targets(store, scope, plan, allow_standard=False):
    if store is None or scope is None or scope.mixed_target_views:
        return
    binding = plan.mixed_binding
    if binding is None:
        if allow_standard:
            capture_standard_targets(store, scope, plan)
        return
    binding.validate()
    target = binding.target
    if target.exchange != 'binance' or target.market_type != 'futures' or not target.identity.is_legacy_default_for('binance'):
        return
    for decomp in plan.decompositions:
        if decomp.composition_policy is None or decomp.custom_interval != target.interval:
            continue
        start, stop = decomp.composition_target_range
        duration = decomp.custom_duration_ms
        if not 0 < (stop - start) // duration <= 128:
            continue
        declaration = IntervalResolver().history_composition_routes(
            exchange=target.exchange, market_type=target.market_type, interval=target.interval)
        if declaration is None or declaration[0] != decomp.composition_policy:
            continue
        key = series_values(target.symbol, target.interval, target.exchange, target.market_type)
        dependencies = tuple(series_values(target.symbol, route.canonical_interval, target.exchange, target.market_type)
                             for route in declaration[2])
        with scope.lock, closing(store.connect()) as conn, conn:
            conn.execute('BEGIN')
            check_deletions(conn, scope, key, *dependencies)
            _check_initial_range(conn, scope, {*dependencies, key}, start, stop)
            view = MixedTarget(key, dependencies, start, stop-duration, duration,
                               fingerprint(conn, key, start, stop-duration))
            view.check(conn, scope)
            scope.mixed_target_views.append(view)


def capture_computations(store, scope, decomp):
    if store is None or scope is None:
        return ()
    views = []
    with scope.lock, closing(store.connect()) as conn, conn:
        conn.execute('BEGIN')
        head = current_revision(conn)
        for target in scope.mixed_target_views:
            if target.key[3] == decomp.custom_interval:
                target.check(conn, scope)
                views.append(MixedComputation(target, head))
    return tuple(views)


def seal_standard_inputs(symbol, interval, exchange, market_type, rows, owner_check):
    """Bind bounded dense 1m inputs used by the qualified built-in reducer.

    True mixed grids, sparse/partial windows and larger reductions retain
    their existing receipt proof. No new fetching or mutable market owner.
    """
    sealed = 0
    for view in _current.get():
        target = view.target
        if ((exchange, market_type, symbol, interval) != target.key[:4]
                or len(target.dependencies) != 1 or target.dependencies[0][3] != '1m'):
            continue
        start, stop = target.start, target.end + target.duration
        count = (stop-start)//60_000
        if not 0 < count <= MAX_SLOTS or len(rows) != count:
            continue
        ordered = sorted(rows, key=lambda row: row['open_time'])
        if any(row.get('interval') != '1m' or row['open_time'] != start+i*60_000
               or row['close_time'] != start+(i+1)*60_000-1 for i, row in enumerate(ordered)):
            continue
        view.canonical_input = NativeHistoryView(target.dependencies[0], start,
            stop-60_000, fingerprint_rows(ordered))
        view.input_owner_check = owner_check
        sealed += 1
    return sealed


def matching_computation(scope, key, rows, source):
    if source != 'backfill_aggregated' or not rows:
        return None
    return next((view for view in _current.get() if view.target in scope.mixed_target_views
        and view.target.key == key and all(view.target.start <= row['open_time'] <= view.target.end
            and row['open_time'] % view.target.duration == 0
            and row['close_time'] == row['open_time'] + view.target.duration - 1 for row in rows)), None)


@contextmanager
def computation_scope(views):
    token = _current.set(views)
    try:
        yield
    finally:
        _current.reset(token)


def capture_standard_targets(store, scope, plan):
    """The built-in fixed 1m reducer uses only its canonical minute inputs.

    Actual tasks establish initial permission. Routing later extends it to the
    bounded owned archive/REST footprints before acquisition starts.
    Other identities, grids, calendars and custom reducers stay on the strict path.
    """
    for decomp in plan.decompositions:
        spec = parse_interval_spec(decomp.custom_interval)
        tasks = [task for task in (*plan.tasks, *plan.derived_source_windows)
                 if task.metadata.get('custom_interval') == decomp.custom_interval]
        if (spec is None or spec.phase_ms or spec.calendar_unit is not None or not tasks
                or spec.nominal_ms <= 60000 or spec.nominal_ms % 60000
                or any(task.exchange != 'binance' or task.market_type != 'futures' or task.interval != '1m'
                       for task in tasks)):
            continue
        from app.data_engine.series_identity import identity_from_metadata
        if any((identity := identity_from_metadata(task.exchange, task.metadata)) is not None
               and not identity.is_legacy_default_for('binance') for task in tasks):
            continue
        first, last = min(task.start_ms for task in tasks), max(task.end_ms for task in tasks)
        start, end = max(0, spec.floor_ms(first)), spec.floor_ms(last)
        if not 0 < (end-start)//spec.nominal_ms+1 <= 512:
            continue
        key = series_values(tasks[0].symbol, spec.canonical, 'binance', 'futures')
        dependencies = (series_values(tasks[0].symbol, '1m', 'binance', 'futures'),)
        with scope.lock, closing(store.connect()) as conn, conn:
            conn.execute('BEGIN')
            check_deletions(conn, scope, key, *dependencies)
            _check_initial_range(conn, scope, {*dependencies, key}, start, end+spec.nominal_ms)
            view = MixedTarget(key, dependencies, start, end, spec.nominal_ms, fingerprint(conn, key, start, end))
            view.check(conn, scope)
            scope.mixed_target_views.append(view)


def affected_targets(scope, key, rows):
    if not rows:
        return ()
    first, last = min(row['open_time'] for row in rows), max(row['close_time'] for row in rows)
    return tuple(view for view in scope.mixed_target_views if key in view.dependencies
                 and first < view.end+view.duration and last >= view.start)


def extend_standard_targets(store, scope, windows):
    """Add only the actual routed 1m write footprint to a builtin target proof."""
    if store is None or scope is None or not scope.mixed_target_views:
        return
    with scope.lock, closing(store.connect()) as conn, conn:
        conn.execute('BEGIN')
        for target in scope.mixed_target_views:
            if len(target.dependencies) != 1 or target.dependencies[0][3] != '1m':
                continue
            selected = [window for window in windows if window.exchange == target.key[0]
                and window.market_type == target.key[1] and window.symbol == target.key[2]
                and window.interval == '1m' and window.metadata.get('custom_interval') == target.key[3]]
            if not selected:
                continue
            start = min(target.start, min(window.start_ms//target.duration*target.duration for window in selected))
            end = max(target.end, max(window.end_ms//target.duration*target.duration for window in selected))
            if (end-start)//target.duration+1 > 512:
                continue
            target.check(conn, scope)
            _check_initial_range(conn, scope, {target.key, *target.dependencies}, start, end+target.duration)
            target.start, target.end = start, end
            target.digest = fingerprint(conn, target.key, start, end)
