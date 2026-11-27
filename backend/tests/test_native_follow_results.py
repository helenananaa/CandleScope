"""FOLLOW rebuilds keep only the results a chart can show (ADR-BACKTEST-015 O2, confirmed 2026-11-27).

The engine is a stand-in: these tests cover which runs the native store keeps, not Pine.
"""
from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backtest.errors import BacktestError
from app.backtest.native import NativeBacktests, PROTOCOL
from app.backtest.native_follow_results import KEPT_FOLLOWS

IDENTITY = {"protocol": PROTOCOL, "historical_session": "fixed-history/1"}
BARS = [{"time": index * 60, "open": 1., "high": 2., "low": 1., "close": 1. + index, "volume": 1.} for index in range(20)]


def output(bars):
    rows = [{"time": item["time"], "value": item["close"]} for item in bars]
    return {"identity": IDENTITY, "execution_mode": "NATIVE", "account_authority": "pine-compat-runtime",
            "equity": rows, "raw_output": {"plots": [{"data": copy.deepcopy(rows)}]}}


@pytest.fixture
def native(tmp_path):
    host = SimpleNamespace(settings=SimpleNamespace(db_path=tmp_path / "backtest.db", bar_effective=True),
                           local_data=SimpleNamespace(get_manifest=lambda _: {"symbol": "BTCUSDT"}))

    def runner(plugin, wire, **kwargs):
        if wire.get("operation") == "describe":
            return {"identity": IDENTITY}
        if wire["source"].startswith("fail"):
            raise BacktestError("NATIVE_EXECUTION_FAILED", "fixture failure")
        if wire["source"].startswith("slow"):
            kwargs["cancelled"].wait(5)  # runs until the app stops
            raise BacktestError("NATIVE_EXECUTION_FAILED", "stopped")
        return output(wire["bars"])

    def start():
        service = NativeBacktests(host, resolver=lambda _: {"plugin_id": "candlescope.pine-compat", "command": ["unused"]},
                                  runner=runner)
        service._freeze = lambda _: copy.deepcopy(BARS)
        service.versions = []
        service._record_version = lambda record: service.versions.append(record["run_id"])
        return service

    services = [start()]
    yield SimpleNamespace(service=services[0], restart=lambda: services.append(start()) or services[-1], services=services)
    for service in services:
        if not service.closed:
            service.shutdown()


def payload(source="strategy"):
    return {"language": "pine", "source": source, "dataset_id": "fixture", "data_epoch": "epoch-fixture",
            "snapshot_hash": "snapshot-fixture", "start_time_ms": 0, "end_time_ms": 1_199_999, "interval": "1m",
            "context": {"symbol": "BTCUSDT", "timeframe": "1"}}


def run(service, key, *, source="strategy", follow_of=None):
    record = service.create(payload(source), key, follow_of=follow_of)
    deadline = time.monotonic() + 5
    while True:
        with service.lock:
            if record["run_id"] not in service.cancel_events:
                break
        assert time.monotonic() < deadline
        time.sleep(.005)
    return record["run_id"]


def stored(service):
    with service.lock:
        return {table: {row[0] for row in service.db.execute(f"SELECT id FROM {table}")}
                for table in ("runs", "native_inputs", "native_run_summaries")}


def kept(service, run_id):
    rows = stored(service)
    present = {run_id in ids for ids in rows.values()}
    assert len(present) == 1, rows  # a run is kept or removed whole
    return present.pop()


def test_a_follow_keeps_only_its_newest_completed_rebuild(native):
    service = native.service
    base = run(service, "user")
    first = run(service, "follow-1", source="strategy-1", follow_of=base)
    assert kept(service, first)
    second = run(service, "follow-2", source="strategy-2", follow_of=base)
    assert kept(service, base) and kept(service, second)
    assert not kept(service, first)
    assert service.get(second)["state"] == "COMPLETED"
    with pytest.raises(BacktestError) as missing:
        service.get(first)
    assert missing.value.code == "RUN_NOT_FOUND"


def test_rebuilds_are_not_the_users_runs(native):
    service = native.service
    base = run(service, "user")
    rebuild = run(service, "follow-1", source="strategy-1", follow_of=base)
    assert [item["run_id"] for item in service.list()] == [base]
    assert service.versions == [base]
    assert service.get(rebuild)["state"] == "COMPLETED"


def test_results_are_kept_for_the_most_recently_active_follows(native):
    service = native.service
    bases = [run(service, f"user-{index}", source=f"user-{index}") for index in range(KEPT_FOLLOWS + 1)]
    rebuilds = [run(service, f"follow-{index}", source=f"rebuild-{index}", follow_of=base)
                for index, base in enumerate(bases)]
    # The least recently active follow lost its result; every user run stays.
    assert not kept(service, rebuilds[0])
    assert all(kept(service, rebuild) for rebuild in rebuilds[1:])
    assert all(kept(service, base) for base in bases)
    # Following again makes it the most recent: the next oldest gives way.
    again = run(service, "follow-again", source="rebuild-again", follow_of=bases[0])
    assert kept(service, again) and not kept(service, rebuilds[1])


def test_a_shared_rebuild_stays_while_any_follow_shows_it(native):
    service = native.service
    one, two = run(service, "user-1", source="one"), run(service, "user-2", source="two")
    shared = run(service, "follow-shared", source="same", follow_of=one)
    assert service.create(payload("same"), "follow-shared", follow_of=two)["run_id"] == shared
    run(service, "follow-next", source="next", follow_of=one)
    assert kept(service, shared)  # the second follow still shows it
    run(service, "follow-next-2", source="next-2", follow_of=two)
    assert not kept(service, shared)


def test_a_newer_failure_is_kept_next_to_the_shown_result(native):
    service = native.service
    base = run(service, "user")
    shown = run(service, "follow-1", source="strategy-1", follow_of=base)
    failed = run(service, "follow-2", source="fail-2", follow_of=base)
    assert service.get(failed)["state"] == "FAILED"
    assert kept(service, shown) and kept(service, failed)
    failed_again = run(service, "follow-3", source="fail-3", follow_of=base)
    assert kept(service, shown) and kept(service, failed_again) and not kept(service, failed)
    recovered = run(service, "follow-4", source="strategy-4", follow_of=base)
    assert kept(service, recovered)
    assert not any(kept(service, run_id) for run_id in (shown, failed_again))


def test_a_rebuild_with_a_replay_becomes_the_users(native):
    service = native.service
    base = run(service, "user")
    rebuild = run(service, "follow-1", source="strategy-1", follow_of=base)
    with service.lock:
        service.db.execute("INSERT INTO native_replays VALUES (?,?)", ("replay-1", json.dumps({"run_id": rebuild})))
        service.db.commit()
    run(service, "follow-2", source="strategy-2", follow_of=base)
    assert kept(service, rebuild)
    assert rebuild in {item["run_id"] for item in service.list()}


def test_only_the_users_own_runs_can_be_followed(native):
    service = native.service
    base = run(service, "user")
    rebuild = run(service, "follow-1", source="strategy-1", follow_of=base)
    for invalid in ("native_" + "0" * 32, rebuild):
        with pytest.raises(BacktestError) as refused:
            service.create(payload("strategy-x"), f"follow-x-{invalid}", follow_of=invalid)
        assert refused.value.code == "FOLLOW_BASE_INVALID"
    with pytest.raises(BacktestError):
        service.link_follow(base, base)


def test_restart_drops_rebuilds_a_chart_can_no_longer_show(native):
    service = native.service
    base = run(service, "user")
    shown = run(service, "follow-1", source="strategy-1", follow_of=base)
    # A rebuild that was still running when the app stopped is interrupted.
    stale = service.create(payload("slow-2"), "follow-2", follow_of=base)["run_id"]
    service.shutdown()
    restarted = native.restart()
    assert restarted.get(stale)["state"] == "INTERRUPTED"
    assert kept(restarted, shown) and kept(restarted, stale) and kept(restarted, base)
    newest = run(restarted, "follow-3", source="strategy-3", follow_of=base)
    assert kept(restarted, newest) and not kept(restarted, shown) and not kept(restarted, stale)


def test_http_routes_carry_the_followed_run_outside_the_input(native):
    from app.api.v1.backtests import router
    service = native.service
    base = run(service, "user")
    app = FastAPI()
    app.state.backtest_runtime = SimpleNamespace(native=service)
    app.include_router(router)
    with TestClient(app) as client:
        created = client.post("/backtests/native/runs", json=payload("strategy-1"),
                              headers={"Idempotency-Key": "follow-1", "Strategy-Follow-Of": base})
        assert created.status_code == 200, created.text
        rebuild = created.json()["run_id"]
        assert "follow_of" not in created.json()["config"]
        invalid = client.post("/backtests/native/runs", json=payload("strategy-2"),
                              headers={"Idempotency-Key": "follow-2", "Strategy-Follow-Of": "user"})
        assert invalid.status_code == 422
    deadline = time.monotonic() + 5
    while service.get(rebuild)["state"] != "COMPLETED":
        assert time.monotonic() < deadline
        time.sleep(.005)
    assert [item["run_id"] for item in service.list()] == [base]
