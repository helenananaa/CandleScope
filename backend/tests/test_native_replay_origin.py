"""Replay origin reads retain seals, JSON types, isolation and rejection behavior."""
import copy
import json
import sqlite3
import threading

import pytest

from app.backtest.native import NativeBacktests, encoded
from app.backtest.native_replay import NativeReplay


@pytest.fixture
def native():
    service = NativeBacktests.__new__(NativeBacktests)
    service.lock = threading.RLock()
    service.db = sqlite3.connect(":memory:")
    service.db.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
    service.db.execute("CREATE TABLE native_inputs (id TEXT PRIMARY KEY, wire TEXT NOT NULL)")
    yield service
    service.db.close()


def record():
    return {"run_id": "native_origin", "state": "COMPLETED", "execution_mode": "CANDLESCOPE",
            "input_hash": "frozen", "runtime_launch": {"command": ["frozen-python", "module"]},
            "config": {"language": "pine", "interval": "1m", "contexts": [
                {"symbol": "测试", "interval": "5m", "options": [True, False, None, 2**100, -0.0, 0.125]}],
                "execution_data": {"events": [{"price": "123.450", "quantity": "0.001"}]}},
            "result": {"account_authority": "candlescope", "report_hash": "sealed",
                       "observations": [{"equity": 123.45, "qty": "0.001"}]},
            "future_header": {"unchanged": [2**100, "元数据", False, None]}}


def store(native, value):
    native.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?)", ("native_origin", encoded(value)))


@pytest.mark.parametrize("missing", [None, "language", "interval", "contexts", "account_authority", "report_hash"])
@pytest.mark.parametrize("explicit_null", [False, True])
def test_origin_keeps_all_required_values_and_missing_versus_null(native, missing, explicit_null):
    value = record()
    if missing:
        parent = value["result"] if missing in {"account_authority", "report_hash"} else value["config"]
        if explicit_null:
            parent[missing] = None
        else:
            del parent[missing]
    store(native, value)
    expected = copy.deepcopy(value)
    expected["config"] = {key: value["config"][key] for key in ("language", "interval", "contexts") if key in value["config"]}
    expected["result"] = {key: value["result"].get(key) for key in ("account_authority", "report_hash")}
    # Canonical bytes also distinguish numeric/boolean types and negative zero.
    assert encoded(native._replay_origin("native_origin")) == encoded(expected)
    assert native.get("native_origin") == value


def test_origin_mutation_does_not_change_public_or_later_reads(native):
    value = record()
    store(native, value)
    origin = native._replay_origin("native_origin")
    origin["config"]["contexts"][0]["options"].append("changed")
    origin["result"]["report_hash"] = "changed"
    origin["runtime_launch"]["command"].clear()
    assert native.get("native_origin") == value
    assert native._replay_origin("native_origin")["result"]["report_hash"] == "sealed"


@pytest.mark.parametrize("field", ["config", "result"])
@pytest.mark.parametrize("replacement", [None, [], "bad shape", 42, False])
def test_non_object_shapes_are_not_normalized_into_usable_metadata(native, field, replacement):
    value = record()
    value[field] = replacement
    store(native, value)
    assert native._replay_origin("native_origin") == native.get("native_origin") == value


@pytest.mark.parametrize("field", ["config", "result"])
def test_absent_containers_remain_absent(native, field):
    value = record()
    del value[field]
    store(native, value)
    assert native._replay_origin("native_origin") == value


def test_missing_run_and_malformed_json_retain_errors(native):
    with pytest.raises(ValueError, match="RUN_NOT_FOUND"):
        native._replay_origin("missing")
    native.db.execute("INSERT INTO runs VALUES (?,?)", ("native_origin", '{"result":'))
    with pytest.raises(json.JSONDecodeError):
        native._replay_origin("native_origin")


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "FAILED", "CANCELLED", "INTERRUPTED"])
def test_replay_creation_rejects_unready_runs_with_the_existing_error(native, state):
    value = record()
    value.update(state=state, result=None)
    store(native, value)
    replay = NativeReplay(native)
    try:
        with pytest.raises(ValueError, match="NATIVE_REPLAY_NOT_READY"):
            replay.create("native_origin")
    finally:
        replay.shutdown()


def test_replay_creation_uses_the_frozen_input_and_keeps_public_full_result(native):
    value = record()
    store(native, value)
    native.db.execute("INSERT INTO native_inputs VALUES (?,?)", ("native_origin", encoded({"bars": [{"time": 0}], "identity": {"version": "frozen"}})))
    replay = NativeReplay(native)
    try:
        created = replay.create("native_origin")
        assert created["input_hash"] == "frozen"
        assert created["runtime_identity"] == {"version": "frozen"}
        assert created["total"] == 1 and created["result"] is None
        assert native.get("native_origin") == value
    finally:
        replay.shutdown()
