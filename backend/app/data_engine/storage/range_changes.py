"""Bounded D126 proof that a declared dependency range stayed unchanged."""
from .revisions import IDENTITY_COLUMNS, StaleAcquisition, block_change_receipts, current_revision, series_change


def check_range_since(conn, keys, start, stop, revision):
    changed = {key for key in keys if (row := series_change(conn, key)) is not None
               and row['revision'] > revision and row['start_ms'] < stop and row['end_ms'] >= start}
    if not changed:
        return
    receipts = block_change_receipts(conn, revision, current_revision(conn))
    if not receipts:
        raise StaleAcquisition('dependency range receipt suffix is unavailable')
    if any(tuple(row[name] for name in IDENTITY_COLUMNS) in changed
           and row['start_ms'] < stop and row['end_ms'] >= start for row in receipts):
        raise StaleAcquisition('canonical dependency range changed during acquisition')


def check_store_range(store, keys, start, stop, revision):
    with store._reading() as conn, conn:
        conn.execute('BEGIN')
        check_range_since(conn, keys, start, stop, revision)
