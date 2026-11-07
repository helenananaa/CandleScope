"""Read one explicitly declared local market-trade revision for a backtest."""
from __future__ import annotations

from typing import Any, Mapping

from app.data_engine.interval_policy import parse_interval_spec
from app.local_data.service import LocalDatasetError, LocalDatasetService
from app.local_data.user_market_trades import UserMarketTrade
from app.market_dataset.snapshot import MarketEvent, sha256_hex

from .errors import BacktestError


def open_user_trade_snapshot(
    service: LocalDatasetService,
    *,
    dataset_id: str,
    data_epoch: str,
    start_time_ms: int,
    end_time_ms: int,
    interval: str | None,
    max_events: int,
    exchange: str,
    market_type: str,
    contract_data_mode: str,
    account_model: str,
    funding_mode: str,
    include_events: bool = False,
) -> tuple[dict[str, Any], tuple[MarketEvent, ...]]:
    if (exchange != "local" or market_type != "spot" or account_model != "SPOT_CASH_V1"
            or contract_data_mode != "LEGACY_FIXED_V1" or funding_mode != "OFF"):
        raise BacktestError("FIDELITY_UNSUPPORTED", "User trade inputs require a local spot account and no external contract data")
    spec = parse_interval_spec(interval or "")
    if (spec is None or spec.nominal_ms < 60_000 or spec.nominal_ms % 60_000
            or start_time_ms <= 0 or end_time_ms < start_time_ms
            or spec.floor_ms(start_time_ms) != start_time_ms
            or spec.next_ms(spec.floor_ms(end_time_ms)) != end_time_ms + 1):
        raise BacktestError("DATA_COVERAGE_INCOMPLETE", "Select complete UTC signal bars within the declared trade coverage")
    try:
        manifest, count, rows = service.read_user_market_trades(
            dataset_id, data_epoch, start_ms=start_time_ms, end_ms=end_time_ms,
            max_rows=max_events, include_rows=include_events,
        )
    except LocalDatasetError as exc:
        raise BacktestError(exc.code, str(exc)) from exc
    identity = {
        "schema_version": "candlescope.user-market-trade-snapshot.v1",
        "dataset_id": dataset_id,
        "data_epoch": data_epoch,
        "interval": spec.canonical,
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "sqlite_sha256": manifest["sqlite_sha256"],
        "instrument": manifest["instrument"],
        "declaration": manifest["market_trade_input"],
        "row_count": count,
    }
    digest = "sha256:" + sha256_hex(identity)
    quality = {
        "status": "accepted",
        "source_event_kind": "AGG_TRADE",
        "completeness": "user_declared_coverage",
        "source_quality": "user_market_trades",
        "gap_count": 0,
        "row_count": count,
    }
    preview = {
        "data_epoch": data_epoch,
        "catalog_dataset_id": dataset_id,
        "snapshot_hash": digest,
        "coverage_start_ms": start_time_ms,
        "coverage_end_ms": end_time_ms,
        "row_count": count,
        "first_sequence": 1,
        "last_sequence": count,
        "quality": quality,
        "role_hashes": {"TRADES": digest},
        "fidelity_capabilities": ["AGG_TRADE_EXECUTION"],
        "identity": identity,
    }
    events = tuple(
        UserMarketTrade(time_ms, sequence, price, quantity, bool(maker)).event(ordinal)
        for ordinal, (time_ms, sequence, price, quantity, maker) in enumerate(rows, start=1)
    )
    return preview, events


def open_user_trade_run_snapshot(
    service: LocalDatasetService, record: Mapping[str, object], config: Mapping[str, Any], *, max_events: int,
) -> tuple[dict[str, Any], tuple[MarketEvent, ...]]:
    preview, events = open_user_trade_snapshot(
        service, dataset_id=str(record["dataset_id"]), data_epoch=str(record["data_epoch"]),
        start_time_ms=int(config["start_time_ms"]), end_time_ms=int(config["end_time_ms"]),
        interval=str(config["interval"]), max_events=max_events,
        exchange=str(config["exchange"]), market_type=str(config["market_type"]),
        contract_data_mode=str(config["contract_data_mode"]), account_model=str(config["account_model"]),
        funding_mode=str(config["funding_mode"]), include_events=True,
    )
    if preview["snapshot_hash"] != record["snapshot_hash"]:
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", "The user trade snapshot changed")
    return preview, events
