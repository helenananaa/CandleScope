"""Strict CSV admission for a user-declared market-wide execution stream."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.market_dataset.snapshot import MarketEvent

from .service import LocalDatasetError


USER_TRADE_SOURCE = "user_market_trades"
MINUTE_MS = 60_000
MAX_TRADE_ROWS = 200_000
MAX_UTC_MS = 253_402_300_799_999
MAX_SQLITE_INTEGER = 2**63 - 1
TRADE_COLUMNS = ("time", "sequence", "price", "quantity", "is_buyer_maker")
_UNSIGNED = re.compile(r"[0-9]{1,19}")
_DECIMAL = re.compile(r"[0-9]{1,18}(?:\.[0-9]{1,18})?")


@dataclass(frozen=True, slots=True)
class UserMarketTradeOptions:
    name: str
    symbol: str
    base_asset: str
    quote_asset: str
    timestamp_unit: str
    coverage_start_ms: int
    coverage_end_ms: int
    trade_kind: str
    dataset_id: str | None = None

    def declaration(self) -> dict[str, str | int]:
        if self.timestamp_unit not in {"s", "ms"}:
            raise LocalDatasetError("Select Unix seconds or milliseconds explicitly", code="trade_time_unit_required")
        if self.trade_kind not in {"MARKET_TRADE", "MARKET_AGG_TRADE"}:
            raise LocalDatasetError("Select a market-wide trade stream", code="trade_source_invalid")
        if (not 0 < self.coverage_start_ms < self.coverage_end_ms <= MAX_UTC_MS
                or self.coverage_start_ms % MINUTE_MS or self.coverage_end_ms % MINUTE_MS):
            raise LocalDatasetError("Coverage must be a nonempty, minute-aligned UTC interval", code="trade_coverage_invalid")
        if (self.coverage_end_ms - self.coverage_start_ms) // MINUTE_MS > MAX_TRADE_ROWS:
            raise LocalDatasetError("Trade coverage exceeds the local import limit", code="trade_import_limit")
        return {
            "schema_version": 1,
            "kind": self.trade_kind,
            "timestamp_unit": self.timestamp_unit,
            "timezone": "UTC",
            "coverage_start_ms": self.coverage_start_ms,
            "coverage_end_ms_exclusive": self.coverage_end_ms,
            "sequence_policy": "CONTIGUOUS_SOURCE_SEQUENCE",
        }


@dataclass(frozen=True, slots=True)
class UserMarketTrade:
    time_ms: int
    sequence: int
    price: str
    quantity: str
    buyer_maker: bool

    def storage_row(self) -> tuple[int, int, str, str, bool]:
        return self.time_ms, self.sequence, self.price, self.quantity, self.buyer_maker

    def event(self, ordinal: int) -> MarketEvent:
        return MarketEvent(ordinal, self.time_ms, "TRADES", {
            "source_event_kind": "AGG_TRADE",
            "source_sequence": self.sequence,
            "tie_break": f"AGG_TRADE:{self.sequence}",
            "price": self.price,
            "qty": self.quantity,
            "is_buyer_maker": self.buyer_maker,
            "agg_trade_id": self.sequence,
        })


def _decimal(value: str, *, field: str, line: int) -> str:
    if not _DECIMAL.fullmatch(value) or Decimal(value) <= 0:
        raise LocalDatasetError(f"Trade row {line} has invalid {field}", code="trade_row_invalid")
    # Normalize without rounding or depending on the process Decimal context.
    whole, separator, fraction = value.partition(".")
    fraction = fraction.rstrip("0")
    return (whole.lstrip("0") or "0") + (separator + fraction if fraction else "")


def _parse_row(columns: list[str], line: int, options: UserMarketTradeOptions) -> UserMarketTrade:
    if len(columns) != len(TRADE_COLUMNS):
        raise LocalDatasetError(f"Trade row {line} has the wrong number of columns", code="trade_row_invalid")
    stamp, sequence, price, qty, maker = (value.strip() for value in columns)
    if not _UNSIGNED.fullmatch(stamp) or not _UNSIGNED.fullmatch(sequence):
        raise LocalDatasetError(f"Trade row {line} needs an integer time and source sequence", code="trade_row_invalid")
    time_ms = int(stamp) * (1000 if options.timestamp_unit == "s" else 1)
    if not options.coverage_start_ms <= time_ms < options.coverage_end_ms:
        raise LocalDatasetError(f"Trade row {line} falls outside the declared UTC coverage. Check the timestamp unit", code="trade_time_outside_coverage")
    if int(sequence) > MAX_SQLITE_INTEGER or maker not in {"true", "false", "1", "0"}:
        raise LocalDatasetError(f"Trade row {line} has invalid sequence or maker side", code="trade_row_invalid")
    return UserMarketTrade(time_ms, int(sequence), _decimal(price, field="price", line=line),
                           _decimal(qty, field="quantity", line=line), maker in {"true", "1"})


def read_market_trade_csv(path: Path, options: UserMarketTradeOptions) -> list[UserMarketTrade]:
    rows: list[UserMarketTrade] = []
    expected_minute = options.coverage_start_ms
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            if tuple(next(reader, ())) != TRADE_COLUMNS:
                raise LocalDatasetError(
                    "Expected a market trade CSV with time,sequence,price,quantity,is_buyer_maker",
                    code="trade_columns_invalid",
                )
            for columns in reader:
                if len(rows) == MAX_TRADE_ROWS:
                    raise LocalDatasetError("Market trade CSV exceeds the row limit", code="trade_import_limit")
                row = _parse_row(columns, reader.line_num, options)
                if rows:
                    previous = rows[-1]
                    if row.sequence <= previous.sequence or row.time_ms < previous.time_ms:
                        raise LocalDatasetError(f"Trade row {reader.line_num} repeats a sequence or is out of order", code="trade_order_invalid")
                    if row.sequence != previous.sequence + 1:
                        raise LocalDatasetError(f"Trade row {reader.line_num} has a source sequence gap", code="trade_sequence_gap")
                    if row.time_ms // MINUTE_MS != previous.time_ms // MINUTE_MS:
                        expected_minute += MINUTE_MS
                if not expected_minute <= row.time_ms < expected_minute + MINUTE_MS:
                    raise LocalDatasetError(f"Trade row {reader.line_num} follows an empty 1-minute bucket", code="trade_coverage_gap")
                rows.append(row)
    except (UnicodeError, csv.Error) as exc:
        raise LocalDatasetError("Market trade CSV must be valid UTF-8 CSV", code="trade_row_invalid") from exc
    if not rows or expected_minute + MINUTE_MS != options.coverage_end_ms:
        raise LocalDatasetError("Declared coverage contains empty 1-minute buckets", code="trade_coverage_gap")
    return rows
