import hashlib
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
import gc
import shutil
import sys

import pytest

from tests.test_generic_native_rows import native_rows, MARKET, pipeline, row
from candlescope_backtest_sdk import Bar, Observation
from app.backtest.identity import canonical_json
from app.simulation.kernel import SimulatedFill, SimulatedOrder, SimulationKernel, _flat_record, _empty_decision_hash


@pytest.mark.parametrize("bound", [False, True])
def test_success_record_matches_full_response_bytes(bound):
    traces = []
    for combined in (False, True):
        factory = native_rows.RowFactory("r", MARKET, Bar, Observation)
        hasher = hashlib.sha256(b"[")
        factory.bind_transcript(hasher)
        chain = "sha256:GENESIS"
        for index in range(1, 129):
            request_id = min(index, 2) if bound else index
            result = None if index % 3 else {"text": chr(index-1), "number": 1e-7}
            raw = canonical_json(result).encode()
            obs = b'{"sequence":' + str(index).encode() + b'}'
            if combined:
                value = factory.record_success(request_id, index < 3, obs, raw, chain if bound else None)
            else:
                response = canonical_json({"id":request_id, "ok":True, "result":result}).encode()
                value = factory.record_v1(request_id, index < 3, obs, response, chain if bound else None)
            if bound:
                chain = value
        hasher.update(b"]")
        traces.append(chain if bound else hasher.hexdigest())
    assert traces[0] == traces[1]


def test_empty_decision_exact_bytes_and_fallback():
    for text in ["sha256:GENESIS", "sha256:"+"f"*64, "".join(map(chr, range(128))), "中文", "\ud800", "x"*129]:
        for sequence in (-9007199254740991, -1, 0, 9007199254740991, 2**90):
            actual = native_rows.empty_decision_hash(text, sequence, sequence, hashlib.sha256)
            if actual is not None:
                assert actual == _empty_decision_hash(text, sequence, sequence)
            else:
                assert not text.isascii() or len(text) > 128 or abs(sequence) > 9007199254740991


def test_native_empty_hash_defers_unsupported_types_and_propagates_errors():
    assert native_rows.empty_decision_hash("x", True, 1, hashlib.sha256) is None
    assert native_rows.empty_decision_hash("x", 1.0, 1, hashlib.sha256) is None
    with pytest.raises(TypeError):
        native_rows.empty_decision_hash("x", 1)
    with pytest.raises(TypeError):
        native_rows.empty_decision_hash("x", 1, 1, None)
    class BadHash:
        def hexdigest(self):
            return 42
    with pytest.raises(ValueError, match="invalid SHA256"):
        native_rows.empty_decision_hash("x", 1, 1, lambda value: BadHash())


def test_native_hash_does_not_retain_inputs():
    previous = "sha256:" + "a"*64
    gc.collect()
    before = sys.getrefcount(previous), sys.getrefcount(hashlib.sha256)
    for i in range(10000):
        native_rows.empty_decision_hash(previous, i, i, hashlib.sha256)
    gc.collect()
    assert (sys.getrefcount(previous), sys.getrefcount(hashlib.sha256)) == before


def test_kernel_hash_fallback_and_restore_keep_snapshot():
    from tests.test_backtest_colocated import bars
    from app.simulation.execution_realism import EXECUTION_REALISM_V2, BAR_PATH_SCENARIO
    snapshots = []
    for enabled in (False, True):
        kernel = SimulationKernel(execution_model_revision=EXECUTION_REALISM_V2,
            bar_path_scenario=BAR_PATH_SCENARIO, participation_rate=Decimal("0.1"))
        if enabled:
            kernel._native_empty_hash = native_rows.empty_decision_hash
            kernel._record_encoder = _flat_record
        kernel._decision_chain_hash = "legacy 中文\ud800"
        kernel.run(bars(10), lambda *_: [])
        saved = kernel.snapshot()
        kernel.restore(saved)
        kernel.run(bars(20)[10:], lambda *_: [])
        snapshots.append(kernel.snapshot())
    assert snapshots[0] == snapshots[1]


def test_flat_records_preserve_recursive_fallback_and_immutability():
    order = SimulatedOrder("o1", "BUY", "MARKET", Decimal("1.00"), 3)
    fill = SimulatedFill("o1", 3, 180000, "BUY", Decimal("100.00"), Decimal("1.00"), Decimal(".1"), "fill")
    for record in (order, fill):
        actual = _flat_record(record)
        assert actual == asdict(record)
        assert actual is not _flat_record(record)
    order.oco_group = {"mutable": [1]}
    detached = _flat_record(order)
    detached["oco_group"]["mutable"].append(2)
    assert order.oco_group == {"mutable": [1]}
    @dataclass
    class ExtraOrder(SimulatedOrder):
        extra: int = 9
    custom = ExtraOrder("o2", "BUY", "LIMIT", Decimal("1"), 3)
    assert _flat_record(custom) == asdict(custom)


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("fused", [False, True])
def test_receipt_route_keeps_outputs_feedback_fallback_and_exception(monkeypatch, bound, fused):
    outcomes = []
    monkeypatch.setenv("BACKTEST_FUSED_OUTPUT_ENABLED", str(int(fused)))
    for enabled in (False, True):
        monkeypatch.setenv("BACKTEST_HOST_HOTPATH_ENABLED", str(int(enabled)))
        runner, session, adapter, _, observe = pipeline(monkeypatch, True, bound)
        original = runner._strategy.step
        def step(obs):
            if obs.sequence == 25:
                raise ValueError("late error 中文")
            return original(obs)
        runner._strategy.step = step
        outputs = []
        try:
            for i in range(1, 28):
                outputs.append(observe(row(i), "WARMUP" if i < 3 else "EVALUATION"))
                if i % 4 == 0:
                    session.on_execution_report({"accepted":True, "generation":1, "fill":{"price":"100"}})
        except Exception as exc:
            outcomes.append((outputs, type(exc), str(exc), session.last_sequence, runner.close()))
        finally:
            adapter.close()
    assert len(outcomes) == 2 and outcomes[0] == outcomes[1]


def test_older_extension_without_success_method_keeps_route(monkeypatch):
    monkeypatch.delattr(native_rows.RowFactory, "record_success")
    runner, _, adapter, _, observe = pipeline(monkeypatch, True, False)
    try:
        assert observe(row(), "EVALUATION").kind == "TARGET_POSITION"
    finally:
        adapter.close()


@pytest.mark.parametrize("case", ["EMPTY", "STATE", "FEEDBACK", "ORDERS"])
@pytest.mark.parametrize("bound", [False, True])
def test_complete_spawned_result_and_report_are_identical(tmp_path, monkeypatch, case, bound):
    from app.backtest.service import BacktestService
    from app.backtest.strategy.python_provider import PythonHostProvider
    from tests.test_backtest_control_plane import _settings, _payload
    from tests.test_backtest_colocated import bars
    from scripts.generic_strategy_sources import SOURCES
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    bundle = tmp_path / "script"
    bundle.mkdir()
    (bundle / "strategy.py").write_text(SOURCES[case], encoding="utf-8")
    settings = _settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="31", BACKTEST_TRADE_EXPLANATION_ENABLED="1")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(execution_model_revision="EXECUTION_REALISM_V2"), idempotency_key="same", now_ms=2)
    seed.shutdown()
    results = []
    for enabled in (False, True):
        monkeypatch.setenv("BACKTEST_HOST_HOTPATH_ENABLED", str(int(enabled)))
        db = tmp_path / f"mode-{enabled}.db"
        shutil.copy2(settings.db_path, db)
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        try:
            provider = PythonHostProvider(bundle, mode="TRUSTED_LOCAL", trusted_confirmed=True, bound_transcript=bound)
            results.append(service.execute_bar_run(run["run_id"], events=bars(350), provider=provider, now_ms=3))
        finally:
            service.shutdown()
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["report"] == results[1]["report"]
