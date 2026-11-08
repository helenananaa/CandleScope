from __future__ import annotations

import base64
import json
import random
import sqlite3
import struct
import zlib

import pytest

from app.replay.training.errors import TrainingRunError
from app.replay.training.repositories import note_captures
from app.replay.training.schema import TRAINING_SCHEMA_VERSION, migrate_training_schema
from tests.test_replay_training_notes import create
from tests.test_replay_v2_training_phase5 import _service

pytestmark = pytest.mark.anyio


def png(red=1, *, large=False):
    width = height = 180 if large else 1
    pixels = random.Random(0).randbytes(width * height * 4) if large else bytes([red, 0, 0, 255])
    rows = b"".join(b"\x00" + pixels[index * width * 4:(index + 1) * width * 4] for index in range(height))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = note_captures.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    raw += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def payload(context, identifier="capture-a", image=None):
    return {"capture_id": identifier, "image": image or png(), "context": context, "captured_context": context,
            "chart": {"interval": "1m", "chartType": "candles", "seriesKey": "explicit-fixture-series", "sourceVersion": 1}}


async def test_version_images_preserve_pixels_and_same_time_event_boundary_across_restart(tmp_path):
    path = tmp_path / "capture-versions.db"
    service = await _service(path)
    try:
        run, session, track = await create(service)
        context = (await service.training.notes(run, track))["context"]
        before = (await service.get_session(session))["snapshot"]
        first_request = payload(context)
        first = await service.training.save_note_capture(run, track, **first_request)
        fields = {"entryBasis": "original with red pixel", "replayScreenshotIds": json.dumps([first["capture"]["id"]])}
        original = await service.training.save_note(run, track, note_id="plan", fields=fields, expected_revision=0, context=context)
        assert original["screenshots"] == [first["capture"]]
        assert (await service.get_session(session))["snapshot"] == before
        event = await service.training.record_review_marker(run, command_id="capture-event", text="same millisecond later event")
        later = (await service.training.notes(run, track))["context"]
        assert later["virtualTimeMs"] == context["virtualTimeMs"] and later["timelineSequence"] > context["timelineSequence"]
        second = await service.training.save_note_capture(run, track, **payload(later, "capture-b", png(200)))
        before = (await service.get_session(session))["snapshot"]
        changed = await service.training.save_note(run, track, note_id="plan", fields={"entryBasis": "later with different pixel",
            "replayScreenshotIds": '["capture-b"]'}, expected_revision=1, context=later)
        assert changed["screenshots"] == [second["capture"]]
        assert (await service.get_session(session))["snapshot"] == before
        assert (await service.training.note_capture_image(run, track, "plan", 1, "capture-a"))["image"] == png()
        assert (await service.training.note_capture_image(run, track, "plan", 2, "capture-b"))["image"] == png(200)
        with pytest.raises(TrainingRunError) as wrong_version:
            await service.training.note_capture_image(run, track, "plan", 1, "capture-b")
        assert wrong_version.value.status_code == 404
        assert await service.training.save_note_capture(run, track, **first_request) == first
        assert await service.training.save_note(run, track, note_id="plan", fields=fields, expected_revision=0, context=context) == original
        other_run, _, other_track = await create(service)
        with pytest.raises(TrainingRunError) as cross_run:
            await service.training.note_captures(other_run, other_track, capture_id="capture-a")
        assert cross_run.value.status_code == 404
        other_context = (await service.training.notes(other_run, other_track))["context"]
        with pytest.raises(TrainingRunError):
            await service.training.save_note(other_run, other_track, note_id="cross-run", fields=fields, expected_revision=0, context=other_context)
        review = await service.training.start_review(run, event_id=None)
        first_event = next(item for item in review["events"] if item["timeline_sequence"] == context["timelineSequence"])
        await service.training.start_review(run, event_id=first_event["event_id"])
        assert (await service.training.note_captures(run, track))["captures"] == []
        with pytest.raises(TrainingRunError) as unpublished:
            await service.training.note_capture_image(run, track, "plan", 1, "capture-a")
        assert unpublished.value.status_code == 404
        await service.training.start_review(run, event_id=event["event_id"])
        history = await service.training.notes(run, track)
        assert history["notes"] == [original]
        assert (await service.training.note_captures(run, track))["captures"] == [first["capture"]]
        with pytest.raises(TrainingRunError) as future_version:
            await service.training.note_capture_image(run, track, "plan", 2, "capture-b")
        assert future_version.value.status_code == 404
        with pytest.raises(TrainingRunError):
            await service.training.save_note(run, track, note_id="review-future", fields={"replayScreenshotIds": '["capture-b"]'},
                expected_revision=0, context=history["context"])
        before = (await service.get_session(session))["snapshot"]
        supplement = await service.training.save_note(run, track, note_id="review-old", fields=fields,
            expected_revision=0, context=history["context"])
        assert supplement["reviewNote"] and supplement["screenshots"] == [first["capture"]]
        assert (await service.get_session(session))["snapshot"] == before
        await service.shutdown(step_timeout=1)
        service = await _service(path)
        assert (await service.training.note_capture_image(run, track, "plan", 1, "capture-a"))["image"] == png()
        assert (await service.training.notes(run, track))["notes"] == [original, supplement]
        await service.store.run_extension_write(lambda db: db.execute(
            "DELETE FROM replay_training_note_capture_link WHERE run_id=? AND note_id='plan' AND revision=1", (run,)))
        with pytest.raises(TrainingRunError) as missing:
            await service.training.notes(run, track)
        assert missing.value.status_code == 503
    finally:
        await service.shutdown(step_timeout=1)


async def test_capture_limits_reject_future_invalid_and_excess_assets_without_partial_notes(tmp_path, monkeypatch):
    service = await _service(tmp_path / "capture-budgets.db")
    try:
        run, session, track = await create(service)
        context = (await service.training.notes(run, track))["context"]
        before = (await service.get_session(session))["snapshot"]
        monkeypatch.setattr(note_captures, "MAX_RUN_BYTES", 1)
        with pytest.raises(TrainingRunError) as budget:
            await service.training.save_note_capture(run, track, **payload(context))
        assert budget.value.code == "REPLAY_NOTE_CAPTURE_BUDGET_EXCEEDED"
        assert (await service.training.note_captures(run, track))["captures"] == []
        monkeypatch.setattr(note_captures, "MAX_RUN_BYTES", 16 * 1024 * 1024)
        monkeypatch.setattr(note_captures, "MAX_CAPTURES", 1)
        first = await service.training.save_note_capture(run, track, **payload(context))
        with pytest.raises(TrainingRunError):
            await service.training.save_note_capture(run, track, **payload(context, "over-count"))
        for change in [{"image": "data:image/png;base64,AAAA"}, {"captured_context": {**context, "virtualTimeMs": context["virtualTimeMs"] + 1}},
                       {"captured_context": {**context, "timelineSequence": context["timelineSequence"] + 1}},
                       {"captured_context": {**context, "dataEpoch": "other"}}, {"chart": {"interval": "1m"}}]:
            with pytest.raises(TrainingRunError) as invalid:
                await service.training.save_note_capture(run, track, **{**payload(context, "invalid"), **change})
            assert invalid.value.code == "REPLAY_NOTE_CAPTURE_INVALID"
        with pytest.raises(TrainingRunError) as changed:
            await service.training.save_note_capture(run, track, **payload(context, "capture-a", png(200)))
        assert changed.value.code == "REPLAY_NOTE_CAPTURE_CONFLICT"
        monkeypatch.setattr(note_captures, "MAX_CAPTURES", 128)
        await service.training.save_note_capture(run, track, **payload(context, "capture-b"))
        await service.training.save_note_capture(run, track, **payload(context, "capture-c"))
        for fields in [{"replayScreenshotIds": '["capture-a","capture-b","capture-c"]'},
                       {"replayScreenshotIds": '["capture-a","capture-a"]'}, {"replayScreenshotIds": '["missing"]'},
                       {"replayPendingCaptureId": "pending"}]:
            with pytest.raises(TrainingRunError):
                await service.training.save_note(run, track, note_id="invalid", fields=fields, expected_revision=0, context=context)
        assert (await service.training.notes(run, track))["notes"] == []
        assert (await service.get_session(session))["snapshot"] == before
        assert (await service.training.note_captures(run, track, capture_id=first["capture"]["id"]))["captures"] == [first["capture"]]
    finally:
        await service.shutdown(step_timeout=1)


async def test_schema_28_adds_capture_storage_without_changing_existing_note_or_financial_rows(tmp_path):
    path = tmp_path / "upgrade28.db"
    service = await _service(path)
    run, _, track = await create(service)
    context = (await service.training.notes(run, track))["context"]
    await service.training.save_note(run, track, note_id="old", fields={"entryBasis": "old note"}, expected_revision=0, context=context)
    await service.shutdown(step_timeout=1)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE replay_training_note_capture_link")
        db.execute("DROP TABLE replay_training_note_capture")
        db.execute("UPDATE replay_training_schema_version SET version=28")
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'replay_training_schema_version'")]
        before = {name: db.execute('SELECT * FROM "' + name + '"').fetchall() for name in names}
        migrate_training_schema(db, now_ms=12345)
        assert {name: db.execute('SELECT * FROM "' + name + '"').fetchall() for name in names} == before
        assert db.execute("SELECT version FROM replay_training_schema_version").fetchone() == (TRAINING_SCHEMA_VERSION,)
        assert db.execute("SELECT COUNT(*) FROM replay_training_note_capture").fetchone() == (0,)
    recovered = await _service(path)
    try:
        assert (await recovered.training.notes(run, track))["notes"][0]["screenshots"] == []
    finally:
        await recovered.shutdown(step_timeout=1)


async def test_capture_http_keeps_large_png_limit_separate_and_images_bound_to_versions(tmp_path):
    import httpx
    from fastapi import FastAPI
    from app.api.v1.replay import router
    from app.data_engine.data_manager.core import DataManagerCore
    service = await _service(tmp_path / "capture-http.db")
    try:
        run, _, track = await create(service)
        context = (await service.training.notes(run, track))["context"]
        core = DataManagerCore()
        core.bind_replay(service)
        app = FastAPI()
        app.state.data_manager_core = core
        app.include_router(router, prefix="/api/v1")
        from fastapi.responses import JSONResponse
        @app.exception_handler(TrainingRunError)
        async def domain_error(_request, error):
            return JSONResponse(error.to_payload(), status_code=error.status_code)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            base = f"/api/v1/replay/runs/{run}/tracks/{track}"
            request = {"id": "large-capture", "image": png(large=True), "context": context, "capturedContext": context,
                       "chart": payload(context)["chart"]}
            assert len(request["image"]) > 64 * 1024
            uploaded = await client.post(base + "/note-captures", json=request)
            assert uploaded.status_code == 200 and uploaded.headers["cache-control"] == "no-store"
            assert (await client.post(base + "/note-captures", json=request)).json() == uploaded.json()
            image_path = base + "/notes/plan/versions/1/screenshots/large-capture"
            assert (await client.get(image_path)).status_code == 404
            saved = await client.post(base + "/notes", json={"id": "plan", "fields": {"replayScreenshotIds": '["large-capture"]'},
                "expectedRevision": 0, "context": context})
            assert saved.status_code == 200 and saved.json()["screenshots"][0]["width"] == 180
            image = await client.get(image_path)
            assert image.status_code == 200 and image.headers["cache-control"] == "no-store"
            assert image.json()["image"] == request["image"]
            assert (await client.get(base + "/note-captures")).json()["captures"] == [uploaded.json()["capture"]]
            oversized_text = await client.post(base + "/notes", json={"id": "large-text", "fields": {"entryBasis": "x" * 70_000},
                "expectedRevision": 0, "context": context})
            assert oversized_text.status_code == 413
            assert (await client.post(base + "/note-captures", content=b"x" * (3 * 1024 * 1024 + 1))).status_code == 413
            assert core.replay.diagnostics()["control_accesses"] >= 6
    finally:
        await service.shutdown(step_timeout=1)


async def test_existing_run_deletion_cascades_linked_and_unbound_captures(tmp_path):
    service = await _service(tmp_path / "capture-delete.db")
    try:
        run, _, track = await create(service)
        context = (await service.training.notes(run, track))["context"]
        await service.training.save_note_capture(run, track, **payload(context, "bound"))
        await service.training.save_note_capture(run, track, **payload(context, "unbound"))
        await service.training.save_note(run, track, note_id="plan", fields={"replayScreenshotIds": '["bound"]'}, expected_revision=0, context=context)
        await service.training.delete_run(run)
        counts = await service.store.run_extension_read(lambda db: [db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in ["replay_training_note_capture", "replay_training_note_capture_link", "replay_training_note_revision"]])
        assert counts == [0, 0, 0]
    finally:
        await service.shutdown(step_timeout=1)
