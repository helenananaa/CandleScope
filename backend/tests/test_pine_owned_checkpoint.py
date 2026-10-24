"""Exclusive capture keeps full replay values without copying finished clocks."""
import threading

import pytest

from app.backtest.native import digest, encoded
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_native_replay import settle
from tests.test_pine_history_tick_workbench import config as history_config
from tests.test_pine_print_ticks import config as print_config


def configuration(main, mode):
    value = (history_config(main, "LINEAR_PERP_ONE_WAY_V2") if mode == "BAR_APPROX"
             else print_config(main, mode, False, "LINEAR_PERP_ONE_WAY_V2"))
    value["cost_sensitivity_mode"] = "SKIP"
    return value


def complete(result, wire):
    result["bars"] = wire["bars"]
    result["report_hash"] = digest(result)
    return result


@pytest.mark.parametrize("mode", ["BAR_APPROX", "TRADE_TAPE", "BOOK_DEPTH"])
@pytest.mark.parametrize("owned", [False, True])
def test_captured_clock_survives_advancement_and_cold_restore_with_exact_full_values(runtime, mode, owned):
    from app.backtest import pine_history_tick_execution, pine_print_tick_execution
    host, main = runtime
    origin = terminal(host.native, host.native.create(configuration(main, mode), "capture-ownership")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    wire = host.native.replay._input(origin["run_id"])
    execution = pine_history_tick_execution if mode == "BAR_APPROX" else pine_print_tick_execution
    worker = execution.ReplayWorker(origin["runtime_launch"], wire)
    cancelled = threading.Event()
    try:
        first, state = worker.execute(host.native.runner, cancelled, resume=None, target=3, capture_owned=owned)
        assert (state["clock"]["groups"] is first["raw_output"]["execution_schedule"]) is owned
        before_state, before_result = encoded(state), encoded(first)
        final, final_state = worker.execute(host.native.runner, cancelled, resume=state,
            target=len(wire["bars"]), capture_owned=owned)
        assert encoded(state) == before_state and encoded(first) == before_result
        assert encoded(complete(final, wire)) == encoded(origin["result"])

        # Even transferred clock graphs freeze the still-live stream boundary.
        live = encoded(worker.stream.checkpoint(compact=True))
        final_state["clock"]["stream"]["opening"]["source"] = "caller-edited checkpoint"
        final_state["clock"]["stream"]["wire"]["identity"]["adapter"] = "caller-edited identity"
        final_state["clock"]["stream"]["journal"].clear()
        assert encoded(worker.stream.checkpoint(compact=True)) == live
        assert encoded(final) == encoded(origin["result"])
        frozen_bars = encoded(wire["bars"])
        final_state["last_request"]["bars"][0]["close"] = 999
        final_state["latest"]["raw_output"]["plots"][0]["values"][0] = 999
        assert encoded(wire["bars"]) == frozen_bars
        assert encoded(worker.stream.checkpoint(compact=True)) == live
        assert encoded(final) == encoded(origin["result"])

        worker.close()
        worker = execution.ReplayWorker(origin["runtime_launch"], wire)
        restored, _ = worker.execute(host.native.runner, cancelled, resume=state,
            target=len(wire["bars"]), capture_owned=owned)
        assert encoded(complete(restored, wire)) == encoded(origin["result"])
        assert encoded(state) == before_state and encoded(first) == before_result
        if not owned:
            state["clock"]["groups"][0][0]["evaluation"]["bar"]["close"] = 999
            assert encoded(first) == before_result
    finally:
        worker.close()


@pytest.mark.parametrize("mode", ["BAR_APPROX", "TRADE_TAPE", "BOOK_DEPTH"])
def test_owned_playback_preserves_the_persisted_midpoint_and_complete_endpoint(runtime, mode):
    host, main = runtime
    origin = terminal(host.native, host.native.create(configuration(main, mode), "owned-playback")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    replay = host.native.replay
    created = replay.create(origin["run_id"]); key = created["replay_id"]
    replay.command(key, created["revision"], "seek", 3)
    middle = settle(replay, key)
    before = encoded(replay._host_state(key))
    snapshot = replay.snapshot(key, middle["revision"])["snapshots"][0]["snapshot_id"]
    replay.command(key, replay.get(key)["revision"], "play")
    final = settle(replay, key)
    assert encoded(final["result"]) == encoded(origin["result"])
    replay.restore(key, final["revision"], snapshot)
    assert replay.get(key)["result"] == middle["result"]
    assert encoded(replay._host_state(key)) == before
    replay.command(key, replay.get(key)["revision"], "play")
    assert encoded(settle(replay, key)["result"]) == encoded(origin["result"])


def test_completed_seek_releases_its_report_before_public_read_can_acquire_the_lock(runtime, monkeypatch):
    import weakref
    from app.backtest.pine_print_tick_execution import ReplayWorker
    host, main = runtime
    origin = terminal(host.native, host.native.create(configuration(main, "BOOK_DEPTH"), "publish-ownership")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    replay = host.native.replay
    created = replay.create(origin["run_id"])
    key = created["replay_id"]
    published, continue_job = threading.Event(), threading.Event()
    original_lock = host.native.lock

    class PublicationLock:
        hold_thread = None
        def __enter__(self):
            original_lock.acquire()
            return self
        def __exit__(self, *args):
            hold = self.hold_thread == threading.get_ident()
            if hold:
                self.hold_thread = None
            original_lock.release()
            if hold:
                published.set()
                assert continue_job.wait(20), "public reader did not finish"

    class TrackedReport(dict):
        pass

    lock, reports = PublicationLock(), []
    execute, save = ReplayWorker.execute, replay._save
    def observed_execute(*args, **kwargs):
        report, state = execute(*args, **kwargs)
        report = TrackedReport(report)
        reports.append(weakref.ref(report))
        return report, state
    def saved(record, **kwargs):
        result = save(record, **kwargs)
        if record["state"] == "COMPLETED" and "external_state" in kwargs:
            lock.hold_thread = threading.get_ident()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(host.native, "lock", lock)
        patch.setattr(ReplayWorker, "execute", observed_execute)
        patch.setattr(replay, "_save", saved)
        try:
            replay.command(key, created["revision"], "seek", created["total"])
            assert published.wait(20), "seek did not publish"
            assert len(reports) == 1 and reports[0]() is None
            assert encoded(replay.get(key)["result"]) == encoded(origin["result"])
        finally:
            continue_job.set()
            settle(replay, key)


def test_play_at_completed_endpoint_preserves_the_complete_durable_result(runtime):
    host, main = runtime
    origin = terminal(host.native, host.native.create(configuration(main, "BAR_APPROX"), "completed-play")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    replay = host.native.replay
    created = replay.create(origin["run_id"])
    key = created["replay_id"]
    replay.command(key, created["revision"], "seek", created["total"])
    final = settle(replay, key)
    for _ in range(2):
        replay.command(key, final["revision"], "play")
        final = settle(replay, key)
        assert final["state"] == "COMPLETED"
        assert encoded(final["result"]) == encoded(origin["result"])
