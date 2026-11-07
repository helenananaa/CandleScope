"""Local market-trade coverage and pages for the formal replay trade clock."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from functools import lru_cache
from pathlib import Path
import sqlite3
from typing import Literal, Mapping

from app.data_engine.storage.raw_trade_archive import (
    RawAggTradeCursor, RawAggTradeDatasetRef, RawAggTradePage, RawAggTradeSelectionWindow,
)
from app.local_data.service import LocalDatasetError, LocalDatasetService
from app.local_data.user_market_trades import USER_TRADE_SOURCE

from .canonical import canonical_sha256
from .errors import ReplayDomainError, ReplayErrorCode
from .local_bar_repository import LOCAL_BAR_MARKET


LOCAL_TRADE_REF_SCHEMA = "replay.local-market-trade-dataset.v1"


@dataclass(frozen=True, slots=True)
class LocalTradeDatasetRef:
    exchange: str
    symbol: str
    revision: str
    start_time_ms: int
    end_time_ms: int
    first_source_sequence: int
    row_count: int
    schema_version: Literal["replay.local-market-trade-dataset.v1"] = LOCAL_TRADE_REF_SCHEMA
    data_epoch: str = field(init=False)
    market_type = LOCAL_BAR_MARKET
    expected_first_agg_trade_id = 1
    completeness = "user_declared_coverage"
    source_quality = USER_TRADE_SOURCE

    def __post_init__(self) -> None:
        if (self.schema_version != LOCAL_TRADE_REF_SCHEMA or self.start_time_ms > self.end_time_ms
                or self.first_source_sequence < 0 or self.row_count < 1):
            raise ValueError("Invalid local market-trade reference")
        object.__setattr__(self, "data_epoch", canonical_sha256(self._identity()))

    @property
    def expected_last_agg_trade_id(self) -> int:
        return self.row_count

    def _identity(self) -> dict[str, object]:
        return {key: getattr(self, key) for key in (
            "schema_version", "exchange", "symbol", "revision", "start_time_ms", "end_time_ms",
            "first_source_sequence", "row_count",
        )}

    def to_dict(self) -> dict[str, object]:
        return {**self._identity(), "data_epoch": self.data_epoch, "market_type": self.market_type,
                "source_quality": self.source_quality, "completeness": self.completeness}


TradeDatasetRef = RawAggTradeDatasetRef | LocalTradeDatasetRef


def decode_trade_dataset_ref(payload: Mapping[str, object]) -> TradeDatasetRef:
    if payload.get("schema_version") == LOCAL_TRADE_REF_SCHEMA:
        identity = dict(payload)
        for key in ("data_epoch", "market_type", "source_quality", "completeness"):
            identity.pop(key, None)
        ref = LocalTradeDatasetRef(**identity)
        if ref.to_dict() != payload:
            raise ValueError("Local market-trade reference identity changed")
        return ref
    return RawAggTradeDatasetRef.from_dict(payload)


class LocalReplayTradeRepository:
    enabled = True

    def __init__(self, library: LocalDatasetService) -> None:
        self._library = library
        # Reuse a validated immutable file identity across actor and display readers.
        self._validated_database = lru_cache(maxsize=32)(self._open_database)

    def diagnostics(self) -> dict[str, object]:
        return {
            "enabled": True, "state": "ready", "source_quality": USER_TRADE_SOURCE,
            "user_trade_datasets_available": any(
                row.get("source") == USER_TRADE_SOURCE for row in self._library.list_datasets()
            ),
        }

    def list_selection_windows(self, *, exchange, market_type, symbol):
        if market_type != LOCAL_BAR_MARKET:
            return ()
        try:
            manifest = self._library.get_manifest(exchange)
        except LocalDatasetError:
            return ()
        if manifest.get("source") != USER_TRADE_SOURCE or manifest["symbol"] != symbol:
            return ()
        declaration = manifest["market_trade_input"]
        return (RawAggTradeSelectionWindow(
            declaration["coverage_start_ms"], declaration["coverage_end_ms_exclusive"] - 1, 1,
        ),)

    def _open(self, exchange, symbol, revision, start_time_ms, end_time_ms):
        manifest, database = self._library.open_user_market_trade_revision(exchange, revision)
        declaration = manifest["market_trade_input"]
        if (manifest["symbol"] != symbol
                or not declaration["coverage_start_ms"] <= start_time_ms <= end_time_ms < declaration["coverage_end_ms_exclusive"]):
            raise ValueError("Local trade window does not match the pinned input")
        bounds = (start_time_ms, end_time_ms)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            first, last = (db.execute(
                f"SELECT source_sequence FROM market_trades WHERE time_ms BETWEEN ? AND ? "
                f"ORDER BY time_ms {direction}, source_sequence {direction} LIMIT 1", bounds,
            ).fetchone() for direction in ("ASC", "DESC"))
        if first is None or last is None or first[0] > last[0]:
            raise ValueError("Local trade window is empty or has invalid sequence")
        return database, first[0], last[0] - first[0] + 1

    def freeze_dataset(self, *, exchange, market_type, symbol, start_time_ms, end_time_ms,
                       source_revision, page_rows):
        if market_type != LOCAL_BAR_MARKET or source_revision is None:
            raise ValueError("A pinned imported trade revision is required")
        _, first, count = self._open(exchange, symbol, source_revision, start_time_ms, end_time_ms)
        return LocalTradeDatasetRef(exchange, symbol, source_revision, start_time_ms, end_time_ms, first, count)

    def _open_database(self, ref: LocalTradeDatasetRef) -> Path:
        database, first, count = self._open(
            ref.exchange, ref.symbol, ref.revision, ref.start_time_ms, ref.end_time_ms,
        )
        if (first, count) != (ref.first_source_sequence, ref.row_count):
            raise ValueError("Pinned local trade sequence changed")
        return database

    def validate_dataset(self, dataset_ref: TradeDatasetRef) -> None:
        if not isinstance(dataset_ref, LocalTradeDatasetRef):
            raise ValueError("Trade reference is not a local import")
        self._validated_database(dataset_ref)

    def pin_dataset(self, dataset_ref: TradeDatasetRef) -> str:
        # The local library retains prior immutable revisions when reimporting.
        self.validate_dataset(dataset_ref)
        return dataset_ref.data_epoch

    def release_dataset(self, token: str) -> None:
        # No remote cache lease is needed for a user-owned local revision.
        pass

    def scan_page(self, *, exchange, market_type, symbol, start_time_ms, end_time_ms,
                  start_agg_trade_id, end_agg_trade_id, after, limit, dataset_ref):
        ref = dataset_ref
        if (not isinstance(ref, LocalTradeDatasetRef)
                or (exchange, market_type, symbol, start_time_ms, end_time_ms)
                != (ref.exchange, ref.market_type, ref.symbol, ref.start_time_ms, ref.end_time_ms)
                or not 1 <= start_agg_trade_id <= end_agg_trade_id <= ref.row_count):
            raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Local trade page identity changed")
        database = self._validated_database(ref)
        offset = ref.first_source_sequence - 1
        start_id = max(start_agg_trade_id, after.agg_trade_id + 1) if after else start_agg_trade_id
        start_ms = max(start_time_ms, after.trade_time_ms) if after else start_time_ms
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            rows = db.execute(
                "SELECT time_ms, source_sequence, price, quantity, buyer_maker FROM market_trades "
                "WHERE time_ms BETWEEN ? AND ? AND source_sequence BETWEEN ? AND ? "
                "ORDER BY time_ms, source_sequence LIMIT ?",
                (start_ms, end_time_ms, offset + start_id, offset + end_agg_trade_id, limit),
            ).fetchall()
        result = []
        for stamp, sequence, price, quantity, maker in rows:
            ordinal = sequence - offset
            with localcontext() as context:
                context.prec = 80
                quote = format(Decimal(price) * Decimal(quantity), "f")
            result.append({
                "exchange": exchange, "market_type": market_type, "symbol": symbol,
                "agg_trade_id": ordinal, "first_trade_id": ordinal, "last_trade_id": ordinal,
                "trade_time_ms": stamp, "price": price, "quantity": quantity,
                "quote_quantity": quote, "is_buyer_maker": bool(maker), "source": USER_TRADE_SOURCE,
            })
        cursor = RawAggTradeCursor(result[-1]["trade_time_ms"], result[-1]["agg_trade_id"]) if result else after
        return RawAggTradePage(tuple(result), cursor, cursor is not None and cursor.agg_trade_id == end_agg_trade_id, ref.data_epoch)
