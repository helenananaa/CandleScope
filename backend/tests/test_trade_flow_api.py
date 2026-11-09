from __future__ import annotations

import asyncio
from types import SimpleNamespace

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.trade_flow import router as trade_flow_router
from app.data_engine.ingestion.models import DataSource
from app.data_engine.market_data.models import MarketChannel, MarketStreamKey
from app.data_engine.market_data.trade_flow import NormalizedAggTrade, TradeHistoryRead
from app.data_engine.storage.raw_trade_archive import (
    RawAggTradeCoverage,
    RawAggTradeGap,
)


@dataclass
class _Failure:
    status_code: int = 429
    retry_after: int = 3


class _TradeFlowDataManager:
    trade_flow_ready = True

    def __init__(self) -> None:
        self.recent_calls: list[dict] = []
        self.history_calls: list[dict] = []
        self.coverage_calls: list[dict] = []

    def trade_flow_recent(
        self,
        key: MarketStreamKey,
        **kwargs,
    ) -> list[NormalizedAggTrade]:
        self.recent_calls.append({"key": key, **kwargs})
        return [
            NormalizedAggTrade(
                exchange=key.exchange,
                market_type=key.market_type,
                symbol=key.symbol,
                agg_trade_id=101,
                price=60_000,
                quantity=0.1,
                trade_time_ms=1_700_000_000_000,
                event_time_ms=1_700_000_000_001,
                received_at_ms=1_700_000_000_002,
                is_buyer_maker=False,
                source=DataSource.WEBSOCKET,
                first_trade_id=1001,
                last_trade_id=1002,
            )
        ]

    async def read_trade_flow_history(self, key: MarketStreamKey, **kwargs) -> TradeHistoryRead:
        self.history_calls.append({"key": key, **kwargs})
        return TradeHistoryRead([
            {
                "exchange": key.exchange,
                "market_type": key.market_type,
                "symbol": key.symbol,
                "period": "1m",
                "bucket_start_ms": 1_700_000_000_000,
                "bucket_end_ms": 1_700_000_059_999,
                "volume_delta_base": 0.1,
                "is_complete": False,
                "is_final": True,
                "revision": 2,
            }
        ])

    async def trade_flow_archive_coverage(
        self,
        key: MarketStreamKey,
        **kwargs,
    ) -> RawAggTradeCoverage:
        self.coverage_calls.append({"key": key, **kwargs})
        return RawAggTradeCoverage(
            enabled=True,
            backend="parquet-pyarrow",
            exchange=key.exchange,
            market_type=key.market_type,
            symbol=key.symbol,
            start_time_ms=kwargs.get("start_time_ms"),
            end_time_ms=kwargs.get("end_time_ms"),
            row_count=2,
            file_count=1,
            earliest_agg_trade_id=101,
            latest_agg_trade_id=103,
            earliest_trade_time_ms=1_700_000_000_000,
            latest_trade_time_ms=1_700_000_000_200,
            gaps=(RawAggTradeGap(102, 102, 1),),
            complete=False,
        )


def _client(data_manager: object | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(trade_flow_router, prefix="/api/v1")
    if data_manager is not None:
        app.state.data_manager = data_manager
    return TestClient(app)


def test_trade_flow_recent_returns_raw_agg_trade_cursor() -> None:
    dm = _TradeFlowDataManager()

    response = _client(dm).get(
        "/api/v1/trade-flow/recent",
        params={"symbol": "btcusdt", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["protocol"] == "tradeflow.v1"
    assert payload["cursor"] == {
        "earliest_agg_trade_id": 101,
        "latest_agg_trade_id": 101,
    }
    assert payload["continuity"] is True
    assert payload["resync_required"] is False
    assert payload["missing_agg_trade_id_ranges"] == []
    assert payload["data"][0]["aggressor_side"] == "buy"
    assert dm.recent_calls == [
        {
            "key": MarketStreamKey.build(
                "binance",
                "futures",
                "BTCUSDT",
                MarketChannel.AGG_TRADE,
            ),
            "limit": 10,
        }
    ]


def test_trade_flow_history_is_rollup_only_and_fail_closed() -> None:
    dm = _TradeFlowDataManager()
    client = _client(dm)

    response = client.get(
        "/api/v1/trade-flow/history",
        params={"symbol": "ETHUSDT", "start_ms": 100, "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["key"]["params"] == {"period": "1m"}
    assert payload["coverage"]["all_rows_complete"] is False
    assert payload["data"][0]["volume_delta_base"] == 0.1

    invalid_period = client.get("/api/v1/trade-flow/history?period=5m")
    assert invalid_period.status_code == 422
    invalid_range = client.get(
        "/api/v1/trade-flow/history?start_ms=200&end_ms=100"
    )
    assert invalid_range.status_code == 422


def test_empty_history_does_not_claim_complete() -> None:
    class _EmptyManager(_TradeFlowDataManager):
        async def read_trade_flow_history(self, key, **kwargs):
            return TradeHistoryRead([])

    response = _client(_EmptyManager()).get("/api/v1/trade-flow/history")

    assert response.status_code == 200
    assert response.json()["coverage"]["all_rows_complete"] is False


def test_recent_snapshot_exposes_internal_id_gaps_fail_closed() -> None:
    class _GappedManager(_TradeFlowDataManager):
        def trade_flow_recent(self, key, **kwargs):
            rows = super().trade_flow_recent(key, **kwargs)
            rows.append(
                NormalizedAggTrade(
                    exchange=key.exchange,
                    market_type=key.market_type,
                    symbol=key.symbol,
                    agg_trade_id=104,
                    price=60_001,
                    quantity=0.1,
                    trade_time_ms=1_700_000_000_100,
                    event_time_ms=1_700_000_000_101,
                    received_at_ms=1_700_000_000_102,
                    is_buyer_maker=True,
                    source=DataSource.WEBSOCKET,
                    first_trade_id=1004,
                    last_trade_id=1005,
                )
            )
            return rows

    payload = _client(_GappedManager()).get(
        "/api/v1/trade-flow/recent"
    ).json()

    assert payload["continuity"] is False
    assert payload["resync_required"] is True
    assert payload["missing_agg_trade_id_ranges"] == [
        {"start_agg_trade_id": 102, "end_agg_trade_id": 103}
    ]


def test_trade_flow_archive_coverage_exposes_gaps_and_bounds() -> None:
    dm = _TradeFlowDataManager()

    response = _client(dm).get(
        "/api/v1/trade-flow/archive/coverage",
        params={
            "start_time_ms": 1_700_000_000_000,
            "end_time_ms": 1_700_000_001_000,
            "expected_start_agg_trade_id": 101,
            "expected_end_agg_trade_id": 103,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["enabled"] is True
    assert data["backend"] == "parquet-pyarrow"
    assert data["complete"] is False
    assert data["gaps"] == [
        {
            "start_agg_trade_id": 102,
            "end_agg_trade_id": 102,
            "missing_count": 1,
        }
    ]


def test_trade_flow_http_rejects_unready_and_hides_internal_errors() -> None:
    assert _client().get("/api/v1/trade-flow/recent").status_code == 503

    class _Unready:
        trade_flow_ready = False

    unready = _client(_Unready()).get("/api/v1/trade-flow/recent")
    assert unready.status_code == 503

    class _Failing(_TradeFlowDataManager):
        def trade_flow_recent(self, key, **kwargs):
            raise RuntimeError("secret upstream response")

    failed = _client(_Failing()).get("/api/v1/trade-flow/recent")
    assert failed.status_code == 502
    assert failed.json()["detail"] == (
        "trade-flow recent is temporarily unavailable"
    )


def test_real_rollup_history_only_pages_to_an_existing_local_row(tmp_path) -> None:
    from app.data_engine.market_data.trade_flow_service import TradeFlowService
    from app.data_engine.storage.raw_trade_archive import DisabledRawAggTradeArchive
    from app.data_engine.storage.trade_flow_store import SQLiteTradeFlowRollupStore
    from tests.test_trade_flow_storage import _rollup

    first = 1_700_000_040_000
    store = SQLiteTradeFlowRollupStore(tmp_path / "trades.sqlite")
    asyncio.run(store.upsert_rollups([
        _rollup(first + index * 120_000, revision=index + 1, is_final=True)
        for index in range(5001)
    ]))
    service = TradeFlowService(object(), rollup_store=store, raw_archive=DisabledRawAggTradeArchive())
    with _client(SimpleNamespace(trade_flow_ready=True, read_trade_flow_history=service.read_history)) as client:
        last = first + 5000 * 120_000
        params = {"start_ms": first, "end_ms": last, "limit": 5000}
        response = client.get("/api/v1/trade-flow/history", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["count"] == 5000 and page["has_more"] is True
        assert page["next_cursor"] == {"start_ms": last}
        assert page["coverage"]["all_rows_complete"] is True
        assert page["coverage"]["observed_only"] is True
        assert page["complete"] is page["retryable"] is False
        assert page["terminal_reason"] == "unverified_continuity"
        final = client.get("/api/v1/trade-flow/history", params={**params, **page["next_cursor"], "limit": 1}).json()
        assert final["count"] == 1 and final["has_more"] is False and final["next_cursor"] is None


def test_bounded_history_rebuilds_only_from_verified_archive_objects(tmp_path, monkeypatch) -> None:
    from datetime import datetime, timezone

    from app.core.bounded_executor import ExecutorBusyError
    from app.data_engine.market_data import trade_flow_service
    from app.data_engine.market_data.trade_flow_service import TradeFlowService
    from app.data_engine.storage.raw_trade_archive import (
        DisabledRawAggTradeArchive, ParquetRawAggTradeArchive, VerifiedRawAggTradeDay,
    )
    from app.data_engine.storage.trade_flow_store import SQLiteTradeFlowRollupStore
    from tests.test_trade_flow_storage import _raw_trade, _rollup

    first = 1_700_000_040_000
    third, fourth = first + 120_000, first + 180_000
    root = tmp_path / "replay-archive"
    archive = ParquetRawAggTradeArchive(root)
    archive_rows = [
        {**_raw_trade(i, trade_time_ms=opened + offset), "source": "binance_public"}
        for i, opened, offset in [
            (10, first, 10), (11, first, 11), (12, third, 10), (13, fourth, 10),
        ]
    ]
    # This trade is present in a best-effort file but outside the verified
    # object set. It must never alter the verified rollups.
    archive.append([_raw_trade(10, trade_time_ms=first + 10, price=900)])
    day = datetime.fromtimestamp(first / 1000, tz=timezone.utc).date()
    archive.import_verified_day(archive_rows, VerifiedRawAggTradeDay(
        exchange="binance", market_type="futures", symbol="BTCUSDT",
        date=day.isoformat(), source_url="https://data.binance.vision/example.zip",
        source_file="example.zip", source_checksum_sha256="a" * 64,
        row_count=len(archive_rows), first_agg_trade_id=10, last_agg_trade_id=13,
        first_trade_time_ms=first + 10, last_trade_time_ms=fourth + 10,
    ))

    store = SQLiteTradeFlowRollupStore(tmp_path / "trades.sqlite")
    asyncio.run(store.upsert_rollups([
        _rollup(first, revision=1, is_complete=False, is_final=True, buy_base=9),
        _rollup(third, revision=2, is_complete=True, is_final=True, buy_base=5),
    ]))
    service = TradeFlowService(
        object(), rollup_store=store, raw_archive=DisabledRawAggTradeArchive(),
        verified_archive_root=root,
    )
    with _client(SimpleNamespace(trade_flow_ready=True, read_trade_flow_history=service.read_history)) as client:
        params = {"start_ms": first, "end_ms": fourth, "limit": 2}
        response = client.get("/api/v1/trade-flow/history", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        rebuilt, existing = page["data"]
        assert rebuilt["bucket_start_ms"] == first
        assert rebuilt["source"] == "verified_archive" and rebuilt["is_complete"] and rebuilt["is_final"]
        assert rebuilt["archive_data_epoch"].startswith("sha256:")
        assert rebuilt["agg_trade_count"] == 2 and rebuilt["max_trade_notional"] == 50.0
        assert existing["bucket_start_ms"] == third and existing["buy_base_volume"] == 5.0
        assert page["next_cursor"] == {"start_ms": fourth} and page["complete"] is False

        final = client.get("/api/v1/trade-flow/history", params={**params, **page["next_cursor"]}).json()
        assert final["data"][0]["bucket_start_ms"] == fourth and final["has_more"] is False
        assert final["complete"] and final["terminal_reason"] is None
        whole = client.get("/api/v1/trade-flow/history", params={**params, "limit": 10}).json()
        assert whole["count"] == 3 and whole["complete"] and not whole["coverage"]["observed_only"]
        quiet = client.get("/api/v1/trade-flow/history", params={
            "start_ms": first + 60_000, "end_ms": first + 60_000,
        }).json()
        assert quiet["data"] == [] and quiet["complete"]
        assert quiet["coverage"]["verified_empty_minutes"] == 1
        assert quiet["coverage"]["verified_empty_ranges"] == [
            {"start_ms": first + 60_000, "end_ms": first + 60_000},
        ]
        leading = client.get("/api/v1/trade-flow/history", params={
            "start_ms": first - 120_000, "end_ms": first - 60_000,
        }).json()
        assert leading["data"] == [] and leading["complete"]
        assert leading["coverage"]["verified_empty_ranges"] == [
            {"start_ms": first - 120_000, "end_ms": first - 60_000},
        ]
        unknown = client.get("/api/v1/trade-flow/history", params={
            "start_ms": first - 86_400_000, "end_ms": first - 86_400_000,
        }).json()
        assert unknown["data"] == [] and not unknown["complete"]
        assert unknown["coverage"]["verified_empty_ranges"] == []

        # The read never replaces SQLite, and a later corrupt verified object
        # must leave the observed SQLite rows available without promotion.
        stored = asyncio.run(store.query_rollups(
            exchange="binance", market_type="futures", symbol="BTCUSDT", limit=10,
        ))
        assert len(stored) == 2 and not stored[0]["is_complete"] and stored[0]["buy_base_volume"] == 9
        asyncio.run(store.upsert_rollups([
            _rollup(first + 60_000, revision=1, is_complete=False, is_final=True, buy_base=1),
        ]))
        conflict = client.get("/api/v1/trade-flow/history", params={
            "start_ms": first + 60_000, "end_ms": first + 60_000,
        }).json()
        assert conflict["count"] == 1 and not conflict["data"][0]["is_complete"]
        assert not conflict["complete"] and conflict["coverage"]["verified_empty_ranges"] == []
        with next(root.rglob("part-verified-*.parquet")).open("ab") as corrupt:
            corrupt.write(b"changed")
        fallback = client.get("/api/v1/trade-flow/history", params=params).json()
        assert fallback["data"][0]["buy_base_volume"] == 9
        assert fallback["data"][0]["is_complete"] is False
        assert "archive_data_epoch" not in fallback["data"][0]
        assert not fallback["complete"] and fallback["coverage"]["verified_empty_ranges"] == []

        async def reject_archive(*args, **kwargs):
            raise ExecutorBusyError("archive")

        monkeypatch.setattr(trade_flow_service, "run_archive", reject_archive)
        saturated = client.get("/api/v1/trade-flow/history", params=params)
        assert saturated.status_code == 200 and saturated.json() == fallback
