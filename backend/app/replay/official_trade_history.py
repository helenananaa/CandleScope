"""Lazy, revision-bound chart history for official aggregate-trade replay.

Availability is metadata, not a claim that bars have already been validated.
Every requested daily body is checksum checked and every execution window is
validated by BarDatasetBuilder before a session can become playable.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.data_engine.backfill.archive_cache import (
    AiohttpArchiveHttpClient,
    HistoricalArchiveCache,
)
from app.exchanges.archive import ArchiveGranularity
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider

from .canonical import canonical_sha256
from .catalog import ReplaySeriesIdentity
from .history_archive import (
    ReplayHistoryArchiveError,
    ReplayHistoryArchiveWriter,
    ReplayHistoryImportBatch,
    ReplayHistoryRepository,
    _atomic_write_json,
)

MINUTE = 60_000
DAY = 86_400_000


class OfficialTradeHistoryRepository:
    supports_unbounded_indexed_gap_scan = True

    def __init__(self, root, trade_archive, *, timeout_seconds=60, day_loader=None):
        self.root = Path(root)
        self.trade_archive = trade_archive
        self.timeout_seconds = timeout_seconds
        self._guard = threading.RLock()
        self._day_locks = {}
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
        import json

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
            with self._guard:
                lock = self._day_locks.setdefault(str(root), threading.Lock())
            with lock:
                writer = ReplayHistoryArchiveWriter(root)
                manifest = writer.current_manifest(identity, "1m")
                if manifest is None:
                    self._day_loader(root, identity, day_start)
                    manifest = writer.current_manifest(identity, "1m")
                if manifest is None:
                    raise ReplayHistoryArchiveError(
                        "official daily K-lines did not materialize"
                    )
                # Freeze the first observed checksum-bound day. Never silently
                # replace a day already used by this catalog revision.
                binding = self.root / "bindings" / revision[7:] / (day + ".json")
                import json

                if binding.exists():
                    pinned = json.loads(binding.read_text())["catalog_epoch"]
                else:
                    pinned = manifest.catalog_epoch
                    _atomic_write_json(binding, {"catalog_epoch": pinned})
                repo = ReplayHistoryRepository(root)
                rows.extend(
                    repo.query_bars_at_revision(
                        pinned,
                        symbol,
                        "1m",
                        start_ms=max(start, day_start),
                        end_ms=min(end, day_start + DAY - MINUTE),
                        limit=1440,
                        exchange=exchange,
                        market_type=market_type,
                    )
                )
        rows.sort(key=lambda row: row["open_time"], reverse=order == "DESC")
        return rows[:limit]

    def _download_day(self, root, identity, day_start):
        async def download():
            provider = BinanceKlineArchiveProvider()
            refs = provider.plan_objects(
                market_type=identity.market_type,
                symbol=identity.symbol,
                interval="1m",
                start_ms=day_start,
                end_ms=day_start + DAY - 1,
                now_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            )
            ref = next(
                r
                for r in refs
                if r.granularity is ArchiveGranularity.DAILY and r.start_ms == day_start
            )
            cache = HistoricalArchiveCache(
                self.root / "downloads", max_bytes=512 * 1024**2
            )
            http = AiohttpArchiveHttpClient(timeout_seconds=self.timeout_seconds)
            async with cache.materialize(ref, provider, http) as cached:
                if cached.provider_checksum is None:
                    raise ReplayHistoryArchiveError(
                        "official K-lines require checksum verification"
                    )
                parsed = await asyncio.to_thread(
                    provider.parse_bars_for_replay, cached.path, ref
                )
                batch = ReplayHistoryImportBatch(
                    rows=parsed.bars,
                    source_provider=ref.provider_id,
                    source_object_key=ref.object_key,
                    source_period=ref.period,
                    source_url=ref.url,
                    source_content_sha256="sha256:" + cached.content_sha256,
                    source_provider_checksum="sha256:" + cached.provider_checksum,
                    source_row_count=parsed.source_row_count,
                    source_rejected_rows=parsed.rejected_row_count,
                    source_normalized_rows=parsed.normalized_row_count,
                    source_filter_policy="binance_checksum_utc_grid_v2",
                    source_rejection_reasons=parsed.rejection_reasons,
                )
                writer = ReplayHistoryArchiveWriter(root)
                writer.import_batches(identity, "1m", [batch])

        asyncio.run(download())


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

    def scan_gaps_at_revision(self, revision, *args, **kwargs):
        repo = self.official if self.official.owns(revision) else self.local
        return repo.scan_gaps_at_revision(revision, *args, **kwargs)

    def query_bars_at_revision(self, revision, *args, **kwargs):
        repo = self.official if self.official.owns(revision) else self.local
        return repo.query_bars_at_revision(revision, *args, **kwargs)
