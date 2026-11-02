import asyncio
import concurrent.futures

import httpx
import pytest
from app.data_engine.data_manager.core import DataManagerCore
from app.history_studies.repository import HistoryStudyRepository, StudyConflict
from fastapi import FastAPI

SERIES = {"exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "1m",
          "providerId": "binance", "venue": "binance", "assetClass": "crypto", "seriesVariant": "native",
          "priceAdjustment": "raw", "sessionVariant": "continuous", "volumeSemantics": "base_asset"}
ROWS = [{"time": 60 * i, "open": 10., "high": 12., "low": 9., "close": 11., "volume": float(i)} for i in range(1, 6)]
ID = "hs_" + "a" * 32
NOTE = "je_" + "b" * 20


def capture(repo, owner="workspace:cell-1", study_id=ID, **kwargs):
    return repo.capture(owner, study_id, SERIES, ROWS, cursor_ms=180_000, expected_revision=0, **kwargs)


def test_frozen_input_independent_views_cursors_restart_and_uncertain_capture_retry(tmp_path):
    path = tmp_path / "study.sqlite3"
    repo = HistoryStudyRepository(path, clock=lambda: 1_000_000)
    assert not path.exists()
    one = capture(repo)
    two = capture(repo, "workspace:cell-2", "hs_" + "c" * 32)
    assert one["study"]["rows"][-1]["closeTimeMs"] == 360_000
    one["study"]["rows"][-1]["close"] = 999
    cursor = repo.move("workspace:cell-1", ID, expected_revision=1, cursor_ms=120_000, active=True)
    assert cursor == {"studyId": ID, "revision": 2, "cursorMs": 120_000, "active": True}
    assert len(str(cursor)) < 200  # per-step response is independent of history size
    moved = repo.view("workspace:cell-1")
    assert moved["study"]["rows"][-1]["close"] == 11.
    assert repo.view("workspace:cell-2") == two
    assert capture(repo) == moved  # response retry cannot advance a cursor again
    assert HistoryStudyRepository(path).view("workspace:cell-1") == moved
    with pytest.raises(StudyConflict):
        repo.move("workspace:cell-2", ID, expected_revision=1, cursor_ms=120_000, active=True)
    with pytest.raises(ValueError):
        repo.move("workspace:cell-1", ID, expected_revision=2, cursor_ms=360_001, active=True)
    assert repo.view("workspace:cell-1") == moved


def test_two_repository_writers_cannot_silently_overwrite_each_other(tmp_path):
    path = tmp_path / "study.sqlite3"
    first, second = HistoryStudyRepository(path), HistoryStudyRepository(path)
    capture(first)
    def move(repo, target):
        try:
            return repo.move("workspace:cell-1", ID, expected_revision=1, cursor_ms=target, active=True)
        except StudyConflict:
            return "conflict"
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(move, first, 120_000), pool.submit(move, second, 240_000)]
        results = [future.result() for future in futures]
    assert results.count("conflict") == 1
    assert first.view("workspace:cell-1")["revision"] == 2


def test_saved_studies_keep_annotations_and_cursors_and_deletion_never_resets_revision(tmp_path):
    repo = HistoryStudyRepository(tmp_path / "study.sqlite3")
    capture(repo)
    repo.save_note(ID, NOTE, {"entryBasis": "keep with saved input"}, market_ms=180_000, expected_revision=0)
    repo.move("workspace:cell-1", ID, expected_revision=1, cursor_ms=120_000, active=False)
    second_id = "hs_" + "d" * 32
    repo.capture("workspace:cell-1", second_id, SERIES, ROWS, cursor_ms=240_000, expected_revision=2)
    assert len(repo.saved("workspace:cell-1")) == 2
    assert repo.saved("other:cell-1") == []
    restored = repo.activate("workspace:cell-1", ID, expected_revision=3)
    assert restored["cursorMs"] == 120_000 and restored["active"]
    assert repo.notes(ID, 180_000)[0]["fields"]["entryBasis"] == "keep with saved input"
    deleted = repo.remove("workspace:cell-1", ID, expected_revision=4)
    assert deleted == {"revision": 5, "active": False, "cursorMs": None, "study": None}
    with pytest.raises(StudyConflict):
        capture(repo)  # a stale first-open revision cannot exploit an ABA reset
    assert len(repo.saved("workspace:cell-1")) == 1
    with pytest.raises(ValueError):
        repo.activate("other:cell-1", second_id, expected_revision=0)


def test_annotations_are_explicit_supplements_have_versions_and_do_not_move_view(tmp_path):
    path = tmp_path / "study.sqlite3"
    times = iter([1_000_000, 1_000_001, 1_000_002, 1_000_003, 1_000_004])
    repo = HistoryStudyRepository(path, clock=lambda: next(times))
    before = capture(repo)
    note = repo.save_note(ID, NOTE, {"entryBasis": "first"}, market_ms=180_000, expected_revision=0)
    assert note["reviewNote"] is True and note["createdAtMs"] > note["marketTimeMs"]
    assert repo.notes(ID, 120_000) == []
    assert repo.notes(ID, 180_000) == [note]
    changed = repo.save_note(ID, NOTE, {"entryBasis": "second"}, market_ms=180_000, expected_revision=1)
    assert changed["revisions"] == []  # cursor-driven lists never repeat old bodies
    history = repo.note_history(ID, NOTE)
    assert [row["fields"]["entryBasis"] for row in history["items"]] == ["first", "second"]
    assert repo.note_history(ID, NOTE, limit=1)["nextBeforeRevision"] == 2
    assert repo.note_history(ID, NOTE, before_revision=2, limit=1)["items"][0]["revision"] == 1
    assert repo.save_note(ID, NOTE, {"entryBasis": "first"}, market_ms=180_000, expected_revision=0) == changed
    with pytest.raises(StudyConflict):
        repo.save_note(ID, NOTE, {"entryBasis": "stale"}, market_ms=180_000, expected_revision=1)
    with pytest.raises(StudyConflict):
        repo.save_note(ID, NOTE, {"entryBasis": "rewrite time"}, market_ms=120_000, expected_revision=2)
    assert repo.view("workspace:cell-1") == before
    assert HistoryStudyRepository(path).notes(ID, 180_000) == [changed]
    with pytest.raises(ValueError):
        repo.note_history("another-study", NOTE)


@pytest.mark.parametrize("rows", [list(reversed(ROWS)), [ROWS[0], ROWS[0]],
    [{**ROWS[0], "high": 8.}], [{**ROWS[0], "volume": -1.}], [{**ROWS[0], "time": 61}]])
def test_bad_input_does_not_create_a_study(tmp_path, rows):
    repo = HistoryStudyRepository(tmp_path / "study.sqlite3", clock=lambda: 1_000_000)
    with pytest.raises(ValueError):
        repo.capture("a", ID, SERIES, rows, cursor_ms=60_000, expected_revision=0)
    assert repo.view("a")["study"] is None


def test_api_is_local_bounded_and_routes_through_common_manager(tmp_path, monkeypatch):
    from app.history_studies import api
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.state.data_manager_core = DataManagerCore()
    app.include_router(api.router)
    async def run():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 5000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            body = {"id": ID, "series": SERIES, "rows": ROWS, "cursorMs": 180_000, "expectedRevision": 0}
            denied = await client.post("/history-studies/views/a", json=body, headers={"Origin": "https://evil.example"})
            assert denied.status_code == 403
            assert not (tmp_path / "history-studies.sqlite3").exists()
            assert (await client.post("/history-studies/views/a", json=body)).status_code == 200
            assert app.state.data_manager_core._history_studies.path == tmp_path / "history-studies.sqlite3"
            assert (await client.post("/history-studies/views/b", json={**body, "rows": [{**ROWS[0], "volume": "1"}]})).status_code == 422
            assert (await client.post("/history-studies/views/b", content=b" " * 2_000_001)).status_code == 413
            assert (await client.patch("/history-studies/views/a", json={"studyId": ID,
                "cursorMs": 240_000, "expectedRevision": 1, "active": True})).status_code == 200
            assert (await client.patch("/history-studies/views/a", json={"studyId": ID,
                "cursorMs": 120_000, "expectedRevision": 1, "active": True})).status_code == 409
            fine = await client.post("/history-studies/views/fine", json={**body,
                "id": "hs_" + "f" * 32, "series": {**SERIES, "interval": "5m"}, "sourceSeries": SERIES})
            assert fine.status_code == 200
            assert fine.json()["study"]["rows"][0]["closeTimeMs"] == 120_000
            assert fine.json()["study"]["sourceSeries"]["interval"] == "1m"
    asyncio.run(run())


def test_finer_capture_keeps_source_and_display_semantics_and_restores_without_reloading(tmp_path):
    path = tmp_path / "fine.sqlite3"
    repo = HistoryStudyRepository(path, clock=lambda: 1_000_000)
    display = {**SERIES, "interval": "5m"}
    result = repo.capture("fine", ID, display, ROWS, source_series=SERIES,
                          cursor_ms=180_000, expected_revision=0)
    assert result["study"]["series"]["interval"] == "5m"
    assert result["study"]["sourceSeries"] == SERIES
    assert result["study"]["rows"][0]["closeTimeMs"] == 120_000
    moved = repo.move("fine", ID, cursor_ms=210_000, expected_revision=1, active=True)
    assert "rows" not in moved and len(str(moved)) < 200
    assert HistoryStudyRepository(path).view("fine")["study"] == result["study"]
    assert repo.saved("fine")[0]["series"] == display
    assert repo.capture("fine", ID, display, ROWS, source_series=SERIES,
                        cursor_ms=180_000, expected_revision=0)["cursorMs"] == 210_000


@pytest.mark.parametrize("source", [{**SERIES, "symbol": "ETHUSDT"},
    {**SERIES, "volumeSemantics": "quote_asset"}, {**SERIES, "interval": "3m"}])
def test_incompatible_finer_series_never_creates_a_saved_study(tmp_path, source):
    repo = HistoryStudyRepository(tmp_path / "fine.sqlite3", clock=lambda: 1_000_000)
    with pytest.raises(ValueError):
        repo.capture("fine", ID, {**SERIES, "interval": "5m"}, ROWS,
                     source_series=source, cursor_ms=180_000, expected_revision=0)
    assert repo.view("fine")["study"] is None
