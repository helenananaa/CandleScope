"""Per-trade strategy lanes (#107 §8.1): whole-run worker and batched provider exchanges."""

from dataclasses import replace
import json
import multiprocessing
from pathlib import Path
import shutil
import time

import pytest

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.backtest.strategy import isolated as isolated_module
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.backtest.strategy.protocol import (
    ObservationFrame,
    StrategyOutput,
    StrategyProviderError,
    StrategyProviderSession,
)
from app.backtest.strategy.python_provider import PythonHostProvider
from app.backtest.strategy.python_runner import IsolatedPythonRunner
from scripts.benchmark_trade_strategy import events, payload, settings

SDK_TEMPLATE = Path(__file__).resolve().parents[2] / "packages/candlescope-backtest-sdk/templates/sma_cross"

# Mostly silent, so batches are long; markers inject hangs, exits, failures
# and slow steps at chosen sequences. The log records every provider call,
# so equal snapshots and transcripts mean equal call and feedback order.
LOGGING_STRATEGY = '''import os
import time
from pathlib import Path
from candlescope_backtest_sdk import TargetPosition
HERE = Path(__file__).parent
class Strategy:
 def prepare(self, context):
  self.log = []
 def warmup(self, frame):
  self.log.append(["warmup", frame.sequence])
 def step(self, frame):
  self.log.append(["step", frame.sequence])
  marker = HERE / f"hang-{frame.sequence}"
  if marker.exists():
   (HERE / "entered").touch()
   while marker.exists():
    pass
  if (HERE / f"exit-{frame.sequence}").exists():
   os._exit(3)
  if (HERE / f"fail-{frame.sequence}").exists():
   raise RuntimeError("strategy failed")
  slow = HERE / f"slow-{frame.sequence}"
  if slow.exists():
   time.sleep(float(slow.read_text()))
  if frame.sequence % 40 == 0:
   return TargetPosition(quantity="1" if frame.sequence % 80 == 0 else "0")
  return None
 def on_execution_report(self, report):
  fill = report.get("fill") or {}
  kind = "fill" if fill else "order" if "order" in report else "rejected"
  self.log.append(["report", report.get("sequence", fill.get("sequence")), kind])
 def snapshot(self):
  return {"log": self.log}
 def restore(self, payload):
  self.log = [list(item) for item in payload["log"]]
 def close(self):
  pass
'''


def trade_payload(**overrides):
    request = payload()
    for key in ("signal_clock", "signal_interval", "execution_clock", "bar_builder", "timezone"):
        request.pop(key)
    request["fidelity_mode"] = "AGG_TRADE_TAPE"
    request.update(overrides)
    return request


def logging_bundle(tmp_path):
    bundle = tmp_path / "logging"
    bundle.mkdir()
    (bundle / "strategy.py").write_text(LOGGING_STRATEGY, encoding="utf-8")
    return bundle


def lanes(monkeypatch, *, colocated, batch):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    monkeypatch.setenv("BACKTEST_COLOCATED_TRADE_ENABLED", "1" if colocated else "0")
    monkeypatch.setenv("BACKTEST_PROVIDER_STEP_BATCH_SIZE", str(batch))


def run_lanes(tmp_path, monkeypatch, make_provider, configurations, *, count=600, interval=100, **request):
    config = settings(tmp_path, interval)
    seed = BacktestService.start(config, now_ms=1)
    created = seed.create_run(trade_payload(**request), idempotency_key="same", now_ms=2)
    seed.shutdown()
    tape = events(count)
    outcomes = []
    for index, (colocated, batch) in enumerate(configurations):
        lanes(monkeypatch, colocated=colocated, batch=batch)
        db = tmp_path / f"lane-{index}.db"
        shutil.copy2(config.db_path, db)
        service = BacktestService.start(replace(config, db_path=db), now_ms=1)
        saved, save = [], service.repository.save_checkpoint

        def record(checkpoint):
            # Completion deletes checkpoints; keep every in-process one. The
            # whole-run worker saves its own, so that lane records none here.
            saved.append((checkpoint["sequence"], checkpoint["payload_json"]))
            return save(checkpoint)

        service.repository.save_checkpoint = record
        try:
            completed = service.execute_trade_run(
                created["run_id"], events=tape, provider=make_provider(), now_ms=3
            )
            outcomes.append((completed, saved))
        finally:
            service.shutdown()
    return outcomes


REFERENCE, BATCHED, COLOCATED = (False, 0), (False, 64), (True, 64)


@pytest.mark.parametrize("python", [False, True])
def test_trade_lanes_have_identical_results_reports_and_final_state(tmp_path, monkeypatch, python):
    def provider():
        if python:
            return PythonHostProvider(SDK_TEMPLATE, parameters={"fast": 3, "slow": 5},
                                      mode="TRUSTED_LOCAL", trusted_confirmed=True)
        return IsolatedStrategyProvider("builtin-sma-cross-v1", step_timeout_s=5)

    outcomes = run_lanes(tmp_path, monkeypatch, provider, (REFERENCE, BATCHED, COLOCATED),
                         execution_model_revision="EXECUTION_REALISM_V2")
    (reference, reference_checkpoints), (batched, batched_checkpoints), (colocated, _) = outcomes
    assert reference.get("execution_lane", "REFERENCE") == "REFERENCE"
    assert batched.get("execution_lane", "REFERENCE") == "REFERENCE"
    assert colocated["execution_lane"] == "COLOCATED_TRADE_V1"
    assert reference["result"]["fills"]
    assert reference["result"]["cost_sensitivity"]["scenarios"]
    for other in (batched, colocated):
        assert other["result"] == reference["result"]
        assert other["report"] == reference["report"]
    # Engine, provider and planner state at every periodic and final checkpoint.
    assert len(reference_checkpoints) == 8
    assert batched_checkpoints == reference_checkpoints


def test_batched_exchanges_keep_transcript_and_feedback_order(tmp_path, monkeypatch):
    bundle = logging_bundle(tmp_path)
    exchanges = {"call": 0, "step_batch": 0}
    original_call, original_batch = IsolatedPythonRunner.call, IsolatedPythonRunner.step_batch

    def counted_call(self, method, *args, **kwargs):
        if method in {"warmup", "step"}:
            exchanges["call"] += 1
        return original_call(self, method, *args, **kwargs)

    def counted_batch(self, *args, **kwargs):
        exchanges["step_batch"] += 1
        return original_batch(self, *args, **kwargs)

    monkeypatch.setattr(IsolatedPythonRunner, "call", counted_call)
    monkeypatch.setattr(IsolatedPythonRunner, "step_batch", counted_batch)
    counts = []

    def provider():
        counts.append(dict(exchanges))
        return PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True)

    (reference, reference_checkpoints), (batched, batched_checkpoints) = run_lanes(
        tmp_path, monkeypatch, provider, (REFERENCE, BATCHED))
    counts.append(dict(exchanges))
    single = counts[1]["call"] - counts[0]["call"]
    batched_exchanges = (counts[2]["call"] - counts[1]["call"]) + (counts[2]["step_batch"] - counts[1]["step_batch"])
    assert single == 600 and counts[1]["step_batch"] == 0
    assert batched_exchanges < single / 4
    # The transcript hash covers every request and reply, in order.
    assert batched["result"]["provider_close_hash"] == reference["result"]["provider_close_hash"]
    assert batched["result"] == reference["result"]
    assert batched["report"] == reference["report"]
    assert batched_checkpoints == reference_checkpoints
    log = json.loads(batched_checkpoints[-1][1])["provider"]["provider"]["log"]
    steps = [entry[1] for entry in log if entry[0] in {"warmup", "step"}]
    assert steps == list(range(1, 601))
    # Order reports follow their own step; fill reports precede the next one.
    for position, entry in enumerate(log):
        if entry[0] == "report" and entry[2] == "order":
            assert log[position - 1] == ["step", entry[1]]
        if entry[0] == "report" and entry[2] == "fill":
            assert log[position + 1] == ["step", entry[1]]


def failing_run(tmp_path, monkeypatch, marker, *, batch, timeout_ms=300):
    lanes(monkeypatch, colocated=False, batch=batch)
    root = tmp_path / f"batch-{batch}"
    root.mkdir()
    bundle = logging_bundle(root)
    (bundle / marker[0]).write_text(marker[1], encoding="utf-8")
    config = replace(settings(root, 100), provider_step_timeout_ms=timeout_ms)
    service = BacktestService.start(config, now_ms=1)
    created = service.create_run(trade_payload(), idempotency_key="failing", now_ms=2)
    provider = PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True)
    try:
        with pytest.raises((BacktestError, StrategyProviderError)) as raised:
            service.execute_trade_run(created["run_id"], events=events(600), provider=provider, now_ms=3)
        run = service.get_run(created["run_id"])
        checkpoint = service.repository.latest_checkpoint(created["run_id"])
        assert provider.runner._process is None
        return {
            "code": raised.value.code,
            "state": run["state"],
            "failure_code": run.get("failure_code"),
            # Each mode has its own run; the payload is otherwise the same.
            "checkpoint": None if checkpoint is None else (
                checkpoint["sequence"],
                checkpoint["payload_json"].replace(created["run_id"], "RUN"),
            ),
        }, service, created["run_id"], bundle
    except BaseException:
        service.shutdown()
        raise


@pytest.mark.parametrize("marker,code", [
    (("hang-150", ""), "PROVIDER_TIMEOUT"),
    (("slow-150", "0.6"), "PROVIDER_TIMEOUT"),
    (("exit-150", ""), "PROVIDER_EOF"),
    (("fail-150", ""), "PROVIDER_PROTOCOL_VIOLATION"),
])
def test_batched_failures_match_single_calls(tmp_path, monkeypatch, marker, code):
    outcomes = []
    for batch in (0, 64):
        outcome, service, _, bundle = failing_run(tmp_path, monkeypatch, marker, batch=batch)
        service.shutdown()
        (bundle / marker[0]).unlink()
        outcomes.append(outcome)
    assert outcomes[0]["code"] == code
    assert outcomes[1] == outcomes[0]
    if code == "PROVIDER_TIMEOUT":
        # Frames 101..150 ran in this exchange; the periodic checkpoint stays at 100.
        assert outcomes[1]["checkpoint"][0] == 100


def test_batched_timeout_resumes_to_the_uninterrupted_result(tmp_path, monkeypatch):
    outcome, service, run_id, bundle = failing_run(tmp_path, monkeypatch, ("hang-150", ""), batch=64)
    try:
        assert outcome["code"] == "PROVIDER_TIMEOUT"
        (bundle / "hang-150").unlink()

        def provider():
            return PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True)

        service.resume_failed_run(run_id, now_ms=4)
        resumed = service.execute_trade_run(run_id, events=events(600), provider=provider(), now_ms=5)
        clean = service.create_run(trade_payload(), idempotency_key="clean", now_ms=6)
        normal = service.execute_trade_run(clean["run_id"], events=events(600), provider=provider(), now_ms=7)
        for key in ("decision_hash", "fill_hash", "ledger_hash", "fills", "equity_curve", "ledger"):
            assert resumed["result"][key] == normal["result"][key]
    finally:
        service.shutdown()


def test_colocated_trade_timeout_terminates_worker_and_resumes(tmp_path, monkeypatch):
    lanes(monkeypatch, colocated=True, batch=64)
    bundle = logging_bundle(tmp_path)
    (bundle / "hang-150").touch()
    config = replace(settings(tmp_path, 100), provider_step_timeout_ms=300)
    service = BacktestService.start(config, now_ms=1)

    def provider():
        return PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True)

    created = service.create_run(trade_payload(), idempotency_key="interrupted", now_ms=2)
    try:
        with pytest.raises(BacktestError, match="PROVIDER_TIMEOUT"):
            service.execute_trade_run(created["run_id"], events=events(600), provider=provider(), now_ms=3)
        assert service.repository.latest_checkpoint(created["run_id"])["sequence"] == 100
        assert not [p for p in multiprocessing.active_children() if p.name.startswith("backtest-run-")]
        (bundle / "hang-150").unlink()
        service.resume_failed_run(created["run_id"], now_ms=4)
        resumed = service.execute_trade_run(created["run_id"], events=events(600), provider=provider(), now_ms=5)
        assert resumed["execution_lane"] == "COLOCATED_TRADE_V1"
        clean = service.create_run(trade_payload(), idempotency_key="clean", now_ms=6)
        normal = service.execute_trade_run(clean["run_id"], events=events(600), provider=provider(), now_ms=7)
        for key in ("decision_hash", "fill_hash", "ledger_hash", "fills", "equity_curve", "ledger"):
            assert resumed["result"][key] == normal["result"][key]
    finally:
        service.shutdown()


def test_colocated_trade_cancel_terminates_hung_worker(tmp_path, monkeypatch):
    import threading

    lanes(monkeypatch, colocated=True, batch=64)
    bundle = logging_bundle(tmp_path)
    (bundle / "hang-150").touch()
    service = BacktestService.start(replace(settings(tmp_path, 100), provider_step_timeout_ms=5000), now_ms=1)
    created = service.create_run(trade_payload(), idempotency_key="cancel", now_ms=2)
    errors = []

    def execute():
        try:
            service.execute_trade_run(created["run_id"], events=events(600),
                provider=PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True), now_ms=3)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not (bundle / "entered").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (bundle / "entered").exists()
        service.cancel_run(created["run_id"], now_ms=4)
        thread.join(10)
        assert not thread.is_alive() and errors
        assert service.get_run(created["run_id"])["state"] == "CANCELLED"
        assert service.repository.get_report(created["run_id"]) is None
        assert not [p for p in multiprocessing.active_children() if p.name.startswith("backtest-run-")]
    finally:
        (bundle / "hang-150").unlink(missing_ok=True)
        thread.join(12)
        service.shutdown()


def test_untrusted_trade_providers_never_route_to_the_worker(tmp_path, monkeypatch):
    from app.backtest.colocated import provider_spec

    monkeypatch.setattr("app.backtest.strategy.python_runner.sandbox_available", lambda: True)
    for fidelity in ("TRADE_TAPE", "AGG_TRADE_TAPE"):
        assert provider_spec(PythonHostProvider(tmp_path, mode="SANDBOXED_LOCAL"), fidelity=fidelity) is None
        assert provider_spec(object(), fidelity=fidelity) is None


def frames(count, *, run_id="run", start=1, warmup=0):
    return [ObservationFrame(run_id, sequence, sequence * 1000, sequence * 1000,
                             "WARMUP" if sequence < start + warmup else "EVALUATION",
                             {"venue": "local", "symbol": "x"}, "sha256:x",
                             bar={"close": str(100 + (sequence // 3) % 5)})
            for sequence in range(start, start + count)]


def test_isolated_step_batch_matches_single_steps():
    single = IsolatedStrategyProvider("builtin-sma-cross-v1", step_timeout_s=5)
    batched = IsolatedStrategyProvider("builtin-sma-cross-v1", step_timeout_s=5)
    try:
        for provider in (single, batched):
            provider.prepare({"parameters": {"fast": 2, "slow": 3}})
        inputs = frames(60, warmup=3)
        expected = [single.warmup(frame) if frame.phase == "WARMUP" else single.step(frame) for frame in inputs]
        actual, position = [], 0
        while position < len(inputs):
            outputs, error = batched.step_batch(inputs[position:position + 16], step_timeout_s=5)
            assert error is None and outputs
            # Stops at the first output and never runs past it.
            assert all(output is None for output in outputs[:-1])
            actual.extend(outputs)
            position += len(outputs)
        assert actual == expected
        assert batched.snapshot() == single.snapshot()
    finally:
        single.close()
        batched.close()


class _Connection:
    def __init__(self, replies, *, silent_after=None):
        self.replies, self.sent, self.silent_after = list(replies), [], silent_after

    def send(self, message):
        self.sent.append(message)

    def poll(self, timeout):
        return bool(self.replies)

    def recv(self):
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def close(self):
        pass


class _Process:
    def __init__(self):
        self.terminated = False

    def is_alive(self):
        return not self.terminated

    def terminate(self):
        self.terminated = True

    def join(self, timeout=None):
        pass

    def kill(self):
        self.terminated = True


def fake_provider(replies):
    provider = IsolatedStrategyProvider("fake", step_timeout_s=1)
    provider._connection, provider._process = _Connection(replies), _Process()
    return provider


@pytest.mark.parametrize("replies,count,code,terminated", [
    ([("ok", None), ("ok", None)], 2, None, False),
    ([("ok", None), EOFError()], 1, "PROVIDER_CRASH_UNRECOVERABLE", True),
    ([("ok", None)], 1, "PROVIDER_TIMEOUT", True),
    ([("ok", None), ("late", None)], 1, "PROVIDER_TIMEOUT", True),
    ([("error", ("PROVIDER_PROTOCOL_VIOLATION", "PROVIDER_PROTOCOL_VIOLATION: bad"))], 0,
     "PROVIDER_PROTOCOL_VIOLATION", False),
])
def test_isolated_step_batch_failures_belong_to_their_frame(replies, count, code, terminated):
    provider = fake_provider(replies)
    process = provider._process
    outputs, error = provider.step_batch(frames(2), step_timeout_s=0.01)
    assert len(outputs) == count
    assert (error.code if error else None) == code
    assert process.terminated is terminated
    assert provider._terminated is terminated


def test_isolated_step_batch_uses_the_smaller_deadline():
    provider = fake_provider([("ok", None)])
    provider.step_batch(frames(1), step_timeout_s=0.25)
    assert provider._connection.sent[0][0] == "step_batch"
    assert provider._connection.sent[0][1][1] == 0.25


def test_child_batch_stops_at_output_error_or_late_step(monkeypatch):
    class Provider:
        def __init__(self, outputs):
            self.outputs, self.seen = list(outputs), []

        def warmup(self, frame):
            self.seen.append(("warmup", frame.sequence))

        def step(self, frame):
            self.seen.append(("step", frame.sequence))
            output = self.outputs.pop(0)
            if isinstance(output, Exception):
                raise output
            return output

    output = StrategyOutput(3, "SIGNAL", {}, "sha256:s", "sha256:o")
    provider, connection = Provider([None, output, None]), _Connection([])
    isolated_module._step_batch(connection, provider, frames(5, warmup=1), 1.0)
    assert provider.seen == [("warmup", 1), ("step", 2), ("step", 3)]
    assert connection.sent == [("ok", None), ("ok", None), ("ok", output)]

    provider, connection = Provider([None, ValueError("boom")]), _Connection([])
    isolated_module._step_batch(connection, provider, frames(5), 1.0)
    assert connection.sent == [("ok", None), ("error", ("PROVIDER_CRASH_UNRECOVERABLE", "ValueError: boom"))]

    clock = iter([0.0, 0.1, 0.2, 5.0])
    monkeypatch.setattr(isolated_module.time, "monotonic", lambda: next(clock))
    provider, connection = Provider([None, None]), _Connection([])
    isolated_module._step_batch(connection, provider, frames(5), 1.0)
    assert connection.sent == [("ok", None), ("late", None)]


def test_session_batch_checks_outputs_and_commits_only_processed_frames():
    class Provider:
        def __init__(self, result):
            self.result = result

        def step_batch(self, frames, *, step_timeout_s):
            return self.result

    inputs = frames(4)
    session = StrategyProviderSession(Provider(([None, None], StrategyProviderError("X", "y"))), run_id="run")
    session.prepared = True
    outputs, error = session.step_batch(inputs, step_timeout_s=1)
    assert outputs == [None, None] and error.code == "X"
    assert session.last_sequence == 3  # the failing frame was accepted, as a single call would
    wrong = StrategyOutput(9, "SIGNAL", {}, "sha256:s", "sha256:o")
    session = StrategyProviderSession(Provider(([None, wrong], None)), run_id="run")
    session.prepared = True
    outputs, error = session.step_batch(inputs, step_timeout_s=1)
    assert outputs == [None] and error.code == "PROVIDER_PROTOCOL_VIOLATION"
    assert session.last_sequence == 2
    session = StrategyProviderSession(Provider(([None], None)), run_id="other")
    session.prepared = True
    with pytest.raises(StrategyProviderError, match="runId"):
        session.step_batch(inputs, step_timeout_s=1)
    assert session.last_sequence == 0
