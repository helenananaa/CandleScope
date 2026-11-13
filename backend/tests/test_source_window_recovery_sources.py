"""Default cold source-only recovery through the real pinned fork boundary."""

import asyncio

from app.data_engine.ingestion import StreamPipeline
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.storage import klines_repo
from tests.test_source_revision_pipeline import Harness, message, OPENED, DESC
from tests.test_source_window_recovery import database, manager_for


def test_default_manager_restart_preserves_source_journal_only_fork_correction(
    database,
):
    async def run():
        first = Harness("2m")
        try:
            await first.ingest(message())
            await first.ingest(message(OPENED + 60000))
        finally:
            await first.close()
        assert not klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")
        manager = manager_for("2m")
        pipeline = StreamPipeline(
            IngestionConfig(ccxt_fork_kline_enabled=True), None, DESC
        )
        pipeline.delivery.on_market_event(manager.bar_aggregator.on_market_event)

        def legacy(*args):
            raise AssertionError(
                "qualified cold recovery used the old full-window reader"
            )

        manager.query_engine.storage.read_source_components = legacy
        try:
            await pipeline.normalize.ingest(
                message(quote="1008", event_time=OPENED + 120010)
            )
            await manager.aggregator_bridge.delivery.flush_pending()
            target = klines_repo.query_klines("BTCUSDT", "2m", market_type="futures")
            assert len(target) == 1 and target[0]["quote_volume"] == 2018
            assert target[0]["source"] == "source_snapshot_verified"
            assert not klines_repo.query_klines("BTCUSDT", "1m", market_type="futures")
            state = manager.bar_aggregator.get_pipeline("2m").bar_state.get_state(
                "binance", "futures", "BTCUSDT", OPENED
            )
            assert (
                state._source_recovery is not None
                and len(state.source_snapshots) == len(state.source_refs) == 1
            )
            assert state._source_recovery.version.closed_count == 2
            assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
        finally:
            await pipeline.recovery.stop()
            await manager.shutdown()

    asyncio.run(run())
