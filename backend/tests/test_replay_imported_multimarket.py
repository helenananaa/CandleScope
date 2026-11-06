from dataclasses import replace
from pathlib import Path

import pytest

from app.local_data.service import LocalDatasetError, LocalDatasetService, LocalImportOptions
from app.replay.local_bar_repository import LOCAL_BAR_MARKET, LocalReplayBarRepository
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.training.errors import TrainingRunError
from app.replay.training.models import ReplayV2CommandType
from tests.fixtures.replay.service_fakes import START_MS, NOW_MS, INTERVAL_MS, replay_settings
from tests.test_replay_v2_training_phase5 import _request, _command, _acquire


def dataset(root, *, symbol="BTCUSDT", base="BTC", quote="USDT", price=100, dataset_id=None):
    library = LocalDatasetService(root / "library")
    csv = root / f"{symbol}-{price}.csv"
    csv.write_text("time,open,high,low,close,volume\n" + "".join(
        f"{START_MS+i*INTERVAL_MS},{price+i},{price+i+2},{price+i-1},{price+i+1},10\n" for i in range(24)))
    return library, library.import_csv(csv, LocalImportOptions(name=symbol, symbol=symbol,
        interval="1m", timestamp_unit="ms", base_asset=base, quote_asset=quote, dataset_id=dataset_id))


def test_asset_units_are_explicit_versioned_and_immutable_within_a_dataset(tmp_path):
    library, explicit = dataset(tmp_path)
    _, unitless = dataset(tmp_path, base=None, quote=None)
    assert explicit["data_epoch"] != unitless["data_epoch"]
    assert "instrument" not in unitless
    assert explicit["instrument"] == {"base_asset": "BTC", "quote_asset": "USDT", "volume_unit": "base_asset"}
    with pytest.raises(LocalDatasetError, match="keep its declared"):
        dataset(tmp_path, dataset_id=explicit["dataset_id"], quote="USD")
    with pytest.raises(LocalDatasetError, match="Declare both"):
        dataset(tmp_path, base=None)
    assert library.get_manifest(explicit["dataset_id"])["data_epoch"] == explicit["data_epoch"]
    _, inherited = dataset(tmp_path, dataset_id=explicit["dataset_id"], base=None, quote=None, price=300)
    assert inherited["instrument"] == explicit["instrument"]
    assert library.revision_details(explicit["dataset_id"], explicit["data_epoch"])["manifest"]["instrument"] == explicit["instrument"]


async def service_for(root):
    repo = LocalReplayBarRepository(LocalDatasetService(root / "library"), max_rows=100)
    path = root / "replay.db"
    service = ReplayService(settings=replay_settings(path), store=ReplaySQLiteStore(path, now_ms=lambda: NOW_MS),
        repository=repo, native_intervals=repo.native_intervals, now_ms=lambda: NOW_MS)
    await service.start()
    return service


@pytest.mark.anyio
@pytest.mark.parametrize("target_symbol,target_base", [("ETHUSDT", "ETH"), ("BTCUSDT", "BTC")])
async def test_imported_tracks_keep_independent_sources_notes_and_pinned_restart(tmp_path, target_symbol, target_base):
    _, btc = dataset(tmp_path)
    _, eth = dataset(tmp_path, symbol=target_symbol, base=target_base, price=500)
    service = await service_for(tmp_path)
    try:
        created = await service.training.create_run(replace(await _request(service),
            exchange=btc["dataset_id"], market_type=LOCAL_BAR_MARKET))
        run, primary = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run, selected_session_id=primary, command_id="acquire")
        plan = await service.training.market_track_plan(run, exchange=eth["dataset_id"],
            market_type=LOCAL_BAR_MARKET, symbol=target_symbol, subscription_tier="FULL")
        assert plan["identity"]["settlement_asset"] == "USDT"
        with pytest.raises(TrainingRunError) as online:
            await service.training.market_track_history(run, exchange=eth["dataset_id"], market_type=LOCAL_BAR_MARKET, symbol=target_symbol)
        assert online.value.code == "LOCAL_DATA_PREPARATION_UNSUPPORTED"
        await service.training.command(run, _command(run, "add-eth", ReplayV2CommandType.ADD_TRACK,
            await service.get_session(primary), {"plan_id": plan["plan_id"]}))
        tracks = (await service.training.store.get_market_tracks(run))["tracks"]
        assert len(tracks) == 2
        assert {t["exchange"] for t in tracks} == {btc["dataset_id"], eth["dataset_id"]}
        await service.training.command(run, _command(run, "step", ReplayV2CommandType.STEP_BASE,
            await service.get_session(primary), {"count": 2}))
        saved = {}
        for track in tracks:
            tid = track["track_id"]
            context = (await service.training.notes(run, tid))["context"]
            before = (await service.get_session(track["adapter_session_id"]))["snapshot"]
            saved[tid] = await service.training.save_note(run, tid, note_id="note-" + tid,
                fields={"entryBasis": track["exchange"] + "/" + track["symbol"]}, expected_revision=0, context=context)
            assert (await service.get_session(track["adapter_session_id"]))["snapshot"] == before
            assert (await service.training.notes(run, tid))["notes"] == [saved[tid]]
        clock = [n["marketTimeMs"] for n in saved.values()]
        assert clock[0] == clock[1]
        snapshots = {t["track_id"]: (await service.get_session(t["adapter_session_id"]))["snapshot"] for t in tracks}
        # Re-import each source after it is frozen. Neither restored actor may
        # resolve to the new head or to the other dataset with a different ID.
        dataset(tmp_path, dataset_id=btc["dataset_id"], price=900)
        dataset(tmp_path, dataset_id=eth["dataset_id"], symbol=target_symbol, base=target_base, price=1500)
    finally:
        await service.shutdown(step_timeout=1)
    restored = await service_for(tmp_path)
    try:
        for track in tracks:
            tid = track["track_id"]
            state = (await restored.get_session(track["adapter_session_id"]))["snapshot"]
            assert state["cursor"] == snapshots[tid]["cursor"]
            assert state["components"] == snapshots[tid]["components"]
            assert state["data_epoch"] == snapshots[tid]["data_epoch"]
            assert (await restored.training.notes(run, tid))["notes"] == [saved[tid]]
            page = await restored.training.history_page(track["adapter_session_id"], track_id=tid,
                before_ms=clock[0]+1, revealed_boundary_ms=clock[0], limit=100,
                data_epoch=state["data_epoch"], history_epoch=None)
            assert page["bars"]
            assert max(float(b["high"]) for b in page["bars"]) < (200 if tid == "track-1" else 600)
    finally:
        await restored.shutdown(step_timeout=1)


@pytest.mark.anyio
@pytest.mark.parametrize("target_quote,primary_units", [("BTC", True), ("USDT", False), (None, True)])
async def test_cross_dataset_account_admission_rejects_unknown_or_different_units(tmp_path, target_quote, primary_units):
    _, btc = dataset(tmp_path, base="BTC" if primary_units else None, quote="USDT" if primary_units else None)
    _, eth = dataset(tmp_path, symbol="ETHUSDT", base="ETH" if target_quote else None, quote=target_quote, price=500)
    service = await service_for(tmp_path)
    try:
        created = await service.training.create_run(replace(await _request(service),
            exchange=btc["dataset_id"], market_type=LOCAL_BAR_MARKET))
        run = created["run"]["run_id"]
        with pytest.raises(TrainingRunError) as failed:
            await service.training.market_track_plan(run, exchange=eth["dataset_id"],
                market_type=LOCAL_BAR_MARKET, symbol="ETHUSDT", subscription_tier="FULL")
        assert failed.value.code in {"MARKET_SCOPE_MISMATCH", "IMPORTED_BAR_UNITS_REQUIRED"}
        assert len((await service.training.store.get_market_tracks(run))["tracks"]) == 1
    finally:
        await service.shutdown(step_timeout=1)
