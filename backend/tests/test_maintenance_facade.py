from __future__ import annotations

import asyncio
from pathlib import Path

from app.data_engine.data_manager import DataManager


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class _Maintenance:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def repair_custom_storage(self, **kwargs):
        self.calls.append(("repair_custom_storage", kwargs))
        return {"status": "ok", "kind": "repair"}

    async def scan_and_fill_gaps(self, **kwargs):
        self.calls.append(("scan_and_fill_gaps", kwargs))
        return {"status": "ok", "kind": "scan"}

    async def delete_storage_data(self, **kwargs):
        self.calls.append(("delete_storage_data", kwargs))
        return 3


def test_data_manager_exposes_maintenance_facade_methods() -> None:
    async def _run() -> None:
        dm = DataManager()
        maintenance = _Maintenance()
        dm.maintenance = maintenance

        repair = await dm.repair_custom_storage(
            symbols_filter=["BTCUSDT"],
            backfill_coordinator=object(),
            exchange="okx",
            market_type="SPOT",
        )
        scan = await dm.scan_and_fill_storage_gaps(
            symbols_filter=[],
            backfill_coordinator=object(),
            exchange="binance",
            market_type="FUTURES",
        )
        deleted = await dm.delete_storage_data(
            symbol="BTCUSDT",
            interval="1m",
            start_ms=1,
            end_ms=2,
            exchange="binance",
            market_type="SPOT",
        )

        assert repair == {"status": "ok", "kind": "repair"}
        assert scan == {"status": "ok", "kind": "scan"}
        assert deleted == 3
        assert maintenance.calls[0][0] == "repair_custom_storage"
        assert maintenance.calls[0][1]["symbols_filter"] == ["BTCUSDT"]
        assert maintenance.calls[0][1]["backfill_coordinator"] is not None
        assert maintenance.calls[0][1]["exchange"] == "okx"
        assert maintenance.calls[0][1]["market_type"] == "spot"
        assert maintenance.calls[1][0] == "scan_and_fill_gaps"
        assert maintenance.calls[1][1]["market_type"] == "futures"
        assert maintenance.calls[2] == (
            "delete_storage_data",
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "start_ms": 1,
                "end_ms": 2,
                "exchange": "binance",
                "market_type": "spot",
            },
        )

    asyncio.run(_run())


def test_api_routes_use_data_manager_maintenance_facade() -> None:
    checked = [
        BACKEND_ROOT / "app/api/v1/settings.py",
        BACKEND_ROOT / "app/api/v1/klines.py",
    ]
    forbidden = (
        "dm.maintenance",
        "query_engine._storage",
        "dm.cache._",
        "dm._db_limits",
        "BackfillEngine(",
        "backfill_engine.run",
        "detect_only",
        "dm.retention.",
        "._cfg",
        "._ingress",
        "._transport",
    )

    offenders: list[str] = []
    for path in checked:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{token}")

    assert offenders == []


def test_settings_repair_requires_complete_trusted_base_before_atomic_replace(tmp_path, monkeypatch):
    from app.data_engine.storage import klines_repo

    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "repair.sqlite")
    klines_repo.init_klines_storage()
    storage = klines_repo.KlinesRepoAdapter()

    class Coordinator:
        def __init__(self):
            self.requests = []

        async def request_and_wait(self, request):
            self.requests.append(request)
            return object()

    def row(at, width, volume):
        return {
            "open_time": at, "close_time": at + width - 1,
            "open": 3, "high": 4, "low": 2, "close": 3, "volume": volume,
            "trades": None, "quote_volume": None, "taker_buy_base": None, "taker_buy_quote": None,
        }

    async def run():
        dm = DataManager()
        dm.set_storage(storage)
        coordinator = Coordinator()
        targets = [row(0, 120_000, 9), row(120_000, 120_000, 11)]
        storage.upsert_bars("BTCUSDT", "1m", [row(at, 60_000, 1) for at in (0, 60_000, 120_000)], "backfill")
        storage.upsert_bars("BTCUSDT", "1m", [row(180_000, 60_000, 2)], "data_manager_closed")

        async def repair():
            return await dm.repair_custom_storage(
                symbols_filter=["BTCUSDT"], backfill_coordinator=coordinator,
            )

        def seed_target():
            storage.upsert_bars("BTCUSDT", "2m", targets, "settings_manual_repair")

        def read_target():
            return storage.query_bars("BTCUSDT", "2m")

        seed_target()
        result = await repair()
        assert result["failed_series"] == 1
        assert coordinator.requests[0].metadata["requires_trusted_finality"] is True
        assert [item["volume"] for item in read_target()] == [9, 11]

        # A trusted label alone cannot make an incorrectly bounded component
        # complete. One good target out of two must not authorize replacement.
        storage.upsert_bars("BTCUSDT", "1m", [row(180_000, 59_999, 2)], "backfill")
        seed_target()
        result = await repair()
        assert result["failed_series"] == 1
        assert [item["volume"] for item in read_target()] == [9, 11]

        storage.upsert_bars("BTCUSDT", "1m", [row(180_000, 60_000, -1)], "backfill")
        seed_target()
        result = await repair()
        assert result["failed_series"] == 1
        assert [item["volume"] for item in read_target()] == [9, 11]

        storage.upsert_bars("BTCUSDT", "1m", [row(180_000, 60_000, 2)], "backfill")
        seed_target()
        replace_bars = storage.replace_bars

        def replace_after_concurrent_write(*args, **kwargs):
            storage.upsert_bars("BTCUSDT", "2m", [row(120_000, 120_000, 13)], "backfill_aggregated")
            return replace_bars(*args, **kwargs)

        with monkeypatch.context() as during_commit:
            during_commit.setattr(storage, "replace_bars", replace_after_concurrent_write)
            result = await repair()
        assert result["failed_series"] == 1
        assert [item["volume"] for item in read_target()] == [9, 13]

        result = await repair()
        assert result["repaired_series"] == 1
        assert result["total_written_rows"] == 2
        repaired = read_target()
        assert [item["volume"] for item in repaired] == [2, 3]
        assert all(item["source"] == "repair_derived_verified" for item in repaired)
        assert all(item["quote_volume"] is None and item["trades"] is None for item in repaired)
        assert (await repair())["unchanged_series"] == 1
        await dm.event_bus.close()

    asyncio.run(run())
