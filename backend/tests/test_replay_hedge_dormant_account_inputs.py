"""Account inputs remain ordered independently of market subscription tiers."""

import json
import sqlite3
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.replay.training.hedge_timeline import IndexedHedgeSnapshot
from app.replay.training.models import ReplayV2CommandType
from tests.fixtures.replay import hedge_input_fakes
from tests.test_replay_hedge_track_readmission import _dormant_run
from tests.test_replay_v2_training_phase6 import _risk_service, _send

pytestmark = pytest.mark.anyio


def _changing_inputs(monkeypatch, *, legacy_primary=False):
    build = hedge_input_fakes.build_hedge_public_history_archive

    def changing(path, **kwargs):
        events = list(kwargs["events"])
        rule = next(e["payload"] for e in events if e["event_kind"] == "RULE")
        fee = next(e["payload"] for e in events if e["event_kind"] == "FEE_POLICY")
        start = kwargs["range_start_ms"]
        events.append({"event_time_ms": start + 120_000, "event_kind": "RULE",
                       "payload": {**rule, "rule_version": "QA_NEXT_RULE", "max_leverage": "10"}})
        for minute, bps in ((2, "3"), (4, "4"), (5, "1")):
            if legacy_primary and kwargs["symbol"] == "ETHUSDT" and minute == 2:
                continue
            events.append({"event_time_ms": start + minute * 60_000, "event_kind": "FEE_POLICY",
                           "payload": {**fee, "policy_version": f"QA_FEE_{minute}", "taker_fee_bps": bps}})
        events.sort(key=lambda e: (e["event_time_ms"],
                                  {"RULE": 10, "FEE_POLICY": 10, "MARK_INDEX": 30, "FUNDING": 40}[e["event_kind"]],
                                  e["event_kind"]))
        return build(path, **{**kwargs, "events": events})

    monkeypatch.setattr(hedge_input_fakes, "build_hedge_public_history_archive", changing)


async def _rows(service, run_id, table):
    return await service.training.hedge_inputs.store.run_extension_read(lambda c: [dict(r) for r in c.execute(
        f"SELECT * FROM {table} WHERE run_id=?", (run_id,),
    )])


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("time_policy", ["NONE", "HIDE_ALL"])
async def test_dormant_primary_funding_rules_fees_restart_and_future_order(tmp_path, monkeypatch, legacy, time_policy):
    _changing_inputs(monkeypatch, legacy_primary=legacy)
    database = tmp_path / "account-inputs.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, initial_count=0,
                                                   legacy=legacy, time_disclosure_policy=time_policy)
        global_before = await _rows(service, run_id, "replay_training_global_event")
        await _send(service, run_id=run_id, session_id=other, command_id="readmit-primary",
                              command_type=ReplayV2CommandType.SELECT_TRACK,
                              payload={"track_id": "track-1", "expected_viewer_revision": 1})
        global_after = await _rows(service, run_id, "replay_training_global_event")
        assert global_after[:len(global_before)] == global_before
        projections = await _rows(service, run_id, "replay_hedge_track_public_projection")
        for row in projections:
            state = json.loads(row["state_json"])
            assert state["rule"]["max_leverage"] == "10"
            if not legacy or row["track_id"] == "track-1":
                assert state["fee_policy"]["taker_fee_bps"] == "3"
        funding = await _rows(service, run_id, "replay_training_hedge_funding_settlement")
        assert len(funding) == 4
        assert all(Decimal(row["cash_delta"]) == 0 for row in funding)
        assert len(await _rows(service, run_id, "replay_hedge_track_input_admission")) == int(legacy)
        await _send(service, run_id=run_id, session_id=primary, command_id="order-after-readmit",
                    command_type=ReplayV2CommandType.PLACE_ORDER, payload={
                        "client_order_id": "after-readmit", "side": "BUY", "position_side": "LONG",
                        "order_type": "MARKET", "quantity": "1", "reduce_only": False,
                        "limit_price": None, "stop_price": None})
        fills = await _rows(service, run_id, "replay_training_contract_fill")
        assert len(fills) == 1
        policies = await _rows(service, run_id, "replay_training_fee_policy")
        assert next(p for p in policies if p["revision"] == fills[0]["fee_policy_revision"])["taker_fee_bps"] == "3"
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        before = (await service.training.get_market_tracks(run_id))["portfolio"]
    finally:
        await service.shutdown(step_timeout=1.0)

    restored = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        assert (await restored.training.get_market_tracks(run_id))["portfolio"] == before
        assert (await restored.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1.0)


async def test_none_tier_advances_account_inputs_without_advancing_market_cursor(tmp_path, monkeypatch):
    _changing_inputs(monkeypatch)
    service = await _risk_service(tmp_path / "none-tier.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, initial_count=0)
        await _send(service, run_id=run_id, session_id=other, command_id="primary-none",
                    command_type=ReplayV2CommandType.SET_SUBSCRIPTION_TIER,
                    payload={"track_id": "track-1", "subscription_tier": "NONE"})
        before = await service.training.get_market_tracks(run_id)
        await _send(service, run_id=run_id, session_id=other, command_id="forward-with-none",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 3})
        after = await service.training.get_market_tracks(run_id)
        assert after["tracks"][0]["subscription_tier"] == "NONE"
        assert after["tracks"][0]["cursor"] == before["tracks"][0]["cursor"]
        policies = await _rows(service, run_id, "replay_training_fee_policy")
        assert max(policies, key=lambda p: p["effective_virtual_time_ms"])["taker_fee_bps"] == "1"
        projections = await _rows(service, run_id, "replay_hedge_track_public_projection")
        assert len({p["as_of_actual_time_ms"] for p in projections}) == 1
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_legacy_secondary_replays_historical_fee_versions_atomically(tmp_path, monkeypatch):
    _changing_inputs(monkeypatch)
    service = await _risk_service(tmp_path / "secondary.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, initial_count=0)
        await _send(service, run_id=run_id, session_id=other, command_id="select-primary",
                    command_type=ReplayV2CommandType.SELECT_TRACK,
                    payload={"track_id": "track-1", "expected_viewer_revision": 1})
        runtime = service.training.hedge_inputs._runtime_events

        async def old_runtime(run):
            snapshot = await runtime(run)
            return IndexedHedgeSnapshot(tuple(e for e in snapshot[0] if e.track_id == "track-1"), snapshot[1])

        with patch.object(service.training.hedge_inputs, "_runtime_events", old_runtime):
            await _send(service, run_id=run_id, session_id=primary, command_id="old-forward",
                        command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 3})
        tables = ("replay_hedge_track_public_projection", "replay_hedge_track_public_applied_event",
                  "replay_hedge_track_input_admission", "replay_training_instrument_rule",
                  "replay_training_fee_policy", "replay_training_global_event")
        before = {t: await _rows(service, run_id, t) for t in tables}
        base = service.training.hedge_inputs.store
        await base.run_extension_write(lambda c: c.execute(
            "CREATE TEMP TRIGGER fail_admission BEFORE INSERT ON replay_hedge_track_public_applied_event "
            "WHEN NEW.track_id='track-2' BEGIN SELECT RAISE(ABORT,'admission interrupted'); END"))
        with pytest.raises(sqlite3.IntegrityError, match="admission interrupted"):
            await _send(service, run_id=run_id, session_id=primary, command_id="interrupted-secondary",
                        command_type=ReplayV2CommandType.SELECT_TRACK,
                        payload={"track_id": "track-2", "expected_viewer_revision": 2})
        assert {t: await _rows(service, run_id, t) for t in tables} == before
        await base.run_extension_write(lambda c: c.execute("DROP TRIGGER fail_admission"))
        await _send(service, run_id=run_id, session_id=primary, command_id="secondary-retry",
                    command_type=ReplayV2CommandType.SELECT_TRACK,
                    payload={"track_id": "track-2", "expected_viewer_revision": 2})
        await _send(service, run_id=run_id, session_id=other, command_id="next-after-secondary",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        assert len(await _rows(service, run_id, "replay_hedge_track_input_admission")) == 1
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_multitrack_funding_review_fork_preserves_tracks(tmp_path, monkeypatch):
    _changing_inputs(monkeypatch)
    service = await _risk_service(tmp_path / "funding-fork.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, initial_count=0)
        await _send(service, run_id=run_id, session_id=other, command_id="fork-select-primary",
                    command_type=ReplayV2CommandType.SELECT_TRACK,
                    payload={"track_id": "track-1", "expected_viewer_revision": 1})
        review = await service.training.start_review(run_id, event_id=None)
        forked = await service.training.fork_run(run_id, event_id=str(review["selected_event_id"]))
        child_id = forked["run"]["run_id"]
        assert (await service.training.audit_account(child_id))["status"] == "PASS"
        assert len(await _rows(service, child_id, "replay_training_hedge_funding_settlement")) == 4
    finally:
        await service.shutdown(step_timeout=1.0)
