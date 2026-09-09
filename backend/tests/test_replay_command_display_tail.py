from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.replay.training.errors import TrainingRunError
from app.replay.training.models import ReplayV2CommandType
from app.replay.training.service import TrainingRunService

pytestmark = pytest.mark.anyio


async def test_command_tail_is_bounded_and_does_not_mutate_durable_result():
    service = object.__new__(TrainingRunService)
    service.replay_service = SimpleNamespace(get_session_state=AsyncMock(
        return_value={"revision": 2, "data_epoch": "sha256:" + "a" * 64}
    ))
    projection = {"bars": [{"open_time_ms": 1000}], "revealed_boundary_ms": 2000}
    service.display_projection = AsyncMock(return_value=projection)
    command = SimpleNamespace(type=ReplayV2CommandType.ADVANCE,
                              payload={"basis": "DISPLAY_BAR", "count": 1})
    result = {"session_id": "session-1", "revision": 2,
              "cursor": {"virtual_time_ms": 2000},
              "viewer_state": {"selected_track_id": "track-1", "display_interval": "15m"},
              "data": {"consumed": 15}}
    attached = await service._with_command_display_tail(command, result)
    assert attached["data"]["display_tail"] == projection
    assert result["data"] == {"consumed": 15}
    assert service.display_projection.call_args.kwargs["limit"] == 2
    assert service.display_projection.call_args.kwargs["revealed_boundary_ms"] == 2000

    service.replay_service.get_session_state.return_value["revision"] = 3
    service.display_projection.reset_mock()
    assert await service._with_command_display_tail(command, result) is result
    service.display_projection.assert_not_called()

    service.replay_service.get_session_state.return_value["revision"] = 2
    service.display_projection.side_effect = TrainingRunError(
        "HISTORY_SNAPSHOT_UNAVAILABLE", "test archive unavailable", status_code=503
    )
    assert await service._with_command_display_tail(command, result) is result


async def test_multi_step_and_non_display_commands_do_not_build_a_tail():
    service = object.__new__(TrainingRunService)
    for payload in ({"basis": "DISPLAY_BAR", "count": 10},
                    {"basis": "BASE_BAR", "count": 1}):
        command = SimpleNamespace(type=ReplayV2CommandType.ADVANCE, payload=payload)
        result = {"data": {}}
        assert await service._with_command_display_tail(command, result) is result
