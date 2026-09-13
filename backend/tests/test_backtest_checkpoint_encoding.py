from dataclasses import replace
import json
import shutil

import pytest

from app.backtest.checkpoint_codec import checkpoint_json, checkpoint_session
from app.backtest.identity import canonical_json, sha256_hex
from app.backtest.service import BacktestService
from app.backtest.strategy.chart_pyne import ChartPyneStrategyProvider
from app.backtest.strategy.protocol import StrategyProviderSession, StrategyProviderError
from tests.test_backtest_chart_batch import events, session
from tests.test_backtest_control_plane import _settings, _payload


@pytest.mark.parametrize("state", [
    {"unicode": "中文\x7f\ud800", "float": 1e-7, "big": 2**100, "list": [False, None, "x"]},
    {}, [], False, None, "", {"tuple": (1, 2, 3)},
])
def test_checkpoint_fragments_equal_original_bytes_and_hashes(state):
    class Provider:
        def snapshot(self):
            return state
    current = StrategyProviderSession(Provider(), run_id="test")
    expected = current.snapshot()
    snapshot, encoded, size = checkpoint_session(current)
    assert snapshot == expected
    assert encoded == canonical_json(expected)
    assert size == len(canonical_json(state or {}).encode("utf-8"))
    payload = {"provider": snapshot, "engine": {"a": [1, "中文"]}, "sequence": 9}
    actual = checkpoint_json(payload, encoded)
    assert actual == canonical_json(payload)
    assert sha256_hex(actual) == sha256_hex(payload)


def test_provider_payload_is_captured_and_encoded_once(monkeypatch):
    state = {"big": ["a"] * 10000}
    captures = []
    class Provider:
        def snapshot(self):
            captures.append(1)
            return state
    dumps, encodings = json.dumps, []
    def tracked(value, *args, **kwargs):
        if value is state:
            encodings.append(1)
        return dumps(value, *args, **kwargs)
    monkeypatch.setattr(json, "dumps", tracked)
    snapshot, encoded, _ = checkpoint_session(StrategyProviderSession(Provider(), run_id="test"))
    checkpoint_json({"provider": snapshot}, encoded)
    assert len(captures) == len(encodings) == 1


@pytest.mark.parametrize("state", [{"bad": float("nan")}, {"bad": object()}])
def test_encoding_keeps_strict_provider_errors(state):
    class Provider:
        def snapshot(self):
            return state
    current = StrategyProviderSession(Provider(), run_id="test")
    with pytest.raises((TypeError, ValueError)) as original:
        current.snapshot()
    with pytest.raises(type(original.value)):
        checkpoint_session(current)


def test_compact_checkpoint_preserves_same_time_ordinal_and_old_restore():
    from app.backtest.strategy.protocol import ObservationFrame
    current = session('strategy("always")\nif close > 0\n  target_position(1)')
    data = events(300)
    def frame(event):
        return ObservationFrame("same", event.sequence, event.event_time_ms, event.event_time_ms,
                                "EVALUATION", {}, "input", bar=event.payload)
    for event in data[:200]:
        current.step(frame(event))
    original = current.snapshot()
    compact, encoded, _ = checkpoint_session(current)
    assert len(compact["provider"]["decisionTimeCounts"]) == 1
    assert len(encoded) < len(canonical_json(original))
    restored = session('strategy("always")\nif close > 0\n  target_position(1)')
    restored.restore(compact)
    legacy = session('strategy("always")\nif close > 0\n  target_position(1)')
    legacy.restore(original)
    for event in data[200:]:
        assert restored.step(frame(event)) == legacy.step(frame(event))
    assert restored.provider.report_metadata() == legacy.provider.report_metadata()
    assert restored.close() == legacy.close()


@pytest.mark.parametrize("compact", [False, True])
def test_fault_resume_from_old_and_compact_checkpoints_matches_clean_report(tmp_path, monkeypatch, compact):
    monkeypatch.setenv("BACKTEST_COMPACT_CHART_CHECKPOINT_ENABLED", str(int(compact)))
    settings = _settings(tmp_path, BACKTEST_TRADE_EXPLANATION_ENABLED="1", BACKTEST_CHECKPOINT_EVENT_INTERVAL="31")
    seed = BacktestService.start(settings, now_ms=1)
    source = 'strategy("always")\nif close > 0\n  target_position(1)'
    created = seed.create_run(_payload(strategy_source=source, execution_model_revision="EXECUTION_REALISM_V2"),
                              idempotency_key="same", now_ms=2)
    seed.shutdown()
    results = []
    for interrupt in (False, True):
        db = tmp_path / f"case-{interrupt}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        def fault(point, context):
            if point == "before_decision" and context["sequence"] == 47:
                raise StrategyProviderError("PROVIDER_TIMEOUT", "test recovery")
        try:
            if interrupt:
                service._fault_injector = fault
                with pytest.raises(StrategyProviderError, match="PROVIDER_TIMEOUT"):
                    service.execute_bar_run(created["run_id"], events=events(200), provider=ChartPyneStrategyProvider(), now_ms=3)
                checkpoint = service.repository.latest_checkpoint(created["run_id"])
                assert checkpoint["sequence"] == 31
                provider_state = json.loads(checkpoint["payload_json"])["provider"]["provider"]
                assert ("checkpointStateRevision" in provider_state) == compact
                service._fault_injector = None
                service.resume_failed_run(created["run_id"], now_ms=4)
            results.append(service.execute_bar_run(created["run_id"], events=events(200),
                                                   provider=ChartPyneStrategyProvider(), now_ms=5))
        finally:
            service.shutdown()
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["report"] == results[1]["report"]


def test_colocated_chart_with_contract_clock_keeps_market_sequence_mapping(tmp_path):
    from app.backtest.strategy.isolated import IsolatedStrategyProvider
    from app.backtest.strategy.chart_pyne import CHART_PYNE_REVISION
    from tests.test_backtest_account_v2_m4 import event, rules
    data = (rules(1), event("MARK_INDEX", 2, mark_price="100", index_price="100"),
            event("BARS", 3, open="100", high="101", low="99", close="100", volume="100"),
            event("MARK_INDEX", 4, mark_price="101", index_price="101"),
            event("BARS", 5, open="100", high="102", low="99", close="101", volume="100"))
    settings = _settings(tmp_path, BACKTEST_TRADE_EXPLANATION_ENABLED="1")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(strategy_source='strategy("always")\nif close > 0\n  target_position(1)',
        account_model="LINEAR_PERP_ONE_WAY_V2", contract_data_mode="HISTORICAL_CONTRACT_V1",
        funding_mode="OFF", leverage="10", execution_model_revision="EXECUTION_REALISM_V2"),
        idempotency_key="clock", now_ms=2)
    seed.shutdown()
    results = []
    for isolated in (False, True):
        db = tmp_path / f"clock-{isolated}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        try:
            provider = (IsolatedStrategyProvider(CHART_PYNE_REVISION, step_timeout_s=2)
                        if isolated else ChartPyneStrategyProvider())
            results.append(service.execute_bar_run(run["run_id"], events=data, provider=provider, now_ms=3))
        finally:
            service.shutdown()
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["report"] == results[1]["report"]
