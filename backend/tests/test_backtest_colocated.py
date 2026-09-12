from dataclasses import replace
from pathlib import Path
import multiprocessing
import shutil
import threading
import time

import pytest

from app.backtest.service import BacktestService
from app.backtest.errors import BacktestError
from app.backtest.colocated import provider_spec
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.backtest.strategy.python_provider import PythonHostProvider
from app.market_dataset.snapshot import MarketEvent
from tests.test_backtest_control_plane import _settings, _payload


def bars(count=200):
    return tuple(MarketEvent(sequence=i, event_time_ms=i*60000, role="BARS", payload={
        "open": str(100+i%9), "high": str(101+i%9), "low": str(99+i%9),
        "close": str(100+i%9), "volume": "1000",
    }) for i in range(1, count+1))


@pytest.mark.parametrize("python,bound", [(False, False), (True, False), (True, True)])
def test_reference_and_colocated_have_identical_full_report_and_result(tmp_path, monkeypatch, python, bound):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    settings = _settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="32")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(parameters={"fast":3,"slow":5}, execution_model_revision="EXECUTION_REALISM_V2"), idempotency_key="same", now_ms=2)
    seed.shutdown()
    bundle = Path(__file__).resolve().parents[2]/"packages/candlescope-backtest-sdk/templates/sma_cross"
    results = []
    for lane in ("0", "1"):
        db = tmp_path/f"lane-{lane}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        monkeypatch.setenv("BACKTEST_COLOCATED_BAR_ENABLED", lane)
        provider = (PythonHostProvider(bundle, parameters={"fast":3,"slow":5}, mode="TRUSTED_LOCAL", trusted_confirmed=True, bound_transcript=bound)
                    if python else IsolatedStrategyProvider("builtin-sma-cross-v1", step_timeout_s=2))
        try:
            result = service.execute_bar_run(run["run_id"], events=bars(), provider=provider, now_ms=3)
            if lane == "1":
                assert result["execution_lane"] == "COLOCATED_BAR_V1"
            results.append(result)
        finally:
            service.shutdown()
    assert results[0]["report"] == results[1]["report"]
    assert results[0]["result"] == results[1]["result"]


def hanging_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    monkeypatch.setenv("BACKTEST_COLOCATED_BAR_ENABLED", "1")
    bundle = tmp_path/"hanging"
    bundle.mkdir()
    marker = bundle/"hang"
    marker.touch()
    (bundle/"strategy.py").write_text('''from pathlib import Path
from candlescope_backtest_sdk import TargetPosition
class Strategy:
 def prepare(self, context):
  assert Path("strategy.py").is_file()
  self.seen = 0
 def warmup(self, frame): pass
 def step(self, frame):
  if frame.sequence == 65 and Path(__file__).with_name("hang").exists():
   Path(__file__).with_name("entered").touch()
   while True: pass
  self.seen = frame.sequence
  return TargetPosition(quantity="1" if frame.sequence % 10 < 5 else "0")
 def on_execution_report(self, report): pass
 def snapshot(self): return {"seen": self.seen}
 def restore(self, payload): self.seen = payload["seen"]
 def close(self): pass
''', encoding="utf-8")
    return bundle, marker


def test_timeout_preserves_checkpoint_then_restores_exact_financial_results(tmp_path, monkeypatch):
    bundle, marker = hanging_provider(tmp_path, monkeypatch)
    settings = _settings(tmp_path, BACKTEST_PROVIDER_STEP_TIMEOUT_MS="200", BACKTEST_CHECKPOINT_EVENT_INTERVAL="32")
    service = BacktestService.start(settings, now_ms=1)
    provider = lambda: PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True)
    run = service.create_run(_payload(), idempotency_key="timeout", now_ms=2)
    try:
        with pytest.raises(BacktestError, match="PROVIDER_TIMEOUT"):
            service.execute_bar_run(run["run_id"], events=bars(), provider=provider(), now_ms=3)
        checkpoint = service.repository.latest_checkpoint(run["run_id"])
        assert checkpoint["sequence"] == 64
        assert service.get_run(run["run_id"])["state"] == "FAILED"
        assert not [p for p in multiprocessing.active_children() if p.name.startswith("backtest-run-")]
        marker.unlink()
        service.resume_failed_run(run["run_id"], now_ms=4)
        resumed = service.execute_bar_run(run["run_id"], events=bars(), provider=provider(), now_ms=5)
        clean = service.create_run(_payload(), idempotency_key="clean", now_ms=6)
        normal = service.execute_bar_run(clean["run_id"], events=bars(), provider=provider(), now_ms=7)
        for key in ("decision_hash", "fill_hash", "ledger_hash", "equity_curve", "fills", "ledger"):
            assert resumed["result"][key] == normal["result"][key]
    finally:
        service.shutdown()


def test_cancel_terminates_hung_provider_without_report(tmp_path, monkeypatch):
    bundle, _ = hanging_provider(tmp_path, monkeypatch)
    service = BacktestService.start(_settings(tmp_path, BACKTEST_PROVIDER_STEP_TIMEOUT_MS="2000"), now_ms=1)
    run = service.create_run(_payload(), idempotency_key="cancel", now_ms=2)
    errors = []
    def execute():
        try:
            service.execute_bar_run(run["run_id"], events=bars(), provider=PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True), now_ms=3)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=execute)
    thread.start()
    try:
        deadline = time.monotonic()+15
        while not (bundle/"entered").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (bundle/"entered").exists()
        service.cancel_run(run["run_id"], now_ms=4)
        thread.join(5)
        assert not thread.is_alive()
        assert errors
        assert service.get_run(run["run_id"])["state"] == "CANCELLED"
        assert service.repository.get_report(run["run_id"]) is None
        assert not [p for p in multiprocessing.active_children() if p.name.startswith("backtest-run-")]
    finally:
        thread.join(12)
        service.shutdown()


def test_sandbox_provider_never_routes_to_colocated(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backtest.strategy.python_runner.sandbox_available", lambda: True)
    provider = PythonHostProvider(tmp_path, mode="SANDBOXED_LOCAL")
    assert provider_spec(provider) is None


@pytest.mark.parametrize("body", ["print('x'*1000000, flush=True)", "__import__('os').write(2, b'x'*1000000)", "__import__('os')._exit(7)"])
def test_native_output_overflow_and_abrupt_exit_fail_closed(tmp_path, monkeypatch, body):
    bundle, marker = hanging_provider(tmp_path, monkeypatch)
    marker.unlink()
    source = bundle/"strategy.py"
    source.write_text(source.read_text(encoding="utf-8").replace('  self.seen = frame.sequence', f'  {body}\n  self.seen = frame.sequence'), encoding="utf-8")
    service = BacktestService.start(_settings(tmp_path), now_ms=1)
    run = service.create_run(_payload(), idempotency_key="failure", now_ms=2)
    try:
        expected = "PROVIDER_CRASH_UNRECOVERABLE" if "_exit" in body else "STDERR_TOO_LARGE"
        with pytest.raises(BacktestError, match=expected):
            service.execute_bar_run(run["run_id"], events=bars(), provider=PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True), now_ms=3)
        assert service.repository.get_report(run["run_id"]) is None
        assert not [p for p in multiprocessing.active_children() if p.name.startswith("backtest-run-")]
    finally:
        service.shutdown()


def test_local_sdk_keeps_integer_and_nesting_limits(monkeypatch):
    from app.backtest.strategy.local_python import LocalPythonRunner
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    runner = LocalPythonRunner(bound_transcript=False)
    runner.start()
    with pytest.raises(RuntimeError, match="53-bit"):
        runner.call("prepare", {"bad": 2**60})
    nested = 0
    for _ in range(100):
        nested = [nested]
    with pytest.raises(RuntimeError, match="nesting"):
        runner.call("prepare", {"bad": nested})


def test_worker_initialization_error_marks_queued_run_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_COLOCATED_BAR_ENABLED", "1")
    service = BacktestService.start(_settings(tmp_path), now_ms=1)
    run = service.create_run(_payload(), idempotency_key="bad-provider", now_ms=2)
    try:
        with pytest.raises(BacktestError):
            service.execute_bar_run(run["run_id"], events=bars(),
                provider=IsolatedStrategyProvider("does-not-exist", step_timeout_s=.2), now_ms=3)
        assert service.get_run(run["run_id"])["state"] == "FAILED"
        assert service.repository.get_report(run["run_id"]) is None
    finally:
        service.shutdown()
