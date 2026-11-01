import asyncio
from pathlib import Path
import threading

from app.backtest.run_updates import RunUpdates, run_updates_for
from app.backtest.repository import BacktestRepository


def test_worker_wakeups_share_only_the_exact_database(tmp_path):
    first = run_updates_for(tmp_path / "a.db")
    assert first is run_updates_for(tmp_path / "child" / ".." / "a.db")
    assert first is not run_updates_for(tmp_path / "b.db")
    assert run_updates_for(Path(":memory:")) is not run_updates_for(Path(":memory:"))


def test_worker_thread_notifications_coalesce_and_isolate_runs():
    async def check():
        updates = RunUpdates()
        selected = updates.subscribe("selected")
        sibling = updates.subscribe("sibling")
        scheduled = 0
        original = selected._loop.call_soon_threadsafe

        def schedule(*args):
            nonlocal scheduled
            scheduled += 1
            return original(*args)

        selected._loop.call_soon_threadsafe = schedule
        try:
            worker = threading.Thread(target=lambda: [updates.notify("selected") for _ in range(10_000)])
            worker.start()
            worker.join()
            assert scheduled == 1
            await asyncio.wait_for(selected.wait(), 1)
            assert not sibling._event.is_set()
            selected.clear_before_read()
            assert not selected._event.is_set()
            # A commit between clearing and finishing the durable read wakes
            # the next iteration; it cannot be swallowed by the prior update.
            updates.notify("selected")
            await asyncio.wait_for(selected.wait(), 1)
        finally:
            selected._loop.call_soon_threadsafe = original
            selected.close()
            sibling.close()
        assert updates.diagnostics() == {"runs": 0, "subscriptions": 0}
        updates.notify("selected")
    asyncio.run(check())


def test_closing_one_subscriber_preserves_another_and_releases_queued_delivery():
    async def check():
        updates = RunUpdates()
        first, second = updates.subscribe("run"), updates.subscribe("run")
        updates.notify("run")
        first.close()
        first.close()
        await asyncio.wait_for(second.wait(), 1)
        assert not first._event.is_set()
        assert updates.diagnostics() == {"runs": 1, "subscriptions": 1}
        second.close()
        assert updates.diagnostics() == {"runs": 0, "subscriptions": 0}
    asyncio.run(check())


def test_distinct_worker_repository_notifies_only_committed_state_and_checkpoint(tmp_path):
    async def check():
        reader, worker = BacktestRepository(tmp_path / "runs.db"), BacktestRepository(tmp_path / "runs.db")
        reader.open(now_ms=1)
        worker.open(now_ms=1)
        payload = dict(run_id="run", study_id=None, idempotency_key="create", state="QUEUED",
                       fidelity_mode="BAR_APPROX", source_event_kind="BAR", strategy_revision_id="rev",
                       dataset_id="data", data_epoch="epoch", snapshot_hash="snapshot", config_json="{}",
                       config_hash="config", engine_version="v1", generation=1, failure_code=None,
                       created_at_ms=1, updated_at_ms=1)
        assert worker.insert_run(payload)
        subscription = reader.run_updates.subscribe("run")
        try:
            worker.update_run_state("run", state="RUNNING", updated_at_ms=2)
            await asyncio.wait_for(subscription.wait(), 1)
            assert reader.get_run_by_id("run")["state"] == "RUNNING"
            subscription.clear_before_read()
            assert not worker.compare_and_set_run_state("run", expected_state="QUEUED", state="FAILED", updated_at_ms=3)
            await asyncio.sleep(0)
            assert not subscription._event.is_set()
            checkpoint = dict(run_id="run", sequence=10, generation=1, payload_json="{}", state_hash="state", created_at_ms=3)
            assert worker.save_checkpoint(checkpoint)
            await asyncio.wait_for(subscription.wait(), 1)
            assert reader.latest_checkpoint("run")["sequence"] == 10
            subscription.clear_before_read()
            assert not worker.save_checkpoint({**checkpoint, "sequence": 11, "generation": 0})
            await asyncio.sleep(0)
            assert not subscription._event.is_set()
            assert worker.compare_and_set_run_state("run", expected_state="RUNNING", state="FAILED", updated_at_ms=4, failure_code="QA_FAILURE")
            await asyncio.wait_for(subscription.wait(), 1)
            assert reader.get_run_by_id("run")["failure_code"] == "QA_FAILURE"
        finally:
            subscription.close()
            reader.close()
            worker.close()
    asyncio.run(check())
