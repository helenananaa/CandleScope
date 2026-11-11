from dataclasses import replace

import pytest

from app.local_data.service import LocalDatasetService
from app.local_data.user_market_trades import UserMarketTradeOptions
from app.replay.local_bar_repository import LOCAL_BAR_MARKET, LocalReplayBarRepository
from app.replay.local_trade_repository import LocalReplayTradeRepository, LocalTradeDatasetRef
from app.replay.service import ReplayService
from app.replay.sources.trade_reader import PagedReplayTradeReader
from app.replay.storage import ReplaySQLiteStore
from tests.fixtures.replay.service_fakes import INTERVAL_MS, NOW_MS, START_MS, replay_settings
from app.replay.training.models import ReplayV2CommandType
from tests.test_replay_v2_training_phase1 import _request
from tests.test_replay_v2_training_phase5 import _acquire, _command


def import_trades(tmp_path, library, *, dataset_id=None, price=100, base="BTC", kind="MARKET_TRADE"):
    csv = tmp_path / "market-trades.csv"
    csv.write_text("time,sequence,price,quantity,is_buyer_maker\n" + "".join(
        f"{START_MS + minute * INTERVAL_MS + 1000},{9007199254740993 + minute * 2 + offset},"
        f"{price + minute + offset},1,true\n"
        for minute in range(24) for offset in range(2)
    ))
    return library.import_user_market_trades(csv, UserMarketTradeOptions(
        name=f"Imported {base} prints", symbol=base + "USDT", base_asset=base, quote_asset="USDT",
        timestamp_unit="ms", coverage_start_ms=START_MS, coverage_end_ms=START_MS + 24 * INTERVAL_MS,
        trade_kind=kind, dataset_id=dataset_id,
    ))


@pytest.mark.anyio
async def test_formal_imported_trade_run_uses_pinned_market_clock_and_restores(tmp_path):
    library = LocalDatasetService(tmp_path / "library")
    library.start()
    original = import_trades(tmp_path, library)
    dataset_id = original["dataset_id"]
    secondary = import_trades(tmp_path, library, price=500, base="ETH", kind="MARKET_AGG_TRADE")
    path = tmp_path / "replay.db"

    async def start():
        bar = LocalReplayBarRepository(library, max_rows=100)
        trade = LocalReplayTradeRepository(library)
        service = ReplayService(settings=replace(replay_settings(path), trade_page_rows=2),
            store=ReplaySQLiteStore(path, now_ms=lambda: NOW_MS), repository=bar,
            native_intervals=bar.native_intervals, raw_trade_archive=trade, now_ms=lambda: NOW_MS)
        await service.start()
        return service

    service = await start()
    try:
        catalog = await service.catalog(warmup_bars=2, horizon_ms=5 * INTERVAL_MS,
            quality_mode="exact", blind_mode=False, source_kind="agg_trade")
        assert [entry["quality"] for entry in catalog["entries"]] == ["USER_MARKET_TRADE_COVERAGE"] * 2
        request = replace(await _request(service), source_kind="AGG_TRADE",
            catalog_epoch=catalog["catalog_epoch"], exchange=dataset_id, market_type=LOCAL_BAR_MARKET)
        result = await service.training.create_run(request)
        run, session = result["run"]["run_id"], result["run"]["adapter_session_id"]
        track = (await service.training.store.get_market_tracks(run))["tracks"][0]["track_id"]
        handle = service._sessions[session]
        ref = handle.trade_dataset_ref
        assert isinstance(ref, LocalTradeDatasetRef) and ref.revision == original["data_epoch"]
        reader = PagedReplayTradeReader(service.raw_trade_archive, ref, page_rows=1)
        first, second = reader.read_page(), reader.read_sequence_page(after_sequence=1, revealed_sequence=2, limit=1)
        assert first.trades[0].trade_time_ms == second.trades[0].trade_time_ms == request.requested_start_ms + 1000
        assert [(t.agg_trade_id, t.price) for t in first.trades + second.trades] == [(1, "104"), (2, "105")]
        await _acquire(service, run_id=run, selected_session_id=session, command_id="local-acquire")

        async def command(command_id, kind, payload):
            return await service.training.command(run, _command(
                run, command_id, kind, await service.get_session(session), payload,
            ))

        plan = await service.training.market_track_plan(run, exchange=secondary["dataset_id"],
            market_type=LOCAL_BAR_MARKET, symbol="ETHUSDT", subscription_tier="FULL")
        await command("local-add", ReplayV2CommandType.ADD_TRACK, {"plan_id": plan["plan_id"]})
        tracks = (await service.training.store.get_market_tracks(run))["tracks"]
        assert {row["exchange"] for row in tracks} == {dataset_id, secondary["dataset_id"]}
        await command("local-buy", ReplayV2CommandType.PLACE_ORDER, {
            "client_order_id": "local-market-order", "side": "BUY", "order_type": "MARKET",
            "quantity": "1", "reduce_only": False, "limit_price": None, "stop_price": None,
        })
        await command("local-step", ReplayV2CommandType.STEP_BASE, {"count": 2})
        snapshots = {
            row["adapter_session_id"]: (await service.get_session(row["adapter_session_id"]))["snapshot"]
            for row in tracks
        }
        snapshot = snapshots[session]
        cursor = snapshot["cursor"]
        assert cursor["source_sequence"] > 0
        assert len(snapshot["components"]["fills"]) == 1
        assert {row["cursor"]["virtual_time_ms"] for row in snapshots.values()} == {cursor["virtual_time_ms"]}
        boundary = cursor["virtual_time_ms"]
        async def visible(owner):
            return await owner.training.history_page(session, track_id=track, before_ms=boundary + 1,
                revealed_boundary_ms=boundary, limit=10, data_epoch=snapshot["data_epoch"], history_epoch=None)
        earlier = await visible(service)
        assert earlier["bars"] and all(float(row["high"]) < 200 for row in earlier["bars"])
        replacement = import_trades(tmp_path, library, dataset_id=dataset_id, price=900)
        assert replacement["data_epoch"] != original["data_epoch"]
    finally:
        await service.shutdown(step_timeout=1)

    restored = await start()
    try:
        for adapter, saved in snapshots.items():
            state = (await restored.get_session(adapter))["snapshot"]
            assert state["cursor"] == saved["cursor"]
            assert state["data_epoch"] == saved["data_epoch"]
            assert state["components"] == saved["components"]
        assert (await visible(restored))["bars"] == earlier["bars"]
        assert restored._sessions[session].trade_dataset_ref == ref
    finally:
        await restored.shutdown(step_timeout=1)
