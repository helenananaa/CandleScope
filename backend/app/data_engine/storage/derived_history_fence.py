"""Bounded dependency views for dense Binance subminute REST reductions.

Target permission is captured before HTTP. Actual canonical inputs are compared
with the fetched reduction inputs before CPU work, then rechecked in the writer
transaction. Other providers, sparse inputs and larger jobs retain D126's strict
family fence. A source label alone never creates a dependency view.
"""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.data_engine.kline_quality import source_is_trusted_final
from .native_history_fence import FIELDS, MAX_SLOTS, MAX_WINDOWS, fingerprint
from .revisions import IDENTITY_COLUMNS, StaleAcquisition, series_values

_computation = ContextVar('derived_history_computation', default=())


def check_deletions(conn, scope, *keys):
    floor = scope.revision if scope.delete_revision is None else scope.delete_revision
    for key in keys:
        row = conn.execute('SELECT revision FROM kline_delete_permissions WHERE ' +
                           ' AND '.join(f'{name}=?' for name in IDENTITY_COLUMNS), key).fetchone()
        if row is not None and int(row[0]) > floor:
            raise StaleAcquisition('derived history was deleted after request permission')


@dataclass
class TargetView:
    key: tuple
    input_key: tuple
    start: int
    end: int
    duration: int
    digest: bytes

    def check(self, conn, scope):
        check_deletions(conn, scope, self.key, self.input_key)
        if fingerprint(conn, self.key, self.start, self.end) != self.digest:
            raise StaleAcquisition('derived target changed during acquisition')


@dataclass
class ComputationView:
    target: TargetView
    start: int
    end: int
    digest: bytes

    def check(self, conn, scope):
        self.target.check(conn, scope)
        if fingerprint(conn, self.target.input_key, self.start, self.end) != self.digest:
            raise StaleAcquisition('derived canonical inputs changed during computation')


def capture_targets(store, scope, plan):
    if store is None or scope is None or scope.derived_target_views:
        return
    eligible = {d.custom_interval: d.custom_duration_ms for d in plan.decompositions
                if d.alignment_epoch_ms == 0 and 1000 < d.custom_duration_ms < 60000
                and d.custom_duration_ms % 1000 == 0
                and len(d.components) == 1 and d.components[0].interval == '1s'}
    ranges = {}
    for task in plan.tasks:
        iv = task.metadata.get('custom_interval')
        if (iv not in eligible or task.exchange != 'binance' or task.market_type != 'spot'
                or task.interval != '1s'):
            continue
        key = series_values(task.symbol, iv, 'binance', 'spot')
        duration = eligible[iv]
        start, end = task.start_ms // duration * duration, task.end_ms // duration * duration
        old = ranges.get(key, (start, end, duration))
        ranges[key] = min(old[0], start), max(old[1], end), duration
    views, slots = [], 0
    with scope.lock, closing(store.connect()) as conn, conn:
        conn.execute('BEGIN')
        for key, (start, end, duration) in ranges.items():
            count = (end + duration - start) // 1000
            if len(views) >= MAX_WINDOWS or slots + count > MAX_SLOTS:
                continue
            # Never renew an old job's permission by snapshotting after a change.
            scope.check(conn, key)
            view = TargetView(key, series_values(key[2], '1s', 'binance', 'spot'),
                              start, end, duration, fingerprint(conn, key, start, end))
            view.check(conn, scope)
            views.append(view)
            slots += count
        scope.derived_target_views.extend(views)


def capture_inputs(store, scope, decomp, grouped):
    if store is None or scope is None:
        return ()
    views, slots = [], 0
    with scope.lock, closing(store.connect()) as conn, conn:
        conn.execute('BEGIN')
        for target in scope.derived_target_views:
            if target.key[3] != decomp.custom_interval:
                continue
            bars = grouped.get(('binance', 'spot', target.key[2], '1s'), [])
            if not bars or slots + len(bars) > MAX_SLOTS:
                continue
            bars = sorted(bars, key=lambda bar: bar.open_time)
            start, end = bars[0].open_time, bars[-1].open_time
            if (start < target.start or end >= target.end + target.duration
                    or start % 1000 or (end-start)//1000+1 != len(bars)):
                continue
            # This finite path proves dense native 1s inputs, not sparse/trade
            # absence, shifted alignment or nondefault semantic identities.
            if any(bar.open_time != start+i*1000 or bar.close_time != bar.open_time+999
                   or bar.exchange != 'binance' or bar.market_type != 'spot'
                   or bar.symbol != target.key[2] or bar.interval != '1s'
                   or (bar.series_identity is not None and
                       not bar.series_identity.is_legacy_default_for('binance'))
                   for i, bar in enumerate(bars)):
                continue
            target.check(conn, scope)
            rows = conn.execute('SELECT ' + ','.join(FIELDS) + ' FROM klines WHERE ' +
                                ' AND '.join(f'{name}=?' for name in IDENTITY_COLUMNS) +
                                ' AND open_time BETWEEN ? AND ? ORDER BY open_time LIMIT ?',
                                (*target.input_key, start, end, MAX_SLOTS+1)).fetchall()
            if len(rows) != len(bars) or any(
                not source_is_trusted_final(row['source']) or
                any(row[name] != bar.to_storage_dict()[name] for name in FIELDS[:-1])
                for row, bar in zip(rows, bars)
            ):
                raise StaleAcquisition('fetched reduction inputs differ from canonical history')
            views.append(ComputationView(target, start, end,
                                         fingerprint(conn, target.input_key, start, end)))
            slots += len(bars)
    return tuple(views)


def affected_targets(scope, key, rows):
    if not rows:
        return ()
    start, end = min(row['open_time'] for row in rows), max(row['close_time'] for row in rows)
    return tuple(view for view in scope.derived_target_views if view.input_key == key
                 and start < view.end + view.duration and end >= view.start)


def matching_computation(scope, key, rows, source):
    if source != 'backfill_aggregated' or not rows:
        return None
    start, end = min(row['open_time'] for row in rows), max(row['close_time'] for row in rows)
    return next((view for view in _computation.get() if view.target in scope.derived_target_views
                 and view.target.key == key and view.start <= start <= end <= view.end+999), None)


@contextmanager
def computation_scope(views):
    token = _computation.set(views)
    try:
        yield
    finally:
        _computation.reset(token)
