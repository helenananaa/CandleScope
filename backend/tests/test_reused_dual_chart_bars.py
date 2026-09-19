from dataclasses import replace
import shutil

import pytest

from app.backtest.service import BacktestService
from scripts.benchmark_trade_strategy import events, settings
from tests.test_trade_research_options import Orders, request


@pytest.mark.parametrize("count", [1, 25, 501])
@pytest.mark.parametrize("interval", ["1m", "5m"])
def test_chart_cache_and_results_are_exact_without_rescan(tmp_path, monkeypatch, count, interval):
    import app.backtest.service as module

    config = settings(tmp_path, 100)
    service = BacktestService.start(config, now_ms=1)
    created = service.create_run({**request(True), "signal_interval": interval}, idempotency_key="same", now_ms=2)
    service.shutdown()
    original = module.derive_complete_trade_bars
    calls = []

    def derive(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "derive_complete_trade_bars", derive)
    outcomes = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_REUSE_DUAL_CHART_BARS_ENABLED", str(enabled))
        db = tmp_path / f"chart-{enabled}.db"
        shutil.copy2(config.db_path, db)
        service = BacktestService.start(replace(config, db_path=db), now_ms=1)
        calls.clear()
        try:
            completed = service.execute_dual_clock_run(created["run_id"], events=events(count), provider=Orders(), now_ms=3)
            outcomes.append((completed["result"], completed["report"], service.repository.get_chart_cache(created["run_id"])))
            assert len(calls) == 1 - enabled
        finally:
            service.shutdown()
    assert outcomes[0] == outcomes[1]


def test_resumed_run_reconstructs_full_chart(tmp_path, monkeypatch):
    import app.backtest.service as module

    monkeypatch.setenv("BACKTEST_REUSE_DUAL_CHART_BARS_ENABLED", "1")
    service = BacktestService.start(settings(tmp_path, 100), now_ms=1)
    run = service.create_run(request(True), idempotency_key="resume", now_ms=2)
    save = service.repository.save_checkpoint

    def interrupt(row):
        value = save(row)
        if row["sequence"] == 200:
            raise KeyboardInterrupt()
        return value

    original = module.derive_complete_trade_bars
    calls = []

    def derive(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "derive_complete_trade_bars", derive)
    service.repository.save_checkpoint = interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            service.execute_dual_clock_run(run["run_id"], events=events(501), provider=Orders(), now_ms=3)
        service.repository.save_checkpoint = save
        assert service.requeue_interrupted_run(run["run_id"], expected_generation=1, now_ms=4)
        resumed = service.execute_dual_clock_run(run["run_id"], events=events(501), provider=Orders(), now_ms=5)
        assert len(calls) == 1
        clean = service.create_run(request(True), idempotency_key="clean", now_ms=6)
        normal = service.execute_dual_clock_run(clean["run_id"], events=events(501), provider=Orders(), now_ms=7)
        assert len(calls) == 1
        assert resumed["result"] == normal["result"]
        resumed_cache = service.repository.get_chart_cache(run["run_id"])
        normal_cache = service.repository.get_chart_cache(clean["run_id"])
        for key in ("bars_json", "bars_hash", "bar_count", "interval"):
            assert resumed_cache[key] == normal_cache[key]
    finally:
        service.shutdown()
