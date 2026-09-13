"""V1 byte identity and ownership at the combined native output boundary."""
import gc
import sys

import pytest

from tests.test_generic_native_rows import native_rows, MARKET, pipeline, row
from candlescope_backtest_sdk import Bar, Observation, TargetPosition, Signal, OrderIntent, encode_output
from app.backtest.identity import canonical_json
from app.backtest.strategy.protocol import StrategyOutput
from app.backtest.strategy.python_provider import _target_state_hash, _to_host_output


@pytest.mark.parametrize("value", [TargetPosition("-0.00"), TargetPosition("1.250"),
    Signal("LONG", score="1.20"), OrderIntent("BUY", "STOP_LIMIT", "2.00", limit_price="99", stop_price="101", client_tag='a"\\\n')])
def test_parts_match_original_wire_and_host_with_detached_payload(value):
    factory = native_rows.RowFactory("test", MARKET, Bar, Observation)
    wire = encode_output(17, value)
    original = dict(wire["payload"])
    args, encoded = factory.output_parts(17, wire["kind"], wire["payload"], wire["schemaVersion"], _target_state_hash)
    assert encoded == canonical_json(wire).encode()
    assert StrategyOutput(*args) == _to_host_output(17, wire)
    args[2]["quantity"] = "mutated"
    assert wire["payload"] == original
    next_args, _ = factory.output_parts(18, wire["kind"], wire["payload"], wire["schemaVersion"], _target_state_hash)
    assert next_args[2] is not args[2]
    assert "mutated" not in next_args[2].values()


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("variant", ["normal", "unicode", "del", "subclass", "changed_method", "exception"])
def test_fused_and_old_output_chains_match(monkeypatch, bound, variant):
    outcomes = []
    for fused in (False, True):
        monkeypatch.setenv("BACKTEST_FUSED_OUTPUT_ENABLED", str(int(fused)))
        runner, session, adapter, _, observe = pipeline(monkeypatch, True, bound)
        original_step = runner._strategy.step
        class CustomTarget(TargetPosition):
            def to_payload(self):
                return {"quantity": self.quantity, "targetExposure": "3", "custom": "中文"}
        def step(obs):
            if obs.sequence == 5:
                if variant == "exception":
                    raise ValueError("same exception")
                if variant in {"unicode", "del"}:
                    return OrderIntent("BUY", "MARKET", "1", client_tag="中文" if variant == "unicode" else "\x7f")
                if variant == "subclass":
                    return CustomTarget("1")
                if variant == "changed_method":
                    runner._strategy.step = lambda observation: Signal("SHORT")
            return original_step(obs)
        runner._strategy.step = step
        outputs, error = [], None
        try:
            for index in range(1, 22):
                value = observe(row(index), "WARMUP" if index < 3 else "EVALUATION")
                outputs.append(value)
                if index % 4 == 0:
                    session.on_execution_report({"accepted": True, "generation": 1, "fill": {"price": "100"}})
        except Exception as exc:
            error = type(exc), str(exc), session.last_sequence
        finally:
            outcomes.append((outputs, error, runner.close()))
            adapter.close()
    assert outcomes[0] == outcomes[1]


def test_parts_do_not_retain_author_payload_or_callback():
    factory = native_rows.RowFactory("test", MARKET, Bar, Observation)
    payload = {"quantity": "1"}
    gc.collect()
    before = sys.getrefcount(payload), sys.getrefcount(_target_state_hash)
    for i in range(10000):
        factory.output_parts(i, "TARGET_POSITION", payload, "schema", _target_state_hash)
    gc.collect()
    assert (sys.getrefcount(payload), sys.getrefcount(_target_state_hash)) == before


def test_all_ascii_output_bytes_and_existing_aliases_match():
    factory = native_rows.RowFactory("test", MARKET, Bar, Observation)
    for code in range(128):
        value = OrderIntent("BUY", "MARKET", "1", client_tag=chr(code))
        wire = encode_output(3, value)
        parts = factory.output_parts(3, wire["kind"], wire["payload"], wire["schemaVersion"], _target_state_hash)
        if code == 127:
            assert parts is None
        else:
            assert StrategyOutput(*parts[0]) == _to_host_output(3, wire)
            assert parts[1] == canonical_json(wire).encode()
    for kind, payload in (("TARGET_POSITION", {"quantity": "1", "targetExposure": "2"}),
                          ("ORDER_INTENT", {"quantity": "1", "qty": "2"})):
        wire = {"kind": kind, "payload": payload, "sequence": 3, "schemaVersion": "schema"}
        from app.backtest.strategy.protocol import canonical_hash
        wire["outputHash"] = canonical_hash(wire)
        parts = factory.output_parts(3, kind, payload, "schema", _target_state_hash)
        assert StrategyOutput(*parts[0]) == _to_host_output(3, wire)
        assert parts[1] == canonical_json(wire).encode()


def test_old_extension_without_parts_keeps_existing_path(monkeypatch):
    runner, _, adapter, direct, observe = pipeline(monkeypatch, True, False)
    class OldFactory:
        def __getattr__(self, name):
            if name == "output_parts":
                raise AttributeError(name)
            return getattr(original, name)
    original = direct.factory
    direct.factory = OldFactory()
    try:
        assert observe(row(), "EVALUATION").kind == "TARGET_POSITION"
    finally:
        adapter.close()


@pytest.mark.parametrize("case", ["EMPTY", "STATE", "FEEDBACK", "ORDERS"])
@pytest.mark.parametrize("bound", [False, True])
def test_fused_switch_preserves_complete_spawned_result_and_report(tmp_path, monkeypatch, case, bound):
    from dataclasses import replace
    import shutil
    from app.backtest.service import BacktestService
    from app.backtest.strategy.python_provider import PythonHostProvider
    from tests.test_backtest_control_plane import _settings, _payload
    from tests.test_backtest_colocated import bars
    from scripts.generic_strategy_sources import SOURCES
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    monkeypatch.setenv("BACKTEST_GENERIC_BAR_ENABLED", "1")
    bundle = tmp_path / "script"
    bundle.mkdir()
    (bundle / "strategy.py").write_text(SOURCES[case], encoding="utf-8")
    settings = _settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="31", BACKTEST_TRADE_EXPLANATION_ENABLED="1")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(execution_model_revision="EXECUTION_REALISM_V2"), idempotency_key="same", now_ms=2)
    seed.shutdown()
    results = []
    for fused in (False, True):
        monkeypatch.setenv("BACKTEST_FUSED_OUTPUT_ENABLED", str(int(fused)))
        db = tmp_path / f"fused-{fused}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        try:
            provider = PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True, bound_transcript=bound)
            results.append(service.execute_bar_run(run["run_id"], events=bars(350), provider=provider, now_ms=3))
        finally:
            service.shutdown()
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["report"] == results[1]["report"]
