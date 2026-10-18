"""User annotations must not freeze an unpublished global account phase."""

import asyncio

import pytest
from app.replay.canonical import canonical_sha256

from tests.test_replay_v2_training_hedge_phase5 import _create_bankrupt_hedge_run, _trigger_crash
from tests.test_replay_v2_training_phase6 import _risk_service

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("annotation", ["marker", "drawing"])
async def test_review_marker_waits_for_published_liquidation_boundary(tmp_path, monkeypatch, annotation):
    service = await _risk_service(tmp_path / "review-boundary.db")
    release = asyncio.Event()
    advance = marker = None
    try:
        run, sid = await _create_bankrupt_hedge_run(service, root=tmp_path, prefix="boundary")
        entered = asyncio.Event()
        original = service.training.store.commit_liquidation_execution

        async def hold_before_commit(**kwargs):
            entered.set()
            await release.wait()
            return await original(**kwargs)

        monkeypatch.setattr(service.training.store, "commit_liquidation_execution", hold_before_commit)
        advance = asyncio.create_task(_trigger_crash(service, run_id=run, session_id=sid, prefix="boundary"))
        await asyncio.wait_for(entered.wait(), 5)
        document = {"documentSchemaVersion": 1, "scopeKey": f"replay-run:{run}",
                    "documentRevision": 1, "updatedAt": 123456, "entities": []}
        request = service.training.record_review_marker(
            run, command_id="while-risk-executes", text="After the complete account command") if annotation == "marker" else service.training.record_drawing_document(
            run, command_id="while-risk-executes", document_hash=canonical_sha256(document),
            document=document, entity_count=0)
        marker = asyncio.create_task(request)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(marker), 0.05)
        release.set()
        await advance
        recorded = await marker
        review = await service.training.start_review(run, event_id=recorded.get("event_id"))
        portfolio = (await service.training.get_market_tracks(run))["portfolio"]
        assert review["projection"]["domain"]["portfolio"]["equity"] == portfolio["equity"]
        assert review["projection"]["domain"]["portfolio"]["positions"] == []
        if annotation == "drawing":
            assert review["drawing_document"] == document
        fork = await service.training.fork_run(run, event_id=review["selected_event_id"])
        assert (await service.training.audit_account(fork["run"]["run_id"]))["status"] == "PASS"
    finally:
        release.set()
        await asyncio.gather(*(task for task in (advance, marker) if task is not None), return_exceptions=True)
        await service.shutdown(step_timeout=1.0)
