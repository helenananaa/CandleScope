from dataclasses import replace
from pathlib import Path
import json

import pytest

from app.backtest.strategy.local_python import LocalPythonRunner
from app.backtest.strategy.protocol import ObservationFrame
from app.simulation.kernel import SimulationKernel
from app.simulation.cost_sensitivity import build_cost_sensitivity_matrix
from app.simulation.execution_realism import EXECUTION_REALISM_V2, BAR_PATH_SCENARIO
from decimal import Decimal
from tests.test_backtest_colocated import bars


def prepared(monkeypatch, direct):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    monkeypatch.setenv("BACKTEST_DIRECT_OBJECTS_ENABLED", str(int(direct)))
    runner = LocalPythonRunner(bound_transcript=False)
    runner.start()
    root = Path(__file__).resolve().parents[2]/"packages/candlescope-backtest-sdk/templates/sma_cross"
    runner.call("prepare", {"bundleDir":str(root), "entrypoint":"strategy:Strategy", "parameters":{"fast":3,"slow":5}})
    return runner


def frame(sequence=1):
    return ObservationFrame(run_id="direct-test", sequence=sequence,
        event_time_ms=sequence*60000, watermark_ms=sequence*60000, phase="EVALUATION",
        market={"venue":"local", "symbol":"BTCUSDT"}, input_hash="sha256:test",
        bar={"open":"1e2", "high":"101.00", "low":"99", "close":"100.000", "volume":"1000"},
        features={"close":"100"})


@pytest.mark.parametrize("variant", ["normal", "unicode", "del", "large_map", "long_string", "unsafe_integer", "nonfinite"])
def test_object_and_json_paths_have_same_outputs_errors_and_receipts(monkeypatch, variant):
    value = frame()
    if variant in {"unicode", "del"}:
        value = replace(value, market={"symbol":"比特币" if variant == "unicode" else "\x7f"})
    elif variant == "large_map":
        value = replace(value, market={str(i):"v" for i in range(20)})
    elif variant == "long_string":
        value = replace(value, run_id="x"*200)
    elif variant == "unsafe_integer":
        value = replace(value, sequence=2**60)
    elif variant == "nonfinite":
        value = replace(value, bar={**value.bar, "close":"NaN"})
    results = []
    for direct in (False, True):
        runner = prepared(monkeypatch, direct)
        try:
            result = runner.observe_frame(value)
            outcome = None if result is None else result.to_wire()
        except Exception as exc:
            outcome = (type(exc).__name__, str(exc))
        results.append((outcome, runner.close()))
    assert results[0] == results[1]


def test_common_observation_has_no_json_roundtrip(monkeypatch):
    runner = prepared(monkeypatch, True)
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected JSON decoding on direct object path")
    monkeypatch.setattr(json, "loads", forbidden)
    assert runner.observe_frame(frame()).kind == "TARGET_POSITION"


def test_fallback_strategy_mutation_does_not_change_request_receipt(monkeypatch):
    from candlescope_backtest_sdk import TargetPosition, encode_output
    from app.backtest.identity import canonical_json
    from app.backtest.strategy.python_provider import _author_observation
    class Mutator:
        def step(self, observation):
            observation.market["nested"]["x"] = "changed"
            return TargetPosition("1")
    runner = prepared(monkeypatch, True)
    runner._strategy = Mutator()
    value = replace(frame(), market={"nested":{"x":"original"}})
    request = {"id":runner._count+1, "method":"step", "params":{"observation":_author_observation(value)}}
    expected = runner._transcript_hash.copy()
    expected.update(b",")
    expected.update(canonical_json({"request":request, "response":{
        "id":request["id"], "ok":True, "result":encode_output(1, TargetPosition("1"))}}).encode())
    expected.update(b"]")
    runner.observe_frame(value)
    assert runner.close()["transcriptHash"] == "sha256:"+expected.hexdigest()


@pytest.mark.parametrize("end_policy", ["CANCEL_AT_END", "KEEP_OPEN"])
@pytest.mark.parametrize("funding", ["0", "0.001"])
def test_sensitivity_only_engine_matches_complete_reference_matrix(end_policy, funding):
    events = bars(1000)
    def strategy(_, event):
        if event.sequence % 23 == 1:
            return [{"side":"BUY" if event.sequence % 2 else "SELL", "type":"MARKET", "qty":"2", "tif":"IOC"}]
        if event.sequence == 999:
            return [{"side":"BUY", "type":"LIMIT", "qty":"1", "limit_price":"1"}]
        return []
    kernel = SimulationKernel(execution_model_revision=EXECUTION_REALISM_V2,
        bar_path_scenario=BAR_PATH_SCENARIO, participation_rate=Decimal("0.001"),
        funding_rate=Decimal(funding), funding_interval_ms=120000,
        equity_curve_event_interval=100, order_end_policy=end_policy)
    primary = kernel.run(events, strategy, finalize=True)
    reference = build_cost_sensitivity_matrix(kernel, events, primary, fast_bar=False)
    assert build_cost_sensitivity_matrix(kernel, events, primary, fast_bar=True) == reference


def test_unsampled_equity_is_not_materialized(monkeypatch):
    kernel = SimulationKernel(execution_model_revision=EXECUTION_REALISM_V2,
        bar_path_scenario=BAR_PATH_SCENARIO, participation_rate=Decimal("0.1"),
        equity_curve_event_interval=100)
    account = type(kernel.account)
    original = account.equity
    calls = []
    def equity(self):
        calls.append(1)
        return original(self)
    monkeypatch.setattr(account, "equity", equity)
    result = kernel.run(bars(1000), lambda *_: [], finalize=True)
    assert [row["sequence"] for row in result.equity_curve] == [1,*range(100,1001,100)]
    assert len(calls) < 30


def test_sensitivity_does_not_recreate_unused_decision_evidence(monkeypatch):
    import app.simulation.kernel as module
    kernel = SimulationKernel(execution_model_revision=EXECUTION_REALISM_V2,
        bar_path_scenario=BAR_PATH_SCENARIO, participation_rate=Decimal("0.1"))
    events = bars(100)
    primary = kernel.run(events, lambda *_: [], finalize=True)
    expected = build_cost_sensitivity_matrix(kernel, events, primary, fast_bar=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("unused decision evidence was rebuilt")
    monkeypatch.setattr(module, "_decision_record", forbidden)
    assert build_cost_sensitivity_matrix(kernel, events, primary) == expected


def test_sensitivity_preserves_historical_mark_and_contract_ledger():
    from tests.test_backtest_account_v2_m4 import event, rules
    events = (rules(1), event("MARK_INDEX", 2, mark_price="100", index_price="100"),
              event("BARS", 3, open="100", high="101", low="99", close="100", volume="10"),
              event("MARK_INDEX", 4, mark_price="101", index_price="101"),
              event("BARS", 5, open="100", high="102", low="99", close="101", volume="10"),
              event("MARK_INDEX", 6, mark_price="102", index_price="102"),
              event("BARS", 7, open="101", high="103", low="100", close="102", volume="10"))
    kernel = SimulationKernel(account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="OFF",
        execution_model_revision=EXECUTION_REALISM_V2, bar_path_scenario=BAR_PATH_SCENARIO,
        participation_rate=Decimal("0.1"))
    def strategy(_, row):
        return [{"side":"BUY" if row.sequence == 1 else "SELL", "type":"MARKET", "qty":"1"}] if row.sequence <= 2 else []
    primary = kernel.run(events, strategy, finalize=True)
    assert primary.fills
    assert build_cost_sensitivity_matrix(kernel, events, primary) == build_cost_sensitivity_matrix(kernel, events, primary, fast_bar=False)


def test_report_sealing_detaches_and_verification_is_read_only():
    from copy import deepcopy
    from app.backtest.reports import seal_report, verify_report_hash
    source = {"runId":"run-1", "hashes":{"report":"old"}, "nested":[{"value":"1"}]}
    original = deepcopy(source)
    sealed = seal_report(source)
    assert verify_report_hash(sealed)
    assert source == original
    before = deepcopy(sealed)
    assert verify_report_hash(sealed) and sealed == before
    sealed["nested"][0]["value"] = "2"
    assert source == original
    assert not verify_report_hash(sealed)


def test_explanation_binding_detaches_without_repeated_encoding(monkeypatch):
    from copy import deepcopy
    from app.backtest import trade_explanation as module
    value = module.unavailable_explanation(run_id="run-1", strategy_revision_id="r1",
        action="ENTER", decision_id="d1", decision_time_ms=1)
    original = deepcopy(value)
    calls = []
    encode = module.jcs_dumps
    def count(payload):
        calls.append(1)
        return encode(payload)
    monkeypatch.setattr(module, "jcs_dumps", count)
    assert module.verify_explanation(value)
    assert len(calls) == 1
    bound = module.bind_trade_id(value, "trade-1")
    assert module.verify_explanation(bound)
    bound["omissions"]["conditionsDropped"] = 20
    assert value == original
    assert not module.verify_explanation(bound)
