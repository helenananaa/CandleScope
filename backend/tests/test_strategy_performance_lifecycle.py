import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backtest.strategy.serial_worker import SerialWorker
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.backtest.strategy.protocol import ProviderCapabilities


def test_serial_worker_reuses_thread_and_propagates_errors():
    worker = SerialWorker("test-strategy-worker")
    try:
        ids = {worker.call(threading.get_ident, 1) for _ in range(100)}
        assert len(ids) == 1
        assert threading.get_ident() not in ids
        def fail():
            raise ValueError("original")
        with pytest.raises(ValueError, match="original"):
            worker.call(fail, 1)
        assert worker.call(lambda: 42, 1) == 42
    finally:
        worker.close()
    assert not worker._thread.is_alive()


def test_serial_timeout_never_delivers_late_result_to_next_call():
    release = threading.Event()
    worker = SerialWorker("test-timeout-worker")
    try:
        with pytest.raises(TimeoutError):
            worker.call(lambda: release.wait(1), .01)
        with pytest.raises(RuntimeError, match="closed"):
            worker.call(lambda: "must not run", 1)
    finally:
        release.set()
        worker.close()
    assert not worker._thread.is_alive()


def test_capabilities_are_detached_cached_and_invalidated(monkeypatch):
    provider = IsolatedStrategyProvider("unused", step_timeout_s=1)
    calls = []
    def call(operation, *args, **kwargs):
        calls.append(operation)
        if operation == "describe":
            return ProviderCapabilities(warmup_requirement={"nested": [1]})
        return {}
    monkeypatch.setattr(provider, "_call", call)
    provider.describe().warmup_requirement["nested"].append(2)
    for _ in range(100):
        assert provider.describe().warmup_requirement == {"nested": [1]}
    assert calls.count("describe") == 1
    provider.prepare({})
    provider.describe()
    provider.restore({})
    provider.describe()
    assert calls.count("describe") == 3
    provider.abort()
    with pytest.raises(ValueError, match="closed"):
        provider.describe()


def test_official_sma_bounded_state_matches_full_history_and_legacy_restore():
    path = Path(__file__).resolve().parents[2] / "packages/candlescope-backtest-sdk/templates/sma_cross/strategy.py"
    spec = importlib.util.spec_from_file_location("official_sma_bounded", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for fast, slow in ((3, 5), (7, 3)):
        strategy = module.Strategy()
        context = SimpleNamespace(parameters={"fast": fast, "slow": slow})
        strategy.prepare(context)
        history = []
        for i in range(1000):
            close = str(100 + i % 23)
            history.append(close)
            frame = SimpleNamespace(bar=SimpleNamespace(close=close))
            if i < 10:
                strategy.warmup(frame)
                continue
            expected = "1" if sum(map(float, history[-fast:])) / fast > sum(map(float, history[-slow:])) / slow else "-1"
            assert strategy.step(frame).quantity == expected
            assert len(strategy.snapshot()["closes"]) <= max(fast, slow)
            if i == 500:
                recovered = module.Strategy()
                recovered.prepare(context)
                recovered.restore({"closes": history})
                assert recovered.snapshot() == strategy.snapshot()
                strategy = recovered
