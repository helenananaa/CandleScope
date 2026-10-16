"""Budget checks must not repeatedly read historical artifact payload pages."""
import sqlite3

import pytest

from app.replay.training.schema import migrate_training_schema
from tests.test_replay_hedge_phase4_accounting import _run_with_opposite_legs
from tests.test_replay_v2_training_phase6 import _risk_service

pytestmark = pytest.mark.anyio

QUERIES = {
    'idx_replay_review_anchor_budget': 'SELECT COALESCE(SUM(CASE WHEN stored_bytes > 0 THEN stored_bytes ELSE length(payload) END),0) FROM replay_review_actor_anchor WHERE run_id=?',
    'idx_replay_review_artifact_budget': 'SELECT SUM(length(CAST(projection_json AS BLOB))) FROM replay_review_timeline_event WHERE run_id=?',
    'idx_replay_equity_sample_window': 'SELECT resolution,bucket_id,source_sequence,revision FROM replay_equity_sample WHERE run_id=?',
}


async def test_additive_indexes_upgrade_existing_rows_and_preserve_rollback_budgets(tmp_path):
    database = tmp_path / 'budgets.db'
    service = await _risk_service(database)
    try:
        run, _, _ = await _run_with_opposite_legs(service, tmp_path, prefix='budgets')
        with sqlite3.connect(database) as connection:
            # Old archives use payload length when stored_bytes was not populated.
            connection.execute('UPDATE replay_review_actor_anchor SET stored_bytes=0 WHERE run_id=?', (run,))
            for name in QUERIES:
                connection.execute(f'DROP INDEX {name}')
            def values():
                return {name: sorted(connection.execute(query, (run,)).fetchall()) for name, query in QUERIES.items()}
            before = values()
            migrate_training_schema(connection, now_ms=1)
            assert values() == before
            for name, query in QUERIES.items():
                plan = ' '.join(str(tuple(row)) for row in connection.execute('EXPLAIN QUERY PLAN '+query, (run,)))
                assert name in plan
            connection.execute('SAVEPOINT budget')
            connection.execute('UPDATE replay_review_actor_anchor SET stored_bytes=123 WHERE run_id=?', (run,))
            assert values()['idx_replay_review_anchor_budget'] != before['idx_replay_review_anchor_budget']
            connection.execute('ROLLBACK TO budget')
            assert values() == before
            connection.rollback()
    finally:
        await service.shutdown(step_timeout=1.0)
