"""Actual SDK/Pine IPC and durable journal lifecycle for explicitly owned ids."""
import sqlite3

import pytest

from app.plugin_runtime.errors import PluginRequestError, PluginRemoteError
from tests.test_runtime_owned_output import owner, bars, request, counter
from tests.test_plugin_runtime_supervisor import _fake_spec, _supervisor


def journal(path):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        return (db.execute('SELECT id FROM journal_sessions ORDER BY id').fetchall(),
                db.execute('SELECT sessions, bytes FROM journal_budget').fetchone(),
                db.execute('SELECT COUNT(*) FROM journal_operations').fetchone()[0])


@pytest.mark.anyio
async def test_release_deletes_one_owned_journal_and_bases_without_touching_another_chart(tmp_path):
    path = tmp_path/'released.sqlite'
    runtime = owner(path)
    try:
        await runtime.execute_batch(request(bars(500), 'chart-a'))
        await runtime.execute_batch(request(bars(50), 'chart-b'))
        old = await runtime.read_output('chart-a')
        before = journal(path)
        assert before[1][0] == 2
        starts = runtime.snapshot()['starts']
        await runtime.release_stream('chart-a')
        remaining = journal(path)
        assert remaining[0] == [('chart-b',)] and remaining[1][0] == 1
        assert 0 < remaining[1][1] < before[1][1]
        assert await runtime.read_output('chart-a', expected=old.reference) is None
        assert counter((await runtime.read_output('chart-b')).output) == 50
        await runtime.release_stream('chart-a')
        assert journal(path) == remaining and runtime.snapshot()['starts'] == starts
        result = await runtime.execute_batch(request(bars(20), 'chart-a'))
        assert result.meta['sessionReset'] is True and result.meta['sessionRecovered'] is False
        assert counter(result.output) == 20
        await runtime.release_stream('chart-a')
        await runtime.release_stream('chart-b')
        assert journal(path) == ([], (0, 0), 0)
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_explicit_release_can_recover_worker_to_remove_durable_orphan_without_executing(tmp_path):
    path = tmp_path/'orphan.sqlite'
    runtime = owner(path)
    try:
        await runtime.execute_batch(request(bars(20), 'orphan'))
        await runtime.stop()
        assert journal(path)[1][0] == 1
        starts = runtime.snapshot()['starts']
        assert await runtime.read_output('orphan') is None
        assert runtime.snapshot()['starts'] == starts
        await runtime.release_stream('orphan')
        assert runtime.snapshot()['starts'] == starts + 1
        assert await runtime.read_output('orphan') is None
        assert journal(path) == ([], (0, 0), 0)
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_invalid_release_never_starts_a_worker(tmp_path):
    runtime = owner(tmp_path/'invalid.sqlite')
    try:
        for value in ('', ' ', 'x'*129, 7, True):
            with pytest.raises(PluginRequestError, match='Invalid stream'):
                await runtime.release_stream(value)
        assert runtime.snapshot()['starts'] == 0
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_durable_release_failure_preserves_state_and_budget_until_exact_retry(tmp_path):
    path = tmp_path/'retry.sqlite'
    runtime = owner(path)
    try:
        await runtime.execute_batch(request(bars(30), 'owned'))
        output = await runtime.read_output('owned')
        before = journal(path)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TRIGGER block_release BEFORE DELETE ON journal_sessions BEGIN SELECT RAISE(ABORT, 'release blocked'); END")
        with pytest.raises(PluginRemoteError):
            await runtime.release_stream('owned')
        assert journal(path) == before
        assert (await runtime.read_output('owned', expected=output.reference)).output == output.output
        with sqlite3.connect(path) as db:
            db.execute('DROP TRIGGER block_release')
        await runtime.release_stream('owned')
        assert journal(path) == ([], (0, 0), 0)
        assert await runtime.read_output('owned') is None
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_old_runtime_rejects_release_without_sending_unnegotiated_method():
    runtime = _supervisor(_fake_spec())
    try:
        await runtime.start()
        before = runtime.snapshot()['requests']
        with pytest.raises(PluginRequestError, match='did not negotiate'):
            await runtime.release_stream('owned')
        assert runtime.snapshot()['requests'] == before and runtime.state == 'ready'
    finally:
        await runtime.stop()
