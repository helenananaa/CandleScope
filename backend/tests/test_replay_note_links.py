from __future__ import annotations

import json
import sqlite3

import pytest

from app.replay.training.errors import TrainingRunError
from app.replay.training.models import ReplayV2CommandType
from app.replay.training.schema import migrate_training_schema, TRAINING_SCHEMA_VERSION
from tests.test_replay_training_notes import create
from tests.test_replay_v2_training_phase5 import _service, _acquire, _command

pytestmark = pytest.mark.anyio


async def command(service, run, session, identifier, kind, payload):
    return await service.training.command(run, _command(run, identifier, kind, await service.get_session(session), payload))


async def buy(service, run, session, identifier):
    return await command(service, run, session, identifier, ReplayV2CommandType.PLACE_ORDER,
        {"client_order_id": identifier, "side": "BUY", "order_type": "MARKET", "quantity": "0.1",
         "reduce_only": False, "limit_price": None, "stop_price": None})


async def test_links_freeze_exact_versions_and_same_time_review_uses_ledger_prefix(tmp_path):
    service = await _service(tmp_path / "linked-notes.db")
    try:
        run, session, track = await create(service)
        await _acquire(service, run_id=run, selected_session_id=session, command_id="links-owner")
        initial = (await service.training.notes(run, track))["context"]
        original = await service.training.save_note(run, track, note_id="plan", fields={"entryBasis": "before fill"},
                                                  expected_revision=0, context=initial)
        await buy(service, run, session, "linked-buy")
        current = (await service.training.notes(run, track))["context"]
        assert current["virtualTimeMs"] == initial["virtualTimeMs"]
        options = await service.training.note_link_options(run, track, kind="FILL")
        assert len(options["links"]) == 1
        fill = options["links"][0]
        fields = {"entryBasis": "after fill", "replayFillIds": json.dumps([fill["id"]])}
        before = (await service.get_session(session))["snapshot"]
        linked = await service.training.save_note(run, track, note_id="plan", fields=fields, expected_revision=1, context=current)
        assert linked["links"] == [fill]
        assert (await service.get_session(session))["snapshot"] == before
        await command(service, run, session, "linked-close", ReplayV2CommandType.PLACE_ORDER,
            {"client_order_id": "linked-close", "side": "SELL", "order_type": "MARKET", "quantity": "0.1",
             "reduce_only": True, "limit_price": None, "stop_price": None})
        trades = await service.training.note_link_options(run, track, kind="TRADE")
        assert len(trades["links"]) == 1
        trade = trades["links"][0]
        latest = (await service.training.notes(run, track))["context"]
        combined = await service.training.save_note(run, track, note_id="plan",
            fields={**fields, "replayTradeIds": json.dumps([trade["id"]])}, expected_revision=2, context=latest)
        assert combined["links"] == [fill, trade]
        assert await service.training.save_note(run, track, note_id="plan", fields=fields, expected_revision=1, context=current) == linked
        versions = await service.training.note_versions(run, track, "plan")
        assert [version["links"] for version in versions["versions"]] == [[fill, trade], [fill], []]
        other_run, _, other_track = await create(service)
        assert (await service.training.note_link_options(other_run, other_track, kind="FILL"))["links"] == []
        other_context = (await service.training.notes(other_run, other_track))["context"]
        with pytest.raises(TrainingRunError):
            await service.training.save_note(other_run, other_track, note_id="wrong-run", fields=fields, expected_revision=0, context=other_context)
        assert (await service.training.notes(other_run, other_track))["notes"] == []
        await service.shutdown(step_timeout=1)
        service = await _service(tmp_path / "linked-notes.db")
        assert (await service.training.notes(run, track))["notes"] == [combined]
        assert (await service.training.note_versions(run, track, "plan"))["versions"] == versions["versions"]
        timeline = await service.training.start_review(run, event_id=None)
        await service.training.start_review(run, event_id=timeline["events"][0]["event_id"])
        history = await service.training.notes(run, track)
        assert history["asOfMs"] == current["virtualTimeMs"]
        assert history["notes"] == [original]
        assert (await service.training.note_link_options(run, track, kind="FILL"))["links"] == []
        assert (await service.training.note_link_options(run, track, kind="TRADE"))["links"] == []
        with pytest.raises(TrainingRunError):
            await service.training.save_note(run, track, note_id="future-ref", fields=fields,
                expected_revision=0, context=history["context"])
    finally:
        await service.shutdown(step_timeout=1)


async def test_link_options_page_and_selection_limits_are_bounded(tmp_path):
    service = await _service(tmp_path / "links-pages.db")
    try:
        run, session, track = await create(service)
        await _acquire(service, run_id=run, selected_session_id=session, command_id="page-owner")
        for index in range(25):
            await buy(service, run, session, f"page-buy-{index}")
        first = await service.training.note_link_options(run, track, kind="FILL")
        assert len(first["links"]) == 20 and first["nextBeforeId"] == first["links"][-1]["id"]
        second = await service.training.note_link_options(run, track, kind="FILL", before_id=first["nextBeforeId"])
        assert len(second["links"]) == 5 and second["nextBeforeId"] is None
        assert len({link["id"] for link in first["links"] + second["links"]}) == 25
        context = (await service.training.notes(run, track))["context"]
        for selected in [[first["links"][0]["id"]] * 2, [link["id"] for link in first["links"][:9]], [True], {"bad": "shape"}]:
            with pytest.raises(TrainingRunError):
                await service.training.save_note(run, track, note_id="invalid", fields={"replayFillIds": json.dumps(selected)},
                    expected_revision=0, context=context)
        for query in [{"kind": "ORDERS"}, {"kind": "FILL", "limit": 21}, {"kind": "FILL", "before_id": ""}]:
            with pytest.raises(TrainingRunError):
                await service.training.note_link_options(run, track, **query)
        assert (await service.training.notes(run, track))["notes"] == []
    finally:
        await service.shutdown(step_timeout=1)


async def test_schema_27_backfills_empty_links_without_changing_text_or_financial_rows(tmp_path):
    path = tmp_path / "upgrade27.db"
    service = await _service(path)
    run, _, track = await create(service)
    context = (await service.training.notes(run, track))["context"]
    await service.training.save_note(run, track, note_id="old-plan", fields={"entryBasis": "old text"}, expected_revision=0, context=context)
    await service.shutdown(step_timeout=1)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE replay_training_note_capture_link")
        db.execute("DROP TABLE replay_training_note_capture")
        db.execute("DROP TABLE replay_training_note_links")
        db.execute("UPDATE replay_training_schema_version SET version=27")
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'replay_training_schema_version'")]
        before = {name: db.execute('SELECT * FROM "' + name + '"').fetchall() for name in names}
        migrate_training_schema(db, now_ms=12345)
        assert {name: db.execute('SELECT * FROM "' + name + '"').fetchall() for name in names} == before
        assert db.execute("SELECT links_json,stored_bytes FROM replay_training_note_links").fetchall() == [("[]", 2)]
        assert db.execute("SELECT version FROM replay_training_schema_version").fetchone() == (TRAINING_SCHEMA_VERSION,)
    recovered = await _service(path)
    try:
        note = (await recovered.training.notes(run, track))["notes"][0]
        assert note["fields"]["entryBasis"] == "old text" and note["links"] == []
        await recovered.store.run_extension_write(lambda db: db.execute("DELETE FROM replay_training_note_links"))
        with pytest.raises(TrainingRunError) as missing:
            await recovered.training.notes(run, track)
        assert missing.value.status_code == 503
    finally:
        await recovered.shutdown(step_timeout=1)


async def test_same_fill_identifier_is_scoped_to_its_own_full_market_track(tmp_path):
    from tests.test_replay_v2_training_phase5 import _add_track
    service = await _service(tmp_path / "two-track-links.db")
    try:
        run, session, btc = await create(service)
        await _acquire(service, run_id=run, selected_session_id=session, command_id="two-track-owner")
        await _add_track(service, run_id=run, selected_session_id=session, symbol="ETHUSDT", tier="FULL", command_id="links-eth")
        await buy(service, run, session, "btc-buy")
        tracks = await service.training.get_market_tracks(run)
        eth = next(track for track in tracks["tracks"] if track["symbol"] == "ETHUSDT")
        await command(service, run, session, "select-link-eth", ReplayV2CommandType.SELECT_TRACK,
            {"track_id": eth["track_id"], "expected_viewer_revision": tracks["viewer_state"]["semantic_view_revision"]})
        await _acquire(service, run_id=run, selected_session_id=eth["adapter_session_id"], command_id="eth-owner")
        await buy(service, run, eth["adapter_session_id"], "eth-buy")
        first = (await service.training.note_link_options(run, btc, kind="FILL"))["links"][0]
        second = (await service.training.note_link_options(run, eth["track_id"], kind="FILL"))["links"][0]
        assert first["id"] == second["id"] and first["price"] != second["price"]
        snapshots = [(await service.get_session(identifier))["snapshot"] for identifier in [session, eth["adapter_session_id"]]]
        for track, link in [(btc, first), (eth["track_id"], second)]:
            context = (await service.training.notes(run, track))["context"]
            saved = await service.training.save_note(run, track, note_id="plan-" + track,
                fields={"replayFillIds": json.dumps([link["id"]])}, expected_revision=0, context=context)
            assert saved["links"] == [link]
        assert [(await service.get_session(identifier))["snapshot"] for identifier in [session, eth["adapter_session_id"]]] == snapshots
    finally:
        await service.shutdown(step_timeout=1)
