"""Import, validate, publish, and query immutable local K-line datasets."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.data_engine.interval_policy import (
    IntervalAlignment,
    IntervalSpec,
    parse_interval_spec,
)


DATASET_ID_RE = re.compile(r"^local-[0-9a-f]{32}$")
EPOCH_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = 2


class LocalDatasetError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_dataset") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class LocalImportOptions:
    name: str
    symbol: str
    interval: str
    timezone_name: str = "UTC"
    timestamp_unit: str = "auto"
    time_column: str = "time"
    open_column: str = "open"
    high_column: str = "high"
    low_column: str = "low"
    close_column: str = "close"
    volume_column: str = "volume"
    volume_required: bool = False
    quote_volume_column: str | None = None
    trades_column: str | None = None
    taker_buy_base_column: str | None = None
    taker_buy_quote_column: str | None = None
    last_bar_closed: bool = True
    dataset_id: str | None = None


@dataclass(frozen=True, slots=True)
class _NormalizedBar:
    open_time_ms: int
    close_time_ms: int
    open: str
    high: str
    low: str
    close: str
    volume: str | None
    quote_volume: str | None
    trades: int | None
    taker_buy_base: str | None
    taker_buy_quote: str | None
    is_closed: bool
    source_row: int


class LocalDatasetService:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".staging").mkdir(exist_ok=True)
        (self.root / ".uploads").mkdir(exist_ok=True)

    def new_upload_path(self) -> Path:
        self.start()
        return self.root / ".uploads" / f"{uuid.uuid4().hex}.csv"

    def import_csv(self, csv_path: Path, options: LocalImportOptions) -> dict[str, Any]:
        self.start()
        interval = parse_interval_spec(options.interval)
        if interval is None:
            raise LocalDatasetError(f"Unsupported interval: {options.interval}")
        dataset_id = options.dataset_id or f"local-{uuid.uuid4().hex}"
        if DATASET_ID_RE.fullmatch(dataset_id) is None:
            raise LocalDatasetError("dataset_id must match local-<32 lowercase hex>")
        name = options.name.strip()
        symbol = options.symbol.strip().upper()
        if not name:
            raise LocalDatasetError("Dataset name is required")
        if not symbol:
            raise LocalDatasetError("Symbol is required")

        staging = self.root / ".staging" / f"{dataset_id}-{uuid.uuid4().hex}"
        staging.mkdir(parents=True)
        try:
            bars, excluded_ranges, resolved_columns = self._parse_csv(
                csv_path, options, interval
            )
            epoch_hex = self._content_epoch(symbol, interval, bars, excluded_ranges)
            manifest = self._write_staging_dataset(
                staging,
                dataset_id=dataset_id,
                epoch_hex=epoch_hex,
                name=name,
                symbol=symbol,
                interval=interval,
                options=options,
                bars=bars,
                excluded_ranges=excluded_ranges,
                resolved_columns=resolved_columns,
            )
            published = self._publish(staging, dataset_id, epoch_hex, manifest)
            staging = None
            return published
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging)

    def _parse_csv(
        self,
        csv_path: Path,
        options: LocalImportOptions,
        interval: IntervalSpec,
    ) -> tuple[
        list[_NormalizedBar],
        list[dict[str, Any]],
        dict[str, str | None],
    ]:
        required = {
            "time": options.time_column,
            "open": options.open_column,
            "high": options.high_column,
            "low": options.low_column,
            "close": options.close_column,
        }
        optional = {
            "quote_volume": options.quote_volume_column,
            "trades": options.trades_column,
            "taker_buy_base": options.taker_buy_base_column,
            "taker_buy_quote": options.taker_buy_quote_column,
        }
        bars: list[_NormalizedBar] = []
        gaps: list[dict[str, Any]] = []
        try:
            timezone_info = ZoneInfo(options.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise LocalDatasetError(
                f"Unknown timezone: {options.timezone_name}"
            ) from exc

        with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise LocalDatasetError("CSV must contain a header row")
            resolved_columns = self._resolve_columns(
                reader.fieldnames,
                {
                    **required,
                    "volume": options.volume_column,
                    **{key: column for key, column in optional.items() if column},
                },
                optional_missing=set() if options.volume_required else {"volume"},
            )
            required = {key: resolved_columns[key] for key in required}
            optional = {
                key: resolved_columns.get(key)
                for key in optional
            }

            previous_open: int | None = None
            fixed_alignment_offset_ms: int | None = None
            for source_row, row in enumerate(reader, start=2):
                if not any((value or "").strip() for value in row.values()):
                    continue
                open_ms = self._parse_time(
                    row.get(required["time"], ""),
                    options.timestamp_unit,
                    timezone_info,
                    source_row,
                )
                if interval.alignment is IntervalAlignment.FIXED_EPOCH:
                    row_offset_ms = open_ms % interval.nominal_ms
                    if fixed_alignment_offset_ms is None:
                        fixed_alignment_offset_ms = row_offset_ms
                    elif row_offset_ms != fixed_alignment_offset_ms:
                        raise LocalDatasetError(
                            f"Row {source_row}: timestamp phase does not match "
                            f"the first {interval.canonical} bar"
                        )
                elif interval.floor_ms(open_ms) != open_ms:
                    raise LocalDatasetError(
                        f"Row {source_row}: timestamp is not aligned to {interval.canonical}"
                    )
                if previous_open is not None and open_ms <= previous_open:
                    relation = (
                        "duplicate" if open_ms == previous_open else "out of order"
                    )
                    raise LocalDatasetError(f"Row {source_row}: {relation} timestamp")

                values = {
                    key: self._parse_decimal(row.get(column, ""), key, source_row)
                    for key, column in required.items()
                    if key != "time"
                }
                volume_column = resolved_columns["volume"]
                volume = (
                    self._parse_decimal(
                        row.get(volume_column, ""), "volume", source_row
                    )
                    if volume_column is not None
                    else None
                )
                if values["high"] < max(values["open"], values["close"]):
                    raise LocalDatasetError(
                        f"Row {source_row}: high is below open or close"
                    )
                if values["low"] > min(values["open"], values["close"]):
                    raise LocalDatasetError(
                        f"Row {source_row}: low is above open or close"
                    )
                if values["low"] > values["high"]:
                    raise LocalDatasetError(f"Row {source_row}: low exceeds high")
                if volume is not None and volume < 0:
                    raise LocalDatasetError(
                        f"Row {source_row}: volume must be non-negative"
                    )

                parsed_optional: dict[str, Any] = {}
                for key, column in optional.items():
                    raw = (row.get(column, "") if column else "").strip()
                    if not raw:
                        parsed_optional[key] = None
                    elif key == "trades":
                        try:
                            parsed_optional[key] = int(raw)
                        except ValueError as exc:
                            raise LocalDatasetError(
                                f"Row {source_row}: trades must be an integer"
                            ) from exc
                        if parsed_optional[key] < 0:
                            raise LocalDatasetError(
                                f"Row {source_row}: trades must be non-negative"
                            )
                    else:
                        parsed_optional[key] = self._parse_decimal(raw, key, source_row)
                        if parsed_optional[key] < 0:
                            raise LocalDatasetError(
                                f"Row {source_row}: {key} must be non-negative"
                            )

                if previous_open is not None:
                    expected = interval.next_ms(previous_open)
                    if open_ms != expected:
                        gaps.append(
                            {
                                "start_ms": expected,
                                "end_ms": open_ms,
                                "reason": "source_gap",
                                "missing_bars": self._count_missing(
                                    interval, expected, open_ms
                                ),
                            }
                        )
                bars.append(
                    _NormalizedBar(
                        open_time_ms=open_ms,
                        close_time_ms=interval.next_ms(open_ms) - 1,
                        open=self._decimal_text(values["open"]),
                        high=self._decimal_text(values["high"]),
                        low=self._decimal_text(values["low"]),
                        close=self._decimal_text(values["close"]),
                        volume=(
                            self._decimal_text(volume)
                            if volume is not None
                            else None
                        ),
                        quote_volume=self._optional_decimal_text(
                            parsed_optional["quote_volume"]
                        ),
                        trades=parsed_optional["trades"],
                        taker_buy_base=self._optional_decimal_text(
                            parsed_optional["taker_buy_base"]
                        ),
                        taker_buy_quote=self._optional_decimal_text(
                            parsed_optional["taker_buy_quote"]
                        ),
                        is_closed=True,
                        source_row=source_row,
                    )
                )
                previous_open = open_ms

        if not bars:
            raise LocalDatasetError("CSV contains no data rows")
        if not options.last_bar_closed:
            last = bars[-1]
            bars[-1] = _NormalizedBar(**{**asdict(last), "is_closed": False})
        return bars, gaps, resolved_columns

    @staticmethod
    def _resolve_columns(
        fieldnames: list[str],
        configured: dict[str, str],
        *,
        optional_missing: set[str] | None = None,
    ) -> dict[str, str | None]:
        optional_missing = optional_missing or set()
        folded: dict[str, list[str]] = {}
        for fieldname in fieldnames:
            folded.setdefault(fieldname.strip().casefold(), []).append(fieldname)

        resolved: dict[str, str | None] = {}
        missing: list[str] = []
        for logical_name, requested in configured.items():
            if requested in fieldnames:
                resolved[logical_name] = requested
                continue
            matches = folded.get(requested.strip().casefold(), [])
            if len(matches) == 1:
                resolved[logical_name] = matches[0]
            elif len(matches) > 1:
                raise LocalDatasetError(
                    f"CSV column is ambiguous ignoring case: {requested}"
                )
            elif logical_name in optional_missing:
                resolved[logical_name] = None
            else:
                missing.append(requested)

        if missing:
            raise LocalDatasetError(
                f"CSV columns not found: {', '.join(sorted(set(missing)))}"
            )
        return resolved

    @staticmethod
    def _parse_decimal(raw: str | None, field: str, row: int) -> Decimal:
        try:
            value = Decimal((raw or "").strip())
        except (InvalidOperation, ValueError) as exc:
            raise LocalDatasetError(f"Row {row}: {field} is not a number") from exc
        if not value.is_finite():
            raise LocalDatasetError(f"Row {row}: {field} must be finite")
        return value

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        normalized = value.normalize()
        text = format(normalized, "f")
        return "0" if text in {"-0", ""} else text

    @classmethod
    def _optional_decimal_text(cls, value: Decimal | None) -> str | None:
        return None if value is None else cls._decimal_text(value)

    @staticmethod
    def _parse_time(raw: str, unit: str, timezone_info: ZoneInfo, row: int) -> int:
        value = raw.strip()
        normalized_unit = unit.strip().lower()
        if normalized_unit not in {"auto", "s", "ms", "iso"}:
            raise LocalDatasetError("timestamp_unit must be auto, s, ms, or iso")
        try:
            if normalized_unit == "iso" or (
                normalized_unit == "auto"
                and not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value)
            ):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone_info)
                return int(parsed.timestamp() * 1000)
            number = Decimal(value)
            if not number.is_finite():
                raise ValueError
            if normalized_unit == "auto":
                normalized_unit = (
                    "ms" if abs(number) >= Decimal("100000000000") else "s"
                )
            multiplier = 1000 if normalized_unit == "s" else 1
            milliseconds = number * multiplier
            if milliseconds != milliseconds.to_integral_value():
                raise ValueError
            return int(milliseconds)
        except (ValueError, InvalidOperation, OverflowError) as exc:
            raise LocalDatasetError(f"Row {row}: invalid timestamp {value!r}") from exc

    @staticmethod
    def _count_missing(interval: IntervalSpec, expected: int, current: int) -> int:
        if current <= expected:
            return 0
        if interval.alignment.value != "calendar_month":
            return max(0, (current - expected) // interval.nominal_ms)
        count = 0
        cursor = expected
        while cursor < current:
            count += 1
            cursor = interval.next_ms(cursor)
        return count

    @staticmethod
    def _content_epoch(
        symbol: str,
        interval: IntervalSpec,
        bars: Iterable[_NormalizedBar],
        gaps: list[dict[str, Any]],
    ) -> str:
        digest = hashlib.sha256()
        identity = {
            "schema_version": SCHEMA_VERSION,
            "symbol": symbol,
            "interval": interval.canonical,
            "alignment": interval.alignment.value,
        }
        digest.update(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        )
        for bar in bars:
            digest.update(b"\n")
            digest.update(
                json.dumps(asdict(bar), sort_keys=True, separators=(",", ":")).encode()
            )
        digest.update(b"\n")
        digest.update(json.dumps(gaps, sort_keys=True, separators=(",", ":")).encode())
        return digest.hexdigest()

    def _write_staging_dataset(
        self,
        staging: Path,
        *,
        dataset_id: str,
        epoch_hex: str,
        name: str,
        symbol: str,
        interval: IntervalSpec,
        options: LocalImportOptions,
        bars: list[_NormalizedBar],
        excluded_ranges: list[dict[str, Any]],
        resolved_columns: dict[str, str | None],
    ) -> dict[str, Any]:
        db_path = staging / "bars.sqlite"
        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=DELETE;
                PRAGMA synchronous=FULL;
                CREATE TABLE bars (
                    open_time_ms INTEGER PRIMARY KEY,
                    close_time_ms INTEGER NOT NULL,
                    open TEXT NOT NULL,
                    high TEXT NOT NULL,
                    low TEXT NOT NULL,
                    close TEXT NOT NULL,
                    volume TEXT,
                    quote_volume TEXT,
                    trades INTEGER,
                    taker_buy_base TEXT,
                    taker_buy_quote TEXT,
                    is_closed INTEGER NOT NULL,
                    source_row INTEGER NOT NULL
                );
                CREATE TABLE excluded_ranges (
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    missing_bars INTEGER NOT NULL
                );
                """
            )
            connection.executemany(
                """
                INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        bar.open_time_ms,
                        bar.close_time_ms,
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        bar.quote_volume,
                        bar.trades,
                        bar.taker_buy_base,
                        bar.taker_buy_quote,
                        int(bar.is_closed),
                        bar.source_row,
                    )
                    for bar in bars
                ],
            )
            connection.executemany(
                "INSERT INTO excluded_ranges VALUES (?, ?, ?, ?)",
                [
                    (gap["start_ms"], gap["end_ms"], gap["reason"], gap["missing_bars"])
                    for gap in excluded_ranges
                ],
            )
            check = connection.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                raise LocalDatasetError("SQLite integrity validation failed")
            connection.commit()
        finally:
            connection.close()

        sqlite_sha256 = self._file_sha256(db_path)
        now = datetime.now(timezone.utc).isoformat()
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "data_epoch": f"sha256:{epoch_hex}",
            "name": name,
            "source": "local_dataset",
            "symbol": symbol,
            "interval": interval.canonical,
            "volume_available": resolved_columns["volume"] is not None,
            "alignment": interval.alignment.value,
            "alignment_offset_ms": (
                bars[0].open_time_ms % interval.nominal_ms
                if interval.alignment is IntervalAlignment.FIXED_EPOCH
                else 0
            ),
            "timezone": options.timezone_name,
            "timestamp_semantics": "bar_open",
            "rows": len(bars),
            "first_open_ms": bars[0].open_time_ms,
            "last_open_ms": bars[-1].open_time_ms,
            "all_rows_final": all(bar.is_closed for bar in bars),
            "excluded_range_count": len(excluded_ranges),
            "sqlite_sha256": sqlite_sha256,
            "imported_at": now,
        }
        quality = {
            "status": "accepted_with_gaps" if excluded_ranges else "accepted",
            "rows": len(bars),
            "excluded_ranges": excluded_ranges,
            "duplicates": 0,
            "out_of_order": 0,
            "invalid_rows": 0,
            "volume_available": resolved_columns["volume"] is not None,
            "missing_volume_rows": (
                0 if resolved_columns["volume"] is not None else len(bars)
            ),
        }
        receipt = {
            "importer": "candlescope.local.csv.v1",
            "imported_at": now,
            "columns": {
                f"{key}_column": value
                for key, value in resolved_columns.items()
                if value
            },
            "timestamp_unit": options.timestamp_unit,
            "timezone": options.timezone_name,
            "volume_required": options.volume_required,
        }
        self._write_json(staging / "manifest.json", manifest)
        self._write_json(staging / "quality-report.json", quality)
        self._write_json(staging / "import-receipt.json", receipt)
        return manifest

    def _publish(
        self,
        staging: Path,
        dataset_id: str,
        epoch_hex: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        dataset_root = self.root / dataset_id
        dataset_root.mkdir(exist_ok=True)
        target = dataset_root / epoch_hex
        if target.exists():
            shutil.rmtree(staging)
        else:
            os.replace(staging, target)
        self._write_json(
            dataset_root / "current.json",
            {"data_epoch": manifest["data_epoch"], "revision": epoch_hex},
        )
        return self.get_manifest(dataset_id)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def list_datasets(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        manifests = []
        for candidate in sorted(self.root.iterdir()):
            if candidate.is_dir() and DATASET_ID_RE.fullmatch(candidate.name):
                try:
                    manifests.append(self.get_manifest(candidate.name))
                except LocalDatasetError:
                    continue
        return sorted(manifests, key=lambda item: item["imported_at"], reverse=True)

    def _revision_dir(self, dataset_id: str) -> Path:
        if DATASET_ID_RE.fullmatch(dataset_id) is None:
            raise LocalDatasetError("Invalid dataset id", code="dataset_not_found")
        current_path = self.root / dataset_id / "current.json"
        try:
            current = json.loads(current_path.read_text(encoding="utf-8"))
            revision = current["revision"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise LocalDatasetError(
                "Dataset not found", code="dataset_not_found"
            ) from exc
        if not isinstance(revision, str) or EPOCH_RE.fullmatch(revision) is None:
            raise LocalDatasetError("Invalid dataset revision", code="dataset_corrupt")
        path = self.root / dataset_id / revision
        if not path.is_dir():
            raise LocalDatasetError(
                "Dataset revision not found", code="dataset_corrupt"
            )
        return path

    def get_manifest(self, dataset_id: str) -> dict[str, Any]:
        try:
            manifest = json.loads(
                (self._revision_dir(dataset_id) / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise LocalDatasetError(
                "Dataset manifest is unreadable", code="dataset_corrupt"
            ) from exc
        manifest.setdefault("volume_available", True)
        return manifest

    def query(
        self,
        dataset_id: str,
        *,
        interval: str,
        limit: int,
        before_ms: int | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict[str, Any]:
        manifest = self.get_manifest(dataset_id)
        requested = parse_interval_spec(interval)
        stored = parse_interval_spec(manifest["interval"])
        if (
            requested is None
            or stored is None
            or requested.signature != stored.signature
        ):
            raise LocalDatasetError(
                f"Dataset contains only interval {manifest['interval']}",
                code="interval_not_available",
            )
        limit = max(1, min(int(limit), 5_000))
        clauses: list[str] = []
        parameters: list[int] = []
        if before_ms is not None:
            clauses.append("open_time_ms < ?")
            parameters.append(int(before_ms))
        if start_ms is not None:
            clauses.append("open_time_ms >= ?")
            parameters.append(int(start_ms))
        if end_ms is not None:
            clauses.append("open_time_ms <= ?")
            parameters.append(int(end_ms))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        db_path = self._revision_dir(dataset_id) / "bars.sqlite"
        uri = f"file:{db_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.row_factory = sqlite3.Row
            selected = connection.execute(
                f"SELECT * FROM bars {where} ORDER BY open_time_ms DESC LIMIT ?",
                [*parameters, limit + 1],
            ).fetchall()
            gaps = connection.execute(
                "SELECT * FROM excluded_ranges ORDER BY start_ms ASC"
            ).fetchall()
        finally:
            connection.close()
        has_more = len(selected) > limit
        selected = selected[:limit]
        selected.reverse()
        rows = [self._wire_bar(row) for row in selected]
        earliest_selected = selected[0]["open_time_ms"] if selected else None
        return {
            "source": "local_dataset",
            "dataset_id": dataset_id,
            "data_epoch": manifest["data_epoch"],
            "symbol": manifest["symbol"],
            "interval": manifest["interval"],
            "volume_available": manifest["volume_available"],
            "data": rows,
            "count": len(rows),
            "all_rows_final": all(row["is_closed"] for row in rows),
            "complete": True,
            "retryable": False,
            "renderable": bool(rows),
            "has_more": has_more,
            "truncated": has_more,
            "next_end_ms": earliest_selected - 1
            if has_more and earliest_selected is not None
            else None,
            "next_before_ms": earliest_selected if has_more else None,
            "history_state": "ready" if has_more else "exhausted",
            "terminal_reason": None if has_more else "dataset_boundary",
            "earliest_available_ms": manifest["first_open_ms"],
            "availability_revision": manifest["data_epoch"],
            "verified_contiguous": True,
            "excluded_ranges": [dict(gap) for gap in gaps],
            "missing_ranges": [],
        }

    @staticmethod
    def _wire_bar(row: sqlite3.Row) -> dict[str, Any]:
        result = {
            "time": row["open_time_ms"] // 1000,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": None if row["volume"] is None else float(row["volume"]),
            "is_closed": bool(row["is_closed"]),
        }
        for key in ("quote_volume", "taker_buy_base", "taker_buy_quote"):
            result[key] = None if row[key] is None else float(row[key])
        result["trades"] = row["trades"]
        return result

    def diagnostics(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "root": str(self.root),
            "datasets": len(self.list_datasets()),
            "immutable_revisions": True,
        }
