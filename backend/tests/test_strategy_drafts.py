"""ADR-BACKTEST-015 P3a: strategy drafts stored in the backend."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.backtest.strategy_drafts import MAX_DRAFTS, SCHEMA
from app.core.config import load_backtest_settings
from app.data_engine.data_manager.strategy import StrategyDataManager


def _settings(tmp_path):
    return load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"}, data_dir=tmp_path,
                                  klines_db_path=tmp_path / "market.db", replay_db_path=tmp_path / "replay.db")


@pytest.fixture
def service(tmp_path):
    value = BacktestService.start(_settings(tmp_path), now_ms=1)
    yield value
    value.shutdown()


def draft(draft_id="draft-abcdefgh", revision=0, source="//@version=6\nstrategy(\"A\")", **extra):
    return {"draft_id": draft_id, "revision": revision, "display_name": "Mine", "language": "pine",
            "source": source, "cursor": {"line": 1, "column": 1}, "created_at_ms": 10, "updated_at_ms": 20 + revision,
            **extra}


def test_drafts_are_compare_and_set_on_their_revision(service):
    drafts = StrategyDataManager(service).drafts()
    created = drafts.save("draft-abcdefgh", {"expected_revision": None, "draft": draft()})
    assert created == {"schema": SCHEMA, **draft(), "updated_at_ms": 20}
    updated = drafts.save("draft-abcdefgh", {"expected_revision": 0, "draft": draft(revision=1, source="v1")})
    assert (updated["revision"], updated["source"]) == (1, "v1")
    with pytest.raises(BacktestError) as stale:
        drafts.save("draft-abcdefgh", {"expected_revision": 0, "draft": draft(revision=1, source="other window")})
    assert stale.value.code == "DRAFT_REVISION_CONFLICT" and stale.value.details == {"current_revision": 1}
    with pytest.raises(BacktestError) as exists:
        drafts.save("draft-abcdefgh", {"expected_revision": None, "draft": draft(revision=5)})
    assert exists.value.code == "DRAFT_REVISION_CONFLICT"
    for body, code in (
        ({"expected_revision": 1, "draft": draft(revision=1)}, "DRAFT_INVALID"),  # must advance
        ({"expected_revision": 1, "draft": draft("draft-zzzzzzzz", revision=2)}, "DRAFT_INVALID"),  # another id
        ({"expected_revision": 1, "draft": draft(revision=2, language="pyne")}, "DRAFT_INVALID"),
        ({"expected_revision": 1, "draft": draft(revision=2, source="x" * (2 * 1024 * 1024 + 1))}, "DRAFT_INVALID"),
        ({"expected_revision": 1, "draft": draft(revision=2, cursor={"line": 0, "column": 1})}, "DRAFT_INVALID"),
        ({"draft": draft(revision=2)}, "DRAFT_INVALID"),
    ):
        with pytest.raises(BacktestError) as failure:
            drafts.save("draft-abcdefgh", body)
        assert failure.value.code == code
    assert drafts.get("draft-abcdefgh")["source"] == "v1"
    assert drafts.remove("draft-abcdefgh") == {"draft_id": "draft-abcdefgh", "removed": True}
    with pytest.raises(BacktestError) as gone:
        drafts.get("draft-abcdefgh")
    assert gone.value.code == "DRAFT_NOT_FOUND"
    with pytest.raises(BacktestError) as bad_id:
        drafts.get("../etc")
    assert bad_id.value.code == "DRAFT_NOT_FOUND"


def test_drafts_survive_a_full_restart(tmp_path):
    """The P3 gate: quit and restart, and the drafts are still there."""
    first = BacktestService.start(_settings(tmp_path), now_ms=1)
    try:
        drafts = StrategyDataManager(first).drafts()
        drafts.save("draft-abcdefgh", {"expected_revision": None, "draft": draft()})
        drafts.save("draft-abcdefgh", {"expected_revision": 0, "draft": draft(revision=1, source="kept")})
        drafts.save("draft-python01", {"expected_revision": None, "draft": draft(
            "draft-python01", language="python", source="def on_bar(ctx): pass", cursor=None)})
    finally:
        first.shutdown()
    second = BacktestService.start(_settings(tmp_path), now_ms=2)
    try:
        listed = StrategyDataManager(second).drafts().list()["drafts"]
        assert [(item["draft_id"], item["revision"], item["source"]) for item in listed] == [
            ("draft-abcdefgh", 1, "kept"), ("draft-python01", 0, "def on_bar(ctx): pass")]
        assert listed[1]["cursor"] is None
    finally:
        second.shutdown()


def test_importing_browser_drafts_keeps_the_newer_copy_and_is_idempotent(service):
    drafts = StrategyDataManager(service).drafts()
    drafts.save("draft-stored01", {"expected_revision": None, "draft": draft("draft-stored01", revision=4, source="backend")})
    drafts.save("draft-stored02", {"expected_revision": None, "draft": draft("draft-stored02", revision=1, source="old")})
    incoming = [draft("draft-stored01", revision=2, source="older browser copy"),
                draft("draft-stored02", revision=3, source="newer browser copy"),
                draft("draft-brandnew", revision=7, source="only in the browser")]
    assert drafts.import_drafts({"drafts": incoming}) == {
        "imported": ["draft-stored02", "draft-brandnew"], "kept": ["draft-stored01"]}
    assert drafts.import_drafts({"drafts": incoming}) == {
        "imported": [], "kept": ["draft-stored01", "draft-stored02", "draft-brandnew"]}
    assert drafts.get("draft-stored01")["source"] == "backend"
    assert (drafts.get("draft-stored02")["source"], drafts.get("draft-brandnew")["revision"]) == ("newer browser copy", 7)
    with pytest.raises(BacktestError) as twice:
        drafts.import_drafts({"drafts": [draft("draft-twice001"), draft("draft-twice001")]})
    assert twice.value.code == "DRAFT_INVALID"
    with pytest.raises(BacktestError) as broken:
        drafts.import_drafts({"drafts": [draft("draft-goodone1"), draft("draft-badlang1", language="pyne")]})
    assert broken.value.code == "DRAFT_INVALID"
    with pytest.raises(BacktestError):
        drafts.get("draft-goodone1")  # an invalid import changes nothing


def test_the_draft_count_is_bounded(service, monkeypatch):
    import app.backtest.strategy_drafts as module
    monkeypatch.setattr(module, "MAX_DRAFTS", 2)
    drafts = StrategyDataManager(service).drafts()
    drafts.save("draft-first001", {"expected_revision": None, "draft": draft("draft-first001")})
    assert drafts.import_drafts({"drafts": [draft("draft-second01")]})["imported"] == ["draft-second01"]
    with pytest.raises(BacktestError) as full:
        drafts.save("draft-third001", {"expected_revision": None, "draft": draft("draft-third001")})
    assert full.value.code == "DRAFT_CAPACITY_EXCEEDED"
    with pytest.raises(BacktestError) as full_import:
        drafts.import_drafts({"drafts": [draft("draft-third001")]})
    assert full_import.value.code == "DRAFT_CAPACITY_EXCEEDED"
    # Existing drafts still save at capacity.
    assert drafts.save("draft-first001", {"expected_revision": 0, "draft": draft("draft-first001", revision=1)})["revision"] == 1
    assert MAX_DRAFTS == 500


def test_the_draft_routes(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.strategy_drafts import router

    app = FastAPI()
    app.state.data_manager_core = SimpleNamespace(strategy=StrategyDataManager(service))
    app.include_router(router)
    with TestClient(app) as client:
        created = client.put("/strategy-drafts/draft-abcdefgh", json={"expected_revision": None, "draft": draft()})
        conflict = client.put("/strategy-drafts/draft-abcdefgh", json={"expected_revision": None, "draft": draft()})
        imported = client.post("/strategy-drafts/import", json={"drafts": [draft("draft-imported", revision=3)]})
        listed = client.get("/strategy-drafts?limit=10")
        fetched = client.get("/strategy-drafts/draft-imported")
        missing = client.get("/strategy-drafts/draft-missing01")
        invalid = client.put("/strategy-drafts/draft-abcdefgh", content=b"not json")
        too_large = client.put("/strategy-drafts/draft-abcdefgh", content=b"x" * (3 * 1024 * 1024 + 1))
        removed = client.delete("/strategy-drafts/draft-abcdefgh")
    assert created.status_code == 200 and created.json()["revision"] == 0
    assert conflict.status_code == 409 and conflict.json()["error"]["details"] == {"current_revision": 0}
    assert imported.json() == {"imported": ["draft-imported"], "kept": []}
    assert [item["draft_id"] for item in listed.json()["drafts"]] == ["draft-imported", "draft-abcdefgh"]
    assert fetched.json()["revision"] == 3 and missing.status_code == 404
    assert invalid.status_code == 400 and too_large.status_code == 413
    assert removed.json() == {"draft_id": "draft-abcdefgh", "removed": True}
