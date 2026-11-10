"""Optional raw ``aggTrade`` Parquet archive for deterministic replay.

The synchronous archive contract is deliberately separate from the rollup
database contract.  ``RawAggTradeArchiveWriter`` is the only async entrypoint
used by the live pipeline: it applies bounded backpressure, combines pending
batches, and sends all Parquet I/O to the shared storage executor.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import shutil
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import islice
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Protocol, runtime_checkable
from urllib.parse import quote
from uuid import uuid4

from app.core.executors import run_storage

from .raw_trade_retention_lock import ReadOnlyLeaseDirectory, partition_lease


ARCHIVE_SCHEMA_VERSION = "1"
_RETENTION_OBJECT_LIMIT = 4_096
_RETENTION_RECLAIM_MARKER = "_reclaim_started"
_RETENTION_REDOWNLOAD_STAGE = "_redownload_stage"
RAW_AGG_TRADE_COLUMNS = (
    "exchange",
    "market_type",
    "symbol",
    "agg_trade_id",
    "first_trade_id",
    "last_trade_id",
    "price",
    "quantity",
    "quote_quantity",
    "trade_time_ms",
    "event_time_ms",
    "received_at_ms",
    "is_buyer_maker",
    "source",
)

REPLAY_TRADE_DATASET_SCHEMA_VERSION = "raw-agg-trade-replay.v1"
VERIFIED_IMPORT_SCHEMA_VERSION = "binance-public-agg-trade.v1"
BAR_COMPATIBILITY_SCHEMA_VERSION = "raw-agg-trade-bar-compatibility.v1"


@dataclass(frozen=True, order=True, slots=True)
class RawAggTradeCursor:
    """Stable exclusive replay position inside an aggregate-trade archive."""

    trade_time_ms: int
    agg_trade_id: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "trade_time_ms",
            _non_negative_int(self.trade_time_ms, "trade_time_ms"),
        )
        object.__setattr__(
            self,
            "agg_trade_id",
            _non_negative_int(self.agg_trade_id, "agg_trade_id"),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "trade_time_ms": self.trade_time_ms,
            "agg_trade_id": self.agg_trade_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RawAggTradeCursor":
        if set(payload) != {"trade_time_ms", "agg_trade_id"}:
            raise ValueError("raw aggTrade cursor fields are incompatible")
        return cls(
            trade_time_ms=payload["trade_time_ms"],  # type: ignore[arg-type]
            agg_trade_id=payload["agg_trade_id"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class RawAggTradeObjectManifest:
    """Content-addressed immutable Parquet object used by one replay epoch."""

    object_id: str
    parquet_sha256: str
    manifest_sha256: str
    row_count: int
    min_agg_trade_id: int
    max_agg_trade_id: int
    min_trade_time_ms: int
    max_trade_time_ms: int
    first_trade_time_ms: int
    first_agg_trade_id: int
    source_quality: str
    source_checksum_sha256: str | None

    def __post_init__(self) -> None:
        object_id = str(self.object_id)
        if (
            not object_id
            or "\\" in object_id
            or object_id.startswith("/")
            or any(part in {"", ".", ".."} for part in object_id.split("/"))
        ):
            raise ValueError("raw aggTrade object_id must be a safe relative path")
        object.__setattr__(self, "object_id", object_id)
        for field_name in ("parquet_sha256", "manifest_sha256"):
            object.__setattr__(
                self,
                field_name,
                _sha256_digest(getattr(self, field_name), field_name),
            )
        for field_name in (
            "row_count",
            "min_agg_trade_id",
            "max_agg_trade_id",
            "min_trade_time_ms",
            "max_trade_time_ms",
            "first_trade_time_ms",
            "first_agg_trade_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name),
            )
        if self.row_count == 0:
            raise ValueError("raw aggTrade object row_count must be positive")
        if self.min_agg_trade_id > self.max_agg_trade_id:
            raise ValueError("raw aggTrade object ID bounds are inverted")
        if self.min_trade_time_ms > self.max_trade_time_ms:
            raise ValueError("raw aggTrade object time bounds are inverted")
        quality = str(self.source_quality).strip()
        if quality not in {"binance_public_checksum", "live_best_effort"}:
            raise ValueError("raw aggTrade source_quality is unsupported")
        object.__setattr__(self, "source_quality", quality)
        if self.source_checksum_sha256 is not None:
            object.__setattr__(
                self,
                "source_checksum_sha256",
                _sha256_digest(
                    self.source_checksum_sha256,
                    "source_checksum_sha256",
                ),
            )

    @property
    def first_order_key(self) -> tuple[int, int]:
        return (self.first_trade_time_ms, self.first_agg_trade_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "parquet_sha256": self.parquet_sha256,
            "manifest_sha256": self.manifest_sha256,
            "row_count": self.row_count,
            "min_agg_trade_id": self.min_agg_trade_id,
            "max_agg_trade_id": self.max_agg_trade_id,
            "min_trade_time_ms": self.min_trade_time_ms,
            "max_trade_time_ms": self.max_trade_time_ms,
            "first_trade_time_ms": self.first_trade_time_ms,
            "first_agg_trade_id": self.first_agg_trade_id,
            "source_quality": self.source_quality,
            "source_checksum_sha256": self.source_checksum_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "RawAggTradeObjectManifest":
        expected = {
            "object_id",
            "parquet_sha256",
            "manifest_sha256",
            "row_count",
            "min_agg_trade_id",
            "max_agg_trade_id",
            "min_trade_time_ms",
            "max_trade_time_ms",
            "first_trade_time_ms",
            "first_agg_trade_id",
            "source_quality",
            "source_checksum_sha256",
        }
        if set(payload) != expected:
            raise ValueError("raw aggTrade object manifest fields are incompatible")
        return cls(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class RawAggTradeDatasetRef:
    """Immutable, checksum-bound archive generation pinned by a replay session."""

    schema_version: str
    data_epoch: str
    exchange: str
    market_type: str
    symbol: str
    start_time_ms: int
    end_time_ms: int
    expected_first_agg_trade_id: int
    expected_last_agg_trade_id: int
    row_count: int
    objects: tuple[RawAggTradeObjectManifest, ...]
    completeness: str = "exact"
    source_quality: str = "binance_public_checksum"

    def __post_init__(self) -> None:
        if self.schema_version != REPLAY_TRADE_DATASET_SCHEMA_VERSION:
            raise ValueError("raw aggTrade replay dataset schema is incompatible")
        object.__setattr__(
            self,
            "data_epoch",
            _prefixed_sha256_digest(self.data_epoch, "data_epoch"),
        )
        object.__setattr__(self, "exchange", _identity(self.exchange, "exchange", lower=True))
        object.__setattr__(
            self,
            "market_type",
            _identity(self.market_type, "market_type", lower=True),
        )
        object.__setattr__(self, "symbol", _identity(self.symbol, "symbol", upper=True))
        for field_name in (
            "start_time_ms",
            "end_time_ms",
            "expected_first_agg_trade_id",
            "expected_last_agg_trade_id",
            "row_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name),
            )
        if self.start_time_ms > self.end_time_ms:
            raise ValueError("raw aggTrade replay time bounds are inverted")
        if self.expected_first_agg_trade_id > self.expected_last_agg_trade_id:
            raise ValueError("raw aggTrade replay ID bounds are inverted")
        if self.row_count != (
            self.expected_last_agg_trade_id - self.expected_first_agg_trade_id + 1
        ):
            raise ValueError("exact raw aggTrade row count must equal its ID span")
        objects = tuple(self.objects)
        if not objects or any(
            not isinstance(item, RawAggTradeObjectManifest) for item in objects
        ):
            raise ValueError("raw aggTrade replay dataset requires object manifests")
        if any(
            item.source_quality != "binance_public_checksum"
            or item.source_checksum_sha256 is None
            for item in objects
        ):
            raise ValueError(
                "raw aggTrade replay dataset contains an unverified object"
            )
        object.__setattr__(self, "objects", objects)
        if self.completeness != "exact":
            raise ValueError("raw aggTrade replay dataset must be exact")
        if self.source_quality != "binance_public_checksum":
            raise ValueError("raw aggTrade replay dataset source quality is not exact")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "data_epoch": self.data_epoch,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "expected_first_agg_trade_id": self.expected_first_agg_trade_id,
            "expected_last_agg_trade_id": self.expected_last_agg_trade_id,
            "row_count": self.row_count,
            "objects": [item.to_dict() for item in self.objects],
            "completeness": self.completeness,
            "source_quality": self.source_quality,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RawAggTradeDatasetRef":
        expected = {
            "schema_version",
            "data_epoch",
            "exchange",
            "market_type",
            "symbol",
            "start_time_ms",
            "end_time_ms",
            "expected_first_agg_trade_id",
            "expected_last_agg_trade_id",
            "row_count",
            "objects",
            "completeness",
            "source_quality",
        }
        if set(payload) != expected or not isinstance(payload["objects"], list):
            raise ValueError("raw aggTrade replay dataset fields are incompatible")
        values = dict(payload)
        values["objects"] = tuple(
            RawAggTradeObjectManifest.from_dict(item)
            for item in payload["objects"]
            if isinstance(item, Mapping)
        )
        if len(values["objects"]) != len(payload["objects"]):
            raise ValueError("raw aggTrade replay dataset contains invalid objects")
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class RawAggTradePage:
    rows: tuple[dict[str, Any], ...]
    next_cursor: RawAggTradeCursor | None
    exhausted: bool
    data_epoch: str | None


class VerifiedTradeDayRetired(RuntimeError):
    """A deliberately detached official day needs an explicit restore."""


@dataclass(frozen=True, slots=True)
class VerifiedTradeReclaimResult:
    status: str
    removed_files: int = 0
    removed_logical_bytes: int = 0
    remaining_files: int | None = None


@dataclass(frozen=True, slots=True)
class VerifiedRawAggTradeDay:
    """Validated official-source provenance supplied to the archive writer."""

    exchange: str
    market_type: str
    symbol: str
    date: str
    source_url: str
    source_file: str
    source_checksum_sha256: str
    row_count: int
    first_agg_trade_id: int
    last_agg_trade_id: int
    first_trade_time_ms: int
    last_trade_time_ms: int
    schema_version: str = VERIFIED_IMPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != VERIFIED_IMPORT_SCHEMA_VERSION:
            raise ValueError("verified aggTrade import schema is incompatible")
        object.__setattr__(self, "exchange", _identity(self.exchange, "exchange", lower=True))
        object.__setattr__(
            self,
            "market_type",
            _identity(self.market_type, "market_type", lower=True),
        )
        object.__setattr__(self, "symbol", _identity(self.symbol, "symbol", upper=True))
        _validate_utc_date(self.date)
        object.__setattr__(
            self,
            "source_checksum_sha256",
            _sha256_digest(self.source_checksum_sha256, "source_checksum_sha256"),
        )
        for field_name in (
            "row_count",
            "first_agg_trade_id",
            "last_agg_trade_id",
            "first_trade_time_ms",
            "last_trade_time_ms",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name),
            )
        if self.row_count == 0:
            raise ValueError("verified aggTrade import cannot be empty")
        if self.first_agg_trade_id > self.last_agg_trade_id:
            raise ValueError("verified aggTrade import ID bounds are inverted")
        if self.row_count != self.last_agg_trade_id - self.first_agg_trade_id + 1:
            raise ValueError("verified aggTrade import IDs must be contiguous")
        if self.first_trade_time_ms > self.last_trade_time_ms:
            raise ValueError("verified aggTrade import time bounds are inverted")

    def to_dict(self) -> dict[str, object]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class VerifiedRawAggTradeWindow:
    """Contiguous UTC coverage proven by one or more verified daily receipts."""

    start_time_ms: int
    end_time_ms: int
    first_agg_trade_id: int
    last_agg_trade_id: int
    partition_count: int

    def __post_init__(self) -> None:
        for field_name in (
            "start_time_ms",
            "end_time_ms",
            "first_agg_trade_id",
            "last_agg_trade_id",
            "partition_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name),
            )
        if self.start_time_ms > self.end_time_ms:
            raise ValueError("verified aggTrade coverage bounds are inverted")
        if self.first_agg_trade_id > self.last_agg_trade_id:
            raise ValueError("verified aggTrade coverage ID bounds are inverted")
        if self.partition_count < 1:
            raise ValueError("verified aggTrade coverage must contain a partition")


@dataclass(frozen=True, slots=True)
class RawAggTradeSelectionWindow:
    """UTC coverage eligible for selection before its body is materialized.

    A local archive derives this from verified receipts.  A remote archive may
    instead derive it from an immutable official object-availability catalog;
    unlike :class:`VerifiedRawAggTradeWindow`, it deliberately makes no claim
    about aggregate-trade ID bounds before the selected daily files are fetched
    and verified.
    """

    start_time_ms: int
    end_time_ms: int
    partition_count: int

    def __post_init__(self) -> None:
        for field_name in ("start_time_ms", "end_time_ms", "partition_count"):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name),
            )
        if self.start_time_ms > self.end_time_ms:
            raise ValueError("aggTrade selection coverage bounds are inverted")
        if self.partition_count < 1:
            raise ValueError("aggTrade selection coverage must contain a partition")


@dataclass(frozen=True, slots=True)
class VerifiedRawAggTradeBarWindow:
    """BAR-close coverage where the verified aggTrade projection passed parity."""

    start_time_ms: int
    end_time_ms: int
    bar_count: int

    def __post_init__(self) -> None:
        for field_name in ("start_time_ms", "end_time_ms", "bar_count"):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name),
            )
        if self.start_time_ms > self.end_time_ms:
            raise ValueError("verified aggTrade BAR bounds are inverted")
        if self.bar_count < 1:
            raise ValueError("verified aggTrade BAR window cannot be empty")

    def to_dict(self) -> dict[str, int]:
        return {
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "bar_count": self.bar_count,
        }


@runtime_checkable
class RawAggTradeArchive(Protocol):
    """Synchronous raw-archive backend called only from a storage worker."""

    @property
    def enabled(self) -> bool:
        """Whether raw archival is enabled."""

    def append(self, rows: Iterable[dict[str, Any]]) -> int:
        """Persist rows, returning the accepted input count.

        Backends only promise atomic publication of each immutable output
        object.  A batch spanning multiple files is not a transaction; retry
        overlap is reconciled by aggregate-trade ID during reads.
        """

    def scan_range(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        start_agg_trade_id: int | None = None,
        end_agg_trade_id: int | None = None,
        limit: int = 100_000,
    ) -> list[dict[str, Any]]:
        """Read a replay range without exposing the archive layout."""

    def scan_page(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        start_agg_trade_id: int | None = None,
        end_agg_trade_id: int | None = None,
        after: RawAggTradeCursor | None = None,
        limit: int = 50_000,
        dataset_ref: RawAggTradeDatasetRef | None = None,
        reject_id_conflicts: bool = False,
    ) -> RawAggTradePage:
        """Read one bounded page after an exclusive stable cursor."""

    def coverage(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        expected_start_agg_trade_id: int | None = None,
        expected_end_agg_trade_id: int | None = None,
    ) -> "RawAggTradeCoverage":
        """Describe ID coverage and internal gaps for replay planning."""

    def list_verified_windows(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> tuple[VerifiedRawAggTradeWindow, ...]:
        """Return exact UTC ranges backed by valid contiguous daily receipts."""

    def list_selection_windows(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> tuple[RawAggTradeSelectionWindow, ...]:
        """Return UTC ranges eligible for random selection without body scans."""

    def list_verified_bar_windows(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        interval_ms: int,
        bar_source_revision: str,
        parity_policy: Mapping[str, object],
    ) -> tuple[VerifiedRawAggTradeBarWindow, ...]:
        """Return source-revision-bound windows that passed BAR parity."""

    def publish_bar_compatibility(
        self,
        *,
        dataset_ref: RawAggTradeDatasetRef,
        interval: str,
        interval_ms: int,
        bar_source_revision: str,
        parity_policy: Mapping[str, object],
        checked_bar_count: int,
        mismatch_bar_count: int,
        compatible_windows: Iterable[VerifiedRawAggTradeBarWindow],
    ) -> dict[str, object]:
        """Atomically publish an offline BAR/aggTrade compatibility proof."""

    def diagnostics(self) -> dict[str, Any]:
        """Return archive backend state."""

    def freeze_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        page_rows: int = 50_000,
    ) -> RawAggTradeDatasetRef:
        """Build an exact immutable replay generation or fail closed."""

    def validate_dataset(self, dataset_ref: RawAggTradeDatasetRef) -> None:
        """Revalidate every object checksum in a frozen generation."""

    def pin_dataset(self, dataset_ref: RawAggTradeDatasetRef) -> str:
        """Protect one validated generation from offline retention."""

    def release_dataset(self, pin_token: str) -> None:
        """Release a previously acquired generation pin."""

    def import_verified_day(
        self,
        rows: Iterable[dict[str, Any]],
        metadata: VerifiedRawAggTradeDay,
    ) -> int:
        """Idempotently publish one checksum-verified official daily file."""


class DisabledRawAggTradeArchive:
    """Explicit no-op used when raw replay data is not configured."""

    enabled = False

    def append(self, rows: Iterable[dict[str, Any]]) -> int:
        # Consume nothing: callers may pass generators and disabled mode must
        # stay allocation-free on the high-frequency path.
        del rows
        return 0

    def scan_range(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        start_agg_trade_id: int | None = None,
        end_agg_trade_id: int | None = None,
        limit: int = 100_000,
    ) -> list[dict[str, Any]]:
        del (
            exchange,
            market_type,
            symbol,
            start_time_ms,
            end_time_ms,
            start_agg_trade_id,
            end_agg_trade_id,
            limit,
        )
        return []

    def scan_page(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        start_agg_trade_id: int | None = None,
        end_agg_trade_id: int | None = None,
        after: RawAggTradeCursor | None = None,
        limit: int = 50_000,
        dataset_ref: RawAggTradeDatasetRef | None = None,
        reject_id_conflicts: bool = False,
    ) -> RawAggTradePage:
        del (
            exchange,
            market_type,
            symbol,
            start_time_ms,
            end_time_ms,
            start_agg_trade_id,
            end_agg_trade_id,
            after,
            limit,
            reject_id_conflicts,
        )
        return RawAggTradePage(
            rows=(),
            next_cursor=None,
            exhausted=True,
            data_epoch=None if dataset_ref is None else dataset_ref.data_epoch,
        )

    def coverage(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        expected_start_agg_trade_id: int | None = None,
        expected_end_agg_trade_id: int | None = None,
    ) -> "RawAggTradeCoverage":
        complete = (
            False
            if expected_start_agg_trade_id is not None
            and expected_end_agg_trade_id is not None
            else None
        )
        return RawAggTradeCoverage(
            enabled=False,
            backend="disabled",
            exchange=str(exchange).lower(),
            market_type=str(market_type).lower(),
            symbol=str(symbol).upper(),
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            row_count=0,
            file_count=0,
            earliest_agg_trade_id=None,
            latest_agg_trade_id=None,
            earliest_trade_time_ms=None,
            latest_trade_time_ms=None,
            gaps=(),
            complete=complete,
            status="disabled",
        )

    def list_verified_windows(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> tuple[VerifiedRawAggTradeWindow, ...]:
        del exchange, market_type, symbol
        return ()

    def list_selection_windows(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> tuple[RawAggTradeSelectionWindow, ...]:
        del exchange, market_type, symbol
        return ()

    def list_verified_bar_windows(
        self,
        **_kwargs: Any,
    ) -> tuple[VerifiedRawAggTradeBarWindow, ...]:
        return ()

    def publish_bar_compatibility(self, **_kwargs: Any) -> dict[str, object]:
        raise RuntimeError("raw aggTrade archive is disabled")

    def diagnostics(self) -> dict[str, Any]:
        return {"enabled": False, "backend": "disabled"}

    def freeze_dataset(self, **_kwargs: Any) -> RawAggTradeDatasetRef:
        raise RuntimeError("raw aggTrade archive is disabled")

    def validate_dataset(self, dataset_ref: RawAggTradeDatasetRef) -> None:
        del dataset_ref
        raise RuntimeError("raw aggTrade archive is disabled")

    def pin_dataset(self, dataset_ref: RawAggTradeDatasetRef) -> str:
        del dataset_ref
        raise RuntimeError("raw aggTrade archive is disabled")

    def release_dataset(self, pin_token: str) -> None:
        del pin_token

    def import_verified_day(
        self,
        rows: Iterable[dict[str, Any]],
        metadata: VerifiedRawAggTradeDay,
    ) -> int:
        del rows, metadata
        raise RuntimeError("raw aggTrade archive is disabled")


@dataclass(frozen=True, slots=True)
class RawAggTradeGap:
    """An internal missing aggregate-trade ID interval."""

    start_agg_trade_id: int
    end_agg_trade_id: int
    missing_count: int


@dataclass(frozen=True, slots=True)
class RawAggTradeCoverage:
    """Replay coverage result; ``complete`` is unknown without expected bounds."""

    enabled: bool
    backend: str
    exchange: str
    market_type: str
    symbol: str
    start_time_ms: int | None
    end_time_ms: int | None
    row_count: int
    file_count: int
    earliest_agg_trade_id: int | None
    latest_agg_trade_id: int | None
    earliest_trade_time_ms: int | None
    latest_trade_time_ms: int | None
    gaps: tuple[RawAggTradeGap, ...]
    complete: bool | None
    status: str = "ready"
    error: str | None = None
    truncated: bool = False
    estimated_row_count: int | None = None
    estimated_physical_row_count: int | None = None
    scanned_row_count: int = 0
    limit_kind: str | None = None


@dataclass(frozen=True, slots=True)
class _FileManifest:
    path: Path
    row_count: int
    min_agg_trade_id: int
    max_agg_trade_id: int
    min_trade_time_ms: int
    max_trade_time_ms: int
    first_trade_time_ms: int
    first_agg_trade_id: int
    parquet_sha256: str | None = None
    manifest_sha256: str | None = None
    source_quality: str = "live_best_effort"
    source_checksum_sha256: str | None = None

    @property
    def first_order_key(self) -> tuple[int, int]:
        return (self.first_trade_time_ms, self.first_agg_trade_id)


class RawAggTradeScanLimitError(RuntimeError):
    """The requested archive read cannot be completed inside safety limits."""


@dataclass(frozen=True, slots=True)
class _RawTradePin:
    data_epoch: str
    partitions: frozenset[str]
    leases: ExitStack


class ParquetRawAggTradeArchive:
    """PyArrow-backed partitioned immutable micro-batch archive.

    Layout::

        exchange=binance/market_type=futures/symbol=BTCUSDT/
        date=2026-07-14/part-00000000000000000123-
        00000000000000000456-<uuid>.parquet

    Appends never reread and rewrite an ever-growing shard.  Each Parquet file
    and its metadata sidecar are separately published by atomic rename.  A
    multi-file append is deliberately *not* transactional: readers deduplicate
    retry overlap by ``agg_trade_id`` so partial retries converge eventually.
    Offline compaction may merge small files later without changing this
    contract.
    """

    enabled = True

    def __init__(
        self,
        root: Path | str,
        *,
        read_only: bool = False,
        max_rows_per_file: int = 100_000,
        compression: str = "zstd",
        scan_batch_size: int = 4096,
        max_scan_files: int = 2048,
        max_scan_rows: int = 1_000_000,
        max_physical_scan_rows: int = 5_000_000,
    ) -> None:
        self.root = Path(root)
        self.read_only = bool(read_only)
        self.max_rows_per_file = max(1, int(max_rows_per_file))
        self.compression = str(compression).strip() or "zstd"
        self.scan_batch_size = max(1, min(int(scan_batch_size), 65_536))
        self.max_scan_files = max(1, int(max_scan_files))
        self.max_scan_rows = max(1, int(max_scan_rows))
        self.max_physical_scan_rows = max(1, int(max_physical_scan_rows))
        try:
            self._pa, self._pq = _load_pyarrow()
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError(
                "raw aggTrade Parquet archive is enabled, but pyarrow is not "
                "installed; install pyarrow or disable raw trade archival"
            ) from exc
        self._schema = _parquet_schema(self._pa)
        self._write_lock = Lock()
        self._pins: dict[str, _RawTradePin] = {}
        self._pin_counts: dict[str, int] = {}
        self._health_marker_path = self.root / "_archive_health.json"
        durability_error, health_marker_error = self._load_health_marker()
        self._stats = {
            "append_calls": 0,
            "input_rows": 0,
            "files_written": 0,
            "write_failures": 0,
            "manifest_fallbacks": 0,
            "scan_limit_rejections": 0,
            "last_append_error": None,
            "durability_error": durability_error,
            "health_marker_error": health_marker_error,
            "compaction_runs": 0,
            "compaction_files_removed": 0,
            "compaction_files_written": 0,
        }

    def append(self, rows: Iterable[dict[str, Any]]) -> int:
        if self.read_only:
            raise RuntimeError("read-only raw aggTrade archive cannot append")
        payload = [_raw_trade_payload(row) for row in rows]
        if not payload:
            return 0
        groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for row in payload:
            date = _utc_date(row["trade_time_ms"])
            key = (
                row["exchange"],
                row["market_type"],
                row["symbol"],
                date,
            )
            groups.setdefault(key, []).append(row)

        with self._write_lock:
            self._stats["append_calls"] += 1
            self._stats["input_rows"] += len(payload)
            try:
                for key, grouped_rows in groups.items():
                    deduplicated = _deduplicate_raw_trades(grouped_rows)
                    for offset in range(0, len(deduplicated), self.max_rows_per_file):
                        self._write_file(
                            key,
                            deduplicated[offset : offset + self.max_rows_per_file],
                        )
            except Exception as exc:
                self._stats["write_failures"] += 1
                self._stats["last_append_error"] = str(exc)[:500]
                raise
            else:
                self._stats["last_append_error"] = None
        return len(payload)

    def compact_live_partitions(
        self,
        *,
        min_files: int = 128,
        max_input_files: int = 512,
        max_input_rows: int = 500_000,
        max_partitions: int = 1,
    ) -> dict[str, int]:
        """Compact bounded best-effort live partitions without touching receipts.

        New objects are published before old objects are removed. A crash can
        therefore leave overlap, but ordinary readers already deduplicate by
        aggregate-trade ID and a later pass converges it.
        """

        if self.read_only:
            raise RuntimeError("read-only raw aggTrade archive cannot compact")
        minimum = max(2, int(min_files))
        file_limit = max(minimum, int(max_input_files))
        row_limit = max(1, int(max_input_rows))
        partition_limit = max(1, int(max_partitions))
        summary = {
            "partitions_compacted": 0,
            "files_removed": 0,
            "files_written": 0,
            "rows_written": 0,
        }
        with self._write_lock:
            if self._pins:
                return summary
            partitions = sorted(
                path
                for path in self.root.rglob("date=*")
                if path.is_dir()
                and not (path / "_verified_import.json").exists()
                and not (path / "_verified_import_conflict.json").exists()
            )
            for partition in partitions:
                paths = sorted(partition.glob("part-*.parquet"))
                if len(paths) < minimum:
                    continue
                selected: list[Path] = []
                manifests: list[_FileManifest] = []
                input_rows = 0
                incompatible = False
                for path in paths[:file_limit]:
                    manifest = self._read_file_manifest(path)
                    if manifest.source_quality != "live_best_effort":
                        incompatible = True
                        break
                    if input_rows + manifest.row_count > row_limit:
                        break
                    selected.append(path)
                    manifests.append(manifest)
                    input_rows += manifest.row_count
                if incompatible or len(selected) < minimum:
                    continue
                estimated_output_files = (
                    input_rows + self.max_rows_per_file - 1
                ) // self.max_rows_per_file
                ordered_by_id = sorted(
                    manifests,
                    key=lambda item: (
                        item.min_agg_trade_id,
                        item.max_agg_trade_id,
                    ),
                )
                has_overlap = any(
                    current.min_agg_trade_id <= previous.max_agg_trade_id
                    for previous, current in zip(
                        ordered_by_id,
                        ordered_by_id[1:],
                    )
                )
                if estimated_output_files >= len(selected) and not has_overlap:
                    continue
                rows: list[dict[str, Any]] = []
                for manifest in manifests:
                    table = self._pq.ParquetFile(manifest.path).read(
                        columns=list(RAW_AGG_TRADE_COLUMNS),
                    )
                    rows.extend(
                        _raw_trade_payload(item)
                        for item in table.to_pylist()
                    )
                compacted = _deduplicate_raw_trades(rows)
                if not compacted:
                    continue
                relative = partition.relative_to(self.root)
                components = {
                    item.split("=", 1)[0]: item.split("=", 1)[1]
                    for item in relative.parts
                    if "=" in item
                }
                key = (
                    components["exchange"],
                    components["market_type"],
                    components["symbol"],
                    components["date"],
                )
                written: list[Path] = []
                generation = uuid4().hex
                for index, offset in enumerate(
                    range(0, len(compacted), self.max_rows_per_file)
                ):
                    chunk = compacted[offset : offset + self.max_rows_per_file]
                    written.append(
                        self._write_file(
                            key,
                            chunk,
                            deterministic_name=(
                                f"part-compacted-{generation}-{index:06d}.parquet"
                            ),
                        )
                    )
                for path in selected:
                    _manifest_path(path).unlink(missing_ok=True)
                    path.unlink(missing_ok=True)
                summary["partitions_compacted"] += 1
                summary["files_removed"] += len(selected)
                summary["files_written"] += len(written)
                summary["rows_written"] += len(compacted)
                if summary["partitions_compacted"] >= partition_limit:
                    break
            self._stats["compaction_runs"] += 1
            self._stats["compaction_files_removed"] += summary["files_removed"]
            self._stats["compaction_files_written"] += summary["files_written"]
        return summary

    def record_writer_failure(self, error: str) -> None:
        """Stickily mark possible loss after the async writer exhausts retries."""

        if self.read_only:
            raise RuntimeError(
                "read-only raw aggTrade archive cannot record writer failures"
            )
        with self._write_lock:
            durability_error = str(error)[:500]
            self._stats["durability_error"] = durability_error
            try:
                self._persist_health_marker(durability_error)
            except Exception as exc:
                # The original durability failure must remain visible even if
                # the marker cannot be published.  This method is called from
                # the writer task and therefore must never terminate it.
                marker_error = f"failed to persist health marker: {exc}"[:500]
                self._stats["health_marker_error"] = marker_error
                self._stats["durability_error"] = (
                    f"{durability_error}; {marker_error}"
                )[:500]

    def _load_health_marker(self) -> tuple[str | None, str | None]:
        try:
            if not self._health_marker_path.exists():
                return None, None
            payload = json.loads(
                self._health_marker_path.read_text(encoding="utf-8"),
            )
            if payload.get("state") != "degraded":
                raise ValueError("health marker state must be degraded")
            error = payload.get("error")
            if not isinstance(error, str) or not error.strip():
                raise ValueError("health marker error cannot be blank")
            return error[:500], None
        except Exception as exc:
            marker_error = f"archive health marker is unreadable: {exc}"[:500]
            # An unreadable marker may represent a torn/corrupt failure record;
            # never interpret it as a healthy archive.
            return marker_error, marker_error

    def _persist_health_marker(self, error: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self._health_marker_path
        temporary = destination.with_name(
            f".{destination.name}.{uuid4().hex}.tmp",
        )
        payload = {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "state": "degraded",
            "error": error,
            "recorded_at_ms": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
        }
        try:
            temporary.write_text(
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def diagnostics(self) -> dict[str, Any]:
        verified_partitions_available = self._verified_partitions_available()
        with self._write_lock:
            durability_error = self._stats["durability_error"]
            return {
                "enabled": True,
                "backend": "parquet-pyarrow",
                "read_only": self.read_only,
                "state": "degraded" if durability_error else "ready",
                "root": str(self.root),
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "max_rows_per_file": self.max_rows_per_file,
                "scan_batch_size": self.scan_batch_size,
                "max_scan_files": self.max_scan_files,
                "max_scan_rows": self.max_scan_rows,
                "max_physical_scan_rows": self.max_physical_scan_rows,
                "pinned_generations": len(self._pin_counts),
                "active_pins": len(self._pins),
                "verified_partitions_available": verified_partitions_available,
                **self._stats,
            }

    def _verified_receipt_paths(self) -> Iterable[Path]:
        return self.root.glob("exchange=*/market_type=*/symbol=*/date=*/_verified_import.json")

    def retention_lease_path(self, partition_key: str) -> Path:
        key = hashlib.sha256(partition_key.encode("utf-8")).hexdigest()
        return self.root / ".trade-retention-locks" / key

    def _enter_retention_lease(self, leases: ExitStack, partition_key: str, deadline: float) -> None:
        try:
            leases.enter_context(partition_lease(
                self.retention_lease_path(partition_key), shared=True, create=True,
                timeout_seconds=max(0.0, deadline - time.monotonic()),
            ))
        except ReadOnlyLeaseDirectory:
            # Legacy externally mounted read-only archives remain readable.
            if not self.read_only:
                raise

    def _retention_lease_busy(self, partition_key: str) -> bool:
        try:
            with partition_lease(self.retention_lease_path(partition_key), shared=False, create=False):
                return False
        except FileNotFoundError:
            return False
        except BlockingIOError:
            return True

    @staticmethod
    def _retired_partition(partition: Path) -> Path:
        # A single same-parent rename is both the visibility change and the
        # recovery record. Ordinary scans only enumerate date=*.
        return partition.with_name(f".retired-{partition.name}")

    def require_day_not_retired(self, identity: tuple[str, str, str], day: str) -> None:
        partition = self._partition_path((*identity, day))
        retired = self._retired_partition(partition)
        if retired.exists() or retired.is_symlink():
            raise VerifiedTradeDayRetired("verified trade day was retired and requires explicit restore")

    def retired_verified_days(self, identity: tuple[str, str, str]) -> tuple[date, ...]:
        days = []
        for entry in self._identity_path(identity).glob(".retired-date=????-??-??"):
            try:
                days.append(date.fromisoformat(entry.name.removeprefix(".retired-date=")))
            except ValueError:
                continue
        return tuple(sorted(days))

    @contextmanager
    def _verified_retention_leases(
        self, identity: tuple[str, str, str], day: str, partition: Path,
    ) -> Iterator[str | None]:
        blocked = "DAY_ACQUISITION_IN_PROGRESS"
        with ExitStack() as leases:
            try:
                leases.enter_context(partition_lease(
                    self.verified_day_acquisition_lock_path(identity, day), shared=False, create=True,
                ))
                blocked = "PARTITION_RETENTION_LEASE"
                leases.enter_context(partition_lease(
                    self.retention_lease_path(partition.relative_to(self.root).as_posix()),
                    shared=False, create=True,
                ))
            except BlockingIOError:
                yield blocked
            except OSError:
                yield "LEASE_UNAVAILABLE"
            else:
                yield None

    def move_verified_retention_day(
        self, *, identity: tuple[str, str, str], day: str, day_id: str, restore: bool,
        authorize: Callable[[str, str], AbstractContextManager[bool]],
    ) -> str:
        """Detach or restore an exact partition under a caller-held policy/reference fence.

        This reversible primitive preserves all bytes. The authorizer must
        retain its policy and reference fence until the context exits.
        """
        day_id = _prefixed_sha256_digest(day_id, "verified day ID")
        partition = self._partition_path((*identity, day))
        retired = self._retired_partition(partition)
        source, destination = (retired, partition) if restore else (partition, retired)
        complete = "RESTORED" if restore else "RETIRED"
        with self._verified_retention_leases(identity, day, partition) as blocked:
            if blocked is not None:
                return blocked
            if (partition.is_symlink() or retired.is_symlink()
                    or not partition.parent.resolve().is_relative_to(self.root.resolve())):
                return "PARTITION_UNSAFE"
            if not source.exists():
                existing = destination / "_verified_import.json"
                if (existing.is_file() and not existing.is_symlink()
                        and "sha256:" + _file_sha256(existing) == day_id):
                    _sync_retention_directory(destination.parent)
                    return complete
                return "STALE_RECEIPT"
            if destination.exists():
                return "DESTINATION_OCCUPIED"
            receipt_path = source / "_verified_import.json"
            if not receipt_path.is_file() or receipt_path.is_symlink():
                return "STALE_RECEIPT"
            if "sha256:" + _file_sha256(receipt_path) != day_id:
                return "STALE_RECEIPT"
            partition_key = partition.relative_to(self.root).as_posix()
            if self._has_retention_pin(partition_key):
                return "ACTIVE_DATASET_PIN"
            with authorize(partition_key, day_id) as approved:
                if not approved:
                    return "RETENTION_NOT_AUTHORIZED"
                if restore and os.path.lexists(source / _RETENTION_RECLAIM_MARKER):
                    return "RECLAIM_STARTED"
                expected = self._retention_expected_files(partition, source, (*identity, day))
                if expected is None:
                    return "PARTITION_UNSAFE"
                files = self._retention_present_files(source, expected, reclaim_started=False)
                if files is None or files.keys() != expected.keys():
                    return "PARTITION_UNSAFE"
                if any(
                    _file_sha256(file) != expected[name]
                    for name, file in files.items() if restore or name.endswith(".manifest.json")
                ):
                    return "PARTITION_UNSAFE"
                source.rename(destination)
                _sync_retention_directory(destination.parent)
                return complete

    def reclaim_retired_verified_day(
        self, *, identity: tuple[str, str, str], day: str, day_id: str,
        max_files: int, max_bytes: int,
        authorize: Callable[[str, str], AbstractContextManager[bool]],
    ) -> VerifiedTradeReclaimResult:
        """Remove a bounded batch of verified files, preserving the retired day and its receipt."""
        if type(max_files) is not int or not 1 <= max_files <= 2 * _RETENTION_OBJECT_LIMIT:
            raise ValueError("retention file budget is outside the supported range")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("retention byte budget must be positive")
        day_id = _prefixed_sha256_digest(day_id, "verified day ID")
        partition = self._partition_path((*identity, day))
        retired = self._retired_partition(partition)
        with self._verified_retention_leases(identity, day, partition) as blocked:
            if blocked is not None:
                return VerifiedTradeReclaimResult(blocked)
            if (partition.exists() or partition.is_symlink() or retired.is_symlink()
                    or not partition.parent.resolve().is_relative_to(self.root.resolve())):
                return VerifiedTradeReclaimResult("PARTITION_UNSAFE")
            receipt = retired / "_verified_import.json"
            if receipt.is_symlink() or not receipt.is_file() or "sha256:" + _file_sha256(receipt) != day_id:
                return VerifiedTradeReclaimResult("STALE_RECEIPT")
            partition_key = partition.relative_to(self.root).as_posix()
            if self._has_retention_pin(partition_key):
                return VerifiedTradeReclaimResult("ACTIVE_DATASET_PIN")
            with authorize(partition_key, day_id) as approved:
                if not approved:
                    return VerifiedTradeReclaimResult("RETENTION_NOT_AUTHORIZED")
                return self._reclaim_verified_files(partition, retired, (*identity, day), max_files, max_bytes)

    def redownload_reclaimed_verified_day(
        self, *, identity: tuple[str, str, str], day: str, day_id: str, max_restore_bytes: int,
        build: Callable[[Path, VerifiedRawAggTradeDay, int], None],
    ) -> str:
        """Publish an exact rebuilt day only through an explicit, receipt-bound request."""
        if type(max_restore_bytes) is not int or max_restore_bytes < 1:
            raise ValueError("restore byte budget must be positive")
        day_id = _prefixed_sha256_digest(day_id, "verified day ID")
        partition = self._partition_path((*identity, day))
        retired = self._retired_partition(partition)
        with self._verified_retention_leases(identity, day, partition) as blocked:
            if blocked is not None:
                return blocked
            if (partition.is_symlink() or retired.is_symlink()
                    or not partition.parent.resolve().is_relative_to(self.root.resolve())):
                return "PARTITION_UNSAFE"
            if not retired.exists():
                existing = partition / "_verified_import.json"
                if existing.is_symlink() or not existing.is_file() or "sha256:" + _file_sha256(existing) != day_id:
                    return "STALE_RECEIPT"
                self._verified_partition_receipt(partition, (*identity, day))
                _sync_retention_directory(partition.parent)
                return "RESTORED"
            if partition.exists():
                return "DESTINATION_OCCUPIED"
            receipt = retired / "_verified_import.json"
            if receipt.is_symlink() or not receipt.is_file() or "sha256:" + _file_sha256(receipt) != day_id:
                return "STALE_RECEIPT"
            if self._has_retention_pin(partition.relative_to(self.root).as_posix()):
                return "ACTIVE_DATASET_PIN"
            return self._redownload_verified_files(partition, retired, (*identity, day), max_restore_bytes, build)

    def _redownload_verified_files(
        self, partition: Path, retired: Path, identity_day: tuple[str, str, str, str],
        max_restore_bytes: int, build: Callable[[Path, VerifiedRawAggTradeDay, int], None],
    ) -> str:
        marker = retired / _RETENTION_RECLAIM_MARKER
        stage = retired / _RETENTION_REDOWNLOAD_STAGE
        started = os.path.lexists(marker)
        if started and (marker.is_symlink() or not marker.is_file() or marker.stat().st_size):
            return "PARTITION_UNSAFE"
        if stage.is_symlink() or (stage.exists() and (not started or not stage.is_dir())):
            return "PARTITION_UNSAFE"
        expected = self._retention_expected_files(partition, retired, identity_day)
        if expected is None:
            return "PARTITION_UNSAFE"
        files = self._retention_present_files(
            retired, expected, reclaim_started=started, redownload_staged=stage.exists(),
        )
        if files is None or any(_file_sha256(file) != expected[name] for name, file in files.items()):
            return "PARTITION_UNSAFE"
        missing = expected.keys() - files.keys()
        if missing and not started:
            return "PARTITION_UNSAFE"

        rebuilt = {}
        if missing:
            original = self._read_verified_receipt(retired / "_verified_import.json")
            staged_day = stage / partition.relative_to(self.root)
            if not staged_day.resolve().is_relative_to(stage.resolve()):
                return "PARTITION_UNSAFE"
            rebuilt = self._redownload_staged_files(staged_day, original, expected, missing)
            if rebuilt is None:
                if stage.exists():
                    shutil.rmtree(stage)
                stage.mkdir()
                try:
                    metadata, objects = original["metadata"], original["objects"]
                    assert isinstance(metadata, Mapping) and isinstance(objects, list)
                    first_object = RawAggTradeObjectManifest.from_dict(objects[0])
                    build(stage, VerifiedRawAggTradeDay(**metadata), first_object.row_count)
                    rebuilt = self._redownload_staged_files(staged_day, original, expected, missing)
                except Exception:
                    shutil.rmtree(stage)
                    raise
                if rebuilt is None:
                    shutil.rmtree(stage)
                    return "REDOWNLOAD_RECEIPT_MISMATCH"
        if sum(file.stat().st_size for file in (*files.values(), *rebuilt.values())) > max_restore_bytes:
            if stage.exists():
                shutil.rmtree(stage)
            return "RESTORE_BUDGET_EXCEEDED"

        for name, file in sorted(rebuilt.items()):
            with file.open("r+b") as handle:
                os.fsync(handle.fileno())
            file.replace(retired / name)
        _sync_retention_directory(retired)
        if stage.exists():
            shutil.rmtree(stage)
        if started:
            marker.unlink()
        _sync_retention_directory(retired)
        retired.rename(partition)
        _sync_retention_directory(partition.parent)
        return "RESTORED"

    def _redownload_staged_files(
        self, staged_day: Path, original: Mapping[str, object], expected: Mapping[str, str],
        missing: set[str],
    ) -> dict[str, Path] | None:
        receipt = staged_day / "_verified_import.json"
        if not receipt.is_file() or receipt.is_symlink():
            return None
        try:
            if self._read_verified_receipt(receipt) != original:
                return None
        except (OSError, RuntimeError, ValueError):
            return None
        files = self._retention_present_files(staged_day, expected, reclaim_started=False)
        if files is None or not missing <= files.keys():
            return None
        needed = {name: files[name] for name in missing}
        if any(_file_sha256(file) != expected[name] for name, file in needed.items()):
            return None
        return needed

    def _has_retention_pin(self, partition_key: str) -> bool:
        with self._write_lock:
            return any(partition_key in pin.partitions for pin in self._pins.values())

    def _retention_expected_files(
        self, partition: Path, source: Path, identity_day: tuple[str, str, str, str],
    ) -> dict[str, str] | None:
        receipt = self._read_verified_receipt(source / "_verified_import.json")
        metadata, objects = receipt["metadata"], receipt["objects"]
        assert isinstance(metadata, Mapping) and isinstance(objects, list)
        if tuple(metadata[key] for key in ("exchange", "market_type", "symbol", "date")) != identity_day:
            return None
        if len(objects) > _RETENTION_OBJECT_LIMIT:
            return None
        expected: dict[str, str] = {}
        for raw in objects:
            item = RawAggTradeObjectManifest.from_dict(raw)
            path = self.root / item.object_id
            if (path.parent != partition or not path.name.startswith("part-verified-")
                    or path.suffix != ".parquet" or path.name in expected
                    or item.source_quality != "binance_public_checksum"
                    or item.source_checksum_sha256 != metadata["source_checksum_sha256"]):
                return None
            expected[path.name] = item.parquet_sha256
            expected[_manifest_path(path).name] = item.manifest_sha256
        return expected

    @staticmethod
    def _retention_present_files(
        source: Path, expected: Mapping[str, str], *, reclaim_started: bool, redownload_staged: bool = False,
    ) -> dict[str, Path] | None:
        metadata = {"_verified_import.json"}
        if reclaim_started:
            metadata.add(_RETENTION_RECLAIM_MARKER)
        if redownload_staged:
            metadata.add(_RETENTION_REDOWNLOAD_STAGE)
        files = {}
        for entry in islice(source.iterdir(), len(expected) + len(metadata) + 1):
            if entry.name in metadata:
                continue
            if entry.name not in expected or entry.is_symlink() or not entry.is_file():
                return None
            files[entry.name] = entry
        return files

    def _reclaim_verified_files(
        self, partition: Path, retired: Path, identity_day: tuple[str, str, str, str],
        max_files: int, max_bytes: int,
    ) -> VerifiedTradeReclaimResult:
        marker = retired / _RETENTION_RECLAIM_MARKER
        started = os.path.lexists(marker)
        if started and (marker.is_symlink() or not marker.is_file() or marker.stat().st_size):
            return VerifiedTradeReclaimResult("PARTITION_UNSAFE")
        expected = self._retention_expected_files(partition, retired, identity_day)
        if expected is None:
            return VerifiedTradeReclaimResult("PARTITION_UNSAFE")
        files = self._retention_present_files(retired, expected, reclaim_started=started)
        if files is None or (not started and files.keys() != expected.keys()):
            return VerifiedTradeReclaimResult("PARTITION_UNSAFE")
        if not files:
            _sync_retention_directory(retired)
            return VerifiedTradeReclaimResult("RECLAIMED", remaining_files=0)

        selected: list[Path] = []
        remaining_budget = max_bytes
        for name in sorted(files)[:max_files]:
            file = files[name]
            size = file.stat().st_size
            if size > remaining_budget:
                break
            if _file_sha256(file) != expected[name]:
                return VerifiedTradeReclaimResult("PARTITION_UNSAFE")
            selected.append(file)
            remaining_budget -= size
        if not selected:
            return VerifiedTradeReclaimResult("RECLAIM_PENDING", remaining_files=len(files))

        # The durable empty marker forbids restore before the first unlink.
        # After interruption the receipt still describes exactly what may be removed.
        if not started:
            with marker.open("xb") as handle:
                os.fsync(handle.fileno())
        _sync_retention_directory(retired)
        for file in selected:
            file.unlink()
        _sync_retention_directory(retired)
        remaining = len(files) - len(selected)
        return VerifiedTradeReclaimResult(
            "RECLAIM_PENDING" if remaining else "RECLAIMED",
            len(selected), max_bytes - remaining_budget, remaining,
        )

    def _verified_retention_item(
        self, receipt_path: Path, receipt: dict[str, object], *, observe_locks: bool = True,
    ) -> dict[str, Any]:
        partition = receipt_path.parent
        metadata = receipt["metadata"]
        objects = receipt["objects"]
        assert isinstance(metadata, Mapping) and isinstance(objects, list)
        identity = (str(metadata["exchange"]), str(metadata["market_type"]), str(metadata["symbol"]))
        day = str(metadata["date"])
        if self._partition_path((*identity, day)) != partition:
            raise RuntimeError("verified receipt does not match its partition")
        self._validate_verified_receipt_objects(partition, receipt, verify_parquet=False)
        byte_size = receipt_path.stat().st_size
        for item in objects:
            path = self._resolve_object_path(str(item["object_id"]))
            byte_size += path.stat().st_size + _manifest_path(path).stat().st_size
        partition_key = partition.relative_to(self.root).as_posix()
        reasons = ["UNMANAGED_RETENTION_POLICY"]
        if (partition / "_verified_import_conflict.json").exists():
            reasons.append("QUARANTINED_DAY")
        lease_busy = False
        if observe_locks:
            lease_busy = self._retention_lease_busy(partition_key)
            if lease_busy:
                reasons.append("PARTITION_RETENTION_LEASE")
            day_start = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
            if self.verified_day_acquisition_pending(identity, (day_start, day_start)):
                reasons.append("DAY_ACQUISITION_IN_PROGRESS")
        return {
            "partition_key": partition_key,
            "day_id": "sha256:" + _file_sha256(receipt_path),
            "identity": dict(zip(("exchange", "market_type", "symbol"), identity)),
            "object_count": len(objects),
            "byte_size": byte_size,
            "retention_lease_busy": lease_busy,
            "protection_reasons": reasons,
        }

    def verified_retention_inventory(self, *, limit: int) -> dict[str, Any]:
        """Inspect committed day objects without refreshing access or opening their bodies."""
        with self._write_lock:
            pins = Counter(partition for pin in self._pins.values() for partition in pin.partitions)
        paths = list(islice(self._verified_receipt_paths(), limit + 1))
        items: list[dict[str, object]] = []
        unreadable = 0
        objects_left = _RETENTION_OBJECT_LIMIT
        truncated = len(paths) > limit
        for receipt_path in sorted(paths[:limit]):
            try:
                receipt = self._read_verified_receipt(receipt_path)
                objects = receipt["objects"]
                assert isinstance(objects, list)
                if len(objects) > objects_left:
                    truncated = True
                    continue
                objects_left -= len(objects)
                item = self._verified_retention_item(receipt_path, receipt)
            except (KeyError, OSError, OverflowError, RuntimeError, TypeError, ValueError):
                unreadable += 1
                continue
            count = pins[item["partition_key"]]
            if count:
                item["protection_reasons"].insert(1, "ACTIVE_DATASET_PIN")
            item["active_pin_count"] = count
            items.append(item)
        return {"items": items, "unreadable_day_count": unreadable, "truncated": truncated}

    @contextmanager
    def verified_retention_recheck(
        self, *, day_id: str, limit: int,
    ) -> Iterator[tuple[str, dict[str, Any] | None]]:
        """Revalidate a preview candidate while day publishers and partition readers are fenced."""
        inventory = self.verified_retention_inventory(limit=limit)
        selected = next((item for item in inventory["items"] if item["day_id"] == day_id), None)
        if selected is None:
            yield "STALE_OR_OUTSIDE_SCAN", None
            return
        partition_key = selected["partition_key"]
        partition = self.root / partition_key
        day = partition.name.removeprefix("date=")
        identity = selected["identity"]
        with self._verified_retention_leases(
            (identity["exchange"], identity["market_type"], identity["symbol"]), day, partition,
        ) as blocked:
            if blocked is not None:
                yield blocked, None
                return
            item = None
            try:
                receipt_path = partition / "_verified_import.json"
                receipt = self._read_verified_receipt(receipt_path)
                objects = receipt["objects"]
                assert isinstance(objects, list)
                if len(objects) <= _RETENTION_OBJECT_LIMIT:
                    item = self._verified_retention_item(receipt_path, receipt, observe_locks=False)
            except (KeyError, OSError, OverflowError, RuntimeError, TypeError, ValueError):
                pass
            if item is None or item["day_id"] != day_id:
                yield "STALE_OR_OUTSIDE_SCAN", None
                return
            with self._write_lock:
                count = sum(partition_key in pin.partitions for pin in self._pins.values())
            item["active_pin_count"] = count
            if count:
                item["protection_reasons"].append("ACTIVE_DATASET_PIN")
            yield "RECHECKED", item

    def list_verified_identities(self) -> list[dict[str, str]]:
        identities: dict[tuple[str, str, str], dict[str, str]] = {}
        for receipt_path in self._verified_receipt_paths():
            if (receipt_path.parent / "_verified_import_conflict.json").exists():
                continue
            try:
                receipt = self._read_verified_receipt(receipt_path)
                metadata = receipt["metadata"]
                assert isinstance(metadata, Mapping)
                identity = (
                    str(metadata["exchange"]),
                    str(metadata["market_type"]),
                    str(metadata["symbol"]),
                )
                if identity in identities:
                    continue
                identity_day = (*identity, str(metadata["date"]))
                if self._partition_path(identity_day) != receipt_path.parent:
                    continue
                self._validate_verified_receipt_objects(
                    receipt_path.parent, receipt, verify_parquet=False,
                )
            except (AssertionError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                continue
            identities[identity] = {
                "exchange": identity[0],
                "market_type": identity[1],
                "symbol": identity[2],
            }
        return [identities[key] for key in sorted(identities)]

    def has_verified_day(self, *, exchange: str, market_type: str, symbol: str, day: str,
                         allow_repair: bool = False) -> bool:
        """Check one committed partition and its objects without scanning other days."""
        identity = (
            _identity(exchange, "exchange", lower=True),
            _identity(market_type, "market_type", lower=True),
            _identity(symbol, "symbol", upper=True),
        )
        self.require_day_not_retired(identity, day)
        partition = self._partition_path((*identity, day))
        if (partition / "_verified_import_conflict.json").exists():
            raise RuntimeError("checksum-verified raw aggTrade partition is quarantined")
        if not (partition / "_verified_import.json").is_file():
            return False
        try:
            self._verified_partition_receipt(partition, (*identity, day))
        except (OSError, RuntimeError, ValueError):
            if not allow_repair:
                raise
            return False
        return True

    def verified_day_acquisition_lock_path(self, identity: tuple[str, str, str], day: str) -> Path:
        """Use stable, bounded lock slots shared by the day publishers and readers."""
        slot = hashlib.blake2b("\0".join((*identity, day)).encode(), digest_size=1).hexdigest()
        return self.root / ".trade-day-locks" / slot

    def verified_day_acquisition_pending(
        self, identity: tuple[str, str, str], time_bounds: tuple[int, int],
    ) -> bool:
        """Observe an existing publisher lock without creating files or waiting on it."""
        first, last = (bound // 86_400_000 for bound in time_bounds)
        for day in range(first, last + 1):
            day_text = datetime.fromtimestamp(day * 86_400, tz=timezone.utc).date().isoformat()
            path = self.verified_day_acquisition_lock_path(identity, day_text)
            try:
                handle = path.open("rb")
            except FileNotFoundError:
                continue
            with handle:
                try:
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                        return True
                    raise
        return False

    def list_verified_windows(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> tuple[VerifiedRawAggTradeWindow, ...]:
        """Verify receipts and bodies, then merge truly contiguous UTC days.

        A verified daily receipt proves the full UTC partition, including quiet
        time before its first trade and after its last trade. Adjacent days are
        merged only when their aggregate-trade IDs are also contiguous, so a
        replay window can never cross an unresolved source gap.
        """
        return self._verified_windows(
            exchange=exchange, market_type=market_type, symbol=symbol, verify_parquet=True,
        )

    def _verified_windows(
        self, *, exchange: str, market_type: str, symbol: str, verify_parquet: bool,
    ) -> tuple[VerifiedRawAggTradeWindow, ...]:
        identity = (
            _identity(exchange, "exchange", lower=True),
            _identity(market_type, "market_type", lower=True),
            _identity(symbol, "symbol", upper=True),
        )
        identity_root = (
            self.root
            / f"exchange={_partition_value(identity[0])}"
            / f"market_type={_partition_value(identity[1])}"
            / f"symbol={_partition_value(identity[2])}"
        )
        daily_windows: list[VerifiedRawAggTradeWindow] = []
        for receipt_path in sorted(identity_root.glob("date=*/_verified_import.json")):
            partition = receipt_path.parent
            if (partition / "_verified_import_conflict.json").exists():
                continue
            try:
                date_component = partition.name
                if not date_component.startswith("date="):
                    continue
                date = date_component.removeprefix("date=")
                _validate_utc_date(date)
                receipt = self._verified_partition_receipt(
                    partition, (*identity, date), verify_parquet=verify_parquet,
                )
                metadata = receipt["metadata"]
                assert isinstance(metadata, Mapping)
                day_start = int(
                    datetime.strptime(date, "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                    * 1_000
                )
                daily_windows.append(
                    VerifiedRawAggTradeWindow(
                        start_time_ms=day_start,
                        end_time_ms=day_start + 86_400_000 - 1,
                        first_agg_trade_id=int(metadata["first_agg_trade_id"]),
                        last_agg_trade_id=int(metadata["last_agg_trade_id"]),
                        partition_count=1,
                    )
                )
            except (
                AssertionError,
                KeyError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                # Planning is fail-closed per partition. The exact freeze path
                # still revalidates every selected Parquet object and checksum.
                continue

        merged: list[VerifiedRawAggTradeWindow] = []
        for current in daily_windows:
            if (
                merged
                and current.start_time_ms == merged[-1].end_time_ms + 1
                and current.first_agg_trade_id == merged[-1].last_agg_trade_id + 1
            ):
                previous = merged[-1]
                merged[-1] = VerifiedRawAggTradeWindow(
                    start_time_ms=previous.start_time_ms,
                    end_time_ms=current.end_time_ms,
                    first_agg_trade_id=previous.first_agg_trade_id,
                    last_agg_trade_id=current.last_agg_trade_id,
                    partition_count=(
                        previous.partition_count + current.partition_count
                    ),
                )
            else:
                merged.append(current)
        return tuple(merged)

    def list_selection_windows(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        verify_parquet: bool = True,
    ) -> tuple[RawAggTradeSelectionWindow, ...]:
        """List committed candidates, optionally deferring body checks to freeze."""

        return tuple(
            RawAggTradeSelectionWindow(
                start_time_ms=item.start_time_ms,
                end_time_ms=item.end_time_ms,
                partition_count=item.partition_count,
            )
            for item in self._verified_windows(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                verify_parquet=verify_parquet,
            )
        )

    def list_verified_bar_windows(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        interval_ms: int,
        bar_source_revision: str,
        parity_policy: Mapping[str, object],
    ) -> tuple[VerifiedRawAggTradeBarWindow, ...]:
        identity = (
            _identity(exchange, "exchange", lower=True),
            _identity(market_type, "market_type", lower=True),
            _identity(symbol, "symbol", upper=True),
        )
        normalized_interval = _identity(interval, "interval")
        normalized_interval_ms = _non_negative_int(interval_ms, "interval_ms")
        if normalized_interval_ms < 1:
            raise ValueError("interval_ms must be positive")
        revision = _prefixed_sha256_digest(
            bar_source_revision,
            "bar_source_revision",
        )
        policy = _normalized_json_mapping(parity_policy, "parity_policy")
        legacy_path = self._bar_compatibility_path(
            identity=identity,
            interval=normalized_interval,
            bar_source_revision=revision,
        )
        directory = self._bar_compatibility_directory(
            identity=identity,
            interval=normalized_interval,
            bar_source_revision=revision,
        )
        paths = (
            ([legacy_path] if legacy_path.is_file() else [])
            + (
                sorted(directory.glob("*.json"))
                if directory.is_dir()
                else []
            )
        )
        if not paths:
            return ()
        records: list[
            tuple[
                RawAggTradeDatasetRef,
                tuple[VerifiedRawAggTradeBarWindow, ...],
                str,
            ]
        ] = []
        seen_epochs: set[str] = set()
        for path in paths:
            dataset_ref, windows, index_epoch = (
                self._read_bar_compatibility_index(
                    path,
                    identity=identity,
                    interval=normalized_interval,
                    interval_ms=normalized_interval_ms,
                    bar_source_revision=revision,
                    parity_policy=policy,
                )
            )
            if index_epoch in seen_epochs:
                continue
            seen_epochs.add(index_epoch)
            records.append((dataset_ref, windows, index_epoch))
        records.sort(
            key=lambda item: (
                item[0].start_time_ms,
                item[0].end_time_ms,
                item[2],
            )
        )
        previous_dataset_end: int | None = None
        combined: list[VerifiedRawAggTradeBarWindow] = []
        for dataset_ref, windows, _index_epoch in records:
            if (
                previous_dataset_end is not None
                and dataset_ref.start_time_ms <= previous_dataset_end
            ):
                raise RuntimeError(
                    "aggregate-trade BAR compatibility indexes overlap"
                )
            previous_dataset_end = dataset_ref.end_time_ms
            combined.extend(windows)
        return tuple(combined)

    def _read_bar_compatibility_index(
        self,
        path: Path,
        *,
        identity: tuple[str, str, str],
        interval: str,
        interval_ms: int,
        bar_source_revision: str,
        parity_policy: Mapping[str, object],
    ) -> tuple[
        RawAggTradeDatasetRef,
        tuple[VerifiedRawAggTradeBarWindow, ...],
        str,
    ]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "aggregate-trade BAR compatibility index is unreadable"
            ) from exc
        expected_fields = {
            "schema_version",
            "identity",
            "interval",
            "interval_ms",
            "bar_source_revision",
            "parity_policy",
            "raw_dataset_ref",
            "checked_bar_count",
            "mismatch_bar_count",
            "compatible_windows",
            "index_epoch",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise RuntimeError(
                "aggregate-trade BAR compatibility index schema is invalid"
            )
        unsigned = {
            key: value
            for key, value in payload.items()
            if key != "index_epoch"
        }
        if (
            payload["schema_version"] != BAR_COMPATIBILITY_SCHEMA_VERSION
            or payload["identity"]
            != {
                "exchange": identity[0],
                "market_type": identity[1],
                "symbol": identity[2],
            }
            or payload["interval"] != interval
            or payload["interval_ms"] != interval_ms
            or payload["bar_source_revision"] != bar_source_revision
            or payload["parity_policy"] != parity_policy
            or payload["index_epoch"] != _canonical_sha256(unsigned)
            or not isinstance(payload["raw_dataset_ref"], Mapping)
            or not isinstance(payload["compatible_windows"], list)
        ):
            raise RuntimeError(
                "aggregate-trade BAR compatibility index identity changed"
            )
        dataset_ref = RawAggTradeDatasetRef.from_dict(
            payload["raw_dataset_ref"]
        )
        self._validate_compatibility_dataset_ref(
            dataset_ref,
            identity=identity,
        )
        checked = _non_negative_int(
            payload["checked_bar_count"],
            "checked_bar_count",
        )
        mismatches = _non_negative_int(
            payload["mismatch_bar_count"],
            "mismatch_bar_count",
        )
        windows = tuple(
            VerifiedRawAggTradeBarWindow(**item)
            for item in payload["compatible_windows"]
            if isinstance(item, Mapping)
        )
        if len(windows) != len(payload["compatible_windows"]):
            raise RuntimeError(
                "aggregate-trade BAR compatibility windows are invalid"
            )
        self._validate_bar_compatibility_windows(
            windows,
            dataset_ref=dataset_ref,
            interval_ms=interval_ms,
            checked_bar_count=checked,
            mismatch_bar_count=mismatches,
        )
        return dataset_ref, windows, str(payload["index_epoch"])

    def publish_bar_compatibility(
        self,
        *,
        dataset_ref: RawAggTradeDatasetRef,
        interval: str,
        interval_ms: int,
        bar_source_revision: str,
        parity_policy: Mapping[str, object],
        checked_bar_count: int,
        mismatch_bar_count: int,
        compatible_windows: Iterable[VerifiedRawAggTradeBarWindow],
    ) -> dict[str, object]:
        if self.read_only:
            raise RuntimeError(
                "read-only raw aggTrade archive cannot publish compatibility"
            )
        if not isinstance(dataset_ref, RawAggTradeDatasetRef):
            raise TypeError("dataset_ref must be RawAggTradeDatasetRef")
        normalized_interval = _identity(interval, "interval")
        normalized_interval_ms = _non_negative_int(interval_ms, "interval_ms")
        if normalized_interval_ms < 1:
            raise ValueError("interval_ms must be positive")
        revision = _prefixed_sha256_digest(
            bar_source_revision,
            "bar_source_revision",
        )
        policy = _normalized_json_mapping(parity_policy, "parity_policy")
        checked = _non_negative_int(checked_bar_count, "checked_bar_count")
        mismatches = _non_negative_int(
            mismatch_bar_count,
            "mismatch_bar_count",
        )
        windows = tuple(compatible_windows)
        identity = (
            dataset_ref.exchange,
            dataset_ref.market_type,
            dataset_ref.symbol,
        )
        self.validate_dataset(dataset_ref)
        self._validate_bar_compatibility_windows(
            windows,
            dataset_ref=dataset_ref,
            interval_ms=normalized_interval_ms,
            checked_bar_count=checked,
            mismatch_bar_count=mismatches,
        )
        payload: dict[str, object] = {
            "schema_version": BAR_COMPATIBILITY_SCHEMA_VERSION,
            "identity": {
                "exchange": identity[0],
                "market_type": identity[1],
                "symbol": identity[2],
            },
            "interval": normalized_interval,
            "interval_ms": normalized_interval_ms,
            "bar_source_revision": revision,
            "parity_policy": policy,
            "raw_dataset_ref": dataset_ref.to_dict(),
            "checked_bar_count": checked,
            "mismatch_bar_count": mismatches,
            "compatible_windows": [item.to_dict() for item in windows],
        }
        payload["index_epoch"] = _canonical_sha256(payload)
        policy_epoch = _canonical_sha256(policy)
        directory = self._bar_compatibility_directory(
            identity=identity,
            interval=normalized_interval,
            bar_source_revision=revision,
        )
        path = directory / (
            f"{dataset_ref.data_epoch.removeprefix('sha256:')}-"
            f"{policy_epoch.removeprefix('sha256:')}.json"
        )
        if path.is_file():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    "existing aggregate-trade BAR compatibility index is unreadable"
                ) from exc
            if current != payload:
                raise RuntimeError(
                    "aggregate-trade BAR compatibility index conflicts with "
                    "an existing immutable proof"
                )
        else:
            _atomic_write_json(path, payload)
        return {
            "path": str(path),
            "index_epoch": payload["index_epoch"],
            "checked_bar_count": checked,
            "mismatch_bar_count": mismatches,
            "compatible_window_count": len(windows),
            "eligible_bar_count": checked - mismatches,
        }

    def _bar_compatibility_path(
        self,
        *,
        identity: tuple[str, str, str],
        interval: str,
        bar_source_revision: str,
    ) -> Path:
        return (
            self.root
            / "_bar_compatibility"
            / f"exchange={_partition_value(identity[0])}"
            / f"market_type={_partition_value(identity[1])}"
            / f"symbol={_partition_value(identity[2])}"
            / f"interval={_partition_value(interval)}"
            / f"{bar_source_revision.removeprefix('sha256:')}.json"
        )

    def _bar_compatibility_directory(
        self,
        *,
        identity: tuple[str, str, str],
        interval: str,
        bar_source_revision: str,
    ) -> Path:
        return self._bar_compatibility_path(
            identity=identity,
            interval=interval,
            bar_source_revision=bar_source_revision,
        ).with_suffix("")

    def _validate_compatibility_dataset_ref(
        self,
        dataset_ref: RawAggTradeDatasetRef,
        *,
        identity: tuple[str, str, str],
    ) -> None:
        if (
            dataset_ref.exchange,
            dataset_ref.market_type,
            dataset_ref.symbol,
        ) != identity:
            raise RuntimeError(
                "aggregate-trade BAR compatibility source identity changed"
            )
        expected_epoch = self._dataset_epoch(
            identity=identity,
            start_time_ms=dataset_ref.start_time_ms,
            end_time_ms=dataset_ref.end_time_ms,
            first_agg_trade_id=dataset_ref.expected_first_agg_trade_id,
            last_agg_trade_id=dataset_ref.expected_last_agg_trade_id,
            objects=dataset_ref.objects,
        )
        if dataset_ref.data_epoch != expected_epoch:
            raise RuntimeError(
                "aggregate-trade BAR compatibility source epoch changed"
            )
        with ExitStack() as leases:
            manifests = self._discover_verified_manifests(
                leases=leases,
                exchange=identity[0],
                market_type=identity[1],
                symbol=identity[2],
                start_time_ms=dataset_ref.start_time_ms,
                end_time_ms=dataset_ref.end_time_ms,
            )
            current_objects = tuple(self._object_manifest(item) for item in manifests)
        if current_objects != dataset_ref.objects:
            raise RuntimeError(
                "aggregate-trade BAR compatibility source object changed"
            )

    @staticmethod
    def _validate_bar_compatibility_windows(
        windows: tuple[VerifiedRawAggTradeBarWindow, ...],
        *,
        dataset_ref: RawAggTradeDatasetRef,
        interval_ms: int,
        checked_bar_count: int,
        mismatch_bar_count: int,
    ) -> None:
        if (
            dataset_ref.start_time_ms % interval_ms != 0
            or (dataset_ref.end_time_ms + 1) % interval_ms != 0
        ):
            raise ValueError(
                "aggregate-trade compatibility range is not BAR aligned"
            )
        expected_checked = (
            (dataset_ref.end_time_ms - dataset_ref.start_time_ms + 1)
            // interval_ms
        )
        if checked_bar_count != expected_checked:
            raise ValueError(
                "aggregate-trade compatibility checked BAR count changed"
            )
        if mismatch_bar_count > checked_bar_count:
            raise ValueError(
                "aggregate-trade compatibility mismatch count is invalid"
            )
        previous_end: int | None = None
        matched = 0
        for window in windows:
            if not isinstance(window, VerifiedRawAggTradeBarWindow):
                raise TypeError(
                    "compatible_windows must contain verified BAR windows"
                )
            if (
                window.start_time_ms < dataset_ref.start_time_ms
                or window.end_time_ms > dataset_ref.end_time_ms
                or window.start_time_ms % interval_ms != 0
                or (window.end_time_ms + 1) % interval_ms != 0
                or window.bar_count
                != (
                    (window.end_time_ms - window.start_time_ms + 1)
                    // interval_ms
                )
                or (
                    previous_end is not None
                    and window.start_time_ms <= previous_end
                )
            ):
                raise ValueError(
                    "aggregate-trade compatibility BAR windows are invalid"
                )
            previous_end = window.end_time_ms
            matched += window.bar_count
        if matched + mismatch_bar_count != checked_bar_count:
            raise ValueError(
                "aggregate-trade compatibility BAR accounting changed"
            )

    def _verified_partitions_available(self) -> bool:
        try:
            return any(
                not (receipt.parent / "_verified_import_conflict.json").exists()
                for receipt in self._verified_receipt_paths()
                if receipt.is_file()
            )
        except OSError:
            return False

    def import_verified_day(
        self,
        rows: Iterable[dict[str, Any]],
        metadata: VerifiedRawAggTradeDay,
    ) -> int:
        if self.read_only:
            raise RuntimeError(
                "read-only raw aggTrade archive cannot import verified data"
            )
        if not isinstance(metadata, VerifiedRawAggTradeDay):
            raise TypeError("metadata must be VerifiedRawAggTradeDay")
        key = (
            metadata.exchange,
            metadata.market_type,
            metadata.symbol,
            metadata.date,
        )
        partition = self._partition_path(key)
        receipt_path = partition / "_verified_import.json"
        conflict_path = partition / "_verified_import_conflict.json"
        checksum_prefix = metadata.source_checksum_sha256[:24]
        written: list[Path] = []
        with partition_lease(
            self.retention_lease_path(partition.relative_to(self.root).as_posix()),
            shared=True, create=True, timeout_seconds=1.0,
        ), self._write_lock:
            self.require_day_not_retired(key[:3], metadata.date)
            if conflict_path.exists():
                raise RuntimeError(
                    "verified raw aggTrade partition is quarantined by an "
                    "unresolved import conflict"
                )
            if receipt_path.exists():
                existing = self._read_verified_receipt(receipt_path)
                if existing["metadata"] == metadata.to_dict():
                    self._validate_verified_receipt_objects(partition, existing)
                    return 0
                self._record_import_conflict(
                    conflict_path,
                    existing=existing["metadata"],
                    incoming=metadata.to_dict(),
                )
                raise RuntimeError(
                    "verified raw aggTrade import conflicts with the existing "
                    "official checksum; partition was quarantined"
                )

            partition.mkdir(parents=True, exist_ok=True)
            stale = sorted(
                partition.glob(f"part-verified-{checksum_prefix}-*.parquet")
            )
            if stale:
                self._quarantine_paths(
                    stale,
                    reason="incomplete_verified_import_retry",
                    metadata=metadata.to_dict(),
                )

            chunk: list[dict[str, Any]] = []
            count = 0
            previous_order: tuple[int, int] | None = None
            first_time: int | None = None
            last_time: int | None = None
            try:
                for raw in rows:
                    row = _raw_trade_payload(raw)
                    if (
                        row["exchange"],
                        row["market_type"],
                        row["symbol"],
                        _utc_date(row["trade_time_ms"]),
                    ) != key:
                        raise ValueError(
                            "verified raw aggTrade row identity/date does not match "
                            "its import metadata"
                        )
                    expected_id = metadata.first_agg_trade_id + count
                    if row["agg_trade_id"] != expected_id:
                        raise ValueError(
                            "verified raw aggTrade IDs are not exactly contiguous "
                            f"at {expected_id}"
                        )
                    order = (row["trade_time_ms"], row["agg_trade_id"])
                    if previous_order is not None and order <= previous_order:
                        raise ValueError(
                            "verified raw aggTrade rows are not strictly ordered"
                        )
                    previous_order = order
                    first_time = row["trade_time_ms"] if first_time is None else first_time
                    last_time = row["trade_time_ms"]
                    chunk.append(row)
                    count += 1
                    if len(chunk) >= self.max_rows_per_file:
                        written.append(
                            self._write_verified_chunk(
                                key,
                                chunk,
                                metadata=metadata,
                                checksum_prefix=checksum_prefix,
                                chunk_index=len(written),
                            )
                        )
                        chunk = []
                if chunk:
                    written.append(
                        self._write_verified_chunk(
                            key,
                            chunk,
                            metadata=metadata,
                            checksum_prefix=checksum_prefix,
                            chunk_index=len(written),
                        )
                    )
                if (
                    count != metadata.row_count
                    or count == 0
                    or previous_order is None
                    or previous_order[1] != metadata.last_agg_trade_id
                    or first_time != metadata.first_trade_time_ms
                    or last_time != metadata.last_trade_time_ms
                ):
                    raise ValueError(
                        "verified raw aggTrade rows do not match declared exact bounds"
                    )
                receipt = {
                    "schema_version": VERIFIED_IMPORT_SCHEMA_VERSION,
                    "metadata": metadata.to_dict(),
                    "objects": [
                        self._verified_receipt_object(path) for path in written
                    ],
                }
                _atomic_write_json(receipt_path, receipt)
            except BaseException:
                if written:
                    self._quarantine_paths(
                        written,
                        reason="verified_import_validation_failed",
                        metadata=metadata.to_dict(),
                    )
                raise
            self._stats["append_calls"] += 1
            self._stats["input_rows"] += count
            self._stats["last_append_error"] = None
            return count

    def freeze_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        page_rows: int = 50_000,
    ) -> RawAggTradeDatasetRef:
        with ExitStack() as leases:
            ref = self._freeze_dataset(
                leases=leases, exchange=exchange, market_type=market_type, symbol=symbol,
                start_time_ms=start_time_ms, end_time_ms=end_time_ms, page_rows=page_rows,
            )
        assert ref is not None
        return ref

    def read_verified_range(
        self, *, exchange: str, market_type: str, symbol: str,
        start_time_ms: int, end_time_ms: int, limit: int,
    ) -> tuple[RawAggTradeDatasetRef, list[dict[str, Any]]]:
        """Read a bounded exact range using the same proof as replay freezing."""
        rows: list[dict[str, Any]] = []
        with ExitStack() as leases:
            ref = self._freeze_dataset(
                leases=leases, exchange=exchange, market_type=market_type, symbol=symbol,
                start_time_ms=start_time_ms, end_time_ms=end_time_ms,
                page_rows=limit, collected=rows, max_rows=limit,
            )
        assert ref is not None
        return ref, rows

    def read_verified_daily_slice(
        self, *, exchange: str, market_type: str, symbol: str,
        start_time_ms: int, end_time_ms: int, limit: int,
    ) -> tuple[RawAggTradeDatasetRef | None, list[dict[str, Any]]]:
        """Read one UTC day's verified history. A successful empty slice proves quiet time."""
        if start_time_ms // 86_400_000 != end_time_ms // 86_400_000:
            raise ValueError("verified daily slice must stay inside one UTC day")
        rows: list[dict[str, Any]] = []
        with ExitStack() as leases:
            ref = self._freeze_dataset(
                leases=leases, exchange=exchange, market_type=market_type, symbol=symbol,
                start_time_ms=start_time_ms, end_time_ms=end_time_ms,
                page_rows=limit, collected=rows, max_rows=limit, allow_empty=True,
            )
        return ref, rows

    def _freeze_dataset(
        self,
        *,
        leases: ExitStack,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        page_rows: int = 50_000,
        collected: list[dict[str, Any]] | None = None,
        max_rows: int | None = None,
        allow_empty: bool = False,
    ) -> RawAggTradeDatasetRef | None:
        if max_rows is not None:
            if max_rows < 1:
                raise ValueError("max_rows must be positive")
            page_rows = min(page_rows, max_rows)
        bounds = self._normalize_scan_bounds(
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        assert bounds[0] is not None and bounds[1] is not None
        with self._write_lock:
            durability_error = self._stats["durability_error"]
        if durability_error:
            raise RuntimeError(
                "raw aggTrade archive is degraded and cannot release exact data"
            )
        identity = (
            _identity(exchange, "exchange", lower=True),
            _identity(market_type, "market_type", lower=True),
            _identity(symbol, "symbol", upper=True),
        )
        manifests = self._discover_verified_manifests(
            leases=leases,
            exchange=identity[0],
            market_type=identity[1],
            symbol=identity[2],
            start_time_ms=bounds[0],
            end_time_ms=bounds[1],
        )
        if not manifests:
            if allow_empty:
                # Discovery already required and checked the daily receipt
                # and every object, including those outside the slice.
                return None
            raise RuntimeError("no checksum-verified raw aggTrade objects cover the range")
        objects = tuple(self._object_manifest(item) for item in manifests)
        provisional = self._build_dataset_ref(
            identity=identity,
            start_time_ms=bounds[0],
            end_time_ms=bounds[1],
            first_agg_trade_id=min(item.min_agg_trade_id for item in objects),
            last_agg_trade_id=max(item.max_agg_trade_id for item in objects),
            objects=objects,
        )
        cursor: RawAggTradeCursor | None = None
        first_id: int | None = None
        last_id: int | None = None
        previous_order: tuple[int, int] | None = None
        row_count = 0
        while True:
            page = self.scan_page(
                exchange=identity[0],
                market_type=identity[1],
                symbol=identity[2],
                start_time_ms=bounds[0],
                end_time_ms=bounds[1],
                start_agg_trade_id=provisional.expected_first_agg_trade_id,
                end_agg_trade_id=provisional.expected_last_agg_trade_id,
                after=cursor,
                limit=page_rows,
                dataset_ref=provisional,
            )
            if max_rows is not None and (
                row_count + len(page.rows) > max_rows
                or (row_count + len(page.rows) == max_rows and not page.exhausted)
            ):
                self._record_scan_limit_rejection()
                raise RawAggTradeScanLimitError("exact raw aggTrade generation exceeds max_rows")
            for row in page.rows:
                order = (row["trade_time_ms"], row["agg_trade_id"])
                if previous_order is not None and order <= previous_order:
                    raise RuntimeError(
                        "exact raw aggTrade generation is not strictly ordered"
                    )
                if last_id is not None and row["agg_trade_id"] != last_id + 1:
                    raise RuntimeError(
                        "exact raw aggTrade generation contains an aggregate-ID gap"
                    )
                first_id = row["agg_trade_id"] if first_id is None else first_id
                last_id = row["agg_trade_id"]
                previous_order = order
                row_count += 1
            if collected is not None:
                collected.extend(page.rows)
            if page.exhausted:
                break
            if page.next_cursor is None or page.next_cursor == cursor:
                raise RuntimeError("raw aggTrade pagination cursor did not advance")
            cursor = page.next_cursor
        if not row_count and allow_empty:
            self.validate_dataset(provisional)
            return None
        if first_id is None or last_id is None or row_count != last_id - first_id + 1:
            raise RuntimeError("exact raw aggTrade range is empty or incomplete")
        dataset_ref = self._build_dataset_ref(
            identity=identity,
            start_time_ms=bounds[0],
            end_time_ms=bounds[1],
            first_agg_trade_id=first_id,
            last_agg_trade_id=last_id,
            objects=objects,
        )
        self.validate_dataset(dataset_ref)
        return dataset_ref

    def validate_dataset(self, dataset_ref: RawAggTradeDatasetRef) -> None:
        if not isinstance(dataset_ref, RawAggTradeDatasetRef):
            raise TypeError("dataset_ref must be RawAggTradeDatasetRef")
        expected_epoch = self._dataset_epoch(
            identity=(
                dataset_ref.exchange,
                dataset_ref.market_type,
                dataset_ref.symbol,
            ),
            start_time_ms=dataset_ref.start_time_ms,
            end_time_ms=dataset_ref.end_time_ms,
            first_agg_trade_id=dataset_ref.expected_first_agg_trade_id,
            last_agg_trade_id=dataset_ref.expected_last_agg_trade_id,
            objects=dataset_ref.objects,
        )
        if dataset_ref.data_epoch != expected_epoch:
            raise RuntimeError("raw aggTrade dataset epoch does not match its manifest")
        with self._write_lock:
            if self._stats["durability_error"]:
                raise RuntimeError("raw aggTrade archive is degraded")
        for item in dataset_ref.objects:
            path = self._resolve_object_path(item.object_id)
            sidecar = _manifest_path(path)
            if not path.is_file() or not sidecar.is_file():
                raise RuntimeError("raw aggTrade dataset object is missing")
            if (path.parent / "_verified_import_conflict.json").exists():
                raise RuntimeError("raw aggTrade dataset partition is quarantined")
            if _file_sha256(path) != item.parquet_sha256:
                raise RuntimeError("raw aggTrade Parquet checksum changed")
            if _file_sha256(sidecar) != item.manifest_sha256:
                raise RuntimeError("raw aggTrade object manifest checksum changed")
            current = self._read_file_manifest(path)
            if self._object_manifest(current) != item:
                raise RuntimeError("raw aggTrade object manifest changed")

    def pin_dataset(self, dataset_ref: RawAggTradeDatasetRef) -> str:
        if not isinstance(dataset_ref, RawAggTradeDatasetRef):
            raise TypeError("dataset_ref must be RawAggTradeDatasetRef")
        token = uuid4().hex
        partitions = frozenset(item.object_id.rsplit("/", 1)[0] for item in dataset_ref.objects)
        deadline = time.monotonic() + 1.0
        with ExitStack() as leases:
            for partition in sorted(partitions):
                self._enter_retention_lease(leases, partition, deadline)
            self.validate_dataset(dataset_ref)
            with self._write_lock:
                self._pins[token] = _RawTradePin(dataset_ref.data_epoch, partitions, leases.pop_all())
                self._pin_counts[dataset_ref.data_epoch] = (
                    self._pin_counts.get(dataset_ref.data_epoch, 0) + 1
                )
        return token

    def release_dataset(self, pin_token: str) -> None:
        token = str(pin_token)
        with self._write_lock:
            pinned = self._pins.pop(token, None)
            if pinned is None:
                return
            data_epoch = pinned.data_epoch
            remaining = self._pin_counts[data_epoch] - 1
            if remaining <= 0:
                self._pin_counts.pop(data_epoch, None)
            else:
                self._pin_counts[data_epoch] = remaining
        pinned.leases.close()

    def scan_range(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        start_agg_trade_id: int | None = None,
        end_agg_trade_id: int | None = None,
        limit: int = 100_000,
    ) -> list[dict[str, Any]]:
        return list(
            self.scan_page(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                start_agg_trade_id=start_agg_trade_id,
                end_agg_trade_id=end_agg_trade_id,
                limit=max(1, min(int(limit), 1_000_000)),
            ).rows
        )

    def scan_page(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        start_agg_trade_id: int | None = None,
        end_agg_trade_id: int | None = None,
        after: RawAggTradeCursor | None = None,
        limit: int = 50_000,
        dataset_ref: RawAggTradeDatasetRef | None = None,
        reject_id_conflicts: bool = False,
    ) -> RawAggTradePage:
        page_limit = max(1, min(int(limit), 1_000_000))
        if after is not None and not isinstance(after, RawAggTradeCursor):
            raise TypeError("after must be RawAggTradeCursor or None")
        bounds = self._normalize_scan_bounds(
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            start_agg_trade_id=start_agg_trade_id,
            end_agg_trade_id=end_agg_trade_id,
        )
        if reject_id_conflicts and (
            after is not None or start_time_ms is not None or end_time_ms is not None
            or bounds[2] is None or bounds[3] is None or bounds[3] - bounds[2] + 1 > page_limit
        ):
            raise ValueError("conflict checking requires an entire bounded ID window")
        if dataset_ref is None:
            manifests = self._discover_manifests(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                start_time_ms=bounds[0],
                end_time_ms=bounds[1],
                start_agg_trade_id=bounds[2],
                end_agg_trade_id=bounds[3],
            )
            data_epoch = None
        else:
            self._validate_dataset_request(
                dataset_ref,
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                bounds=bounds,
            )
            bounds = (
                dataset_ref.start_time_ms if bounds[0] is None else bounds[0],
                dataset_ref.end_time_ms if bounds[1] is None else bounds[1],
                (
                    dataset_ref.expected_first_agg_trade_id
                    if bounds[2] is None
                    else bounds[2]
                ),
                (
                    dataset_ref.expected_last_agg_trade_id
                    if bounds[3] is None
                    else bounds[3]
                ),
            )
            manifests = [
                self._file_manifest_from_object(item) for item in dataset_ref.objects
                if not (
                    (bounds[0] is not None and item.max_trade_time_ms < bounds[0])
                    or (bounds[1] is not None and item.min_trade_time_ms > bounds[1])
                    or (bounds[2] is not None and item.max_agg_trade_id < bounds[2])
                    or (bounds[3] is not None and item.min_agg_trade_id > bounds[3])
                )
            ]
            data_epoch = dataset_ref.data_epoch
        return self._scan_manifests(
            manifests, bounds, after, page_limit,
            filter_arrow=dataset_ref is not None,
            reject_id_conflicts=dataset_ref is not None or reject_id_conflicts,
            data_epoch=data_epoch,
        )

    def read_verified_repair_page(
        self, *, exchange: str, market_type: str, symbol: str,
        start_agg_trade_id: int, end_agg_trade_id: int, time_bounds: tuple[int, int],
    ) -> RawAggTradePage:
        """Read bounded repair candidates from committed, checksum-verified days."""
        start_ms, end_ms, first, last = self._normalize_scan_bounds(
            start_time_ms=time_bounds[0], end_time_ms=time_bounds[1],
            start_agg_trade_id=start_agg_trade_id, end_agg_trade_id=end_agg_trade_id,
        )
        assert start_ms is not None and end_ms is not None and first is not None and last is not None
        if last - first >= 1000 or end_ms // 86_400_000 - start_ms // 86_400_000 > 1:
            raise ValueError("verified repair requires at most 1,000 IDs across two UTC days")
        with ExitStack() as leases:
            manifests = self._discover_verified_manifests(
                leases=leases,
                exchange=_identity(exchange, "exchange", lower=True),
                market_type=_identity(market_type, "market type", lower=True),
                symbol=_identity(symbol, "symbol", upper=True),
                start_time_ms=start_ms, end_time_ms=end_ms, repair_ids=(first, last),
            )
            # Use time to select days only. A matching ID outside the bracket must
            # reach the repair owner so it can reject it instead of hiding it.
            return self._scan_manifests(
                manifests, (None, None, first, last), None, last - first + 1,
                filter_arrow=True, reject_id_conflicts=True, data_epoch=None,
            )

    def _scan_manifests(self, manifests, bounds, after, page_limit, *,
                        filter_arrow, reject_id_conflicts, data_epoch):
        bounded_limit = page_limit + 1
        if len(manifests) > self.max_scan_files:
            self._record_scan_limit_rejection()
            raise RawAggTradeScanLimitError(
                "raw aggTrade scan exceeds max_scan_files "
                f"({self.max_scan_files}); add narrower time/ID bounds",
            )
        estimated_physical_rows = sum(item.row_count for item in manifests)
        if (
            data_epoch is None
            and estimated_physical_rows > self.max_physical_scan_rows
        ):
            self._record_scan_limit_rejection()
            raise RawAggTradeScanLimitError(
                "raw aggTrade scan exceeds max_physical_scan_rows "
                f"({estimated_physical_rows} > "
                f"{self.max_physical_scan_rows}); add narrower time/ID bounds",
            )
        deduplicated: dict[int, dict[str, Any]] = {}
        scanned_rows = 0
        files_scanned = 0
        for index, manifest in enumerate(manifests):
            if after is not None and (
                manifest.max_trade_time_ms,
                manifest.max_agg_trade_id,
            ) <= (after.trade_time_ms, after.agg_trade_id):
                continue
            if files_scanned >= self.max_scan_files:
                self._record_scan_limit_rejection()
                raise RawAggTradeScanLimitError(
                    "raw aggTrade scan exceeds max_scan_files "
                    f"({self.max_scan_files}); add narrower time/ID bounds",
                )
            files_scanned += 1
            stop_file = False
            parquet = self._pq.ParquetFile(manifest.path)
            for batch in parquet.iter_batches(
                batch_size=self.scan_batch_size,
                columns=list(RAW_AGG_TRADE_COLUMNS),
            ):
                scanned_rows += batch.num_rows
                if scanned_rows > self.max_physical_scan_rows:
                    self._record_scan_limit_rejection()
                    raise RawAggTradeScanLimitError(
                        "raw aggTrade scan exceeds max_physical_scan_rows "
                        f"({self.max_physical_scan_rows}); add narrower "
                        "time/ID bounds",
                    )
                cutoff = _row_cutoff(deduplicated, bounded_limit)
                if filter_arrow:
                    # A revealed tape page can contain only a handful of IDs
                    # in a multi-million-row day. Filter in Arrow before Python
                    # conversion so these UI reads cannot monopolize the actor.
                    import pyarrow.compute as pc

                    mask = None
                    for column, lower, upper in (
                        ("trade_time_ms", bounds[0], bounds[1]),
                        ("agg_trade_id", bounds[2], bounds[3]),
                    ):
                        for value, compare in ((lower, pc.greater_equal), (upper, pc.less_equal)):
                            if value is not None:
                                predicate = compare(batch.column(column), value)
                                mask = predicate if mask is None else pc.and_(mask, predicate)
                    if after is not None:
                        times = batch.column("trade_time_ms")
                        ids = batch.column("agg_trade_id")
                        predicate = pc.or_(
                            pc.greater(times, after.trade_time_ms),
                            pc.and_(pc.equal(times, after.trade_time_ms), pc.greater(ids, after.agg_trade_id)),
                        )
                        mask = predicate if mask is None else pc.and_(mask, predicate)
                    if mask is not None:
                        batch = batch.filter(mask)
                for raw in batch.to_pylist():
                    row = _raw_trade_payload(raw)
                    order_key = (row["trade_time_ms"], row["agg_trade_id"])
                    if after is not None and order_key <= (
                        after.trade_time_ms,
                        after.agg_trade_id,
                    ):
                        continue
                    if cutoff is not None and order_key > cutoff:
                        stop_file = True
                        break
                    if not _row_matches_bounds(row, bounds):
                        continue
                    current = deduplicated.get(row["agg_trade_id"])
                    if current is not None and reject_id_conflicts:
                        if _immutable_trade_payload(current) != _immutable_trade_payload(row):
                            raise RuntimeError(
                                "raw aggTrade read contains conflicting "
                                f"duplicate aggregate-trade ID {row['agg_trade_id']}"
                            )
                    if current is None or row["received_at_ms"] >= current["received_at_ms"]:
                        deduplicated[row["agg_trade_id"]] = row
                if stop_file:
                    break
            cutoff = _row_cutoff(deduplicated, bounded_limit)
            next_manifest = (
                manifests[index + 1] if index + 1 < len(manifests) else None
            )
            if (
                cutoff is not None
                and next_manifest is not None
                and next_manifest.first_order_key > cutoff
            ):
                break
        ordered = sorted(
            deduplicated.values(),
            key=lambda item: (item["trade_time_ms"], item["agg_trade_id"]),
        )[:bounded_limit]
        exhausted = len(ordered) <= page_limit
        page_rows = tuple(ordered[:page_limit])
        next_cursor = (
            after
            if not page_rows
            else RawAggTradeCursor(
                trade_time_ms=page_rows[-1]["trade_time_ms"],
                agg_trade_id=page_rows[-1]["agg_trade_id"],
            )
        )
        return RawAggTradePage(
            rows=page_rows,
            next_cursor=next_cursor,
            exhausted=exhausted,
            data_epoch=data_epoch,
        )

    def coverage(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        expected_start_agg_trade_id: int | None = None,
        expected_end_agg_trade_id: int | None = None,
    ) -> RawAggTradeCoverage:
        bounds = self._normalize_scan_bounds(
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            start_agg_trade_id=expected_start_agg_trade_id,
            end_agg_trade_id=expected_end_agg_trade_id,
        )
        expected_start = bounds[2]
        expected_end = bounds[3]
        manifests = self._discover_manifests(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            start_time_ms=bounds[0],
            end_time_ms=bounds[1],
            start_agg_trade_id=bounds[2],
            end_agg_trade_id=bounds[3],
        )
        estimated_rows = sum(
            _estimated_matching_rows(item, bounds[2], bounds[3])
            for item in manifests
        )
        estimated_physical_rows = sum(item.row_count for item in manifests)
        identity = (
            _identity(exchange, "exchange", lower=True),
            _identity(market_type, "market_type", lower=True),
            _identity(symbol, "symbol", upper=True),
        )
        limit_kind: str | None = None
        if len(manifests) > self.max_scan_files:
            limit_kind = "files"
        elif estimated_physical_rows > self.max_physical_scan_rows:
            limit_kind = "physical_rows"
        elif estimated_rows > self.max_scan_rows:
            limit_kind = "matched_rows"
        if limit_kind is not None:
            self._record_scan_limit_rejection()
            return self._limited_coverage(
                identity=identity,
                bounds=bounds,
                manifests=manifests,
                estimated_rows=estimated_rows,
                estimated_physical_rows=estimated_physical_rows,
                limit_kind=limit_kind,
            )

        by_id: dict[int, tuple[int, int]] = {}
        scanned_rows = 0
        matched_rows = 0
        for manifest in manifests:
            parquet = self._pq.ParquetFile(manifest.path)
            for batch in parquet.iter_batches(
                batch_size=self.scan_batch_size,
                columns=["agg_trade_id", "trade_time_ms", "received_at_ms"],
            ):
                scanned_rows += batch.num_rows
                if scanned_rows > self.max_physical_scan_rows:
                    self._record_scan_limit_rejection()
                    return self._limited_coverage(
                        identity=identity,
                        bounds=bounds,
                        manifests=manifests,
                        estimated_rows=estimated_rows,
                        estimated_physical_rows=estimated_physical_rows,
                        scanned_rows=scanned_rows,
                        limit_kind="physical_rows",
                    )
                for raw in batch.to_pylist():
                    trade_time = int(raw["trade_time_ms"])
                    if bounds[0] is not None and trade_time < bounds[0]:
                        continue
                    if bounds[1] is not None and trade_time > bounds[1]:
                        continue
                    trade_id = int(raw["agg_trade_id"])
                    if bounds[2] is not None and trade_id < bounds[2]:
                        continue
                    if bounds[3] is not None and trade_id > bounds[3]:
                        continue
                    matched_rows += 1
                    if matched_rows > self.max_scan_rows:
                        self._record_scan_limit_rejection()
                        return self._limited_coverage(
                            identity=identity,
                            bounds=bounds,
                            manifests=manifests,
                            estimated_rows=estimated_rows,
                            estimated_physical_rows=estimated_physical_rows,
                            scanned_rows=scanned_rows,
                            limit_kind="matched_rows",
                        )
                    received_at = int(raw["received_at_ms"])
                    current = by_id.get(trade_id)
                    if current is None or received_at >= current[0]:
                        by_id[trade_id] = (received_at, trade_time)

        ids = sorted(by_id)
        gaps = tuple(
            RawAggTradeGap(
                start_agg_trade_id=left + 1,
                end_agg_trade_id=right - 1,
                missing_count=right - left - 1,
            )
            for left, right in zip(ids, ids[1:])
            if right > left + 1
        )
        earliest_id = ids[0] if ids else None
        latest_id = ids[-1] if ids else None
        expected_bounds = (
            expected_start is not None
            and expected_end is not None
        )
        if expected_bounds:
            assert expected_start is not None and expected_end is not None
            complete: bool | None = (
                earliest_id == expected_start
                and latest_id == expected_end
                and not gaps
            )
        else:
            complete = None
        with self._write_lock:
            durability_error = self._stats["durability_error"]
        if durability_error:
            complete = False
        trade_times = [value[1] for value in by_id.values()]
        return RawAggTradeCoverage(
            enabled=True,
            backend="parquet-pyarrow",
            exchange=identity[0],
            market_type=identity[1],
            symbol=identity[2],
            start_time_ms=bounds[0],
            end_time_ms=bounds[1],
            row_count=len(ids),
            file_count=len(manifests),
            earliest_agg_trade_id=earliest_id,
            latest_agg_trade_id=latest_id,
            earliest_trade_time_ms=min(trade_times) if trade_times else None,
            latest_trade_time_ms=max(trade_times) if trade_times else None,
            gaps=gaps,
            complete=complete,
            status="degraded" if durability_error else "ready",
            error=str(durability_error) if durability_error else None,
            estimated_row_count=estimated_rows,
            estimated_physical_row_count=estimated_physical_rows,
            scanned_row_count=scanned_rows,
        )

    def _identity_path(self, identity: tuple[str, str, str]) -> Path:
        exchange, market_type, symbol = identity
        return (
            self.root
            / f"exchange={_partition_value(exchange)}"
            / f"market_type={_partition_value(market_type)}"
            / f"symbol={_partition_value(symbol)}"
        )

    def _partition_path(self, key: tuple[str, str, str, str]) -> Path:
        exchange, market_type, symbol, day = key
        _validate_utc_date(day)
        return self._identity_path((exchange, market_type, symbol)) / f"date={day}"

    def _write_verified_chunk(
        self,
        key: tuple[str, str, str, str],
        rows: list[dict[str, Any]],
        *,
        metadata: VerifiedRawAggTradeDay,
        checksum_prefix: str,
        chunk_index: int,
    ) -> Path:
        first_id = rows[0]["agg_trade_id"]
        last_id = rows[-1]["agg_trade_id"]
        name = (
            f"part-verified-{checksum_prefix}-{chunk_index:06d}-"
            f"{first_id:020d}-{last_id:020d}.parquet"
        )
        return self._write_file(
            key,
            rows,
            source_quality="binance_public_checksum",
            source_checksum_sha256=metadata.source_checksum_sha256,
            deterministic_name=name,
        )

    def _verified_receipt_object(self, path: Path) -> dict[str, object]:
        manifest = self._object_manifest(self._read_file_manifest(path))
        return manifest.to_dict()

    @staticmethod
    def _read_verified_receipt(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("verified raw aggTrade receipt is unreadable") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "metadata", "objects"}
            or payload.get("schema_version") != VERIFIED_IMPORT_SCHEMA_VERSION
            or not isinstance(payload.get("metadata"), dict)
            or not isinstance(payload.get("objects"), list)
        ):
            raise RuntimeError("verified raw aggTrade receipt schema is invalid")
        try:
            metadata = VerifiedRawAggTradeDay(**payload["metadata"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("verified raw aggTrade receipt metadata is invalid") from exc
        if not payload["objects"]:
            raise RuntimeError("verified raw aggTrade receipt has no objects")
        return {
            "schema_version": VERIFIED_IMPORT_SCHEMA_VERSION,
            "metadata": metadata.to_dict(),
            "objects": payload["objects"],
        }

    def _validate_verified_receipt_objects(
        self,
        partition: Path,
        receipt: Mapping[str, object],
        *,
        repair_ids: tuple[int, int] | None = None,
        verify_parquet: bool = True,
    ) -> None:
        objects = receipt.get("objects")
        metadata = receipt.get("metadata")
        if not isinstance(objects, list) or not isinstance(metadata, Mapping):
            raise RuntimeError("verified raw aggTrade receipt objects are invalid")
        for raw in objects:
            if not isinstance(raw, Mapping):
                raise RuntimeError("verified raw aggTrade receipt object is invalid")
            item = RawAggTradeObjectManifest.from_dict(raw)
            if (item.source_quality != "binance_public_checksum"
                    or item.source_checksum_sha256 != metadata["source_checksum_sha256"]):
                raise RuntimeError("verified raw aggTrade object does not match the day source")
            if repair_ids is not None and not _overlaps_ids(item, repair_ids):
                continue
            path = self._resolve_object_path(item.object_id)
            if path.parent.resolve() != partition.resolve():
                raise RuntimeError("verified raw aggTrade receipt object escaped partition")
            if not path.is_file() or not _manifest_path(path).is_file():
                raise RuntimeError("verified raw aggTrade receipt object is missing")
            manifest = self._read_file_manifest(path, allow_fallback=verify_parquet)
            if self._object_manifest(manifest, verify_parquet=verify_parquet) != item:
                raise RuntimeError("verified raw aggTrade receipt checksum changed")

    def _verified_partition_receipt(
        self,
        partition: Path,
        identity_day: tuple[str, str, str, str],
        *,
        repair_ids: tuple[int, int] | None = None,
        verify_parquet: bool = True,
    ) -> dict[str, object]:
        receipt = self._read_verified_receipt(partition / "_verified_import.json")
        metadata = receipt["metadata"]
        assert isinstance(metadata, Mapping)
        if (
            metadata["exchange"], metadata["market_type"], metadata["symbol"], metadata["date"],
        ) != identity_day:
            raise RuntimeError("verified raw aggTrade receipt identity changed")
        self._validate_verified_receipt_objects(
            partition, receipt, repair_ids=repair_ids, verify_parquet=verify_parquet,
        )
        return receipt

    def _record_import_conflict(
        self,
        conflict_path: Path,
        *,
        existing: object,
        incoming: object,
    ) -> None:
        payload = {
            "schema_version": VERIFIED_IMPORT_SCHEMA_VERSION,
            "state": "quarantined",
            "reason": "official_source_checksum_or_schema_conflict",
            "existing": existing,
            "incoming": incoming,
        }
        _atomic_write_json(conflict_path, payload)
        quarantine = self.root / "_quarantine" / f"conflict-{uuid4().hex}"
        quarantine.mkdir(parents=True, exist_ok=False)
        _atomic_write_json(quarantine / "report.json", payload)

    def _quarantine_paths(
        self,
        paths: Iterable[Path],
        *,
        reason: str,
        metadata: Mapping[str, object],
    ) -> None:
        quarantine = self.root / "_quarantine" / f"import-{uuid4().hex}"
        quarantine.mkdir(parents=True, exist_ok=False)
        moved: list[str] = []
        for path in paths:
            for candidate in (path, _manifest_path(path)):
                if not candidate.exists():
                    continue
                destination = quarantine / candidate.name
                os.replace(candidate, destination)
                moved.append(destination.name)
        _atomic_write_json(
            quarantine / "report.json",
            {
                "schema_version": VERIFIED_IMPORT_SCHEMA_VERSION,
                "state": "quarantined",
                "reason": reason,
                "metadata": dict(metadata),
                "objects": moved,
            },
        )

    def _discover_verified_manifests(
        self,
        *,
        leases: ExitStack,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        repair_ids: tuple[int, int] | None = None,
    ) -> list[_FileManifest]:
        identity_root = (
            self.root
            / f"exchange={_partition_value(exchange)}"
            / f"market_type={_partition_value(market_type)}"
            / f"symbol={_partition_value(symbol)}"
        )
        manifests: list[_FileManifest] = []
        for date in _utc_dates(start_time_ms, end_time_ms):
            partition = identity_root / f"date={date}"
            receipt_path = partition / "_verified_import.json"
            conflict_path = partition / "_verified_import_conflict.json"
            if conflict_path.exists():
                raise RuntimeError(
                    "checksum-verified raw aggTrade partition is quarantined"
                )
            if not receipt_path.is_file():
                if repair_ids is not None:
                    continue
                raise RuntimeError(
                    "checksum-verified raw aggTrade daily coverage is missing"
                )
            # Repair already has a bounded async retry budget in its owner.
            deadline = time.monotonic() + (1.0 if repair_ids is None else 0.0)
            self._enter_retention_lease(leases, partition.relative_to(self.root).as_posix(), deadline)
            # Maintenance could have won the lease after the first observation.
            if conflict_path.exists():
                raise RuntimeError("checksum-verified raw aggTrade partition is quarantined")
            if not receipt_path.is_file():
                if repair_ids is not None:
                    continue
                raise RuntimeError("checksum-verified raw aggTrade daily coverage is missing")
            receipt = self._verified_partition_receipt(
                partition, (exchange, market_type, symbol, date), repair_ids=repair_ids,
            )
            objects = receipt["objects"]
            assert isinstance(objects, list)
            for raw in objects:
                assert isinstance(raw, Mapping)
                item = RawAggTradeObjectManifest.from_dict(raw)
                if repair_ids is not None:
                    if not _overlaps_ids(item, repair_ids):
                        continue
                elif item.max_trade_time_ms < start_time_ms or item.min_trade_time_ms > end_time_ms:
                    continue
                manifests.append(
                    self._file_manifest_from_object(item)
                )
            if len(manifests) > self.max_scan_files:
                raise RawAggTradeScanLimitError(
                    "exact raw aggTrade generation exceeds max_scan_files"
                )
        manifests.sort(key=lambda item: (item.first_order_key, item.path.name))
        return manifests

    def _object_manifest(
        self,
        manifest: _FileManifest,
        *,
        verify_parquet: bool = True,
    ) -> RawAggTradeObjectManifest:
        path = manifest.path.resolve()
        root = self.root.resolve()
        if not path.is_relative_to(root):
            raise RuntimeError("raw aggTrade object escaped archive root")
        sidecar = _manifest_path(path)
        parquet_sha256 = _file_sha256(path) if verify_parquet else manifest.parquet_sha256
        if parquet_sha256 is None:
            raise RuntimeError("verified raw aggTrade Parquet checksum is missing")
        if (
            manifest.parquet_sha256 is not None
            and manifest.parquet_sha256 != parquet_sha256
        ):
            raise RuntimeError("raw aggTrade Parquet checksum does not match sidecar")
        manifest_sha256 = _file_sha256(sidecar)
        if (
            manifest.manifest_sha256 is not None
            and manifest.manifest_sha256 != manifest_sha256
        ):
            raise RuntimeError("raw aggTrade manifest checksum changed")
        return RawAggTradeObjectManifest(
            object_id=path.relative_to(root).as_posix(),
            parquet_sha256=parquet_sha256,
            manifest_sha256=manifest_sha256,
            row_count=manifest.row_count,
            min_agg_trade_id=manifest.min_agg_trade_id,
            max_agg_trade_id=manifest.max_agg_trade_id,
            min_trade_time_ms=manifest.min_trade_time_ms,
            max_trade_time_ms=manifest.max_trade_time_ms,
            first_trade_time_ms=manifest.first_trade_time_ms,
            first_agg_trade_id=manifest.first_agg_trade_id,
            source_quality=manifest.source_quality,
            source_checksum_sha256=manifest.source_checksum_sha256,
        )

    def _resolve_object_path(self, object_id: str) -> Path:
        root = self.root.resolve()
        path = (root / Path(object_id)).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError("raw aggTrade object escaped archive root")
        return path

    def _file_manifest_from_object(
        self,
        item: RawAggTradeObjectManifest,
    ) -> _FileManifest:
        return _FileManifest(
            path=self._resolve_object_path(item.object_id),
            row_count=item.row_count,
            min_agg_trade_id=item.min_agg_trade_id,
            max_agg_trade_id=item.max_agg_trade_id,
            min_trade_time_ms=item.min_trade_time_ms,
            max_trade_time_ms=item.max_trade_time_ms,
            first_trade_time_ms=item.first_trade_time_ms,
            first_agg_trade_id=item.first_agg_trade_id,
            parquet_sha256=item.parquet_sha256,
            manifest_sha256=item.manifest_sha256,
            source_quality=item.source_quality,
            source_checksum_sha256=item.source_checksum_sha256,
        )

    def _build_dataset_ref(
        self,
        *,
        identity: tuple[str, str, str],
        start_time_ms: int,
        end_time_ms: int,
        first_agg_trade_id: int,
        last_agg_trade_id: int,
        objects: tuple[RawAggTradeObjectManifest, ...],
    ) -> RawAggTradeDatasetRef:
        epoch = self._dataset_epoch(
            identity=identity,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            first_agg_trade_id=first_agg_trade_id,
            last_agg_trade_id=last_agg_trade_id,
            objects=objects,
        )
        return RawAggTradeDatasetRef(
            schema_version=REPLAY_TRADE_DATASET_SCHEMA_VERSION,
            data_epoch=epoch,
            exchange=identity[0],
            market_type=identity[1],
            symbol=identity[2],
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            expected_first_agg_trade_id=first_agg_trade_id,
            expected_last_agg_trade_id=last_agg_trade_id,
            row_count=last_agg_trade_id - first_agg_trade_id + 1,
            objects=objects,
        )

    @staticmethod
    def _dataset_epoch(
        *,
        identity: tuple[str, str, str],
        start_time_ms: int,
        end_time_ms: int,
        first_agg_trade_id: int,
        last_agg_trade_id: int,
        objects: tuple[RawAggTradeObjectManifest, ...],
    ) -> str:
        payload = {
            "schema_version": REPLAY_TRADE_DATASET_SCHEMA_VERSION,
            "identity": list(identity),
            "start_time_ms": start_time_ms,
            "end_time_ms": end_time_ms,
            "expected_first_agg_trade_id": first_agg_trade_id,
            "expected_last_agg_trade_id": last_agg_trade_id,
            "objects": [item.to_dict() for item in objects],
            "completeness": "exact",
            "source_quality": "binance_public_checksum",
        }
        return "sha256:" + hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _validate_dataset_request(
        dataset_ref: RawAggTradeDatasetRef,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        bounds: tuple[int | None, int | None, int | None, int | None],
    ) -> None:
        identity = (
            _identity(exchange, "exchange", lower=True),
            _identity(market_type, "market_type", lower=True),
            _identity(symbol, "symbol", upper=True),
        )
        if identity != (
            dataset_ref.exchange,
            dataset_ref.market_type,
            dataset_ref.symbol,
        ):
            raise ValueError("raw aggTrade dataset identity does not match request")
        frozen = (
            dataset_ref.start_time_ms,
            dataset_ref.end_time_ms,
            dataset_ref.expected_first_agg_trade_id,
            dataset_ref.expected_last_agg_trade_id,
        )
        allowed = (
            (frozen[0], frozen[1]),
            (frozen[0], frozen[1]),
            (frozen[2], frozen[3]),
            (frozen[2], frozen[3]),
        )
        if any(
            value is not None and not allowed[index][0] <= value <= allowed[index][1]
            for index, value in enumerate(bounds)
        ):
            raise ValueError("raw aggTrade request escapes frozen dataset bounds")

    @staticmethod
    def _normalize_scan_bounds(
        *,
        start_time_ms: int | None,
        end_time_ms: int | None,
        start_agg_trade_id: int | None = None,
        end_agg_trade_id: int | None = None,
    ) -> tuple[int | None, int | None, int | None, int | None]:
        start_time = _optional_non_negative_int(start_time_ms, "start_time_ms")
        end_time = _optional_non_negative_int(end_time_ms, "end_time_ms")
        start_id = _optional_non_negative_int(
            start_agg_trade_id,
            "start_agg_trade_id",
        )
        end_id = _optional_non_negative_int(end_agg_trade_id, "end_agg_trade_id")
        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("start_time_ms cannot exceed end_time_ms")
        if start_id is not None and end_id is not None and start_id > end_id:
            raise ValueError("start_agg_trade_id cannot exceed end_agg_trade_id")
        return start_time, end_time, start_id, end_id

    def _discover_manifests(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        start_time_ms: int | None,
        end_time_ms: int | None,
        start_agg_trade_id: int | None = None,
        end_agg_trade_id: int | None = None,
    ) -> list[_FileManifest]:
        normalized_exchange = _identity(exchange, "exchange", lower=True)
        normalized_market = _identity(market_type, "market_type", lower=True)
        normalized_symbol = _identity(symbol, "symbol", upper=True)
        identity_root = (
            self.root
            / f"exchange={_partition_value(normalized_exchange)}"
            / f"market_type={_partition_value(normalized_market)}"
            / f"symbol={_partition_value(normalized_symbol)}"
        )
        if not identity_root.exists():
            return []
        start_date = _utc_date(start_time_ms) if start_time_ms is not None else None
        end_date = _utc_date(end_time_ms) if end_time_ms is not None else None
        manifests: list[_FileManifest] = []
        partitions = sorted(
            path
            for path in identity_root.iterdir()
            if path.is_dir() and path.name.startswith("date=")
        )
        for partition in partitions:
            date = partition.name.removeprefix("date=")
            if start_date is not None and date < start_date:
                continue
            if end_date is not None and date > end_date:
                continue
            for path in partition.glob("part-*.parquet"):
                manifest = self._read_file_manifest(path)
                if (
                    start_time_ms is not None
                    and manifest.max_trade_time_ms < start_time_ms
                ):
                    continue
                if (
                    end_time_ms is not None
                    and manifest.min_trade_time_ms > end_time_ms
                ):
                    continue
                if (
                    start_agg_trade_id is not None
                    and manifest.max_agg_trade_id < start_agg_trade_id
                ):
                    continue
                if (
                    end_agg_trade_id is not None
                    and manifest.min_agg_trade_id > end_agg_trade_id
                ):
                    continue
                manifests.append(manifest)
                # One overflow marker is enough for callers to fail closed;
                # never build an unbounded in-memory file catalog.
                if len(manifests) > self.max_scan_files:
                    manifests.sort(
                        key=lambda item: (item.first_order_key, item.path.name),
                    )
                    return manifests
        manifests.sort(key=lambda item: (item.first_order_key, item.path.name))
        return manifests

    def _read_file_manifest(self, path: Path, *, allow_fallback: bool = True) -> _FileManifest:
        sidecar = _manifest_path(path)
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("file") != path.name:
                raise ValueError("manifest file identity mismatch")
            parquet_sha256 = payload.get("parquet_sha256")
            if parquet_sha256 is not None:
                parquet_sha256 = _sha256_digest(
                    parquet_sha256,
                    "parquet_sha256",
                )
            source_checksum = payload.get("source_checksum_sha256")
            if source_checksum is not None:
                source_checksum = _sha256_digest(
                    source_checksum,
                    "source_checksum_sha256",
                )
            return _FileManifest(
                path=path,
                row_count=_non_negative_int(payload.get("row_count"), "row_count"),
                min_agg_trade_id=_non_negative_int(
                    payload.get("min_agg_trade_id"),
                    "min_agg_trade_id",
                ),
                max_agg_trade_id=_non_negative_int(
                    payload.get("max_agg_trade_id"),
                    "max_agg_trade_id",
                ),
                min_trade_time_ms=_non_negative_int(
                    payload.get("min_trade_time_ms"),
                    "min_trade_time_ms",
                ),
                max_trade_time_ms=_non_negative_int(
                    payload.get("max_trade_time_ms"),
                    "max_trade_time_ms",
                ),
                first_trade_time_ms=_non_negative_int(
                    payload.get("first_trade_time_ms"),
                    "first_trade_time_ms",
                ),
                first_agg_trade_id=_non_negative_int(
                    payload.get("first_agg_trade_id"),
                    "first_agg_trade_id",
                ),
                parquet_sha256=parquet_sha256,
                manifest_sha256=_file_sha256(sidecar),
                source_quality=str(
                    payload.get("source_quality", "live_best_effort")
                ),
                source_checksum_sha256=source_checksum,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            if not allow_fallback:
                raise
            with self._write_lock:
                self._stats["manifest_fallbacks"] += 1
            parquet = self._pq.ParquetFile(path)
            metadata = parquet.metadata
            id_min, id_max = _column_statistics(metadata, "agg_trade_id")
            time_min, time_max = _column_statistics(metadata, "trade_time_ms")
            return _FileManifest(
                path=path,
                row_count=int(metadata.num_rows),
                min_agg_trade_id=id_min,
                max_agg_trade_id=id_max,
                min_trade_time_ms=time_min,
                max_trade_time_ms=time_max,
                # Statistics are conservative lower bounds for early-stop.
                first_trade_time_ms=time_min,
                first_agg_trade_id=id_min,
                parquet_sha256=None,
                manifest_sha256=None,
                source_quality="live_best_effort",
                source_checksum_sha256=None,
            )

    def _limited_coverage(
        self,
        *,
        identity: tuple[str, str, str],
        bounds: tuple[int | None, int | None, int | None, int | None],
        manifests: list[_FileManifest],
        estimated_rows: int,
        estimated_physical_rows: int,
        limit_kind: str,
        scanned_rows: int = 0,
    ) -> RawAggTradeCoverage:
        earliest_id = (
            min(item.min_agg_trade_id for item in manifests)
            if manifests
            else None
        )
        latest_id = (
            max(item.max_agg_trade_id for item in manifests)
            if manifests
            else None
        )
        if earliest_id is not None and bounds[2] is not None:
            earliest_id = max(earliest_id, bounds[2])
        if latest_id is not None and bounds[3] is not None:
            latest_id = min(latest_id, bounds[3])
        limits = {
            "files": (
                f"candidate files={len(manifests)}/{self.max_scan_files}"
            ),
            "matched_rows": (
                f"estimated matched rows={estimated_rows}/{self.max_scan_rows}"
            ),
            "physical_rows": (
                "estimated physical rows="
                f"{estimated_physical_rows}/{self.max_physical_scan_rows}"
            ),
        }
        error = (
            f"coverage scan exceeds {limit_kind} safety limit "
            f"({limits[limit_kind]}); add narrower UTC time or aggregate-ID bounds"
        )
        return RawAggTradeCoverage(
            enabled=True,
            backend="parquet-pyarrow",
            exchange=identity[0],
            market_type=identity[1],
            symbol=identity[2],
            start_time_ms=bounds[0],
            end_time_ms=bounds[1],
            row_count=0,
            file_count=len(manifests),
            earliest_agg_trade_id=earliest_id,
            latest_agg_trade_id=latest_id,
            earliest_trade_time_ms=(
                min(item.min_trade_time_ms for item in manifests)
                if manifests
                else None
            ),
            latest_trade_time_ms=(
                max(item.max_trade_time_ms for item in manifests)
                if manifests
                else None
            ),
            gaps=(),
            complete=False,
            status="scan_limit_exceeded",
            error=error,
            truncated=True,
            estimated_row_count=estimated_rows,
            estimated_physical_row_count=estimated_physical_rows,
            scanned_row_count=scanned_rows,
            limit_kind=limit_kind,
        )

    def _record_scan_limit_rejection(self) -> None:
        with self._write_lock:
            self._stats["scan_limit_rejections"] += 1

    def _write_file(
        self,
        key: tuple[str, str, str, str],
        rows: list[dict[str, Any]],
        *,
        source_quality: str = "live_best_effort",
        source_checksum_sha256: str | None = None,
        deterministic_name: str | None = None,
    ) -> Path:
        exchange, market_type, symbol, date = key
        partition = (
            self.root
            / f"exchange={_partition_value(exchange)}"
            / f"market_type={_partition_value(market_type)}"
            / f"symbol={_partition_value(symbol)}"
            / f"date={date}"
        )
        partition.mkdir(parents=True, exist_ok=True)
        first_id = min(row["agg_trade_id"] for row in rows)
        last_id = max(row["agg_trade_id"] for row in rows)
        destination = partition / (
            deterministic_name
            or f"part-{first_id:020d}-{last_id:020d}-{uuid4().hex}.parquet"
        )
        if destination.suffix != ".parquet" or destination.parent != partition:
            raise ValueError("raw aggTrade destination name is invalid")
        ordered = sorted(
            rows,
            key=lambda item: (item["trade_time_ms"], item["agg_trade_id"]),
        )
        table = self._pa.Table.from_pylist(ordered, schema=self._schema)
        temporary = destination.with_name(
            f".{destination.name}.{uuid4().hex}.tmp"
        )
        try:
            self._pq.write_table(
                table,
                temporary,
                compression=self.compression,
            )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        parquet_sha256 = _file_sha256(destination)
        sidecar = _manifest_path(destination)
        sidecar_temporary = sidecar.with_name(
            f".{sidecar.name}.{uuid4().hex}.tmp",
        )
        first = ordered[0]
        manifest = {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "file": destination.name,
            "exchange": exchange,
            "market_type": market_type,
            "symbol": symbol,
            "date": date,
            "row_count": len(ordered),
            "min_agg_trade_id": min(row["agg_trade_id"] for row in ordered),
            "max_agg_trade_id": max(row["agg_trade_id"] for row in ordered),
            "min_trade_time_ms": min(row["trade_time_ms"] for row in ordered),
            "max_trade_time_ms": max(row["trade_time_ms"] for row in ordered),
            "first_trade_time_ms": first["trade_time_ms"],
            "first_agg_trade_id": first["agg_trade_id"],
            "parquet_sha256": parquet_sha256,
            "source_quality": source_quality,
            "source_checksum_sha256": source_checksum_sha256,
        }
        try:
            sidecar_temporary.write_text(
                json.dumps(manifest, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            os.replace(sidecar_temporary, sidecar)
        finally:
            sidecar_temporary.unlink(missing_ok=True)
        self._stats["files_written"] += 1
        return destination


@dataclass(slots=True)
class _ArchiveRequest:
    rows: list[dict[str, Any]]
    acknowledgement: asyncio.Future[int]


class RawAggTradeArchiveWriter:
    """Bounded single-consumer async batch writer for raw aggTrades.

    ``enqueue`` acknowledges queue ownership immediately while returning a
    future for application/process-level committed completion; ``write`` waits
    for that future.  The acknowledgement means atomic rename has completed,
    not that file and directory metadata survived sudden power loss: this
    implementation deliberately does not promise cross-platform file/directory
    ``fsync`` semantics.  Publication is atomic per immutable file, not across
    all files in a combined batch.  There is intentionally no lossy ``offer``
    method: silently dropping raw trades would invalidate replay completeness.
    """

    def __init__(
        self,
        archive: RawAggTradeArchive,
        *,
        flush_interval_seconds: float = 1.0,
        max_pending_batches: int = 16,
        max_rows_per_batch: int = 10_000,
        target_rows_per_file: int | None = None,
        max_buffer_seconds: float | None = None,
        compact_every_batches: int = 64,
        max_write_attempts: int = 3,
        retry_base_seconds: float = 0.05,
        retry_max_seconds: float = 1.0,
    ) -> None:
        self.archive = archive
        self._flush_interval_seconds = max(
            0.0,
            min(float(flush_interval_seconds), 10.0),
        )
        self._max_rows_per_batch = max(1, int(max_rows_per_batch))
        self._target_rows_per_file = max(
            1,
            int(
                self._max_rows_per_batch
                if target_rows_per_file is None
                else target_rows_per_file
            ),
        )
        self._max_buffer_seconds = max(
            0.0,
            float(
                self._flush_interval_seconds
                if max_buffer_seconds is None
                else max_buffer_seconds
            ),
        )
        self._compact_every_batches = max(1, int(compact_every_batches))
        self._max_write_attempts = max(1, min(int(max_write_attempts), 10))
        self._retry_base_seconds = max(0.0, float(retry_base_seconds))
        self._retry_max_seconds = max(
            self._retry_base_seconds,
            float(retry_max_seconds),
        )
        self._queue: asyncio.Queue[_ArchiveRequest | None] = asyncio.Queue(
            maxsize=max(1, int(max_pending_batches)),
        )
        self._enqueue_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._closing = False
        self._metrics = {
            "batches_written": 0,
            "rows_archived": 0,
            "write_failures": 0,
            "retry_attempts": 0,
            "failed_batches": 0,
            "failed_rows": 0,
            "failure_marker_errors": 0,
            "compaction_runs": 0,
            "compaction_failures": 0,
            "last_error": None,
        }
        self._durability_failed = False

    def start(self) -> None:
        if self._closing:
            raise RuntimeError("raw aggTrade archive writer is closed")
        if not self.archive.enabled:
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run(),
                name="raw-agg-trade-archive-writer",
            )

    async def write(self, rows: Iterable[dict[str, Any]]) -> int:
        acknowledgement = await self.enqueue(rows)
        if acknowledgement is None:
            return 0
        return await asyncio.shield(acknowledgement)

    async def enqueue(
        self,
        rows: Iterable[dict[str, Any]],
    ) -> asyncio.Future[int] | None:
        """Transfer a batch without waiting for its process-level commit ack."""

        copied = [dict(row) for row in rows]
        if not copied or not self.archive.enabled:
            return None
        if len(copied) > self._max_rows_per_batch:
            raise ValueError(
                "raw aggTrade archive batch exceeds max_rows_per_batch "
                f"({len(copied)} > {self._max_rows_per_batch})"
            )
        async with self._enqueue_lock:
            if self._closing:
                raise RuntimeError("raw aggTrade archive writer is closed")
            self.start()
            acknowledgement = asyncio.get_running_loop().create_future()
            acknowledgement.add_done_callback(self._consume_acknowledgement)
            await self._queue.put(
                _ArchiveRequest(rows=copied, acknowledgement=acknowledgement)
            )
        return acknowledgement

    async def close(self) -> None:
        async with self._enqueue_lock:
            if self._closing:
                task = self._task
            else:
                self._closing = True
                task = self._task
                if task is not None:
                    await self._queue.put(None)
        if task is not None:
            await asyncio.shield(task)

    def diagnostics(self) -> dict[str, Any]:
        if not self.archive.enabled:
            state = "disabled"
        elif self._durability_failed:
            state = "failed"
        elif self._closing and (self._task is None or self._task.done()):
            state = "closed"
        elif self._closing:
            state = "closing"
        elif self._task is not None and not self._task.done():
            state = "running"
        else:
            state = "idle"
        return {
            "state": state,
            "pending_batches": self._queue.qsize(),
            "limits": {
                "pending_batches": self._queue.maxsize,
                "rows_per_batch": self._max_rows_per_batch,
                "target_rows_per_file": self._target_rows_per_file,
                "max_buffer_seconds": self._max_buffer_seconds,
                "compact_every_batches": self._compact_every_batches,
                "write_attempts": self._max_write_attempts,
                "retry_base_seconds": self._retry_base_seconds,
                "retry_max_seconds": self._retry_max_seconds,
            },
            **self._metrics,
            "archive": self.archive.diagnostics(),
        }

    async def _run(self) -> None:
        should_stop = False
        while not should_stop:
            item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            requests = [item]
            buffered_rows = len(item.rows)
            deadline = (
                asyncio.get_running_loop().time() + self._max_buffer_seconds
            )
            while buffered_rows < self._target_rows_per_file:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    pending = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    break
                if pending is None:
                    self._queue.task_done()
                    should_stop = True
                    break
                requests.append(pending)
                buffered_rows += len(pending.rows)

            rows = [row for request in requests for row in request.rows]
            error: Exception | None = None
            accepted = 0
            for attempt in range(1, self._max_write_attempts + 1):
                try:
                    accepted = await run_storage(self.archive.append, rows)
                    if accepted != len(rows):
                        raise RuntimeError(
                            "raw aggTrade archive accepted an unexpected row "
                            f"count ({accepted} != {len(rows)})",
                        )
                except Exception as exc:
                    error = exc
                    self._metrics["write_failures"] += 1
                    if attempt >= self._max_write_attempts:
                        break
                    self._metrics["retry_attempts"] += 1
                    delay = min(
                        self._retry_base_seconds * (2 ** (attempt - 1)),
                        self._retry_max_seconds,
                    )
                    if delay:
                        await asyncio.sleep(delay)
                else:
                    error = None
                    break
            if error is not None:
                self._durability_failed = True
                self._metrics["failed_batches"] += len(requests)
                self._metrics["failed_rows"] += len(rows)
                self._metrics["last_error"] = str(error)[:500]
                marker = getattr(self.archive, "record_writer_failure", None)
                if callable(marker):
                    try:
                        marker(str(error))
                    except Exception:
                        # A backend marker hook is diagnostic state handling;
                        # it must not strand acknowledgements or queue joins.
                        self._metrics["failure_marker_errors"] += 1
                for request in requests:
                    if not request.acknowledgement.done():
                        request.acknowledgement.set_exception(error)
            else:
                self._metrics["batches_written"] += 1
                self._metrics["rows_archived"] += accepted
                for request in requests:
                    if not request.acknowledgement.done():
                        request.acknowledgement.set_result(len(request.rows))
                compact = getattr(self.archive, "compact_live_partitions", None)
                if (
                    callable(compact)
                    and self._metrics["batches_written"]
                    % self._compact_every_batches
                    == 0
                ):
                    try:
                        await run_storage(compact)
                    except Exception:
                        self._metrics["compaction_failures"] += 1
                    else:
                        self._metrics["compaction_runs"] += 1
            for _ in requests:
                self._queue.task_done()

    @staticmethod
    def _consume_acknowledgement(acknowledgement: asyncio.Future[int]) -> None:
        if not acknowledgement.cancelled():
            acknowledgement.exception()


def _manifest_path(parquet_path: Path) -> Path:
    return parquet_path.with_suffix(f"{parquet_path.suffix}.manifest.json")


def _estimated_matching_rows(
    manifest: _FileManifest,
    start_agg_trade_id: int | None,
    end_agg_trade_id: int | None,
) -> int:
    """Return a safe upper bound for rows matching an optional ID slice.

    Every immutable file is deduplicated by aggregate-trade ID before write, so
    an inclusive ID interval cannot match more rows than its integer width.
    """

    lower = manifest.min_agg_trade_id
    upper = manifest.max_agg_trade_id
    if start_agg_trade_id is not None:
        lower = max(lower, start_agg_trade_id)
    if end_agg_trade_id is not None:
        upper = min(upper, end_agg_trade_id)
    if lower > upper:
        return 0
    return min(manifest.row_count, upper - lower + 1)


def _row_matches_bounds(
    row: dict[str, Any],
    bounds: tuple[int | None, int | None, int | None, int | None],
) -> bool:
    start_time, end_time, start_id, end_id = bounds
    return not (
        (start_time is not None and row["trade_time_ms"] < start_time)
        or (end_time is not None and row["trade_time_ms"] > end_time)
        or (start_id is not None and row["agg_trade_id"] < start_id)
        or (end_id is not None and row["agg_trade_id"] > end_id)
    )


def _row_cutoff(
    rows: dict[int, dict[str, Any]],
    limit: int,
) -> tuple[int, int] | None:
    if len(rows) < limit:
        return None
    return sorted(
        (row["trade_time_ms"], row["agg_trade_id"]) for row in rows.values()
    )[limit - 1]


def _column_statistics(metadata: Any, column_name: str) -> tuple[int, int]:
    try:
        column_index = list(metadata.schema.names).index(column_name)
    except (AttributeError, ValueError) as exc:
        raise RuntimeError(
            f"Parquet archive is missing required column {column_name!r}",
        ) from exc
    minima: list[int] = []
    maxima: list[int] = []
    for index in range(metadata.num_row_groups):
        statistics = metadata.row_group(index).column(column_index).statistics
        if statistics is None or not statistics.has_min_max:
            raise RuntimeError(
                "Parquet archive sidecar is missing and column statistics "
                f"are unavailable for {column_name!r}",
            )
        minima.append(int(statistics.min))
        maxima.append(int(statistics.max))
    if not minima:
        raise RuntimeError("raw aggTrade Parquet file contains no row groups")
    return min(minima), max(maxima)


def _load_pyarrow() -> tuple[Any, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    return pa, pq


def _parquet_schema(pa: Any) -> Any:
    return pa.schema(
        [
            pa.field("exchange", pa.string(), nullable=False),
            pa.field("market_type", pa.string(), nullable=False),
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("agg_trade_id", pa.int64(), nullable=False),
            pa.field("first_trade_id", pa.int64(), nullable=False),
            pa.field("last_trade_id", pa.int64(), nullable=False),
            pa.field("price", pa.float64(), nullable=False),
            pa.field("quantity", pa.float64(), nullable=False),
            pa.field("quote_quantity", pa.float64(), nullable=False),
            pa.field("trade_time_ms", pa.int64(), nullable=False),
            pa.field("event_time_ms", pa.int64(), nullable=False),
            pa.field("received_at_ms", pa.int64(), nullable=False),
            pa.field("is_buyer_maker", pa.bool_(), nullable=False),
            pa.field("source", pa.string(), nullable=False),
        ],
        metadata={
            b"candlescope.dataset": b"raw_agg_trade",
            b"candlescope.schema_version": ARCHIVE_SCHEMA_VERSION.encode("ascii"),
        },
    )


def _raw_trade_payload(row: dict[str, Any]) -> dict[str, Any]:
    price = _positive_float(row.get("price"), "price")
    quantity = _positive_float(row.get("quantity"), "quantity")
    first_trade_id = _non_negative_int(row.get("first_trade_id"), "first_trade_id")
    last_trade_id = _non_negative_int(row.get("last_trade_id"), "last_trade_id")
    if first_trade_id > last_trade_id:
        raise ValueError("first_trade_id cannot exceed last_trade_id")
    is_buyer_maker = row.get("is_buyer_maker")
    if not isinstance(is_buyer_maker, bool):
        raise ValueError("is_buyer_maker must be a boolean")
    return {
        "exchange": _identity(row.get("exchange"), "exchange", lower=True),
        "market_type": _identity(
            row.get("market_type"),
            "market_type",
            lower=True,
        ),
        "symbol": _identity(row.get("symbol"), "symbol", upper=True),
        "agg_trade_id": _non_negative_int(
            row.get("agg_trade_id"),
            "agg_trade_id",
        ),
        "first_trade_id": first_trade_id,
        "last_trade_id": last_trade_id,
        "price": price,
        "quantity": quantity,
        "quote_quantity": _positive_float(
            row.get("quote_quantity", price * quantity),
            "quote_quantity",
        ),
        "trade_time_ms": _non_negative_int(
            row.get("trade_time_ms"),
            "trade_time_ms",
        ),
        "event_time_ms": _non_negative_int(
            row.get("event_time_ms"),
            "event_time_ms",
        ),
        "received_at_ms": _non_negative_int(
            row.get("received_at_ms"),
            "received_at_ms",
        ),
        "is_buyer_maker": is_buyer_maker,
        "source": _identity(row.get("source"), "source", lower=True),
    }


def _deduplicate_raw_trades(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduplicated: dict[int, dict[str, Any]] = {}
    for row in rows:
        current = deduplicated.get(row["agg_trade_id"])
        if current is None or row["received_at_ms"] >= current["received_at_ms"]:
            deduplicated[row["agg_trade_id"]] = row
    return sorted(
        deduplicated.values(),
        key=lambda item: (item["trade_time_ms"], item["agg_trade_id"]),
    )


def _utc_date(timestamp_ms: int) -> str:
    try:
        return datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=timezone.utc,
        ).date().isoformat()
    except (OSError, OverflowError, ValueError) as exc:
        raise ValueError("trade_time_ms is outside the supported UTC range") from exc


def _partition_value(value: str) -> str:
    return quote(value, safe="-_.")


def _identity(
    value: Any,
    label: str,
    *,
    lower: bool = False,
    upper: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be blank")
    normalized = value.strip()
    if lower:
        return normalized.lower()
    if upper:
        return normalized.upper()
    return normalized


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{label} must be finite")
    return number


def _positive_float(value: Any, label: str) -> float:
    number = _finite_float(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a non-negative integer") from exc
    if number < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return number


def _optional_non_negative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, label)


def _sha256_digest(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a SHA-256 digest")
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{label} must be a SHA-256 digest")
    return normalized


def _normalized_json_mapping(
    value: Mapping[str, object],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    try:
        normalized = json.loads(
            json.dumps(
                dict(value),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain canonical JSON values") from exc
    if not isinstance(normalized, dict):
        raise ValueError(f"{label} must be an object")
    return normalized


def _canonical_sha256(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _prefixed_sha256_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(f"{label} must be a prefixed SHA-256 digest")
    return "sha256:" + _sha256_digest(value.removeprefix("sha256:"), label)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_retention_directory(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_utc_date(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("archive date must use YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("archive date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("archive date must use canonical YYYY-MM-DD")


def _utc_dates(start_time_ms: int, end_time_ms: int) -> tuple[str, ...]:
    start = datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc).date()
    end = datetime.fromtimestamp(end_time_ms / 1000, tz=timezone.utc).date()
    values: list[str] = []
    current = start
    while current <= end:
        values.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(values)


def _immutable_trade_payload(row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(
        row[field_name]
        for field_name in RAW_AGG_TRADE_COLUMNS
        if field_name not in {"event_time_ms", "received_at_ms", "source"}
    )


def _overlaps_ids(item: RawAggTradeObjectManifest, ids: tuple[int, int]) -> bool:
    return item.min_agg_trade_id <= ids[1] and item.max_agg_trade_id >= ids[0]


__all__ = [
    "ARCHIVE_SCHEMA_VERSION",
    "BAR_COMPATIBILITY_SCHEMA_VERSION",
    "DisabledRawAggTradeArchive",
    "ParquetRawAggTradeArchive",
    "RAW_AGG_TRADE_COLUMNS",
    "REPLAY_TRADE_DATASET_SCHEMA_VERSION",
    "RawAggTradeArchive",
    "RawAggTradeCursor",
    "RawAggTradeCoverage",
    "RawAggTradeDatasetRef",
    "RawAggTradeGap",
    "RawAggTradeObjectManifest",
    "RawAggTradePage",
    "RawAggTradeSelectionWindow",
    "RawAggTradeScanLimitError",
    "RawAggTradeArchiveWriter",
    "VERIFIED_IMPORT_SCHEMA_VERSION",
    "VerifiedRawAggTradeDay",
    "VerifiedRawAggTradeBarWindow",
    "VerifiedRawAggTradeWindow",
]
