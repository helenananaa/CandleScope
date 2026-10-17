"""Lazy, revision-bound chart history for official aggregate-trade replay.

Availability is metadata, not a claim that bars have already been validated.
Every selected archive body is checksum checked and every execution window is
validated by BarDatasetBuilder before a session can become playable.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from .canonical import canonical_sha256
from .catalog import ReplaySeriesIdentity
from .history_archive import (
    ReplayHistoryArchiveError,
    ReplayHistoryArchiveWriter,
    _atomic_write_json,
)
from .official_chart_archive import OfficialChartArchive

MINUTE = 60_000
DAY = 86_400_000
DISPLAY_PAGE_BASE_ROWS = 8192
DAY_ROW_CACHE_SIZE = 64


class OfficialTradeHistoryRepository:
    supports_unbounded_indexed_gap_scan = True

    def __init__(self, root, trade_archive, *, timeout_seconds=60, day_loader=None):
        self.root = Path(root)
        self.trade_archive = trade_archive
        self.timeout_seconds = timeout_seconds
        self._guard = threading.RLock()
        self._archives = OfficialChartArchive(self.root, timeout_seconds)
        self._day_rows = OrderedDict()
        self._day_loader = day_loader or self._download_day

    def _path(self, revision):
        if (
            not isinstance(revision, str)
            or len(revision) != 71
            or not revision.startswith("sha256:")
            or any(c not in "0123456789abcdef" for c in revision[7:])
        ):
            raise ReplayHistoryArchiveError("invalid official history revision")
        return self.root / "revisions" / (revision[7:] + ".json")

    def owns(self, revision):
        return self._path(revision).is_file()

    def _load(self, revision, symbol, interval, exchange=None, market_type=None):
        payload = json.loads(self._path(revision).read_text())
        if (
            canonical_sha256(payload) != revision
            or payload["identity"]
            != {"exchange": exchange, "market_type": market_type, "symbol": symbol}
            or interval != "1m"
        ):
            raise ReplayHistoryArchiveError(
                "official history revision identity mismatch"
            )
        return payload

    def list_all_series(self, custom_only=False):
        result = []
        for identity in self.trade_archive.list_verified_identities():
            if (
                identity["exchange"] != "binance"
                or identity["market_type"] != "futures"
            ):
                continue
            epoch, windows = self.trade_archive.selection_snapshot(**identity)
            if not windows:
                continue
            payload = {
                "schema": "official-trade-chart-history.v1",
                "identity": identity,
                "trade_epoch": epoch,
                "ranges": [[w.start_time_ms, w.end_time_ms] for w in windows],
            }
            revision = canonical_sha256(payload)
            path = self._path(revision)
            if not path.exists():
                _atomic_write_json(path, payload)
            result.append(
                {**identity, "interval": "1m", **self._bounds(payload, revision)}
            )
        return result

    def list_series(self, custom_only=False, exchange=None, market_type=None):
        return [
            s
            for s in self.list_all_series(custom_only)
            if (exchange is None or s["exchange"] == exchange)
            and (market_type is None or s["market_type"] == market_type)
        ]

    @staticmethod
    def _bounds(payload, revision):
        ranges = payload["ranges"]
        return {
            "earliest_open_time": ranges[0][0],
            "latest_open_time": ranges[-1][1] // MINUTE * MINUTE,
            "total_count": sum((b - a + 1) // MINUTE for a, b in ranges),
            "source_revision": revision,
            "source_bucket_anchor_ms": 0,
            "alignment_policy": "CANONICAL_INTERVAL_V1",
        }

    def get_bounds_at_revision(
        self, revision, symbol, interval, exchange=None, market_type=None
    ):
        return self._bounds(
            self._load(revision, symbol, interval, exchange, market_type), revision
        )

    def get_history_bounds_at_revision(
        self, revision, symbol, interval, exchange=None, market_type=None
    ):
        bounds = self.get_bounds_at_revision(
            revision, symbol, interval, exchange, market_type
        )
        # Availability catalogs are day-granular. The first archive can begin
        # partway through its day; only its pinned, verified body proves the
        # first available minute. Keep catalog discovery lazy, but resolve this
        # exact origin before a bound history/indicator calculation starts.
        start = bounds["earliest_open_time"]
        rows = self.query_bars_at_revision(
            revision,
            symbol,
            interval,
            exchange=exchange,
            market_type=market_type,
            start_ms=start,
            end_ms=(start // DAY + 1) * DAY - MINUTE,
            limit=1440,
            order="ASC",
        )
        if not rows:
            raise ReplayHistoryArchiveError(
                "official first history day contains no bars"
            )
        return {
            **bounds,
            "listing_boundary_ms": rows[0]["open_time"],
            "listing_boundary_source": "verified_official_first_bar",
            "history_origin_complete": True,
        }

    def get_bounds(self, symbol, interval, exchange=None, market_type=None):
        for s in self.list_all_series():
            if (s["symbol"], s["interval"], s["exchange"], s["market_type"]) == (
                symbol,
                interval,
                exchange,
                market_type,
            ):
                return s
        raise ReplayHistoryArchiveError("official chart history is unavailable")

    def scan_gaps_at_revision(
        self, revision, symbol, interval, start_ms=None, end_ms=None, **kwargs
    ):
        payload = self._load(
            revision,
            symbol,
            interval,
            kwargs.get("exchange"),
            kwargs.get("market_type"),
        )
        bounds = self._bounds(payload, revision)
        start = bounds["earliest_open_time"] if start_ms is None else start_ms
        end = bounds["latest_open_time"] if end_ms is None else end_ms
        cursor = start
        gaps = []
        for a, b in payload["ranges"]:
            a, b = max(start, a), min(end, b // MINUTE * MINUTE)
            if a > b:
                continue
            if cursor < a:
                gaps.append(
                    {
                        "start_ms": cursor,
                        "end_ms": a - MINUTE,
                        "missing_bars": (a - cursor) // MINUTE,
                        "reason": "official_archive_unavailable",
                    }
                )
            cursor = max(cursor, b + MINUTE)
        if cursor <= end:
            gaps.append(
                {
                    "start_ms": cursor,
                    "end_ms": end,
                    "missing_bars": (end - cursor) // MINUTE + 1,
                    "reason": "official_archive_unavailable",
                }
            )
        return {
            "gaps": gaps,
            "gap_count": len(gaps),
            "scanned_bars": max(0, (end - start) // MINUTE + 1),
            "truncated": False,
            "calendar_id": "crypto.24x7.utc",
            "source_revision": revision,
        }

    def query_bars_at_revision(
        self,
        revision,
        symbol,
        interval,
        start_ms=None,
        end_ms=None,
        limit=None,
        order="ASC",
        exchange=None,
        market_type=None,
    ):
        payload = self._load(revision, symbol, interval, exchange, market_type)
        bounds = self._bounds(payload, revision)
        start = max(
            bounds["earliest_open_time"],
            start_ms if start_ms is not None else bounds["earliest_open_time"],
        )
        end = min(
            bounds["latest_open_time"],
            end_ms if end_ms is not None else bounds["latest_open_time"],
        )
        if order not in ("ASC", "DESC") or limit is None or not 1 <= limit <= 100_001:
            raise ReplayHistoryArchiveError("official history requires a bounded page")
        # Bound I/O as well as the returned rows, even for all-available history.
        if order == "ASC":
            end = min(end, start + (limit - 1) * MINUTE)
        else:
            start = max(start, end - (limit - 1) * MINUTE)
        rows = []
        for day_start in range(start // DAY * DAY, end // DAY * DAY + 1, DAY):
            if not any(
                a <= day_start and day_start + DAY - 1 <= b
                for a, b in payload["ranges"]
            ):
                continue
            day = (
                datetime.fromtimestamp(day_start / 1000, timezone.utc)
                .date()
                .isoformat()
            )
            identity = ReplaySeriesIdentity(exchange, market_type, symbol)
            root = self.root / "days" / exchange / market_type / symbol / day
            with self._archives.own(root):
                cache_key = (revision, exchange, market_type, symbol, day_start)
                with self._guard:
                    cached_rows = self._day_rows.get(cache_key)
                    if cached_rows is not None:
                        self._day_rows.move_to_end(cache_key)
                if cached_rows is not None:
                    rows.extend(
                        dict(row)
                        for row in cached_rows
                        if start <= row["open_time"] <= end
                    )
                    continue
                binding = self.root / "bindings" / revision[7:] / (day + ".json")
                publish = None
                selected = self._archives.day_binding(binding, day)
                if selected is not None:
                    pinned, month = selected
                    if month is not None:
                        root = self._archives.month_root(identity, month)
                else:
                    # Existing daily objects win over a new monthly transport.
                    # Already-bound days above never download or change source.
                    manifest = ReplayHistoryArchiveWriter(root).current_manifest(
                        identity, "1m"
                    )
                    if manifest is None:
                        selected_root = self._day_loader(root, identity, day_start)
                        if selected_root is not None:
                            root = Path(selected_root)
                        manifest = ReplayHistoryArchiveWriter(root).current_manifest(
                            identity, "1m"
                        )
                    if manifest is None:
                        raise ReplayHistoryArchiveError(
                            "official chart K-lines did not materialize"
                        )
                    pinned = manifest.catalog_epoch
                    publish = {"catalog_epoch": pinned}
                    if root == self._archives.month_root(identity, day[:7]):
                        publish["month"] = day[:7]
                repo = self._archives.repository(root)
                day_rows = tuple(
                    dict(row)
                    for row in repo.query_bars_at_revision(
                        pinned,
                        symbol,
                        "1m",
                        start_ms=day_start,
                        end_ms=day_start + DAY - MINUTE,
                        limit=1440,
                        exchange=exchange,
                        market_type=market_type,
                    )
                )
                if not day_rows:
                    raise ReplayHistoryArchiveError(
                        "official available history day contains no bars"
                    )
                if publish is not None:
                    _atomic_write_json(binding, publish)
                # The revision's first checksum-bound day stays immutable.
                # Keep private rows; callers receive copies filtered to their
                # own revealed boundary, including after a future page read.
                with self._guard:
                    self._day_rows[cache_key] = day_rows
                    self._day_rows.move_to_end(cache_key)
                    while len(self._day_rows) > DAY_ROW_CACHE_SIZE:
                        self._day_rows.popitem(last=False)
                rows.extend(
                    dict(row) for row in day_rows if start <= row["open_time"] <= end
                )
        rows.sort(key=lambda row: row["open_time"], reverse=order == "DESC")
        return rows[:limit]

    def _download_day(self, root, identity, day_start):
        return self._archives.ensure_day_source(root, identity, day_start)

    def tape_context_market_at_revision(
        self,
        revision,
        symbol,
        interval,
        *,
        start_ms,
        end_ms,
        offset_ms=0,
        exchange=None,
        market_type=None,
        cancelled,
    ):
        """Select existing day pins, then share their immutable range indexes."""
        from .shared_market_index import MarketRange

        payload = self._load(revision, symbol, interval, exchange, market_type)
        bounds = self._bounds(payload, revision)
        if (
            interval != "1m"
            or start_ms < bounds["earliest_open_time"]
            or end_ms > bounds["latest_open_time"] + MINUTE
            or not 0 < end_ms - start_ms <= 32_768 * MINUTE
        ):
            return None
        identity = ReplaySeriesIdentity(exchange, market_type, symbol)
        selections = []
        for day_start in range(
            start_ms // DAY * DAY, (end_ms - 1) // DAY * DAY + 1, DAY
        ):
            if cancelled.is_set():
                raise InterruptedError("official indexed context cancelled")
            if not any(
                a <= day_start and day_start + DAY - 1 <= b
                for a, b in payload["ranges"]
            ):
                return None
            day = (
                datetime.fromtimestamp(day_start / 1000, timezone.utc)
                .date()
                .isoformat()
            )
            binding = self.root / "bindings" / revision[7:] / (day + ".json")
            selected = self._archives.day_binding(binding, day)
            if selected is None:
                # The normal source selection owns validation/publication. A
                # one-row request binds only this day, never future day pins.
                self.query_bars_at_revision(
                    revision,
                    symbol,
                    interval,
                    start_ms=max(start_ms, day_start),
                    end_ms=min(end_ms, day_start + DAY) - 1,
                    limit=1,
                    exchange=exchange,
                    market_type=market_type,
                )
                selected = self._archives.day_binding(binding, day)
            if selected is None:
                return None
            pin, month = selected
            root = self.root / "days" / exchange / market_type / symbol / day
            if month is not None:
                root = self._archives.month_root(identity, month)
            first, last = max(start_ms, day_start), min(end_ms, day_start + DAY)
            if (
                selections
                and selections[-1][:2] == (root, pin)
                and selections[-1][3] == first
            ):
                previous = selections[-1]
                selections[-1] = (root, pin, previous[2], last)
            else:
                selections.append((root, pin, first, last))
        parts = []
        for root, pin, first, last in selections:
            if cancelled.is_set():
                raise InterruptedError("official indexed context cancelled")
            market = self._archives.repository(root).shared_market_at_revision(
                pin,
                symbol,
                interval,
                start_ms=first,
                end_ms=last,
                exchange=exchange,
                market_type=market_type,
            )
            if market is None:
                return None
            parts.extend(market.parts)
        return MarketRange(parts, offset_ms) if parts else None


class TradeHistoryRouter:
    """Preserve BAR catalogs; route only official revision-bound reads lazily."""

    supports_unbounded_indexed_gap_scan = True

    def __init__(self, local, official):
        self.local, self.official = local, official

    def __getattr__(self, name):
        # Optional optimized reads assume local Parquet manifests. The generic
        # bounded history reader supports both kinds of source revision.
        if name in (
            "query_aggregated_bars_at_revision",
            "query_source_bucket_bars_at_revision",
        ):
            raise AttributeError(name)
        return getattr(self.local, name)

    def get_bounds_at_revision(self, revision, *args, **kwargs):
        repo = self.official if self.official.owns(revision) else self.local
        return repo.get_bounds_at_revision(revision, *args, **kwargs)

    def get_history_bounds_at_revision(self, revision, *args, **kwargs):
        repo = self.official if self.official.owns(revision) else self.local
        reader = getattr(
            repo, "get_history_bounds_at_revision", repo.get_bounds_at_revision
        )
        return reader(revision, *args, **kwargs)

    def scan_gaps_at_revision(self, revision, *args, **kwargs):
        repo = self.official if self.official.owns(revision) else self.local
        return repo.scan_gaps_at_revision(revision, *args, **kwargs)

    def query_bars_at_revision(self, revision, *args, **kwargs):
        repo = self.official if self.official.owns(revision) else self.local
        return repo.query_bars_at_revision(revision, *args, **kwargs)

    def tape_context_market_at_revision(self, revision, *args, **kwargs):
        if not self.official.owns(revision):
            return None
        return self.official.tape_context_market_at_revision(revision, *args, **kwargs)

    def query_source_bucket_bars_at_revision(self, revision, *args, **kwargs):
        # A mixed trade/BAR deployment must retain local BAR projections. The
        # official daily source cannot use the local Parquet implementation;
        # aggregate its bounded, immutable minute reads through the same
        # revealed-only reducer used for progressive history instead.
        if not self.official.owns(revision):
            return self.local.query_source_bucket_bars_at_revision(
                revision, *args, **kwargs
            )
        from .source_bucket_projection import query_source_bucket_projection

        return query_source_bucket_projection(
            self.official,
            revision,
            *args,
            **kwargs,
            max_base_rows=DISPLAY_PAGE_BASE_ROWS,
        )
