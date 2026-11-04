from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.local_data.service import LocalDatasetService, LocalImportOptions
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.errors import ReplayDomainError
from app.replay.local_bar_repository import LOCAL_BAR_MARKET, LocalReplayBarRepository
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from tests.fixtures.replay.service_fakes import START_MS, NOW_MS, INTERVAL_MS, replay_settings
from tests.test_replay_v2_training_phase1 import _request, _command
from app.replay.constants import CommandType, REPLAY_PROTOCOL


def imported(root: Path, *, dataset_id=None, price=100, omitted=None, volume=True, final=True):
    library = LocalDatasetService(root / "library")
    library.start()
    csv = root / f"candles-{price}.csv"
    csv.write_text("time,open,high,low,close" + (",volume" if volume else "") + "\n" + "".join(
        f"{START_MS + i * INTERVAL_MS},{price+i},{price+i+2},{price+i-1},{price+i+1}" + (",10" if volume else "") + "\n"
        for i in range(24) if i != omitted
    ))
    manifest = library.import_csv(csv, LocalImportOptions(name="Imported BTC", symbol="BTCUSDT", interval="1m",
        timestamp_unit="ms", dataset_id=dataset_id, last_bar_closed=final))
    return library, manifest


def scope(manifest):
    return {"exchange": manifest["dataset_id"], "market_type": LOCAL_BAR_MARKET}


def test_same_symbol_imports_and_revision_changes_are_isolated(tmp_path):
    library, first = imported(tmp_path)
    _, second = imported(tmp_path, price=500)
    repo = LocalReplayBarRepository(library, max_rows=100)
    rows = repo.query_bars_at_revision(first["data_epoch"], "BTCUSDT", "1m", **scope(first))
    assert rows[0]["open"] == "100" and rows[0]["close_time"] == START_MS + INTERVAL_MS - 1
    assert repo.query_bars_at_revision(second["data_epoch"], "BTCUSDT", "1m", **scope(second))[0]["open"] == "500"
    _, changed = imported(tmp_path, dataset_id=first["dataset_id"], price=900)
    assert repo.query_bars("BTCUSDT", "1m", **scope(first))[0]["open"] == "900"
    assert repo.query_bars_at_revision(first["data_epoch"], "BTCUSDT", "1m", **scope(first)) == rows
    with pytest.raises(ReplayDomainError):
        repo.query_bars_at_revision(first["data_epoch"], "BTCUSDT", "1m", **scope(second))
    with pytest.raises(ReplayDomainError):
        repo.query_bars("BTCUSDT", "1m", exchange="binance", market_type="spot")
    assert changed["data_epoch"] != first["data_epoch"]


@pytest.mark.parametrize("options", [{"volume": False}, {"final": False}])
def test_missing_volume_and_forming_rows_are_explicitly_unsupported(tmp_path, options):
    library, manifest = imported(tmp_path, **options)
    repo = LocalReplayBarRepository(library, max_rows=100)
    assert repo.native_intervals(ReplaySeriesIdentity(**scope(manifest), symbol="BTCUSDT")) == ("1m",)
    with pytest.raises(ReplayDomainError, match="requires closed"):
        repo.get_bounds("BTCUSDT", "1m", **scope(manifest))


def test_gap_and_budget_contracts_never_fill_or_truncate_silently(tmp_path):
    library, manifest = imported(tmp_path, omitted=7)
    repo = LocalReplayBarRepository(library, max_rows=100)
    gaps = repo.scan_gaps("BTCUSDT", "1m", **scope(manifest))
    assert gaps["gaps"] == [{"start_ms": START_MS + 7 * INTERVAL_MS, "end_ms": START_MS + 7 * INTERVAL_MS,
                             "missing_bars": 1, "reason": "imported_bar_gap"}]
    assert repo.scan_gaps("BTCUSDT", "1m", limit=3, **scope(manifest))["truncated"] is True
    with pytest.raises(ReplayDomainError):
        LocalReplayBarRepository(library, max_rows=3).query_bars("BTCUSDT", "1m", **scope(manifest))
    assert len(repo.query_bars("BTCUSDT", "1m", **scope(manifest))) == 23


@pytest.mark.anyio
async def test_imported_bar_uses_existing_training_engine_and_restores_pinned_source(tmp_path):
    library, manifest = imported(tmp_path)
    repo = LocalReplayBarRepository(library, max_rows=100)
    path = tmp_path / "replay.db"
    async def start():
        service = ReplayService(settings=replay_settings(path), store=ReplaySQLiteStore(path, now_ms=lambda: NOW_MS),
            repository=repo, native_intervals=repo.native_intervals, now_ms=lambda: NOW_MS)
        await service.start()
        return service
    service = await start()
    try:
        request = replace(await _request(service), exchange=manifest["dataset_id"], market_type=LOCAL_BAR_MARKET)
        result = await service.training.create_run(request)
        run, session = result["run"]["run_id"], result["run"]["adapter_session_id"]
        before = (await service.get_session(session))["snapshot"]
        track = (await service.training.store.get_market_tracks(run))["tracks"][0]["track_id"]
        async def history(owner, snapshot):
            boundary = snapshot["cursor"]["virtual_time_ms"]
            page = await owner.training.history_page(session, track_id=track, before_ms=boundary + 1,
                revealed_boundary_ms=boundary, limit=100, data_epoch=snapshot["data_epoch"], history_epoch=None)
            assert page["bars"]
            assert all(row["close_time_ms"] <= boundary for row in page["bars"])
            assert all(float(row["high"]) < 200 for row in page["bars"])
            return page["bars"]
        await history(service, before)
        acquired = await service.command(session, _command("local-acquire", CommandType.ACQUIRE_CONTROLLER, revision=before["revision"]))
        from app.replay.models import ReplayCommand
        stepped = await service.command(session, ReplayCommand(protocol=REPLAY_PROTOCOL, command_id="local-step",
            client_instance_id="phase1-browser", expected_revision=acquired["revision"], type=CommandType.STEP, payload={"count": 1}))
        assert stepped["cursor"]["virtual_time_ms"] > before["cursor"]["virtual_time_ms"]
        cursor = stepped["cursor"]
        visible = await history(service, (await service.get_session(session))["snapshot"])
        _, changed = imported(tmp_path, dataset_id=manifest["dataset_id"], price=900)
        assert changed["data_epoch"] != manifest["data_epoch"]
    finally:
        await service.shutdown(step_timeout=1)
    restored = await start()
    try:
        try:
            recovered = await restored.get_session(session)
        except ReplayDomainError as exc:
            raise AssertionError(dict(exc.details)) from exc
        assert recovered["snapshot"]["cursor"] == cursor
        assert await history(restored, recovered["snapshot"]) == visible
        assert (await restored.store.get_session(session))["config"]["exchange"] == manifest["dataset_id"]
        assert (await restored.training.store.get_run(run))["run_id"] == run
    finally:
        await restored.shutdown(step_timeout=1)


@pytest.mark.parametrize("base_interval,base_ms", [("1m",60_000),("5m",300_000)])
def test_coarse_projection_aggregates_only_closed_revealed_base_prefix(tmp_path,base_interval,base_ms):
    library=LocalDatasetService(tmp_path/"library");library.start()
    csv=tmp_path/"coarse.csv"
    csv.write_text("time,open,high,low,close,volume\n"+"".join(
        f"{START_MS+i*base_ms},{100+i if i<9 else 99999},{102+i if i<9 else 99999},{99+i},{101+i if i<9 else 99999},10\n"
        for i in range(18)))
    manifest=library.import_csv(csv,LocalImportOptions(name="coarse",symbol="BTCUSDT",interval=base_interval,timestamp_unit="ms"))
    repo=LocalReplayBarRepository(library,max_rows=100)
    # A fully stored future row has an extreme price, but current projection
    # stops before that row is revealed. Rewind must not reuse future summaries.
    kwargs=dict(actual_start_ms=START_MS,actual_end_ms=START_MS+8*base_ms,
        actual_replay_start_ms=START_MS,public_replay_start_ms=START_MS,limit=100,include_partial=True,**scope(manifest))
    first=repo.query_source_bucket_bars_at_revision(manifest["data_epoch"],"BTCUSDT",base_interval,"15m",**kwargs)
    assert first["bars"] and max(float(b["high"]) for b in first["bars"])<200
    repo.query_source_bucket_bars_at_revision(manifest["data_epoch"],"BTCUSDT",base_interval,"15m",
        **{**kwargs,"actual_end_ms":START_MS+18*base_ms})
    assert repo.query_source_bucket_bars_at_revision(manifest["data_epoch"],"BTCUSDT",base_interval,"15m",**kwargs)==first
    assert all(b["last_base_open_ms"]+base_ms-1<kwargs["actual_end_ms"] for b in first["bars"])
