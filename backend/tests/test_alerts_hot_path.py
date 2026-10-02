from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import app.alerts.runtime as runtime_module
from app.alerts.facade import AlertFacade
from app.alerts.runtime import AlertRuntimeEngine
from app.alerts.store import AlertStore
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey


def _rule(**overrides):
    return {
        "name": "price", "target": {"symbol": "BTCUSDT", "interval": "1m"},
        "expression": {"left": "close", "comparator": ">", "right": {"type": "number", "value": 1000000}},
        "afterTrigger": "keep", "cooldownMs": 0, **overrides,
    }


@pytest.mark.parametrize("legacy_list", [False, True])
def test_rule_lookup_does_not_parse_history_and_detaches_returned_values(tmp_path, monkeypatch, legacy_list):
    path = tmp_path / "alerts.json"
    record = {"id": "rule", **_rule()}
    payload = {"schemaVersion": 1, "rules": [record] if legacy_list else {"rule": record},
               "history": [{"message": "history"} for _ in range(5000)]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = AlertStore(path)
    assert store.get_rule("rule")["name"] == "price"
    monkeypatch.setattr(store, "_load", lambda: pytest.fail("hot read parsed history"))
    for _ in range(20):
        detached = store.get_rule("rule")
        detached["target"]["symbol"] = "mutated"
        assert store.get_rule("rule")["target"]["symbol"] == "BTCUSDT"


def test_rule_snapshot_remains_readable_while_history_writer_holds_lock(tmp_path):
    store = AlertStore(tmp_path / "alerts.json")
    rule = store.upsert_rule(_rule())
    entered, resume = threading.Event(), threading.Event()

    def writer():
        with store._lock:
            entered.set()
            assert resume.wait(3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(writer)
        assert entered.wait(3)
        try:
            read = pool.submit(store.get_rule, rule["id"])
            assert read.result(timeout=1)["id"] == rule["id"]
        finally:
            resume.set()
        pending.result()


def test_external_edits_refresh_and_failed_write_does_not_publish_new_rules(tmp_path, monkeypatch):
    path = tmp_path / "alerts.json"
    store = AlertStore(path)
    rule = store.upsert_rule(_rule())
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"][0]["name"] = "external name"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert store.list_rules()[0]["name"] == "external name"
    def fail_replace(*_):
        raise OSError("disk unavailable")
    monkeypatch.setattr("app.alerts.store.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk unavailable"):
        store.upsert_rule({**store.get_rule(rule["id"]), "name": "uncommitted"})
    assert store.get_rule(rule["id"])["name"] == "external name"


def test_concurrent_history_writes_keep_rule_snapshot_and_trigger_counts_consistent(tmp_path):
    store = AlertStore(tmp_path / "alerts.json")
    rule = store.upsert_rule(_rule())
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: store.append_history_if_eligible({"ruleId": rule["id"]}), range(20)))
    assert all(records)
    assert len({record["id"] for record in records}) == 20
    assert store.get_rule(rule["id"])["triggerCount"] == 20
    assert len(store.list_history()) == 20
    assert AlertStore(store.path).get_rule(rule["id"])["triggerCount"] == 20


@pytest.mark.anyio
async def test_price_rules_skip_indicators_and_same_series_rules_share_rebuild(tmp_path, monkeypatch):
    facade = AlertFacade(store_path=tmp_path / "alerts.json")
    price = facade.save_rule(_rule())
    first = facade.save_rule(_rule(name="rsi1", expression={"left": "rsi", "comparator": ">", "right": {"type": "number", "value": 200}}))
    second = facade.save_rule(_rule(name="rsi2", expression={"left": "rsi", "comparator": ">", "right": {"type": "number", "value": 300}}))
    runtime = AlertRuntimeEngine(facade=facade)
    seed = [BarData(time=n, open=n, high=n, low=n, close=n, volume=1) for n in range(1, 61)]
    for rule in (price, first, second):
        runtime._bar_windows[rule["id"]] = list(seed)
    calls = []
    original = runtime_module.compute_alert_indicator_values
    def compute(bars):
        calls.append(tuple((bar.time, bar.close) for bar in bars))
        return original(bars)
    monkeypatch.setattr(runtime_module, "compute_alert_indicator_values", compute)
    event = DataEvent(DataEventType.BAR_CLOSED, SeriesKey("BTCUSDT", "1m"),
                      BarData(time=61, open=61, high=61, low=61, close=61, volume=1))
    assert await runtime.evaluate_event(price["id"], event) is None
    assert calls == []
    for rule in (first, second):
        assert await runtime.evaluate_event(rule["id"], event) is None
    assert len(calls) == 1
    amendment = DataEvent(DataEventType.BAR_AMENDED, event.key,
                          BarData(time=20, open=500, high=500, low=500, close=500, volume=1))
    for rule in (first, second):
        await runtime.evaluate_event(rule["id"], amendment)
    assert len(calls) == 2
    assert runtime._previous_values[first["id"]]["rsi"] != 100
