from __future__ import annotations

import ast
import os
import socket
from pathlib import Path

import pytest

from app.backtest.strategy.python_runner import (
    IsolatedPythonRunner,
    PythonRunnerError,
    sandbox_available,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "candlescope-backtest-sdk"
    / "fixtures"
    / "sma_cross"
)
RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "backtest"
    / "strategy"
    / "python_runner.py"
)


def _frame(sequence: int, close: str) -> dict:
    return {
        "schemaVersion": "candlescope.python-strategy-observation/1",
        "runId": "bt_1",
        "revisionId": "rev_1",
        "generation": 1,
        "sequence": sequence,
        "eventTimeMs": sequence * 60_000,
        "watermarkMs": sequence * 60_000,
        "phase": "STEP",
        "market": {"symbol": "BTCUSDT"},
        "bar": {
            "openTimeMs": (sequence - 1) * 60_000,
            "closeTimeMs": sequence * 60_000,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": "1",
        },
        "features": {"close": close},
        "accountView": {"equity": "10000"},
        "inputHash": "sha256:" + "ab" * 32,
    }


def test_trusted_local_requires_flag_and_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "0")
    with pytest.raises(PythonRunnerError, match="TRUSTED_LOCAL_DISABLED"):
        IsolatedPythonRunner(FIXTURE, mode="TRUSTED_LOCAL", trusted_confirmed=True)
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    with pytest.raises(PythonRunnerError, match="TRUSTED_LOCAL_UNCONFIRMED"):
        IsolatedPythonRunner(FIXTURE, mode="TRUSTED_LOCAL", trusted_confirmed=False)


def test_sandboxed_local_fails_closed_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.backtest.strategy.python_runner.sandbox_available", lambda: False
    )
    with pytest.raises(PythonRunnerError, match="SANDBOX_UNAVAILABLE"):
        IsolatedPythonRunner(FIXTURE, mode="SANDBOXED_LOCAL")


def test_trusted_local_lifecycle_and_probe(monkeypatch) -> None:
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    runner = IsolatedPythonRunner(
        FIXTURE, mode="TRUSTED_LOCAL", trusted_confirmed=True, step_timeout_s=5
    )
    runner.start()
    try:
        runner.call(
            "prepare",
            {
                "bundleDir": str(FIXTURE),
                "entrypoint": "strategy:Strategy",
                "parameters": {"fast": 2, "slow": 3},
            },
        )
        runner.call("warmup", {"observation": _frame(1, "10")})
        output = runner.call("step", {"observation": _frame(2, "20")})
        assert output["kind"] == "TARGET_POSITION"
        runner.call("close")
    finally:
        receipt = runner.close()
    assert runner._process is None
    assert receipt["mode"] == "TRUSTED_LOCAL"
    assert receipt["transcriptHash"].startswith("sha256:")


def test_cold_strategy_worker_does_not_modify_sdk_or_bundle_with_bytecode(tmp_path, monkeypatch):
    import hashlib
    import shutil
    from app.backtest.strategy import python_runner

    sdk = tmp_path / "packaged-sdk"
    bundle = tmp_path / "strategy"
    shutil.copytree(python_runner.SDK_SRC, sdk, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(FIXTURE, bundle, ignore=shutil.ignore_patterns("__pycache__"))
    def tree(directory):
        return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in directory.rglob("*") if path.is_file()}
    before = tree(tmp_path)
    monkeypatch.setattr(python_runner, "SDK_SRC", sdk)
    monkeypatch.setattr(python_runner, "WORKER", sdk / "candlescope_backtest_sdk/worker.py")
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    # Isolated Python ignores PYTHON* environment flags. The launch itself must
    # keep imports out of the signed application and original user bundle.
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    runner = IsolatedPythonRunner(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True, step_timeout_s=5)
    try:
        runner.start()
        runner.call("prepare", {"bundleDir": str(bundle), "entrypoint": "strategy:Strategy", "parameters": {"fast": 2, "slow": 3}})
        runner.call("warmup", {"observation": _frame(1, "10")})
        assert runner.call("step", {"observation": _frame(2, "20")})["kind"] == "TARGET_POSITION"
        runner.call("close")
    finally:
        runner.close()
    assert tree(tmp_path) == before, "strategy execution must not add bytecode to signed SDK or user input"


def test_runner_source_does_not_import_service_repository_or_database() -> None:
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = (
        "app.backtest.service",
        "app.backtest.repository",
        "sqlite3",
        "app.backtest.schema",
    )
    assert all(name not in imported for name in forbidden)
    assert sandbox_available() in {True, False}


@pytest.mark.parametrize("size,overflow", [(20_000, False), (100_000, True)])
def test_strategy_stderr_is_drained_and_bounded(tmp_path, monkeypatch, size, overflow):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    (tmp_path / "strategy.py").write_text(
        f"class Strategy:\n def prepare(self, ctx):\n  print('x' * {size}, end='', flush=True)\n",
        encoding="utf-8",
    )
    runner = IsolatedPythonRunner(
        tmp_path, mode="TRUSTED_LOCAL", trusted_confirmed=True
    )
    runner.start()
    try:
        if overflow:
            with pytest.raises(PythonRunnerError, match="STDERR_TOO_LARGE"):
                runner.call(
                    "prepare",
                    {"bundleDir": str(tmp_path), "entrypoint": "strategy:Strategy"},
                )
        else:
            assert runner.call(
                "prepare",
                {"bundleDir": str(tmp_path), "entrypoint": "strategy:Strategy"},
            ) == {"ok": True}
    finally:
        receipt = runner.close()
    assert receipt["stderrBytes"] >= min(size, 65536)
    assert receipt["stderrOverflow"] is overflow


@pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer only")
def test_sandboxed_strategy_runs_sdk_but_cannot_read_host_file_or_connect_loopback(
    tmp_path,
):
    marker = tmp_path / "host-private.txt"
    marker.write_text("host secret", encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    (bundle / "strategy.py").write_text(
        f"""
import socket
from pathlib import Path
class Strategy:
 def prepare(self, ctx):
  try: Path({str(marker)!r}).read_text(); self.file = True
  except OSError: self.file = False
  try:
   with socket.create_connection(('127.0.0.1', {port}), timeout=0.3): self.network = True
  except OSError: self.network = False
 def snapshot(self): return {{'file': self.file, 'network': self.network}}
 def close(self): pass
""",
        encoding="utf-8",
    )
    runner = None
    try:
        # Prove these controlled targets are accessible outside AppContainer.
        # Otherwise a broken listener could look like successful isolation.
        assert marker.read_text(encoding="utf-8") == "host secret"
        listener.settimeout(2)
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            connection, _ = listener.accept()
            connection.close()
        runner = IsolatedPythonRunner(bundle, mode="SANDBOXED_LOCAL", step_timeout_s=5)
        runner.start()
        runner.call(
            "prepare", {"bundleDir": str(bundle), "entrypoint": "strategy:Strategy"}
        )
        snapshot = runner.call("snapshot")
        assert snapshot["payload"] == {"file": False, "network": False}
        runner.call("close")
    finally:
        if runner is not None:
            runner.close()
        listener.close()


def test_request_write_is_covered_by_step_timeout(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time

    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    runner = IsolatedPythonRunner(
        tmp_path, mode="TRUSTED_LOCAL", trusted_confirmed=True, step_timeout_s=0.1
    )
    # A hung worker deliberately never consumes stdin. The allowed request exceeds the OS pipe buffer.
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    runner._process = child
    started = time.monotonic()
    try:
        with pytest.raises(PythonRunnerError, match="PROVIDER_TIMEOUT"):
            runner.call("restore", {"payload": "x" * 100_000})
        assert time.monotonic() - started < 3
        assert child.poll() is not None
    finally:
        runner.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer ACL lifecycle")
def test_disposable_strategy_profiles_do_not_accumulate_shared_acl_grants(tmp_path):
    import re
    import subprocess
    from app.backtest.strategy.python_runner import SDK_SRC

    def grants(path):
        result = subprocess.run(
            ["icacls.exe", str(path)], check=True, capture_output=True
        )
        return sorted(
            re.findall(
                r"S-1-15-2-(?:\d+-)*\d+", result.stdout.decode("ascii", errors="ignore")
            )
        )

    baseline = grants(SDK_SRC)
    worker_baseline = grants(SDK_SRC / "candlescope_backtest_sdk" / "worker.py")
    for _ in range(2):
        runner = IsolatedPythonRunner(tmp_path, mode="SANDBOXED_LOCAL")
        try:
            runner.start()
            assert runner._sandbox_sid in grants(SDK_SRC)
        finally:
            runner.close()
        assert grants(SDK_SRC) == baseline
        assert (
            grants(SDK_SRC / "candlescope_backtest_sdk" / "worker.py")
            == worker_baseline
        )


@pytest.mark.parametrize("writer,size,overflow", [
    ("print('x' * 100_000, end='', flush=True)", 100_000, True),
    ("__import__('sys').stderr.buffer.write(b'x' * 100_000)", 100_000, True),
    ("print('中' * 22_000, end='', flush=True)", 66_000, True),
    ("print('x' * 65_536, end='', flush=True)", 65_536, False),
    ("print('x' * 20_000, end='', flush=True)", 20_000, False),
    ("__import__('sys').stdout.writelines(['x' * 40_000] * 2)", 80_000, True),
    ("__import__('sys').stderr.buffer.writelines([b'x' * 40_000] * 2)", 80_000, True),
])
def test_worker_rejects_log_overflow_before_publishing_success(tmp_path, writer, size, overflow):
    """Pipe scheduling cannot decide whether a successful reply exceeds budget."""
    import json
    import subprocess
    from app.backtest.strategy.python_runner import WORKER, SDK_SRC, _real_python

    (tmp_path / "strategy.py").write_text(
        "class Strategy:\n def prepare(self, ctx):\n  " + writer + "\n", encoding="utf-8",
    )
    request = {"id": 1, "method": "prepare", "params": {
        "bundleDir": str(tmp_path), "entrypoint": "strategy:Strategy",
    }}
    result = subprocess.run(
        [str(_real_python()), "-I", "-B", "-u", str(WORKER), str(SDK_SRC)],
        input=(json.dumps(request) + "\n").encode("utf-8"), capture_output=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr[-500:]
    reply = json.loads(result.stdout)
    assert reply["ok"] is not overflow
    if overflow:
        assert reply["errorCode"] == "STDERR_TOO_LARGE"
    assert len(result.stderr) == min(size, 65_537)


def test_batch_stops_before_next_step_after_log_budget_failure(tmp_path, monkeypatch):
    from candlescope_backtest_sdk import Bar, Observation

    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    marker = tmp_path / "second-step-ran"
    (tmp_path / "strategy.py").write_text(
        "from pathlib import Path\nclass Strategy:\n"
        " def prepare(self, ctx): self.calls = 0\n"
        " def warmup(self, obs):\n"
        "  self.calls += 1\n"
        "  if self.calls == 1: print('x' * 100_000, end='', flush=True)\n"
        f"  else: Path({str(marker)!r}).write_text('unexpected')\n",
        encoding="utf-8",
    )
    observation = Observation("run", "revision", 0, 1, 1000, 1000, "WARMUP", {},
                              Bar(0, 999, "1", "1", "1", "1", "1")).to_wire()
    runner = IsolatedPythonRunner(tmp_path, mode="TRUSTED_LOCAL", trusted_confirmed=True)
    runner.start()
    try:
        runner.call("prepare", {"bundleDir": str(tmp_path), "entrypoint": "strategy:Strategy"})
        results, error = runner.step_batch([("warmup", {"observation": observation})] * 2)
        assert results == []
        assert error is not None and error.code == "STDERR_TOO_LARGE"
        assert not marker.exists()
    finally:
        runner.close()
