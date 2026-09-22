from dataclasses import replace
import json
import sqlite3

import pytest

from app.replay.constants import CommandType, SessionState
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.service import ReplayService
from app.replay.broker.models import PAPER_LINEAR_EXECUTION_MODE, TOUCH_OR_TAPE_EXECUTION_MODE, BAR_TOUCH_OR_TAPE_MODEL_VERSION
from app.replay.storage import ReplaySQLiteStore
from tests.test_replay_progressive_history import fixture
from tests.test_replay_service import _command
from tests.test_data_preparation import async_test, START
from tests.fixtures.replay.service_fakes import replay_settings, replay_config


@async_test
@pytest.mark.parametrize("blind", [False, True])
@pytest.mark.parametrize("training", [False, True])
async def test_progressive_session_preserves_full_horizon_through_sqlite_restart(tmp_path, blind, training):
    history, feed_id, publish, archive, identity = fixture(tmp_path)
    first = publish(0, 2)
    history.publish(feed_id, first, START, START + 120_000)
    settings = replace(replay_settings(tmp_path / "replay.db"), replay_history_archive_dir=tmp_path / "archive")

    def service():
        result = ReplayService(settings=settings, store=ReplaySQLiteStore(tmp_path / "replay.db"),
            repository=archive, native_intervals=lambda _: ("1m",))
        result._progressive_history = history
        return result

    runtime = service()
    await runtime.start()
    config = replace(replay_config(blind_mode=blind), requested_start_ms=START, warmup_bars=0, horizon_ms=360_000)
    prefix = replace(config, horizon_ms=120_000)
    try:
        catalog = runtime._catalog.build(warmup_bars=0, horizon_ms=120_000, quality_mode=config.quality_mode)
        entry = next(item for item in catalog.entries if item.identity == identity)
        window = await runtime._select_manual_window(runtime._catalog, entry, prefix, start_ms=START)
        initial = runtime._dataset_builder.create(entry, window)
        if training:
            selection = await runtime.select_training_window(prefix, expected_catalog_epoch=catalog.catalog_epoch)
            created = await runtime.create_progressive_session(
                config, feed_id=feed_id, training_selection=selection,
                initial_horizon_ms=120_000, execution_mode=TOUCH_OR_TAPE_EXECUTION_MODE,
            )
        else:
            created = await runtime.create_progressive_session(
                config, initial_dataset=initial, feed_id=feed_id, execution_mode=PAPER_LINEAR_EXECUTION_MODE,
            )
        session_id = created["session_id"]
        await runtime.command(session_id, _command("acquire", CommandType.ACQUIRE_CONTROLLER, revision=0))
        stepped = await runtime.command(session_id, _command("prefix", CommandType.STEP, revision=1, payload={"count": 2}))
        assert stepped["cursor"]["source_sequence"] == 2
        assert stepped["state"] == "PAUSED"
        assert stepped["cursor"]["at_end"] is False
        with pytest.raises(ReplayDomainError) as pending:
            await runtime.command(session_id, _command("not-ready", CommandType.STEP, revision=2, payload={"count": 1}))
        assert pending.value.code is ReplayErrorCode.DATASET_PENDING
    finally:
        await runtime.shutdown()
    history.pin(feed_id, runtime._progressive_session_owner("interrupted-creation"))
    restarted = service()
    await restarted.start()
    try:
        with history.connect() as db:
            owners = {row[0] for row in db.execute("SELECT owner FROM progressive_bar_refs")}
        assert restarted._progressive_session_owner("interrupted-creation") not in owners
        assert restarted._progressive_session_owner(session_id) in owners
        state = await restarted.get_session_state(session_id, include_config=True)
        assert state["cursor"]["source_sequence"] == 2
        assert state["config"]["horizon_ms"] == 360_000
        if training:
            async with restarted._lease_handle(session_id) as handle:
                snapshot = await handle.actor.public_snapshot()
                assert snapshot["components"]["model_version"] == BAR_TOUCH_OR_TAPE_MODEL_VERSION
        second = publish(2, 4)
        history.publish(feed_id, second, START + 120_000, START + 360_000)
        acquired = await restarted.command(session_id, _command("owner", CommandType.ACQUIRE_CONTROLLER, revision=state["revision"]))
        ended = await restarted.command(session_id, _command("rest", CommandType.STEP, revision=acquired["revision"], payload={"count": 4}))
        assert ended["state"] == SessionState.ENDED.value
        assert ended["cursor"]["source_sequence"] == 6
        assert ended["cursor"]["at_end"] is True
        await restarted.shutdown()
        restarted = service()
        await restarted.start()
        from app.replay.progressive_history import retained_revisions
        history.release("preparation:progressive-request")
        assert set(retained_revisions(archive.root)) == {first, second}
        await restarted.discard_session(session_id)
        assert retained_revisions(archive.root) == ()
    finally:
        await restarted.shutdown()


@async_test
@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("shell", [False, True])
async def test_training_creation_persists_full_request_and_progressive_selection(tmp_path, monkeypatch, retry, shell):
    from tests.test_replay_v2_training_phase1 import _request

    history, feed_id, publish, archive, _identity = fixture(tmp_path)
    history.publish(feed_id, publish(-1, 3), START, START + 120_000)
    settings = replace(replay_settings(tmp_path / "training.db"),
        replay_history_archive_dir=tmp_path / "archive")
    runtime = ReplayService(settings=settings, store=ReplaySQLiteStore(tmp_path / "training.db"),
        repository=archive, native_intervals=lambda _: ("1m",))
    runtime._progressive_history = history
    await runtime.start()
    try:
        catalog = await runtime.catalog(warmup_bars=1, horizon_ms=120_000,
            quality_mode="exact", blind_mode=False)
        request = replace(await _request(runtime), catalog_epoch=catalog["catalog_epoch"],
            requested_start_ms=START, warmup_bars=1, visible_history_lookback=None,
            forward_cache_ms=360_000)
        assert runtime.training is not None
        if shell:
            from app.replay.training.models import TrainingRunSetupRequest, TrainingRunMarketSelectionRequest
            setup = TrainingRunSetupRequest.from_market_request(request)
            empty = await runtime.training.create_empty_run(setup,
                preparation_id="progressive-shell", _progressive_initial_horizon_ms=120_000)
            run_id = empty["run"]["run_id"]
            saved_setup = await runtime.training.store.get_run_setup(run_id)
            assert saved_setup.to_dict()["forward_cache_ms"] == 360_000
            market = TrainingRunMarketSelectionRequest.from_dict({
                "catalog_epoch": catalog["catalog_epoch"], "exchange": "binance",
                "market_type": "spot", "symbol": "BTCUSDT", "base_interval": "1m",
                "display_interval": "1m", "account_history_ref": None,
                "hedge_public_history_ref": None, "simulation_manifest_ref": None,
            })

        async def create():
            if shell:
                return await runtime.training.select_initial_market(run_id, market,
                    _progressive_feed_id=feed_id, _progressive_initial_horizon_ms=120_000)
            return await runtime.training.create_run(request,
                _preparation_id="progressive-training-test",
                _progressive_feed_id=feed_id, _progressive_initial_horizon_ms=120_000)

        if retry:
            from app.replay.training.errors import TrainingRunError

            original = runtime.create_progressive_session

            async def interrupted(*args, **kwargs):
                raise ReplayDomainError(ReplayErrorCode.DATASET_PENDING, "fixture interrupted preparation")

            monkeypatch.setattr(runtime, "create_progressive_session", interrupted)
            with pytest.raises(TrainingRunError, match="could not be created"):
                await create()
            monkeypatch.setattr(runtime, "create_progressive_session", original)
            # The catalog advances before retry. The stored prefix selection
            # still binds the original archive revision and the full request.
            history.publish(feed_id, publish(2, 4), START + 120_000, START + 360_000)
            if shell:
                preparation_id = await runtime.store.run_extension_read(lambda db: db.execute(
                    "SELECT preparation_id FROM replay_training_selection_preparation"
                ).fetchone()[0])
                created = await runtime.training._retry_selection_preparation(
                    preparation_id, existing_shell_run_id=run_id)
            else:
                created = await runtime.training._retry_selection_preparation("progressive-training-test")
        else:
            created = await create()
        assert created["run"]
        preparation_id = await runtime.store.run_extension_read(lambda db: db.execute(
            "SELECT preparation_id FROM replay_training_selection_preparation"
        ).fetchone()[0])
        preparation = await runtime.training.store.selection_preparation(preparation_id)
        assert preparation["status"] == "READY"
        with sqlite3.connect(tmp_path / "training.db") as db:
            request_json, selection_json, required_end = db.execute(
                "SELECT request_json, selection_json, required_end_ms "
                "FROM replay_training_selection_preparation WHERE preparation_id = ?",
                (preparation_id,),
            ).fetchone()
        assert required_end == START + 300_000
        assert json.loads(request_json)["forward_cache_ms"] == 360_000
        assert json.loads(selection_json)["progressive_preparation"] == {
            "feed_id": feed_id, "initial_horizon_ms": 120_000,
        }
    finally:
        await runtime.shutdown()
