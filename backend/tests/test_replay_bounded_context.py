"""Local display inputs do not depend on discovering the provider's first bar."""

from __future__ import annotations

import pytest

from app.data_preparation.models import PreparationError
from app.data_preparation.replay_context import ReplayHistoryContext, project_context
from app.data_preparation.replay_origin import ReplayContextScope
from app.indicator.warmup import replay_display_warmup_bars
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.display_time import SourceBucketTimeMapper
from app.replay.models import ReplaySessionConfig
from app.replay.training.errors import TrainingRunError
from app.replay.training.history import _decode_bar_snapshot
from tests import test_replay_indicator_prepared_context as fixture
from tests.test_replay_indicator_prefix import lines, reference

pytestmark = pytest.mark.anyio


async def local_window(replay, preparation, session, values, downloads, interval):
    # These rows are already available to the acquisition owner's local read.
    # There is no network response substitution in the replay service itself.
    values.update({at: fixture.market_row(at) for at in range(
        fixture.START, fixture.REPLAY_START + 120 * fixture.MINUTE, fixture.MINUTE
    )})
    downloads.clear()
    attempts = []

    async def unavailable(identity, frozen_start):
        attempts.append((identity, frozen_start))
        raise PreparationError("HISTORY_ORIGIN_UNAVAILABLE", "provider is in backoff", retryable=True)

    replay.history_context.origin_resolver = unavailable
    state = await replay.get_session_state(session)
    common = dict(track_id="track-1", display_interval=interval,
                  revealed_boundary_ms=state["cursor"]["virtual_time_ms"],
                  data_epoch=state["data_epoch"])
    page = await replay.training.history_page(session, **common,
        before_ms=common["revealed_boundary_ms"], limit=12, history_epoch=None)
    rows = [row for row in page["bars"] if row["is_closed"]][-4:]
    assert rows
    return common, page, rows, attempts


@pytest.mark.parametrize("progressive,disclosure", [(False, "NONE"), (True, "HIDE_ALL")])
@pytest.mark.parametrize("interval", ["1m", "5m"])
@pytest.mark.parametrize("name,display_math", [
    ("MA", "viewport-v1"), ("EMA", "viewport-v1"), ("MA", "canonical"),
])
async def test_bounded_math_uses_local_context_while_origin_is_unavailable(
    tmp_path, progressive, disclosure, interval, name, display_math
):
    async with fixture.prepared_run(tmp_path, progressive, disclosure, prepare_timeout=30) as data:
        replay, preparation, session, _, _, _, downloads, values = data
        common, page, rows, attempts = await local_window(
            replay, preparation, session, values, downloads, interval)
        params = {"period": 20}
        for _ in range(16):
            answer = await replay.training.canonical_indicator_compute(session, **common,
                name=name, params=params, bars=rows, display_math=display_math,
                history_epoch=page["history_epoch"])
            if answer["status"] == "ready":
                break
        assert answer["status"] == "ready"
        assert attempts == [], "bounded display math must not probe the provider listing origin"
        assert downloads == [], "all required context was already local"

        binding = await replay.training.store.history_binding(session_id=session, track_id="track-1")
        persisted = await replay.store.load_dataset(session)
        snapshot = _decode_bar_snapshot(persisted, config=ReplaySessionConfig.from_dict(binding["config"]))
        mapper = SourceBucketTimeMapper.create(interval=interval,
            actual_replay_start_ms=fixture.REPLAY_START, public_replay_start_ms=snapshot.replay_start_ms)
        width = int(interval[:-1]) * fixture.MINUTE
        start = max(0, rows[0]["open_time_ms"] - replay_display_warmup_bars(name, params) * width)
        end = rows[-1]["close_time_ms"] + 1
        actual_start, actual_end = mapper.actual_from_public(start), mapper.actual_from_public(end)
        source = [fixture.market_row(at) for at in range(actual_start, actual_end, fixture.MINUTE)]
        projected = project_context(source, actual_start, actual_end, mapper,
                                    ReplaySeriesIdentity("binance", "spot", "BTCUSDT"))
        expected = reference(name, params, [ReplayDisplayBar.from_dict(row) for row in projected])
        first = rows[0]["open_time_ms"] // 1000
        assert lines(answer["payload"]) == [
            (title, [point for point in points if point["time"] >= first])
            for title, points in lines(expected)
        ]


async def test_canonical_recursive_math_still_requires_its_verified_origin(tmp_path):
    async with fixture.prepared_run(tmp_path, False, "NONE", prepare_timeout=30) as data:
        replay, preparation, session, _, _, _, downloads, values = data
        common, page, rows, attempts = await local_window(
            replay, preparation, session, values, downloads, "1m")
        with pytest.raises(TrainingRunError) as failure:
            await replay.training.canonical_indicator_compute(session, **common,
                name="EMA", params={"period": 20}, bars=rows,
                history_epoch=page["history_epoch"])
        assert failure.value.code == "HISTORY_ORIGIN_UNAVAILABLE"
        assert len(attempts) == 1


async def test_unknown_origin_scope_survives_restore_and_fences_cache_release(tmp_path):
    async with fixture.prepared_run(tmp_path, False, "NONE", prepare_timeout=30) as data:
        replay, preparation, session, _, _, _, downloads, values = data
        common, page, rows, attempts = await local_window(
            replay, preparation, session, values, downloads, "1m")
        before = (await replay.get_session(session))["snapshot"]
        context = replay.history_context
        binding = await replay.training.store.history_binding(session_id=session, track_id="track-1")
        persisted = await replay.store.load_dataset(session)
        repository = replay.prepared_history_repository(session, common["data_epoch"])
        args = dict(binding=binding, persisted=persisted, repository=repository)
        scope = await context.origin(**args)
        assert isinstance(scope, ReplayContextScope)
        assert context.origins.get(scope.key) is None, "an unknown listing must never be pinned as verified"
        restored = ReplayHistoryContext(preparation)
        assert await restored.origin(**args) == scope
        foreign = await context.origin(**{**args, "binding": {**binding, "session_id": "another-run"}})
        assert foreign.revision != scope.revision, "equal market inputs do not alias Run context ownership"

        answer = await replay.training.canonical_indicator_compute(session, **common,
            name="MA", params={"period": 20}, bars=rows,
            history_epoch=page["history_epoch"], display_math="viewport-v1")
        assert answer["status"] == "ready"
        with preparation.repository.connect() as db:
            db.execute("UPDATE preparation_context_state SET generation=generation+1")
        with pytest.raises(TrainingRunError) as released:
            await context.assert_origin(scope)
        assert released.value.code == "HISTORY_EPOCH_MISMATCH"
        fresh = await context.origin(**args)
        assert fresh.generation == scope.generation + 1
        assert fresh.revision != scope.revision
        with pytest.raises(TrainingRunError) as stale:
            await replay.training.canonical_indicator_compute(session, **common,
                name="MA", params={"period": 20}, bars=rows,
                history_epoch=page["history_epoch"], display_math="viewport-v1")
        assert stale.value.code == "HISTORY_EPOCH_MISMATCH"
        assert attempts == []
        assert (await replay.get_session(session))["snapshot"] == before
