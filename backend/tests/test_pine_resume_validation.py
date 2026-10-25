"""Exclusive resume validation retains corruption and caller-ownership boundaries."""
import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.native import encoded
from app.backtest.native_checkpoint import checkpoint_digest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_pine_owned_checkpoint import configuration, complete


def saved_execution(runtime, mode):
    from app.backtest import pine_history_tick_execution, pine_print_tick_execution
    host, main = runtime
    origin = terminal(host.native, host.native.create(configuration(main, mode), "resume-validation")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    wire = host.native.replay._input(origin["run_id"])
    execution = pine_history_tick_execution if mode == "BAR_APPROX" else pine_print_tick_execution
    worker = execution.ReplayWorker(origin["runtime_launch"], wire)
    try:
        _, state = worker.execute(host.native.runner, threading.Event(), resume=None, target=3)
    finally:
        worker.close()
    return host, origin, wire, execution, state


@pytest.mark.parametrize("mode", ["BAR_APPROX", "TRADE_TAPE", "BOOK_DEPTH"])
def test_public_and_exclusive_cold_resumes_preserve_every_output_and_recheck_each_job(runtime, monkeypatch, mode):
    from app.backtest import external_replay
    host, origin, wire, execution, state = saved_execution(runtime, mode)
    original = encoded(state)
    validation = external_replay.validate_state
    for owned in (False, True):
        worker = execution.ReplayWorker(origin["runtime_launch"], wire)
        resume, calls = json.loads(original), []
        def checked(current_wire, current_state):
            calls.append(current_state is resume)
            return validation(current_wire, current_state)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(external_replay, "validate_state", checked)
                result, final = worker.execute(host.native.runner, threading.Event(), resume=resume,
                    target=len(wire["bars"]), resume_owned=owned, capture_owned=owned)
            assert calls == [True] * (1 if owned else 2)
            assert encoded(complete(result, wire)) == encoded(origin["result"])
            assert resume == {} if owned else encoded(resume) == original
            validation(wire, final)  # Fresh capture has the original complete checksum.
            # A later job may not inherit the earlier job's validation receipt.
            final["checksum"] = "sha256:" + "00" * 32
            with pytest.raises(BacktestError, match="checkpoint identity differs"):
                worker.execute(host.native.runner, threading.Event(), resume=final,
                    target=len(wire["bars"]), resume_owned=owned)
        finally:
            worker.close()
    assert encoded(state) == original


@pytest.mark.parametrize("mode", ["BAR_APPROX", "TRADE_TAPE", "BOOK_DEPTH"])
def test_exclusive_resume_rejects_bad_checksum_semantics_and_replayed_receipts(runtime, mode):
    host, origin, wire, execution, saved = saved_execution(runtime, mode)
    for damage in ("checksum", "observations", "result-receipt"):
        state = deepcopy(saved)
        if damage == "checksum":
            state["checksum"] = "sha256:" + "00" * 32
        elif damage == "observations":
            state["clock"]["groups"][0][0]["evaluation"]["account"]["equity"] += 1
            state["last_request"]["execution_schedule"] = deepcopy(state["clock"]["groups"])
        else:
            journal = state["clock"]["stream"]["journal"]
            entry = json.loads(journal[0])
            entry["result_sha256"] = "00" * 32
            journal[0] = encoded(entry)
        if damage != "checksum":
            state["checksum"] = checkpoint_digest({key: value for key, value in state.items() if key != "checksum"})
        before = encoded(state)
        worker = execution.ReplayWorker(origin["runtime_launch"], wire)
        try:
            with pytest.raises(BacktestError):
                worker.execute(host.native.runner, threading.Event(), resume=state,
                    target=len(wire["bars"]), resume_owned=True)
            assert encoded(state) == before  # Reject before consuming the durable account.
        finally:
            worker.close()


def test_owned_receipt_is_bound_to_exact_graphs_and_one_consumption_and_capture_validates_content(runtime):
    from app.backtest.external_replay import _OwnedResumeValidation, make_state, validate_state
    _, _, wire, _, state = saved_execution(runtime, "TRADE_TAPE")
    receipt = _OwnedResumeValidation(wire, state)
    for different_wire, different_state in ((deepcopy(wire), state), (wire, deepcopy(state))):
        with pytest.raises(BacktestError, match="owned resume validation differs"):
            receipt.consume(different_wire, different_state)
    receipt.check(wire, state)
    receipt.consume(wire, state)
    with pytest.raises(BacktestError, match="owned resume validation differs"):
        receipt.consume(wire, state)
    for owned in (False, True):
        def capture(accounts):
            return make_state(wire, state["cursor"], SimpleNamespace(snapshot=lambda: state["kernel"]),
                SimpleNamespace(snapshot=lambda: state["orders"]), accounts, state["history"], state["latest"],
                state["clock"], state["last_request"], _owned_output=owned)
        validate_state(wire, capture(state["accounts"]))
        with pytest.raises(BacktestError, match="checkpoint identity differs"):
            capture(state["accounts"][:-1])
