from __future__ import annotations

import pytest

from app.replay.constants import REPLAY_PROTOCOL, CommandType
from app.replay.models import ReplayCommand
from app.replay.training.errors import TrainingRunError
from app.replay.training.repositories.notes import TrainingNoteRepository
from tests.test_replay_v2_training_phase1 import _service, _request, _command

pytestmark = pytest.mark.anyio


async def create(service, policy="NONE"):
    run = (await service.training.create_run(await _request(service, time_disclosure_policy=policy)))["run"]
    tracks = await service.training.store.get_market_tracks(run["run_id"])
    return run["run_id"], run["adapter_session_id"], tracks["tracks"][0]["track_id"]


async def advance(service, session_id):
    acquired = await service.command(session_id, _command("notes-controller", CommandType.ACQUIRE_CONTROLLER, revision=0))
    return await service.command(session_id, ReplayCommand(
        protocol=REPLAY_PROTOCOL, command_id="notes-step", client_instance_id="phase1-browser",
        expected_revision=acquired["revision"], type=CommandType.STEP, payload={"count": 1},
    ))


@pytest.mark.parametrize("policy", ["NONE", "HIDE_ALL"])
async def test_versions_hide_future_edits_and_retry_returns_original_submission(tmp_path, policy):
    service = await _service(tmp_path / "notes.db")
    try:
        run, session, track = await create(service, policy)
        repo = TrainingNoteRepository(service.store)
        first = await repo.notes(run, track)
        before = (await service.get_session(session))["snapshot"]
        assert first["context"]["virtualTimeMs"] == before["cursor"]["virtual_time_ms"]
        original = await repo.save_note(run, track, note_id="plan", fields={"entryBasis": "before the move"},
                                       expected_revision=0, context=first["context"])
        assert original["reviewNote"] is False
        assert (await service.get_session(session))["snapshot"] == before
        await advance(service, session)
        current = await repo.notes(run, track)
        assert current["asOfMs"] > first["asOfMs"]
        before = (await service.get_session(session))["snapshot"]
        edited = await repo.save_note(run, track, note_id="plan", fields={"entryBasis": "later edit"},
                                     expected_revision=1, context=current["context"])
        await repo.save_note(run, track, note_id="future-note", fields={"entryBasis": "future creation"},
                             expected_revision=0, context=current["context"])
        historical = await repo.notes(run, track, at_time_ms=first["asOfMs"])
        assert historical["notes"] == [original]
        assert (await repo.notes(run, track))["notes"][0] == edited
        retry = await repo.save_note(run, track, note_id="plan", fields={"entryBasis": "before the move"},
                                    expected_revision=0, context=first["context"])
        assert retry == original
        assert (await service.get_session(session))["snapshot"] == before
        with pytest.raises(TrainingRunError, match="exceeds"):
            await repo.notes(run, track, at_time_ms=current["asOfMs"] + 1)
    finally:
        await service.shutdown(step_timeout=1)


async def test_late_context_and_concurrent_editor_do_not_write_or_move_notes(tmp_path):
    service = await _service(tmp_path / "conflicts.db")
    try:
        run, session, track = await create(service)
        repo = TrainingNoteRepository(service.store)
        first = await repo.notes(run, track)
        await advance(service, session)
        with pytest.raises(TrainingRunError) as stale:
            await repo.save_note(run, track, note_id="late", fields={"entryBasis": "draft"},
                                 expected_revision=0, context=first["context"])
        assert stale.value.code == "REPLAY_NOTE_CONTEXT_CHANGED"
        current = await repo.notes(run, track)
        assert current["notes"] == []
        await repo.save_note(run, track, note_id="shared", fields={"entryBasis": "editor A"},
                             expected_revision=0, context=current["context"])
        with pytest.raises(TrainingRunError) as conflict:
            await repo.save_note(run, track, note_id="shared", fields={"entryBasis": "editor B"},
                                 expected_revision=0, context=current["context"])
        assert conflict.value.code == "REPLAY_NOTE_CONFLICT"
        assert (await repo.notes(run, track))["notes"][0]["fields"] == {"entryBasis": "editor A"}
    finally:
        await service.shutdown(step_timeout=1)


async def test_run_scope_and_service_restart_preserve_text_versions(tmp_path):
    path = tmp_path / "restart.db"
    service = await _service(path)
    try:
        first_run, session, first_track = await create(service)
        second_run, _, second_track = await create(service)
        repo = TrainingNoteRepository(service.store)
        for run, track, text in [(first_run, first_track, "first run"), (second_run, second_track, "second run")]:
            context = (await repo.notes(run, track))["context"]
            await repo.save_note(run, track, note_id="same-client-id", fields={"entryBasis": text},
                                 expected_revision=0, context=context)
        saved = (await repo.notes(first_run, first_track))["notes"]
        cursor = (await service.get_session(session))["snapshot"]["cursor"]
    finally:
        await service.shutdown(step_timeout=1)
    restarted = await _service(path)
    try:
        repo = TrainingNoteRepository(restarted.store)
        assert (await repo.notes(first_run, first_track))["notes"] == saved
        assert (await repo.notes(second_run, second_track))["notes"][0]["fields"] == {"entryBasis": "second run"}
        assert (await restarted.get_session(session))["snapshot"]["cursor"] == cursor
    finally:
        await restarted.shutdown(step_timeout=1)


async def test_missing_historical_version_does_not_substitute_later_text(tmp_path):
    service = await _service(tmp_path / "corrupt.db")
    try:
        run, session, track = await create(service)
        repo = TrainingNoteRepository(service.store)
        first = await repo.notes(run, track)
        await repo.save_note(run, track, note_id="plan", fields={"entryBasis": "old"},
                             expected_revision=0, context=first["context"])
        await advance(service, session)
        current = await repo.notes(run, track)
        await repo.save_note(run, track, note_id="plan", fields={"entryBasis": "future"},
                             expected_revision=1, context=current["context"])
        await service.store.run_extension_write(lambda db: db.execute(
            "DELETE FROM replay_training_note_revision WHERE run_id=? AND note_id=? AND revision=1", (run, "plan")))
        with pytest.raises(TrainingRunError) as missing:
            await repo.notes(run, track, at_time_ms=first["asOfMs"])
        assert missing.value.code == "REPLAY_NOTE_CORRUPT"
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.parametrize("policy", ["NONE", "HIDE_ALL"])
async def test_review_supplement_does_not_replace_original_plan_or_touch_finances(tmp_path, policy):
    from app.replay.training.models import ReplayV2CommandType
    from tests.fixtures.replay.service_fakes import INTERVAL_MS
    from tests.test_replay_v2_training_phase5 import _service as multi_service, _request as multi_request, _acquire, _command as multi_command

    service = await multi_service(tmp_path / "review.db")
    try:
        run = (await service.training.create_run(await _request(service, time_disclosure_policy=policy)))["run"]
        run_id, session = run["run_id"], run["adapter_session_id"]
        tracks = await service.training.store.get_market_tracks(run_id)
        track = tracks["tracks"][0]["track_id"]
        repo = TrainingNoteRepository(service.store)
        original_context = (await repo.notes(run_id, track))["context"]
        original = await repo.save_note(run_id, track, note_id="plan", fields={"entryBasis": "original plan"},
                                       expected_revision=0, context=original_context)
        saved_event = await service.training.record_review_marker(run_id, command_id="original-saved", text="Original plan saved")
        await _acquire(service, run_id=run_id, selected_session_id=session, command_id="note-acquire")
        snapshot = await service.get_session(session)
        await service.training.command(run_id, multi_command(run_id, "note-advance", ReplayV2CommandType.ADVANCE_TO,
            snapshot, {"virtual_time_ms": original_context["virtualTimeMs"] + 2 * INTERVAL_MS}))
        later = (await repo.notes(run_id, track))["context"]
        await repo.save_note(run_id, track, note_id="plan", fields={"entryBasis": "later plan"},
                             expected_revision=1, context=later)
        await service.training.start_review(run_id, event_id=saved_event["event_id"])
        review = await repo.notes(run_id, track)
        assert review["context"]["reviewId"] is not None and review["context"]["reviewNote"] is True
        assert review["notes"] == [original]
        before = (await service.get_session(session))["snapshot"]
        with pytest.raises(TrainingRunError):
            await repo.save_note(run_id, track, note_id="plan", fields={"entryBasis": "rewrite old plan"},
                                 expected_revision=1, context=review["context"])
        supplement = await repo.save_note(run_id, track, note_id="review-note", fields={"entryBasis": "later review"},
                                         expected_revision=0, context=review["context"])
        assert supplement["reviewNote"] is True
        assert supplement["marketTimeMs"] == original_context["virtualTimeMs"]
        assert (await repo.notes(run_id, track))["notes"] == [original, supplement]
        assert (await service.get_session(session))["snapshot"] == before
    finally:
        await service.shutdown(step_timeout=1)


async def test_notes_http_uses_data_manager_and_strict_context(tmp_path):
    import httpx
    from fastapi import FastAPI
    from app.api.v1.replay import router
    from app.data_engine.data_manager.core import DataManagerCore

    service = await _service(tmp_path / "api.db")
    try:
        run, session, track = await create(service)
        core = DataManagerCore()
        core.bind_replay(service)
        app = FastAPI()
        app.state.data_manager_core = core
        app.include_router(router, prefix="/api/v1")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/replay/runs/{run}/tracks/{track}/notes"
            loaded = await client.get(path)
            assert loaded.status_code == 200
            context = loaded.json()["context"]
            before = (await service.get_session(session))["snapshot"]
            payload = {"id": "api-plan", "fields": {"entryBasis": "HTTP plan"}, "expectedRevision": 0, "context": context}
            saved = await client.post(path, json=payload)
            assert saved.status_code == 200
            assert saved.json()["fields"] == payload["fields"]
            assert (await client.post(path, json=payload)).json() == saved.json()
            invalid = await client.post(path, json={**payload, "context": {**context, "sourceSequence": True}})
            assert invalid.status_code == 422
            assert (await client.get(path)).json()["notes"] == [saved.json()]
            candidates = await client.get(path + "/link-options", params={"kind": "FILL"})
            assert candidates.status_code == 200 and candidates.json()["links"] == []
            assert (await client.get(path + "/link-options", params={"kind": "ORDERS"})).status_code == 422
            history = await client.get(path + "/api-plan/versions", params={"before_revision": 2, "limit": 1})
            assert history.status_code == 200
            assert history.json()["versions"] == [saved.json()]
            for params in [{"before_revision": 102}, {"limit": 21}, {"at_time_ms": context["virtualTimeMs"] + 1}]:
                assert (await client.get(path + "/api-plan/versions", params=params)).status_code == 422
            assert (await client.get(path + "/missing/versions")).status_code == 404
            assert (await client.get(path + "?at_time_ms=" + str(context["virtualTimeMs"] + 1))).status_code == 422
            assert (await service.get_session(session))["snapshot"] == before
            assert core.replay.diagnostics()["control_accesses"] >= 5
    finally:
        await service.shutdown(step_timeout=1)


async def test_annotation_budget_failure_rolls_back_new_note(tmp_path, monkeypatch):
    import app.replay.training.repositories.notes as notes_module
    service = await _service(tmp_path / "budget.db")
    try:
        run, _, track = await create(service)
        repo = TrainingNoteRepository(service.store)
        context = (await repo.notes(run, track))["context"]
        monkeypatch.setattr(notes_module, "MAX_RUN_BYTES", 1)
        with pytest.raises(TrainingRunError) as full:
            await repo.save_note(run, track, note_id="over-budget", fields={"entryBasis": "retained in client draft"},
                                 expected_revision=0, context=context)
        assert full.value.code == "REPLAY_NOTE_BUDGET_EXCEEDED"
        assert (await repo.notes(run, track))["notes"] == []
    finally:
        await service.shutdown(step_timeout=1)


async def test_same_time_later_event_does_not_reveal_later_note_version(tmp_path):
    from tests.test_replay_v2_training_phase5 import _service as multi_service
    service = await multi_service(tmp_path / "same-time.db")
    try:
        run, _, track = await create(service)
        repo = TrainingNoteRepository(service.store)
        context = (await repo.notes(run, track))["context"]
        original = await repo.save_note(run, track, note_id="plan", fields={"entryBasis": "before event"},
                                       expected_revision=0, context=context)
        event = await service.training.record_review_marker(run, command_id="same-time-event", text="later event at the same market time")
        later = (await repo.notes(run, track))["context"]
        assert later["virtualTimeMs"] == context["virtualTimeMs"]
        await repo.save_note(run, track, note_id="plan", fields={"entryBasis": "after event"},
                             expected_revision=1, context=later)
        await repo.save_note(run, track, note_id="later-note", fields={"entryBasis": "later creation"},
                             expected_revision=0, context=later)
        review = await service.training.start_review(run, event_id=None)
        first_event = next(item for item in review["events"] if item["timeline_sequence"] == context["timelineSequence"])
        await service.training.start_review(run, event_id=first_event["event_id"])
        assert (await repo.notes(run, track))["notes"] == []
        training_view = await service.training.notes(run, track, training_view=True)
        assert training_view["context"]["reviewId"] is None
        assert [note["revisionCount"] for note in training_view["notes"] if note["id"] == "plan"] == [2]
        with pytest.raises(TrainingRunError) as unpublished:
            await service.training.note_versions(run, track, "plan")
        assert unpublished.value.status_code == 404
        await service.training.start_review(run, event_id=event["event_id"])
        historical = await repo.notes(run, track)
        assert historical["notes"] == [original]
        versions = await service.training.note_versions(run, track, "plan")
        assert versions["versions"] == [original]
        assert versions["nextBeforeRevision"] is None
        with pytest.raises(TrainingRunError) as hidden:
            await service.training.note_versions(run, track, "later-note")
        assert hidden.value.status_code == 404
    finally:
        await service.shutdown(step_timeout=1)


async def test_schema_26_adds_notes_without_rewriting_existing_run_or_financial_rows(tmp_path):
    import sqlite3
    from app.replay.training.schema import TRAINING_SCHEMA_VERSION

    path = tmp_path / "v26.db"
    service = await _service(path)
    run, session, track = await create(service)
    await advance(service, session)
    before = await service.get_session(session)
    await service.shutdown(step_timeout=1)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE replay_training_note_capture_link")
        db.execute("DROP TABLE replay_training_note_capture")
        db.execute("DROP TABLE replay_training_note_links")
        db.execute("DROP TABLE replay_training_note_revision")
        db.execute("DROP TABLE replay_training_note")
        db.execute("DROP INDEX replay_note_context_visited_time")
        db.execute("UPDATE replay_training_schema_version SET version=26")
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'replay_training_schema_version'")]
        rows = {name: db.execute('SELECT * FROM "' + name + '"').fetchall() for name in names}
    restarted = await _service(path)
    try:
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT version FROM replay_training_schema_version").fetchone() == (TRAINING_SCHEMA_VERSION,)
            assert {name: db.execute('SELECT * FROM "' + name + '"').fetchall() for name in names} == rows
        recovered_snapshot = (await restarted.get_session(session))["snapshot"]
        # Existing actor recovery drops controller ownership and adds its own checkpoint.
        # The additive schema migration above preserves every pre-existing row.
        for key in before["snapshot"]:
            if key not in {"controller_client_id", "status_reason", "checkpoint_count"}:
                assert recovered_snapshot[key] == before["snapshot"][key]
        repo = TrainingNoteRepository(restarted.store)
        current = await repo.notes(run, track)
        assert current["notes"] == []
        await repo.save_note(run, track, note_id="after-upgrade", fields={"entryBasis": "new annotation"},
                             expected_revision=0, context=current["context"])
        assert (await restarted.get_session(session))["snapshot"] == recovered_snapshot
    finally:
        await restarted.shutdown(step_timeout=1)


async def test_simultaneous_editors_have_one_authoritative_winner(tmp_path):
    import asyncio
    service = await _service(tmp_path / "two-editors.db")
    try:
        run, session, track = await create(service)
        context = (await service.training.notes(run, track))["context"]
        before = (await service.get_session(session))["snapshot"]
        results = await asyncio.gather(*(
            service.training.save_note(run, track, note_id="same-note", fields={"entryBasis": text},
                                       expected_revision=0, context=context)
            for text in ("editor A", "editor B")
        ), return_exceptions=True)
        saved = [value for value in results if isinstance(value, dict)]
        errors = [value for value in results if isinstance(value, TrainingRunError)]
        assert len(saved) == len(errors) == 1
        assert errors[0].code == "REPLAY_NOTE_CONFLICT"
        assert (await service.training.notes(run, track))["notes"] == saved
        assert (await service.get_session(session))["snapshot"] == before
    finally:
        await service.shutdown(step_timeout=1)


async def test_notes_follow_committed_run_time_after_an_older_account_checkpoint(tmp_path):
    from app.replay.training.models import ReplayV2CommandType
    from tests.test_replay_v2_training_phase5 import _acquire, _command as training_command

    service = await _service(tmp_path / "account-checkpoint.db")
    try:
        run, session, track = await create(service)
        await _acquire(service, run_id=run, selected_session_id=session, command_id="note-account-owner")
        original = await service.training.notes(run, track)
        await service.training.save_note(run, track, note_id="plan", fields={"entryBasis":"before the order"},
            expected_revision=0, context=original["context"])
        snapshot = await service.get_session(session)
        await service.training.command(run, training_command(run,"note-market-buy",ReplayV2CommandType.PLACE_ORDER,
            snapshot,{"client_order_id":"note-market-order","side":"BUY","order_type":"MARKET","quantity":"0.1",
                      "reduce_only":False,"limit_price":None,"stop_price":None}))
        snapshot = await service.get_session(session)
        await service.training.command(run, training_command(run,"note-step",ReplayV2CommandType.STEP_BASE,
            snapshot,{"count":1}))
        current = (await service.get_session(session))["snapshot"]
        clock = current["cursor"]["virtual_time_ms"]
        assert clock > original["asOfMs"]
        visible = await service.training.notes(run, track, at_time_ms=clock)
        assert visible["context"]["virtualTimeMs"] == visible["asOfMs"] == clock
        await service.training.save_note(run, track, note_id="plan", fields={"entryBasis":"after the fill"},
            expected_revision=1, context=visible["context"])
        assert (await service.get_session(session))["snapshot"] == current
        historical = await service.training.notes(run, track, at_time_ms=original["asOfMs"])
        assert historical["notes"][0]["fields"]["entryBasis"] == "before the order"
    finally:
        await service.shutdown(step_timeout=1)


async def test_notes_use_the_same_committed_global_time_for_two_full_tracks(tmp_path):
    from app.replay.training.models import ReplayV2CommandType
    from tests.test_replay_v2_training_phase5 import _service as multi_service, _request as multi_request, _acquire, _add_track, _command as training_command

    service=await multi_service(tmp_path/"global-note-clock.db")
    try:
        result=await service.training.create_run(await multi_request(service))
        run,session=result["run"]["run_id"],result["run"]["adapter_session_id"]
        await _acquire(service,run_id=run,selected_session_id=session,command_id="global-note-owner")
        await _add_track(service,run_id=run,selected_session_id=session,symbol="ETHUSDT",tier="FULL",command_id="global-note-eth")
        snapshot=await service.get_session(session)
        await service.training.command(run,training_command(run,"global-note-step",ReplayV2CommandType.STEP_BASE,snapshot,{"count":1}))
        tracks=(await service.training.store.get_market_tracks(run))["tracks"]
        assert len(tracks)==2
        clock=await service.store.run_extension_read(lambda db:db.execute(
            "SELECT virtual_time_ms FROM replay_training_run WHERE run_id=?",(run,)).fetchone()[0])
        checkpoint=await service.store.run_extension_read(lambda db:db.execute(
            "SELECT global_virtual_time_ms FROM replay_training_global_checkpoint WHERE run_id=? ORDER BY checkpoint_sequence DESC LIMIT 1",(run,)).fetchone()[0])
        assert clock==checkpoint
        for track in tracks:
            context=(await service.training.notes(run,track["track_id"]))["context"]
            assert context["virtualTimeMs"]==clock
            await service.training.save_note(run,track["track_id"],note_id="same-local-id-"+track["track_id"],
                fields={"entryBasis":track["symbol"]},expected_revision=0,context=context)
    finally:
        await service.shutdown(step_timeout=1)


async def test_version_pages_are_bounded_temporal_and_note_scoped(tmp_path):
    service=await _service(tmp_path/"note-version-pages.db")
    try:
        run,session,track=await create(service)
        first=(await service.training.notes(run,track))["context"]
        for revision in range(25):
            await service.training.save_note(run,track,note_id="paged-plan",fields={"entryBasis":f"version {revision+1}"},
                expected_revision=revision,context=first)
        page=await service.training.note_versions(run,track,"paged-plan",limit=20)
        assert [v["revisionCount"] for v in page["versions"]]==list(range(25,5,-1))
        assert page["nextBeforeRevision"]==6
        tail=await service.training.note_versions(run,track,"paged-plan",before_revision=page["nextBeforeRevision"])
        assert [v["revisionCount"] for v in tail["versions"]]==[5,4,3,2,1]
        assert tail["nextBeforeRevision"] is None
        await advance(service,session)
        later=(await service.training.notes(run,track))["context"]
        await service.training.save_note(run,track,note_id="paged-plan",fields={"entryBasis":"future version"},expected_revision=25,context=later)
        await service.training.save_note(run,track,note_id="future-created",fields={"entryBasis":"future note"},expected_revision=0,context=later)
        history=await service.training.note_versions(run,track,"paged-plan",at_time_ms=first["virtualTimeMs"])
        assert history["versions"]==page["versions"]
        with pytest.raises(TrainingRunError) as hidden:
            await service.training.note_versions(run,track,"future-created",at_time_ms=first["virtualTimeMs"])
        assert hidden.value.status_code==404
        for options in [{"limit":21},{"limit":True},{"before_revision":0},{"before_revision":102}]:
            with pytest.raises(TrainingRunError):
                await service.training.note_versions(run,track,"paged-plan",**options)
    finally:
        await service.shutdown(step_timeout=1)
