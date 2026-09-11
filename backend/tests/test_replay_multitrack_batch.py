from dataclasses import replace
from time import perf_counter

import pytest

from app.replay.training.models import ReplayV2CommandType
from tests.fixtures.replay.service_fakes import INTERVAL_MS
from tests.test_replay_v2_training_phase5 import _trade_service, _trade_request, _command, _acquire, _place_limit
from tests.test_replay_v2_training_phase8 import _advance_to


@pytest.mark.anyio
@pytest.mark.parametrize("offset,terminal,waiting_order", [(0, False, False), (200, False, False), (0, True, False), (200, True, False), (200, False, True), (200, False, "marketable"), (200, False, "held-constant"), (200, False, "trigger-stop")])
async def test_real_multitrack_tape_batch_preserves_global_order_and_reduces_commands(tmp_path, monkeypatch, offset, terminal, waiting_order, record_property):
    services = []
    results = []
    try:
        for name, enabled in (("fast", True), ("reference", False)):
            owner = await _trade_service(tmp_path / f"{name}.db", archive_root=tmp_path / name,
                                         symbols=("BTCUSDT", "ETHUSDT"), symbol_time_offset_ms=offset, constant_prices=waiting_order == "held-constant")
            services.append(owner)
            owner.settings = replace(owner.settings, replay_fast_forward_optimization_enabled=enabled)
            created = await owner.training.create_run(await _trade_request(owner))
            run = str(created["run"]["run_id"])
            session = str(created["run"]["adapter_session_id"])
            await owner.training.command(run, _command(run, "add", ReplayV2CommandType.ADD_TRACK,
                await owner.get_session(session), {"exchange": "binance", "market_type": "futures",
                    "symbol": "ETHUSDT", "settlement_asset": "USDT", "subscription_tier": "FULL"}))
            await _acquire(owner, run_id=run, selected_session_id=session, command_id="acquire")
            if waiting_order == "trigger-stop":
                await owner.training.command(run, _command(run, "wait", ReplayV2CommandType.PLACE_ORDER,
                    await owner.get_session(session), {"client_order_id": "wait", "side": "SELL", "order_type": "LIMIT",
                        "quantity": "1", "reduce_only": False, "limit_price": "101", "stop_price": None}))
            elif waiting_order:
                await _place_limit(owner, run_id=run, selected_session_id=session, command_id="wait",
                                   client_order_id="wait", quantity="1", limit_price="500" if waiting_order in ("marketable", "held-constant") else "90")
            before = await owner.get_session_state(session)
            calls = []
            original = owner.training._advance_adapter_to
            async def observe(*args, _original=original, _calls=calls, _owner=owner, **kwargs):
                _calls.append(kwargs.get("final_state_max_events"))
                return await _original(*args, **kwargs)
            monkeypatch.setattr(owner.training, "_advance_adapter_to", observe)
            started = perf_counter()
            target = (owner.training._training_terminal_time_ms(await owner.training.store.run_binding(run))
                      if terminal else int(before["cursor"]["virtual_time_ms"]) + 3 * INTERVAL_MS)
            if waiting_order == "trigger-stop":
                result = await owner.training.command(run, _command(run, "advance", ReplayV2CommandType.ADVANCE_TO,
                    await owner.get_session(session), {"virtual_time_ms": target, "stop_on_event": True}))
                assert result["data"]["event_stop"]["reason"] == "ORDER_FILLED"
                assert result["cursor"]["virtual_time_ms"] < target
            else:
                await _advance_to(owner, run_id=run, session_id=session, command_id="advance", target=target)
            elapsed_ms = (perf_counter() - started) * 1000
            states = []
            for track in await owner.training.store.get_market_track_heads(run):
                snapshot = (await owner.get_session(track["adapter_session_id"]))["snapshot"]
                states.append((snapshot["cursor"], snapshot["components"]))
            events = await owner.training.store.global_events(run)
            ordered = [(e["actual_event_time_ms"], e["event_phase"], e["track_id"], e["source_sequence"]) for e in events]
            results.append((states, ordered, calls, elapsed_ms))
        assert results[0][:2] == results[1][:2]
        if waiting_order == "marketable":
            assert len(results[0][2]) <= len(results[1][2])
        else:
            assert any(limit is not None and limit > 1 for limit in results[0][2])
            assert len(results[0][2]) < len(results[1][2])
        record_property("fast_adapter_calls", len(results[0][2]))
        record_property("reference_adapter_calls", len(results[1][2]))
        record_property("fast_ms", round(results[0][3], 3))
        record_property("reference_ms", round(results[1][3], 3))
    finally:
        for owner in services:
            await owner.shutdown(step_timeout=1)
