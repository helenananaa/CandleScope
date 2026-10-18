from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

from app.data_engine.storage.raw_trade_archive import (
    ParquetRawAggTradeArchive,
    VerifiedRawAggTradeDay,
)

from tests.test_external_provider_http_runtime import (
    LocalHost,
    completed,
    launch_client,
    select,
    stop_client,
    wait_until,
)
from tests.test_external_provider_http_runtime import (
    fixture as fixture,  # noqa: PLC0414 - re-export shared pytest fixture
)


def test_external_http_model_receives_only_completed_trade_bars_and_host_fills_next_print(fixture, tmp_path):
    settings, local_root, _, _ = fixture
    settings = replace(settings, trade_tape_enabled=True)
    archive_dir = tmp_path / "test-aggregate-archive"
    # Deliberate test fixture, not a downloaded or qualified market archive.
    # The final real-trade BAR closes at 6, while the imported CSV closes at 14:
    # the external model must follow the authoritative trade stream.
    prices = [10, 9, 8, 12, 13, 7, 6, 6, 6]
    rows = [{"exchange": "binance", "market_type": "usdm", "symbol": "LTCUSDT",
             "agg_trade_id": 1000 + index, "first_trade_id": 2000 + index, "last_trade_id": 2000 + index,
             "price": price, "quantity": 1, "trade_time_ms": index * 60000 + 1000,
             "event_time_ms": index * 60000 + 1000, "received_at_ms": index * 60000 + 1001,
             "is_buyer_maker": False, "source": "binance_public_archive"} for index, price in enumerate(prices)]
    ParquetRawAggTradeArchive(archive_dir).import_verified_day(rows, VerifiedRawAggTradeDay(
        exchange="binance", market_type="usdm", symbol="LTCUSDT", date="1970-01-01",
        source_url="https://data.binance.vision/fixture.zip", source_file="fixture.zip", source_checksum_sha256="a" * 64,
        row_count=len(rows), first_agg_trade_id=1000, last_agg_trade_id=1008, first_trade_time_ms=1000, last_trade_time_ms=481000))
    host = LocalHost(settings, local_root, archive_dir)
    client = None
    try:
        selected, binding = select(host, fixture, fidelity_mode="AGG_TRADE_EXECUTION", end_time_ms=481000)
        client = launch_client(binding, tmp_path)
        wait_until(lambda: host.runtime.service.external.waiting_reason(binding["connection_id"]) is None)
        smoke = host.request("POST", "/provider-connections/" + binding["connection_id"] + "/smoke", selected)
        assert smoke["evaluationBars"] == 3
        created = host.request("POST", "/runs", {**selected, "external_connection_id": binding["connection_id"], "warmup_bars": 3,
                                                "symbol": "WRONGUSDT"},
                               headers={"Idempotency-Key": "external-trade-clock"})
        _, report = completed(host, created["run_id"])
        assert report["fidelity_mode"] == "AGG_TRADE_EXECUTION"
        assert [fill["sequence"] for fill in report["fills"]] == [5, 7]
        assert all(fill["reason"] == "NEXT_PRINT" for fill in report["fills"])
        assert [fill["event_time_ms"] for fill in report["fills"]] == [241000, 361000]
        net = sum((Decimal(fill["price"]) * Decimal(fill["qty"]) * (1 if fill["side"] == "SELL" else -1)
                   - Decimal(fill["fee"]) for fill in report["fills"]), Decimal(0))
        assert net == Decimal("-0.0070019")
        with host.runtime.service.external.store._read() as connection:
            calls = connection.execute("SELECT payload_json FROM external_provider_calls WHERE run_id = ? AND operation IN ('warmup', 'step') ORDER BY cursor",
                                       (created["run_id"],)).fetchall()
        observations = [json.loads(call[0])["observation"] for call in calls]
        assert len(observations) == 8
        assert Decimal(observations[-1]["features"]["close"]) == Decimal(6)
        assert all(item["bar"]["close_time_ms"] <= item["watermark_ms"] == item["event_time_ms"] for item in observations)
        assert all("trade" not in item and "book" not in item for item in observations)
        assert all(item["market"] == {"venue": "binance", "market_type": "usdm", "symbol": "LTCUSDT"}
                   for item in observations)
        with host.runtime.service.external.store._read() as connection:
            smoke_calls = connection.execute("SELECT payload_json FROM external_provider_calls WHERE run_id LIKE 'smoke_%' AND operation IN ('warmup', 'step')").fetchall()
        assert len(smoke_calls) == 6
        assert all(json.loads(call[0])["observation"]["market"] == observations[0]["market"] for call in smoke_calls)
    finally:
        if client is not None:
            stop_client(client)
        host.close()
