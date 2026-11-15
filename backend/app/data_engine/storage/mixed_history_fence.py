"""Range proof for qualified mixed canonical reductions, using D126 receipts.

Capture the target before fetching. After native commits, capture a computation
head before any canonical read/precedence check. The final writer rejects every
intersecting source/target mutation since that head, including finer insertions.
Unrelated live tail writes are allowed only with a complete receipt suffix.
"""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.data_engine.interval_resolution import IntervalResolver
from .derived_history_fence import check_deletions
from .native_history_fence import fingerprint
from .revisions import IDENTITY_COLUMNS, StaleAcquisition, block_change_receipts, current_revision, series_change, series_values

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
            raise StaleAcquisition('mixed target changed during acquisition')


@dataclass
class MixedComputation:
    target: MixedTarget
    revision: int

    def check(self, conn, scope):
        self.target.check(conn, scope)
        keys = {*self.target.dependencies, self.target.key}
        changed = {key for key in keys if (row := series_change(conn, key)) is not None
                   and row['revision'] > self.revision}
        if not changed:
            return
        receipts = block_change_receipts(conn, self.revision, current_revision(conn))
        if not receipts:
            raise StaleAcquisition('mixed computation receipt suffix is unavailable')
        for receipt in receipts:
            if (tuple(receipt[name] for name in IDENTITY_COLUMNS) in changed
                    and receipt['start_ms'] < self.target.end + self.target.duration
                    and receipt['end_ms'] >= self.target.start):
                raise StaleAcquisition('mixed canonical inputs or target changed during computation')


def capture_targets(store, scope, plan):
    if store is None or scope is None or scope.mixed_target_views or plan.mixed_binding is None:
        return
    binding = plan.mixed_binding
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
            scope.check(conn, key)
            view = MixedTarget(key, dependencies, start, stop-duration, duration,
                               fingerprint(conn, key, start, stop-duration))
            view.check(conn, scope)
            scope.mixed_target_views.append(view)


def capture_computations(store, scope, decomp):
    if store is None or scope is None or decomp.composition_policy is None:
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
