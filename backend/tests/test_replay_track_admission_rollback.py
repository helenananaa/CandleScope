from dataclasses import replace

import pytest

from app.replay.training.errors import TrainingRunError
from app.replay.training.models import ReplayV2CommandType
from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
from tests.test_replay_v2_training_phase5 import _acquire, _request
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


async def test_missing_hedge_manifest_symbol_rolls_back_track_and_keeps_run_playable(tmp_path):
    service = await _risk_service(tmp_path / "track-rollback.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        base = replace(_sandbox_request(await _request(service)), market_type="futures")
        request = await prepare_hedge_request(service, base, root=tmp_path,
            prefix="rollback-missing-symbol", mark_prices=["100"] * 13,
            required_symbols=["BTCUSDT"], book_mode="OFF")
        training = service.training
        assert training is not None
        created = await training.create_run(request)
        run_id = str(created["run"]["run_id"])
        session = str(created["run"]["adapter_session_id"])
        await _acquire(service, run_id=run_id, selected_session_id=session, command_id="rollback-acquire")
        baseline = await service.get_session_state(session)
        before = await training.get_market_tracks(run_id)
        with pytest.raises(TrainingRunError) as rejected:
            await _send(service, run_id=run_id, session_id=session, command_id="rollback-add-eth",
                command_type=ReplayV2CommandType.ADD_TRACK, payload={"exchange": "binance",
                    "market_type": "futures", "symbol": "ETHUSDT", "settlement_asset": "USDT",
                    "subscription_tier": "FULL"})
        assert rejected.value.code == "HEDGE_TRACK_SIMULATION_COVERAGE_MISMATCH"
        after = await training.get_market_tracks(run_id)
        assert [track["track_id"] for track in after["tracks"]] == ["track-1"]
        assert after["viewer_state"] == before["viewer_state"]
        assert (await service.get_session_state(session))["cursor"] == baseline["cursor"]
        advanced = await _send(service, run_id=run_id, session_id=session, command_id="rollback-continue",
            command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert advanced["cursor"]["source_sequence"] > baseline["cursor"]["source_sequence"]
    finally:
        await service.shutdown()
