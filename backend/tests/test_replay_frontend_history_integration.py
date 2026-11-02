from __future__ import annotations

from copy import deepcopy

import pytest
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.training.models import ReplayV2CommandType
from app.replay.training.errors import TrainingRunError

from tests.replay_frontend_probe import frontend_probe
from tests.test_replay_indicator_prefix import lines, reference
from tests.test_replay_indicator_prepared_context import START, prepared_run
from tests.test_replay_tape_phases import setup_tape
from tests.test_replay_v2_training_phase6 import _send

pytestmark = pytest.mark.anyio



def binding(snapshot, session, track, interval):
    config = snapshot["config"]
    return {
        "sessionId": session,
        "trackId": track,
        "dataEpoch": snapshot["data_epoch"],
        "revealedBoundaryMs": snapshot["cursor"]["virtual_time_ms"],
        "sourceSequence": snapshot["cursor"]["source_sequence"],
        "identity": {
            "exchange": config["exchange"],
            "market_type": config["market_type"],
            "symbol": config["symbol"],
            "source_kind": config["source_kind"].upper(),
            "base_interval": config["base_interval"],
            "display_interval": interval,
        },
    }


@pytest.mark.parametrize("disclosure", ["NONE", "HIDE_ALL"])
async def test_real_preparation_review_and_canonical_reload(tmp_path, disclosure):
    async with prepared_run(tmp_path, False, disclosure) as fixture:
        service, _, session, *_ = fixture
        before = deepcopy((await service.get_session(session))["snapshot"])
        # This provider fixture starts at START. Previously the first RSI
        # request happened to discover/pin that boundary before the coarse
        # chart loaded. Viewport math deliberately no longer makes that global
        # probe. Declare the known source boundary explicitly for this test of
        # canonical review/reload, rather than manufacturing prelisting rows.
        bound = await service.training.store.history_binding(session_id=session, track_id="track-1")
        origin = await service.history_context.origin(
            binding=bound,
            persisted=await service.store.load_dataset(session),
            repository=service.prepared_history_repository(session, before["data_epoch"]),
            discover=True,
        )
        assert origin.start_ms == START
        cases = [
            {"binding": binding(before, session, "track-1", interval)}
            for interval in ["1m", "5m", "90m"]
        ]
        result = await frontend_probe(service, tmp_path, cases)
        assert len(result["output"]) == 3
        assert all(item["status"] in (200, 409) for item in result["requests"])
        assert (await service.get_session(session))["snapshot"] == before
        assert all(start >= START for start, _ in fixture[-2])
        for case, output in zip(cases, result["output"], strict=True):
            bound = case["binding"]
            page = await service.training.history_page(
                session,
                track_id="track-1",
                before_ms=bound["revealedBoundaryMs"] + 1,
                revealed_boundary_ms=bound["revealedBoundaryMs"],
                limit=500,
                data_epoch=bound["dataEpoch"],
                history_epoch=None,
                display_interval=bound["identity"]["display_interval"],
            )
            # The initial view already has the server's source phase, without
            # relying on any builtin indicator to correct local aggregation.
            rows = {row["open_time_ms"]: row for row in page["bars"]}
            if bound["identity"]["display_interval"] != "1m":
                tail = await service.training.display_projection(
                    session,
                    track_id="track-1",
                    revealed_boundary_ms=bound["revealedBoundaryMs"],
                    limit=1,
                    data_epoch=bound["dataEpoch"],
                    display_interval=bound["identity"]["display_interval"],
                )
                rows.update({row["open_time_ms"]: row for row in tail["bars"]})
            for actual in output["initial"]:
                expected = rows[actual["time"] * 1000]
                assert actual["close"] == float(expected["close"])
                assert actual["replayCloseTimeMs"] == expected["close_time_ms"]
            assert len(output["initial"]) == len(rows)


async def test_unknown_context_rejects_invalid_provider_history_without_mutating_run(tmp_path):
    async with prepared_run(tmp_path, False, "NONE") as fixture:
        service, _, session, *_ = fixture
        before = deepcopy((await service.get_session(session))["snapshot"])
        # An unknown origin is not proof of a listing date. This intentionally
        # invalid provider fixture generates negative volume before START;
        # keep the real validation and explicit failure instead of filling or
        # relabeling those rows to make a chart look complete.
        with pytest.raises(TrainingRunError, match="volume cannot be negative") as failure:
            await service.training.history_page(
                session, track_id="track-1", display_interval="5m",
                revealed_boundary_ms=before["cursor"]["virtual_time_ms"],
                before_ms=before["cursor"]["virtual_time_ms"] + 1,
                limit=500, data_epoch=before["data_epoch"], history_epoch=None,
            )
        assert failure.value.code == "DATASET_INCOMPLETE"
        assert fixture[5] == [], "bounded display must not silently probe the global origin"
        assert (await service.get_session(session))["snapshot"] == before


async def test_real_tape_forming_tail_survives_canonical_reload(tmp_path):
    service, run_id, session = await setup_tape(tmp_path, held=True)
    try:
        state = await service.get_session_state(session)
        target = (state["cursor"]["virtual_time_ms"] // 60_000 + 2) * 60_000 + 1200
        await _send(
            service,
            run_id=run_id,
            session_id=session,
            command_id="frontend-prefix",
            command_type=ReplayV2CommandType.ADVANCE_TO,
            payload={"virtual_time_ms": target},
        )
        cases, snapshots = [], []
        for number in (1, 2):
            sid = f"trade-adapter-{number}"
            snapshot = deepcopy((await service.get_session(sid))["snapshot"])
            snapshots.append(snapshot)
            rows = snapshot["components"]["bar_builder"]["public_projection"]["bars"]
            assert not rows[-1]["is_closed"]
            cases.append(
                {
                    "binding": {
                        **binding(snapshot, sid, f"track-{number}", "1m"),
                        "forceInitialRefresh": True,
                    },
                    "rows": rows,
                }
            )
        result = await frontend_probe(service, tmp_path, cases)
        assert all(
            "display-projection" not in item["path"] for item in result["requests"]
        )
        for case, output, snapshot in zip(
            cases, result["output"], snapshots, strict=True
        ):
            expected = reference(
                "RSI",
                {"period": 2},
                [ReplayDisplayBar.from_dict(row) for row in case["rows"]],
            )
            assert lines(output["payload"]) == lines(expected)
            assert (await service.get_session(case["binding"]["sessionId"]))[
                "snapshot"
            ] == snapshot
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=3)
