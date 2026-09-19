from copy import deepcopy
import gc
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

native_rows = pytest.importorskip("app.backtest.strategy._native_rows", reason="build backend/native/setup_native.py for native qualification")
RowFactory = native_rows.RowFactory
from app.backtest.strategy.protocol import ObservationFrame, StrategyProviderSession, canonical_hash
from app.backtest.identity import canonical_json
from app.backtest.strategy.python_provider import _author_observation, PythonHostProvider
from app.backtest.strategy.local_python import LocalPythonRunner
from app.backtest.strategy.host_adapter import StrategyHostAdapter
from app.backtest.strategy.generic_bar import build_generic_bar
from app.backtest.colocated import _GuardedProvider
from app.market_dataset.snapshot import MarketEvent
from candlescope_backtest_sdk import Bar, Observation, TargetPosition, OrderIntent, Signal

FIELDS = ("open", "high", "low", "close", "volume")
MARKET = {"venue": "local", "symbol": 'BTC"\\\x7f'}


def row(index=1):
    return MarketEvent(index, index*60000, "BARS", {"open":"100.00", "high":"101.000",
        "low":"99", "close":"100.0", "volume":"10000", "open_time_ms":index*60000-60000,
        "close_time_ms": index*60000})


def reference_frame(event, market=MARKET, phase="EVALUATION"):
    features = {name: str(event.payload[name]) for name in FIELDS if event.payload.get(name) is not None}
    return ObservationFrame("native", event.sequence, event.event_time_ms, event.event_time_ms, phase,
        market, canonical_hash({"sequence":event.sequence,"watermark":event.event_time_ms,
            "bar":event.payload,"trade":None,"features":features}), bar=event.payload, features=features)


def test_native_values_and_bytes_cover_ascii_and_decimal_spelling():
    factory = RowFactory("native", MARKET, Bar, Observation)
    rng = random.Random(17)
    for index in range(1, 200):
        event = row(index)
        event.payload["extra"] = ''.join(chr(rng.randrange(128)) for _ in range(80))
        event.payload['key"\x00\x7f'] = -index
        event.payload["low"] = "-0.000" if index % 2 else "0.000"
        obs, encoded = factory.build(event.payload, event.sequence, event.event_time_ms, "EVALUATION")
        expected = _author_observation(reference_frame(event))
        assert encoded == canonical_json(expected).encode()
        assert obs == Observation.from_wire(expected)
    assert factory.stats() == {"built":199, "fallback":0}


@pytest.mark.parametrize("value", ["1e2", "+1", "01", ".1", "1.", "NaN", "中文", "1"*129, None, 100, 1.5])
def test_unqualified_values_defer_without_exception(value):
    factory = RowFactory("native", MARKET, Bar, Observation)
    event = row()
    event.payload["close"] = value
    assert factory.build(event.payload, 1, 60000, "EVALUATION") is None


def test_native_object_ownership_and_factory_references():
    factory = RowFactory("native", MARKET, Bar, Observation)
    first, wire = factory.build(row().payload, 1, 60000, "EVALUATION")
    first.market["symbol"] = "changed"
    first.features["close"] = "changed"
    second, _ = factory.build(row(2).payload, 2, 120000, "EVALUATION")
    assert second.market == MARKET and second.features["close"] == "100.0"
    assert json.loads(wire)["market"] == MARKET
    gc.collect()
    before = sys.getrefcount(RowFactory), sys.getrefcount(Bar), sys.getrefcount(Observation)
    for _ in range(2000):
        temporary = RowFactory("native", MARKET, Bar, Observation)
        temporary.build(row().payload, 1, 60000, "EVALUATION")
    del temporary
    gc.collect()
    assert (sys.getrefcount(RowFactory), sys.getrefcount(Bar), sys.getrefcount(Observation)) == before
    with pytest.raises(RuntimeError, match="already initialized"):
        factory.__init__("other", MARKET, Bar, Observation)


class Stateful:
    def __init__(self):
        self.seen = 0
        self.feedback = 0
        self.previous = None
    def warmup(self, obs):
        self.seen += 1
    def step(self, obs):
        assert self.previous is None or self.previous is not obs
        self.previous = obs
        obs.market["custom"] = "mutated"
        obs.features["custom"] = "mutated"
        self.seen += 1
        if self.seen == 9:
            return Signal("LONG", score="1.2")
        if self.seen == 13:
            return OrderIntent("BUY", "LIMIT", "1", limit_price="99", client_tag="中文\x7f")
        return TargetPosition("1" if (self.seen+self.feedback) % 3 else "-1")
    def on_execution_report(self, report):
        self.feedback += 1


def pipeline(monkeypatch, native, bound):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    monkeypatch.setenv("BACKTEST_GENERIC_BAR_ENABLED", str(int(native)))
    runner = LocalPythonRunner(bound_transcript=bound)
    runner.start()
    runner._strategy = Stateful()
    provider = PythonHostProvider.__new__(PythonHostProvider)
    provider.runner = runner
    guarded = _GuardedProvider(provider, SimpleNamespace(value=0.), 2., 2.)
    session = StrategyProviderSession(guarded, run_id="native")
    session.prepared = True
    adapter = StrategyHostAdapter(session, inline=True)
    direct = build_generic_bar(guarded, session, adapter, MARKET, FIELDS)
    assert (direct is not None) == native
    def observe(event, phase):
        if direct:
            return direct.observe(event, phase)
        frame = reference_frame(event, phase=phase)
        return adapter.observe(sequence=frame.sequence, event_time_ms=frame.event_time_ms,
            watermark_ms=frame.watermark_ms, phase=phase, market=MARKET, bar=event.payload, features=frame.features)
    return runner, session, adapter, direct, observe


@pytest.mark.parametrize("bound", [False, True])
def test_state_feedback_fallback_and_v1_transcript_match(monkeypatch, bound):
    outcomes = []
    for native in (False, True):
        runner, session, adapter, direct, observe = pipeline(monkeypatch, native, bound)
        outputs = []
        try:
            for index in range(1, 31):
                event = row(index)
                if index == 10:
                    event.payload["close"] = "1e2"
                output = observe(event, "WARMUP" if index < 4 else "EVALUATION")
                outputs.append(None if output is None else output.to_wire())
                if index % 4 == 0:
                    session.on_execution_report({"accepted":True,"generation":session.generation,"fill":{"price":"100"}})
            outcomes.append((outputs, runner.close(), runner._strategy.seen, runner._strategy.feedback))
            if direct:
                assert direct.factory.stats() == {"built":29, "fallback":1}
        finally:
            adapter.close()
    assert outcomes[0] == outcomes[1]


def test_user_exception_has_same_position_and_receipt(monkeypatch):
    outcomes = []
    for native in (False, True):
        runner, session, adapter, _, observe = pipeline(monkeypatch, native, False)
        original = runner._strategy.step
        def failure(obs):
            if obs.sequence == 7:
                raise ValueError('failure 中文\\"\x7f')
            return original(obs)
        runner._strategy.step = failure
        try:
            with pytest.raises(Exception) as caught:
                for i in range(1, 9):
                    observe(row(i), "EVALUATION")
            outcomes.append((type(caught.value), str(caught.value), session.last_sequence, runner.close()))
        finally:
            adapter.close()
    assert outcomes[0] == outcomes[1]


def test_native_fast_route_does_not_rebuild_host_or_sdk_wire_dict(monkeypatch):
    runner, _, adapter, _, observe = pipeline(monkeypatch, True, False)
    def forbidden(*args, **kwargs):
        raise AssertionError("redundant observation construction")
    runner._author_frame = runner._make_frame = runner._bounded_frame = forbidden
    try:
        assert observe(row(), "EVALUATION").kind == "TARGET_POSITION"
    finally:
        adapter.close()


def test_native_event_budget_and_output_wire_are_exact():
    from candlescope_backtest_sdk import encode_output
    from app.backtest.strategy.direct_observation import encode_prepared_output
    factory = RowFactory("native", MARKET, Bar, Observation)
    for i in range(1, 129):
        event = row(i)
        event.payload["extra"] = chr(i-1)
        expected = canonical_json({"sequence":event.sequence,"event_time_ms":event.event_time_ms,
                                   "role":event.role,"payload":event.payload}).encode()
        assert native_rows.event_wire_size(event.payload, event.sequence, event.event_time_ms, event.role) == len(expected)
    for value in (TargetPosition("-1"), Signal("LONG", score="1.20"),
                  OrderIntent("BUY", "LIMIT", "1", limit_price="99", client_tag='tag"\\\n')):
        wire, qualified, encoded = encode_prepared_output(13, value, factory)
        assert qualified and wire == encode_output(13, value)
        assert encoded == canonical_json(wire).encode()
    assert native_rows.event_wire_size({"float":1e-7}, 1, 1, "BARS") is None
    assert native_rows.event_wire_size({"unicode":"中文"}, 1, 1, "BARS") is None


def test_missing_or_incompatible_native_module_keeps_reference_available(monkeypatch):
    _, session, adapter, _, observe = pipeline(monkeypatch, False, False)
    monkeypatch.setenv("BACKTEST_GENERIC_BAR_ENABLED", "1")
    try:
        monkeypatch.setattr(native_rows, "ROW_PROTOCOL_ABI", -1)
        assert build_generic_bar(session.provider, session, adapter, MARKET, FIELDS) is None
        monkeypatch.setitem(sys.modules, "app.backtest.strategy._native_rows", None)
        # The package may retain a previously imported attribute; an incompatible
        # ABI still refuses the accelerator, and ordinary execution is unchanged.
        assert build_generic_bar(session.provider, session, adapter, MARKET, FIELDS) is None
        assert observe(row(), "EVALUATION").kind == "TARGET_POSITION"
    finally:
        adapter.close()


def test_sdk_constructor_and_slot_changes_take_reference_path(monkeypatch):
    from candlescope_backtest_sdk import models
    runner, _, adapter, direct, observe = pipeline(monkeypatch, True, False)
    original = models._decimal_string
    try:
        monkeypatch.setattr(models, "_decimal_string", lambda value, label: original(value, label))
        assert observe(row(), "EVALUATION").kind == "TARGET_POSITION"
        assert direct.factory.stats()["built"] == 0
    finally:
        adapter.close()
    monkeypatch.setattr(models, "_decimal_string", original)
    runner, _, adapter, direct, observe = pipeline(monkeypatch, True, False)
    original_slot = models.Bar.close
    try:
        monkeypatch.setattr(models.Bar, "close", property(lambda self: "changed"))
        with pytest.raises(Exception, match="setter"):
            observe(row(), "EVALUATION")
        assert direct.factory.stats()["built"] == 0
    finally:
        monkeypatch.setattr(models.Bar, "close", original_slot)
        adapter.close()


@pytest.mark.parametrize("case", ["EMPTY", "STATE", "FEEDBACK", "ORDERS"])
@pytest.mark.parametrize("bound", [False, True])
def test_arbitrary_scripts_keep_entire_report_and_v1_receipt(tmp_path, monkeypatch, case, bound):
    from dataclasses import replace
    import shutil
    from app.backtest.service import BacktestService
    from tests.test_backtest_control_plane import _settings, _payload
    from tests.test_backtest_colocated import bars
    from scripts.generic_strategy_sources import SOURCES
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    bundle = tmp_path / "user-script"
    bundle.mkdir()
    (bundle / "strategy.py").write_bytes(SOURCES[case].encode())
    settings = _settings(tmp_path, BACKTEST_CHECKPOINT_EVENT_INTERVAL="31", BACKTEST_TRADE_EXPLANATION_ENABLED="1")
    seed = BacktestService.start(settings, now_ms=1)
    run = seed.create_run(_payload(parameters={"fast":3,"slow":5}, execution_model_revision="EXECUTION_REALISM_V2"),
                          idempotency_key="same", now_ms=2)
    seed.shutdown()
    results = []
    for native in (False, True):
        db = tmp_path / f"mode-{native}.db"
        shutil.copy2(settings.db_path, db)
        monkeypatch.setenv("BACKTEST_GENERIC_BAR_ENABLED", str(int(native)))
        service = BacktestService.start(replace(settings, db_path=db), now_ms=1)
        try:
            provider = PythonHostProvider(bundle, parameters={"fast":3,"slow":5}, mode="TRUSTED_LOCAL",
                                          trusted_confirmed=True, bound_transcript=bound)
            results.append(service.execute_bar_run(run["run_id"], events=bars(350), provider=provider, now_ms=3))
        finally:
            service.shutdown()
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["report"] == results[1]["report"]
