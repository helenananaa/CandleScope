from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.replay import router
from app.data_engine.storage import raw_trade_archive
from app.data_engine.storage.raw_trade_archive import (
    ParquetRawAggTradeArchive,
    VerifiedRawAggTradeBarWindow,
)
from app.replay.bars.trade_parity import trade_bar_parity_policy
from app.replay.constants import (
    REPLAY_PROTOCOL,
    CommandType,
    SessionState,
    StartPolicy,
)
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.models import ReplayCommand
from app.replay.official_trade_catalog import OfficialAggTradeArchive
from app.replay.service import ReplayService, SYNTHETIC_TIME_ANCHOR_MS
from app.replay.storage import ReplaySQLiteStore
from app.replay.trade_compatibility import build_trade_bar_compatibility
from app.replay.trade_import import trade_archive_day_acquisition
from tests.fixtures.replay.fakes import FixtureIdentity
from tests.fixtures.replay.service_fakes import SessionIdFactory, replay_settings
from tests.fixtures.replay.trade_service_fakes import (
    DAY_START_MS,
    TRADE_NOW_MS,
    TRADE_REPLAY_START_MS,
    trade_replay_config,
    trade_replay_repository,
    verified_trade_archive,
)


pytestmark = pytest.mark.anyio


def _command(
    command_id: str,
    command_type: CommandType,
    revision: int,
    payload: dict[str, object] | None = None,
) -> ReplayCommand:
    return ReplayCommand(
        protocol=REPLAY_PROTOCOL,
        command_id=command_id,
        client_instance_id="trade-browser",
        expected_revision=revision,
        type=command_type,
        payload=payload or {},
    )


async def _service(
    database: Path,
    archive,
    *,
    prefix: str,
    repository=None,
) -> ReplayService:
    service = ReplayService(
        settings=replay_settings(database),
        store=ReplaySQLiteStore(database, now_ms=lambda: TRADE_NOW_MS),
        repository=repository or trade_replay_repository(),
        raw_trade_archive=archive,
        now_ms=lambda: TRADE_NOW_MS,
        session_id_factory=SessionIdFactory(prefix),
        native_intervals=lambda _identity: ("1m",),
    )
    await service.start()
    return service


async def test_raw_trade_retention_preview_reports_live_and_saved_protection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "archive"
    verified_trade_archive(archive_root)
    archive = OfficialAggTradeArchive(archive_root, defer_refresh=True)
    service = await _service(tmp_path / "replay.db", archive, prefix="retention-preview")
    app = FastAPI()
    app.state.replay_service = service
    app.include_router(router, prefix="/api/v1")
    uri = "/api/v1/replay/runs/storage/raw-trades/preview"
    originals = {
        p: p.read_bytes() for p in archive_root.rglob("*")
        if p.is_file() and (p.name == "_verified_import.json" or "part-verified-" in p.name)
    }
    hash_file = raw_trade_archive._file_sha256

    def metadata_hash(path: Path):
        assert path.suffix != ".parquet", "preview opened a trade body"
        return hash_file(path)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            assert (await client.get(uri, params={"limit": 201})).status_code == 422

            async def inspect():
                with monkeypatch.context() as patch:
                    patch.setattr(raw_trade_archive, "_file_sha256", metadata_hash)
                    response = await client.get(uri, params={"limit": 1})
                assert response.status_code == 200
                payload = response.json()
                assert payload["estimated_reclaim_bytes"] == 0
                assert payload["policy_state"] == "UNMANAGED"
                assert payload["observed_bytes"] == sum(map(len, originals.values()))
                assert not payload["truncated"]
                assert "partition_key" not in response.text
                assert str(archive_root) not in response.text
                assert "2026-06-01" not in response.text
                return payload, payload["items"][0]

            _, item = await inspect()
            assert item["protection_reasons"] == ["UNMANAGED_RETENTION_POLICY"]
            assert item["saved_reference_count"] == item["active_pin_count"] == 0
            config = trade_replay_config()
            created = await service.create_session(config)
            with trade_archive_day_acquisition(
                archive.cache, exchange=config.exchange, market_type=config.market_type,
                symbol=config.symbol, day=date(2026, 6, 1),
            ) as missing:
                assert not missing
                _, protected = await inspect()
            assert protected["day_id"] == item["day_id"]
            assert protected["active_pin_count"] == protected["saved_reference_count"] == 1
            assert protected["retention_lease_busy"] is True
            assert set(protected["protection_reasons"]) == {
                "UNMANAGED_RETENTION_POLICY", "SAVED_REPLAY_REFERENCE",
                "ACTIVE_DATASET_PIN", "DAY_ACQUISITION_IN_PROGRESS", "PARTITION_RETENTION_LEASE",
            }
            await service.release_session_to_hub(str(created["session_id"]))
            _, saved = await inspect()
            assert saved["active_pin_count"] == 0
            assert saved["retention_lease_busy"] is False
            assert saved["saved_reference_count"] == 1
            assert saved["protection_reasons"] == ["UNMANAGED_RETENTION_POLICY", "SAVED_REPLAY_REFERENCE"]

            def break_reference(connection):
                connection.execute("UPDATE replay_dataset_ref SET snapshot_ref_json='invalid'")

            await service.store.run_extension_write(break_reference)
            payload, incomplete = await inspect()
            assert not payload["saved_reference_scan_complete"]
            assert "SAVED_REFERENCE_SCAN_INCOMPLETE" in incomplete["protection_reasons"]
            await service.store.run_extension_write(
                lambda connection: connection.execute("DELETE FROM replay_dataset_ref"),
            )
            payload, _ = await inspect()
            assert not payload["saved_reference_scan_complete"]
            assert all(p.read_bytes() == body for p, body in originals.items())
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_retention_preview_reads_saved_refs_across_profiles(tmp_path):
    archive_root = tmp_path / "shared"
    verified_trade_archive(archive_root)
    first_db = tmp_path / "profile-first" / "replay.db"
    second_db = tmp_path / "profile-second" / "replay.db"

    def archive():
        return OfficialAggTradeArchive(archive_root, defer_refresh=True)

    first = await _service(first_db, archive(), prefix="first")
    second = await _service(second_db, archive(), prefix="second")

    async def inspect():
        report = await second.training.raw_trade_retention_preview(limit=1)
        assert report["estimated_reclaim_bytes"] == 0
        assert str(first_db) not in json.dumps(report)
        assert str(second_db) not in json.dumps(report)
        return report, report["items"][0]

    try:
        created = await first.create_session(trade_replay_config())
        session = str(created["session_id"])
        live, item = await inspect()
        assert live["saved_reference_store_count"] == 2
        assert live["saved_reference_scan_complete"]
        assert item["saved_reference_count"] == 1
        assert item["active_pin_count"] == 0 and item["retention_lease_busy"]

        await first.release_session_to_hub(session)
        await first.shutdown(step_timeout=1.0)
        dormant, item = await inspect()
        assert dormant["saved_reference_scan_complete"]
        assert item["saved_reference_count"] == 1 and not item["retention_lease_busy"]

        parked = first_db.with_suffix(".parked")
        first_db.rename(parked)
        try:
            missing, item = await inspect()
            assert not missing["saved_reference_scan_complete"]
            assert missing["unavailable_reference_store_count"] == 1
            assert "SAVED_REFERENCE_SCAN_INCOMPLETE" in item["protection_reasons"]

            replacement = ReplaySQLiteStore(first_db)
            try:
                replaced, _ = await inspect()
                assert not replaced["saved_reference_scan_complete"]
                assert replaced["unavailable_reference_store_count"] == 1
            finally:
                await replacement.close()
        finally:
            parked.replace(first_db)

        # Emulate a pre-registration database which already has a saved replay.
        registry = archive_root / ".replay-reference-stores"
        for entry in registry.glob("*.json"):
            if json.loads(entry.read_text())["database"] == str(first_db):
                entry.unlink()
                break
        legacy = sqlite3.connect(first_db)
        try:
            legacy.execute("DROP TABLE replay_trade_reference_store")
        finally:
            legacy.close()
        first = await _service(first_db, archive(), prefix="reopened")
        enrolled, item = await inspect()
        assert enrolled["saved_reference_scan_complete"]
        assert item["saved_reference_count"] == 1
        await first.discard_session(session)
        after_delete, item = await inspect()
        assert after_delete["saved_reference_scan_complete"]
        assert after_delete["saved_reference_store_count"] == 2
        assert item["saved_reference_count"] == 0
        assert not item["retention_lease_busy"]
        assert len(list(registry.glob("*.json"))) == 2
    finally:
        await first.shutdown(step_timeout=1.0)
        await second.shutdown(step_timeout=1.0)


async def test_retention_rechecks_stale_preview_against_other_profile(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    verified_trade_archive(root)
    receipt, = root.rglob("_verified_import.json")
    originals = {path: path.read_bytes() for path in receipt.parent.iterdir() if path.is_file()}
    first_db = tmp_path / "first" / "replay.db"
    first = await _service(first_db, OfficialAggTradeArchive(root, defer_refresh=True), prefix="first")
    second = await _service(
        tmp_path / "second" / "replay.db",
        OfficialAggTradeArchive(root, defer_refresh=True),
        prefix="second",
    )
    app = FastAPI()
    app.state.replay_service = second
    app.include_router(router, prefix="/api/v1")
    uri = "/api/v1/replay/runs/storage/raw-trades/recheck"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            preview = await second.training.raw_trade_retention_preview(limit=1)
            candidate, = preview["items"]
            assert candidate["saved_reference_count"] == 0
            day_id = candidate["day_id"]

            async def inspect():
                response = await client.get(uri, params={"day_id": day_id, "limit": 1})
                assert response.status_code == 200
                assert str(tmp_path) not in response.text
                report = response.json()
                assert report["estimated_reclaim_bytes"] == 0
                return report

            assert (await client.get(uri, params={"day_id": "not-a-receipt"})).status_code == 422
            baseline = await inspect()
            assert baseline["status"] == "RECHECKED"
            assert baseline["saved_reference_scan_complete"]
            assert baseline["item"]["protection_reasons"] == ["UNMANAGED_RETENTION_POLICY"]

            config = trade_replay_config()
            with trade_archive_day_acquisition(
                second.raw_trade_archive.cache, exchange=config.exchange, market_type=config.market_type,
                symbol=config.symbol, day=date(2026, 6, 1),
            ):
                assert (await inspect())["status"] == "DAY_ACQUISITION_IN_PROGRESS"

            created = await first.create_session(config)
            blocked = await inspect()
            assert blocked["status"] == "PARTITION_RETENTION_LEASE"
            assert blocked["item"] is None
            await first.release_session_to_hub(str(created["session_id"]))
            await first.shutdown(step_timeout=1.0)

            saved = await inspect()
            assert saved["status"] == "RECHECKED"
            assert saved["saved_reference_scan_complete"]
            assert saved["saved_reference_store_count"] == 2
            assert saved["item"]["saved_reference_count"] == 1
            assert saved["item"]["active_pin_count"] == 0
            assert "SAVED_REPLAY_REFERENCE" in saved["item"]["protection_reasons"]

            parked = first_db.with_suffix(".parked")
            first_db.rename(parked)
            try:
                unavailable = await inspect()
                assert not unavailable["saved_reference_scan_complete"]
                assert unavailable["unavailable_reference_store_count"] == 1
                assert "SAVED_REFERENCE_SCAN_INCOMPLETE" in unavailable["item"]["protection_reasons"]
            finally:
                parked.replace(first_db)

            assert all(path.read_bytes() == body for path, body in originals.items())
            try:
                receipt.write_bytes(originals[receipt] + b"\n")
                stale = await inspect()
                assert stale["status"] == "STALE_OR_OUTSIDE_SCAN"
                assert stale["item"] is None
            finally:
                receipt.write_bytes(originals[receipt])
    finally:
        await first.shutdown(step_timeout=1.0)
        await second.shutdown(step_timeout=1.0)


async def test_reclaim_revalidates_saved_references_for_each_batch(tmp_path: Path, monkeypatch) -> None:
    from contextlib import nullcontext

    from app.replay.training import raw_trade_retention

    root = tmp_path / "archive"
    archive = verified_trade_archive(root)
    first_db = tmp_path / "first" / "replay.db"
    first = await _service(first_db, OfficialAggTradeArchive(root, defer_refresh=True), prefix="first")
    second = await _service(
        tmp_path / "second" / "replay.db",
        OfficialAggTradeArchive(root, defer_refresh=True),
        prefix="second",
    )
    try:
        report = await second.training.raw_trade_retention_preview(limit=1)
        candidate, = report["items"]
        assert candidate["saved_reference_count"] == 0
        created = await first.create_session(trade_replay_config())
        session_id = str(created["session_id"])
        await first.release_session_to_hub(session_id)
        operation = dict(identity=("binance", "futures", "BTCUSDT"),
                         day="2026-06-01", day_id=candidate["day_id"])

        def policy(_key, _receipt):
            return nullcontext(True)

        # Simulate an older operator moving a day after the preview. The
        # reclaim owner must independently reject the new saved reference.
        assert archive.move_verified_retention_day(**operation, authorize=policy, restore=False) == "RETIRED"
        retired, = root.glob("exchange=*/market_type=*/symbol=*/.retired-date=*")
        originals = {file.name: file.read_bytes() for file in retired.iterdir()}

        async def reclaim():
            return await raw_trade_retention.reclaim_retired_day(
                second.store, archive, **operation, max_files=1,
                max_bytes=sum(map(len, originals.values())), policy=policy,
            )

        assert (await reclaim()).status == "RETENTION_NOT_AUTHORIZED"
        await first.discard_session(session_id)
        await first.shutdown(step_timeout=1.0)
        parked = first_db.with_suffix(".parked")
        first_db.rename(parked)
        try:
            assert (await reclaim()).status == "RETENTION_NOT_AUTHORIZED"
        finally:
            parked.replace(first_db)
        assert {file.name: file.read_bytes() for file in retired.iterdir()} == originals

        original_unlink = Path.unlink

        def check_fence(file, *args, **kwargs):
            if file.parent == retired:
                with pytest.raises(BlockingIOError):
                    with raw_trade_retention._registry_lease(root / ".replay-reference-stores", shared=False):
                        pytest.fail("registry publication overlapped reclaim")
            return original_unlink(file, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", check_fence)
            result = await reclaim()
        assert result.status == "RECLAIM_PENDING" and result.removed_files == 1
        first_db.rename(parked)
        try:
            assert (await reclaim()).status == "RETENTION_NOT_AUTHORIZED"
        finally:
            parked.replace(first_db)
        assert len(tuple(retired.iterdir())) == len(originals)  # One file removed and one marker added.
    finally:
        await first.shutdown(step_timeout=1.0)
        await second.shutdown(step_timeout=1.0)


async def test_managed_retention_routes_fence_use_policy_expiry_and_references(tmp_path, monkeypatch):
    from app.replay.training import raw_trade_retention

    root = tmp_path / "archive"
    archive = verified_trade_archive(root)
    first_db = tmp_path / "first" / "replay.db"
    first = await _service(first_db, OfficialAggTradeArchive(root, defer_refresh=True), prefix="first")
    second_db = tmp_path / "second" / "replay.db"
    second = await _service(second_db, OfficialAggTradeArchive(root, defer_refresh=True), prefix="second")
    app = FastAPI()
    app.state.replay_service = second
    app.include_router(router, prefix="/api/v1")
    prefix = "/api/v1/replay/runs/storage/raw-trades"
    now = TRADE_NOW_MS
    monkeypatch.setattr(raw_trade_retention, "_now_ms", lambda: now)

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            preview = (await client.get(prefix + "/preview", params={"limit": 1})).json()
            candidate, = preview["items"]
            day = {"symbol": "BTCUSDT", "day": "2026-06-01", "day_id": candidate["day_id"]}

            async def submit(method, route, **payload):
                response = await client.request(method, prefix + route, json={**day, **payload})
                assert response.status_code == 200, response.text
                return response.json()

            async def inspect_day():
                response = await client.get(prefix + "/day", params={"symbol": day["symbol"], "day": day["day"]})
                assert response.status_code == 200, response.text
                return response.json()

            assert (await inspect_day())["item"]["day_id"] == day["day_id"]
            assert (await inspect_day())["policy"] is None

            async def policy(revision, retain_until):
                return await submit("PUT", "/policy", expected_revision=revision, retain_until_ms=retain_until)

            async def plan():
                return await submit("POST", "/plan", max_files=1, max_bytes=100_000)

            async def run(record, action="RETIRE"):
                return await submit("POST", "/run", plan_id=record["plan"]["plan_id"], action=action)

            denied = await client.post(
                prefix + "/plan", headers={"origin": "https://untrusted.invalid"},
                json={**day, "max_files": 1, "max_bytes": 100_000},
            )
            assert denied.status_code == 403
            denied = await client.post(
                prefix + "/plan", headers={"host": "untrusted.invalid"},
                json={**day, "max_files": 1, "max_bytes": 100_000},
            )
            assert denied.status_code == 403
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.10", 1111)),
                base_url="http://127.0.0.1",
            ) as remote:
                denied = await remote.post(prefix + "/plan", json={**day, "max_files": 1, "max_bytes": 100_000})
                assert denied.status_code == 403
            assert (await plan())["status"] == "UNMANAGED"
            assert (await policy(0, None))["policy"]["revision"] == 1
            pinned = (await client.get(prefix + "/preview", params={"limit": 1})).json()
            assert pinned["policy_state"] == "MANAGED"
            assert pinned["items"][0]["retention_policy"]["revision"] == 1
            assert pinned["items"][0]["protection_reasons"] == ["POLICY_RETAINS_DAY"]
            assert (await policy(0, 0))["status"] == "POLICY_CONFLICT"
            assert (await plan())["status"] == "POLICY_RETAINS_DAY"
            assert (await policy(1, now + 1_000))["policy"]["revision"] == 2
            assert (await plan())["status"] == "POLICY_RETAINS_DAY"
            assert (await policy(2, 0))["policy"]["revision"] == 3

            read_plan = await plan()
            assert read_plan["status"] == "PLANNED"
            assert read_plan["candidate"]["state"] == "COMMITTED"
            archive.freeze_dataset(exchange="binance", market_type="futures", symbol="BTCUSDT",
                                   start_time_ms=TRADE_REPLAY_START_MS, end_time_ms=TRADE_REPLAY_START_MS + 20_000)
            assert (await run(read_plan))["status"] == "STALE_PLAN"

            extended_plan = await plan()
            assert (await policy(3, None))["policy"]["revision"] == 4
            assert (await run(extended_plan))["status"] == "STALE_PLAN"
            assert (await policy(4, 0))["policy"]["revision"] == 5
            await second.shutdown(step_timeout=1.0)
            second = await _service(second_db, OfficialAggTradeArchive(root, defer_refresh=True), prefix="second-restarted")
            app.state.replay_service = second

            saved_plan = await plan()
            assert saved_plan["plan"]["revision"] == 5
            created = await first.create_session(trade_replay_config())
            session_id = str(created["session_id"])
            await first.release_session_to_hub(session_id)
            assert (await run(saved_plan))["status"] == "STALE_PLAN"
            assert (await plan())["status"] == "SAVED_REFERENCES_PROTECTED"
            await first.discard_session(session_id)
            await first.shutdown(step_timeout=1.0)

            expired = await plan()
            now = expired["plan"]["expires_ms"]
            assert (await run(expired))["status"] == "RETENTION_NOT_AUTHORIZED"
            assert archive.verified_retention_inventory(limit=1)["items"]
            current = await plan()
            assert (await run(current))["status"] == "RETIRED"
            assert archive.verified_retention_inventory(limit=1)["items"] == []
            assert (await inspect_day())["item"]["state"] == "RETIRED"
            assert not (await inspect_day())["item"]["reclaim_started"]
            assert (await submit("POST", "/recover", action="RESTORE"))["status"] == "RESTORED"
            assert (await run(current))["status"] == "STALE_PLAN"
            current = await plan()
            assert (await run(current))["status"] == "RETIRED"
            reclaimed = await run(current, "RECLAIM")
            assert reclaimed["status"] == "RECLAIM_PENDING" and reclaimed["removed_files"] == 1

            parked = first_db.with_suffix(".parked")
            first_db.rename(parked)
            try:
                assert (await run(current, "RECLAIM"))["status"] == "RETENTION_NOT_AUTHORIZED"
            finally:
                parked.replace(first_db)
            while reclaimed["remaining_files"]:
                reclaimed = await run(current, "RECLAIM")
                assert reclaimed["removed_files"] == 1
            assert reclaimed["status"] == "RECLAIMED"
            assert (await run(current, "RECLAIM"))["removed_logical_bytes"] == 0
            gone = (await inspect_day())["item"]
            assert gone["reclaim_started"] and gone["files"] == 0
            assert (await submit("POST", "/recover", action="REDOWNLOAD"))["status"] == "RECOVERY_BUDGET_REQUIRED"
    finally:
        await first.shutdown(step_timeout=1.0)
        await second.shutdown(step_timeout=1.0)


async def test_production_catalog_selects_a_local_day_before_official_discovery(
    tmp_path: Path,
) -> None:
    settings = replay_settings(tmp_path / "replay.db")
    verified_trade_archive(settings.replay_agg_trade_archive_dir)
    archive = OfficialAggTradeArchive(settings.replay_agg_trade_archive_dir, defer_refresh=True)
    service = ReplayService(
        settings=settings,
        store=ReplaySQLiteStore(settings.db_path, now_ms=lambda: TRADE_NOW_MS),
        raw_trade_archive=archive,
        now_ms=lambda: TRADE_NOW_MS,
    )
    await service.start()
    try:
        config = trade_replay_config()
        assert service.capabilities()["sources"]["agg_trade"]["enabled"]
        catalog = await service.catalog(
            warmup_bars=config.warmup_bars, horizon_ms=config.horizon_ms,
            quality_mode=config.quality_mode.value, blind_mode=False, source_kind="agg_trade",
        )
        assert [entry["identity"]["symbol"] for entry in catalog["entries"]] == ["BTCUSDT"]
        selected = await service.select_training_window(
            config, expected_catalog_epoch=str(catalog["catalog_epoch"]),
        )
        assert selected["selected_start_ms"] == TRADE_REPLAY_START_MS
        assert selected["agg_trade_catalog_epoch"] == archive.selection_snapshot(
            exchange=config.exchange, market_type=config.market_type, symbol=config.symbol,
        )[0]
        assert archive.diagnostics()["official_days_downloaded"] == 0
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_trade_service_uses_shared_actor_api_and_pin_lifecycle(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "archive")
    service = await _service(tmp_path / "replay.db", archive, prefix="trade")
    capability = service.capabilities()["sources"]["agg_trade"]
    assert capability["enabled"] is True
    assert capability["fidelity"] == "VERIFIED_AGG_TRADE_APPROXIMATE_BARS"
    assert capability["bar_parity_required"] is False

    created = await service.create_session(trade_replay_config())
    session_id = str(created["session_id"])
    assert created["data_fidelity"] == "VERIFIED_AGG_TRADE_APPROXIMATE_BARS"
    assert created["execution_fidelity"] == "AGG_TRADE_TAPE"
    assert created["snapshot"]["state"] == SessionState.PAUSED.value
    assert archive.diagnostics()["active_pins"] == 1

    acquired = await service.command(
        session_id,
        _command("acquire", CommandType.ACQUIRE_CONTROLLER, 0),
    )
    stepped = await service.command(
        session_id,
        _command("step", CommandType.STEP, acquired["revision"], {"count": 3}),
    )
    assert stepped["cursor"]["source_sequence"] == 3
    assert stepped["cursor"]["last_agg_trade_id"] == 1_002
    assert stepped["cursor"]["last_trade_time_ms"] is not None
    assert stepped["cursor"]["last_base_bar_open_ms"] is None

    forked = await service.fork_session(session_id)
    assert forked["snapshot"]["state_hash"] == stepped["state_hash"]
    assert archive.diagnostics()["active_pins"] == 2
    await service.shutdown(step_timeout=1.0)
    assert archive.diagnostics()["active_pins"] == 0


async def test_trade_capability_stays_closed_without_a_verified_exact_partition(
    tmp_path: Path,
) -> None:
    archive = ParquetRawAggTradeArchive(tmp_path / "empty-archive")
    service = await _service(tmp_path / "empty.db", archive, prefix="empty-trade")

    capability = service.capabilities()["sources"]["agg_trade"]
    assert capability == {
        "enabled": False,
        "reason": "DATASET_INCOMPLETE",
    }
    await service.shutdown(step_timeout=1.0)


async def test_trade_catalog_filters_identities_and_intersects_official_coverage(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "catalog-archive")
    repository = trade_replay_repository()
    futures_rows = next(iter(repository.rows.values()))
    repository.add_rows(
        FixtureIdentity("binance", "spot", "BTCUSDT"),
        "1m",
        futures_rows,
    )
    service = await _service(
        tmp_path / "catalog.db",
        archive,
        prefix="trade-catalog",
        repository=repository,
    )
    try:
        bar_catalog = await service.catalog(
            warmup_bars=2,
            horizon_ms=4 * 60_000,
            quality_mode="exact",
            blind_mode=False,
        )
        assert {
            entry["identity"]["market_type"] for entry in bar_catalog["entries"]
        } == {"futures", "spot"}

        trade_catalog = await service.catalog(
            warmup_bars=2,
            horizon_ms=4 * 60_000,
            quality_mode="exact",
            blind_mode=False,
            source_kind="AGG_TRADE",
        )
        assert [entry["identity"] for entry in trade_catalog["entries"]] == [{
            "exchange": "binance",
            "market_type": "futures",
            "symbol": "BTCUSDT",
        }]
        entry = trade_catalog["entries"][0]
        assert entry["quality"] == "VERIFIED_AGG_TRADE_APPROXIMATE_BARS"
        assert entry["eligible_ranges"][0]["first_start_ms"] == (
            TRADE_REPLAY_START_MS
        )
        assert entry["eligible_ranges"][0]["last_start_ms"] == (
            TRADE_REPLAY_START_MS + 2 * 60_000
        )
        assert entry["eligible_ranges"][0]["count"] == 3
        assert entry["eligible_ranges"][0]["replay_bars"] == 4
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_trade_catalog_epoch_binds_official_availability_epoch(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "epoch-archive")
    service = await _service(
        tmp_path / "epoch.db",
        archive,
        prefix="trade-epoch",
    )
    windows = archive.list_selection_windows(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
    )
    try:
        archive.selection_snapshot = lambda **_kwargs: (  # type: ignore[attr-defined]
            "sha256:" + "a" * 64,
            windows,
        )
        first = await service.catalog(
            warmup_bars=2,
            horizon_ms=4 * 60_000,
            quality_mode="exact",
            blind_mode=False,
            source_kind="AGG_TRADE",
        )
        archive.selection_snapshot = lambda **_kwargs: (  # type: ignore[attr-defined]
            "sha256:" + "b" * 64,
            windows,
        )
        second = await service.catalog(
            warmup_bars=2,
            horizon_ms=4 * 60_000,
            quality_mode="exact",
            blind_mode=False,
            source_kind="AGG_TRADE",
        )
        assert first["catalog_epoch"] != second["catalog_epoch"]
        assert first["entries"][0]["catalog_epoch"] == first["catalog_epoch"]
        assert second["entries"][0]["catalog_epoch"] == second["catalog_epoch"]
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_manual_trade_selection_rejects_bar_only_window_before_freeze(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "manual-archive")
    service = await _service(
        tmp_path / "manual.db",
        archive,
        prefix="trade-manual",
    )
    try:
        config = replace(
            trade_replay_config(),
            requested_start_ms=TRADE_REPLAY_START_MS - 60_000,
        )
        catalog = await service.catalog(
            warmup_bars=config.warmup_bars,
            horizon_ms=config.horizon_ms,
            quality_mode=config.quality_mode.value,
            blind_mode=False,
            source_kind="AGG_TRADE",
        )
        with pytest.raises(ReplayDomainError, match="not eligible") as exc_info:
            await service.select_training_window(
                config,
                expected_catalog_epoch=str(catalog["catalog_epoch"]),
            )
        assert exc_info.value.code is ReplayErrorCode.NO_ELIGIBLE_WINDOW
        assert archive.diagnostics()["active_pins"] == 0
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_random_trade_selection_uses_only_verified_trade_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = verified_trade_archive(tmp_path / "verified-archive")
    trade_catalog_epoch = "sha256:" + "a" * 64
    archive.selection_snapshot = lambda **kwargs: (  # type: ignore[attr-defined]
        trade_catalog_epoch,
        archive.list_selection_windows(**kwargs),
    )
    repository = trade_replay_repository()
    identity = FixtureIdentity("binance", "futures", "BTCUSDT")
    key = (identity.exchange, identity.market_type, identity.symbol, "1m")
    verified_rows = repository.rows[key]
    unverified_rows = [
        {
            **row,
            "open_time": int(row["open_time"]) - 86_400_000,
            "close_time": int(row["close_time"]) - 86_400_000,
        }
        for row in verified_rows
    ]
    repository.add_rows(identity, "1m", unverified_rows + verified_rows)
    service = ReplayService(
        settings=replay_settings(tmp_path / "random-trade.db"),
        store=ReplaySQLiteStore(
            tmp_path / "random-trade.db",
            now_ms=lambda: TRADE_NOW_MS,
        ),
        repository=repository,
        raw_trade_archive=archive,
        now_ms=lambda: TRADE_NOW_MS,
        session_id_factory=SessionIdFactory("random-trade"),
        native_intervals=lambda _identity: ("1m",),
    )
    await service.start()
    try:
        config = replace(
            trade_replay_config(),
            start_policy=StartPolicy.RANDOM_ELIGIBLE,
            requested_start_ms=None,
        )
        catalog = await service.catalog(
            warmup_bars=config.warmup_bars,
            horizon_ms=config.horizon_ms,
            quality_mode=config.quality_mode.value,
            blind_mode=False,
            source_kind="AGG_TRADE",
        )
        entry = catalog["entries"][0]
        assert entry["eligible_window_count"] == 3
        assert archive.list_verified_bar_windows(
            exchange="binance",
            market_type="futures",
            symbol="BTCUSDT",
            interval="1m",
            interval_ms=60_000,
            bar_source_revision=str(entry["source_fingerprint"]),
            parity_policy=trade_bar_parity_policy(compare_trade_count=False),
        ) == ()
        monkeypatch.setattr(
            service._catalog,
            "_stable_sample_index",
            lambda **_kwargs: 0,
        )

        selected = await service.select_training_window(
            config,
            expected_catalog_epoch=str(catalog["catalog_epoch"]),
        )

        assert selected["selected_start_ms"] >= DAY_START_MS
        assert (
            int(selected["selected_start_ms"])
            + config.horizon_ms
            - 1
            <= DAY_START_MS + 86_400_000 - 1
        )
        assert selected["selected_start_ms"] == TRADE_REPLAY_START_MS
        assert selected["agg_trade_catalog_epoch"] == trade_catalog_epoch
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_trade_bar_compatibility_builder_publishes_matching_segments(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "compatibility-archive")
    revision = "sha256:" + "a" * 64

    report = build_trade_bar_compatibility(
        archive,
        trade_replay_repository(),
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        interval="1m",
        start_time_ms=TRADE_REPLAY_START_MS,
        end_time_ms=TRADE_REPLAY_START_MS + 4 * 60_000 - 1,
        bar_source_revision=revision,
    )

    assert report["checked_bar_count"] == 4
    assert report["matching_bar_count"] == 4
    assert report["mismatch_bar_count"] == 0
    assert archive.list_verified_bar_windows(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        interval="1m",
        interval_ms=60_000,
        bar_source_revision=revision,
        parity_policy=trade_bar_parity_policy(compare_trade_count=False),
    ) == (
        VerifiedRawAggTradeBarWindow(
            start_time_ms=TRADE_REPLAY_START_MS,
            end_time_ms=TRADE_REPLAY_START_MS + 4 * 60_000 - 1,
            bar_count=4,
        ),
    )


async def test_trade_bar_compatibility_keeps_disjoint_dataset_proofs(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "multi-compatibility-archive")
    revision = "sha256:" + "b" * 64
    policy = trade_bar_parity_policy(compare_trade_count=False)
    expected_windows: list[VerifiedRawAggTradeBarWindow] = []

    for start_offset_minutes in (0, 2):
        start_time_ms = (
            TRADE_REPLAY_START_MS + start_offset_minutes * 60_000
        )
        end_time_ms = start_time_ms + 2 * 60_000 - 1
        dataset_ref = archive.freeze_dataset(
            exchange="binance",
            market_type="futures",
            symbol="BTCUSDT",
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        window = VerifiedRawAggTradeBarWindow(
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            bar_count=2,
        )
        expected_windows.append(window)
        archive.publish_bar_compatibility(
            dataset_ref=dataset_ref,
            interval="1m",
            interval_ms=60_000,
            bar_source_revision=revision,
            parity_policy=policy,
            checked_bar_count=2,
            mismatch_bar_count=0,
            compatible_windows=(window,),
        )

    assert archive.list_verified_bar_windows(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        interval="1m",
        interval_ms=60_000,
        bar_source_revision=revision,
        parity_policy=policy,
    ) == tuple(expected_windows)


async def test_blind_trade_service_never_exposes_archive_paths_or_actual_time(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "private-archive")
    service = await _service(tmp_path / "replay.db", archive, prefix="blind-trade")
    created = await service.create_session(trade_replay_config(blind_mode=True))
    session_id = str(created["session_id"])
    serialized = json.dumps(created, sort_keys=True)
    assert str(TRADE_REPLAY_START_MS) not in serialized
    assert "date=2026-06-01" not in serialized
    assert ".parquet" not in serialized
    assert str(tmp_path) not in serialized
    assert created["snapshot"]["cursor"]["virtual_time_ms"] == (
        SYNTHETIC_TIME_ANCHOR_MS
    )

    acquired = await service.command(
        session_id,
        _command("acquire", CommandType.ACQUIRE_CONTROLLER, 0),
    )
    stepped = await service.command(
        session_id,
        _command("step", CommandType.STEP, acquired["revision"], {"count": 1}),
    )
    serialized_step = json.dumps(stepped, sort_keys=True)
    assert str(TRADE_REPLAY_START_MS) not in serialized_step
    assert "date=2026-06-01" not in serialized_step
    assert stepped["cursor"]["last_trade_time_ms"] == SYNTHETIC_TIME_ANCHOR_MS + 1_000
    assert stepped["cursor"]["last_agg_trade_id"] == 1
    expected_hash = stepped["state_hash"]
    await service.shutdown(step_timeout=1.0)

    recovered_service = await _service(
        tmp_path / "replay.db",
        archive,
        prefix="blind-trade-recovered",
    )
    recovered = await recovered_service.get_session(session_id)
    assert recovered["snapshot"]["state_hash"] == expected_hash
    assert recovered["snapshot"]["cursor"]["last_agg_trade_id"] == 1
    await recovered_service.shutdown(step_timeout=1.0)


async def test_blind_trade_accepts_bar_mismatch_without_revealing_actual_times(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "private-archive")
    repository = trade_replay_repository()
    for rows in repository.rows.values():
        for row in rows:
            if row["open_time"] == TRADE_REPLAY_START_MS:
                for field in ("open", "high", "low", "close"):
                    row[field] = 999
                break
    service = ReplayService(
        settings=replay_settings(tmp_path / "parity.db"),
        store=ReplaySQLiteStore(tmp_path / "parity.db", now_ms=lambda: TRADE_NOW_MS),
        repository=repository,
        raw_trade_archive=archive,
        now_ms=lambda: TRADE_NOW_MS,
        session_id_factory=SessionIdFactory("blind-parity"),
        native_intervals=lambda _identity: ("1m",),
    )
    await service.start()

    created = await service.create_session(trade_replay_config(blind_mode=True))
    assert created["data_fidelity"] == "VERIFIED_AGG_TRADE_APPROXIMATE_BARS"
    serialized = json.dumps(created, sort_keys=True)
    assert str(TRADE_REPLAY_START_MS) not in serialized
    await service.shutdown(step_timeout=1.0)


async def test_trade_service_recovers_checkpoint_and_revalidates_generation(
    tmp_path: Path,
) -> None:
    archive = verified_trade_archive(tmp_path / "archive")
    database = tmp_path / "replay.db"
    service = await _service(database, archive, prefix="first")
    created = await service.create_session(trade_replay_config())
    session_id = str(created["session_id"])
    acquired = await service.command(
        session_id,
        _command("acquire", CommandType.ACQUIRE_CONTROLLER, 0),
    )
    stepped = await service.command(
        session_id,
        _command("step", CommandType.STEP, acquired["revision"], {"count": 3}),
    )
    expected_hash = stepped["state_hash"]
    await service.shutdown(step_timeout=1.0)
    assert archive.diagnostics()["active_pins"] == 0

    recovered_service = await _service(database, archive, prefix="second")
    recovered = await recovered_service.get_session(session_id)
    assert recovered["snapshot"]["state"] == SessionState.PAUSED.value
    assert recovered["snapshot"]["state_hash"] == expected_hash
    assert recovered["snapshot"]["cursor"]["last_agg_trade_id"] == 1_002
    assert archive.diagnostics()["active_pins"] == 1
    await recovered_service.shutdown(step_timeout=1.0)
    assert archive.diagnostics()["active_pins"] == 0
