"""Reuse verified monthly minute objects without changing existing day bindings."""

from __future__ import annotations

import asyncio
import json
import threading
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic

import aiohttp

from app.core.executors import run_archive
from app.data_engine.backfill.archive_cache import (
    AiohttpArchiveHttpClient,
    HistoricalArchiveCache,
)
from app.exchanges.archive import (
    ArchiveGranularity,
    ArchiveRequestContext,
    ArchiveHttpStatusError,
    ArchiveTransportError,
)
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider

from .history_archive import (
    ReplayHistoryArchiveError,
    ReplayHistoryArchiveWriter,
    ReplayHistoryImportBatch,
    ReplayHistoryRepository,
    _digest,
)

DAY = 86_400_000
DAY_BINDING_CACHE_SIZE = 4096


def _covers_day(manifest, day_start):
    # A published, checksum-valid month may still omit its last days or an
    # interior interval. Select it only when its verified segments cover the
    # entire requested day; otherwise independently verify the daily source.
    # The daily importer remains responsible for genuine listing/gap semantics.
    return manifest is not None and any(
        segment.start_ms <= day_start and segment.end_ms >= day_start + DAY - 60_000
        for segment in manifest.segments
    )


class OfficialChartArchive:
    def __init__(self, root, timeout_seconds):
        self.root, self.timeout_seconds = root, timeout_seconds
        self._guard = threading.Lock()
        self._owners = {}
        self._repositories = OrderedDict()
        self._day_bindings = OrderedDict()
        self._missing_months = OrderedDict()
        self._downloads = None

    @contextmanager
    def own(self, key):
        with self._guard:
            entry = self._owners.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._guard:
                entry[1] -= 1
                if not entry[1]:
                    del self._owners[key]

    def month_root(self, identity, period):
        return (
            self.root
            / "months"
            / identity.exchange
            / identity.market_type
            / identity.symbol
            / period
        )

    def repository(self, root):
        # Reuse verified object receipts across separate day selections from
        # the same month. Disk reload still validates the immutable manifest.
        with self._guard:
            repo = self._repositories.get(root)
            if repo is None:
                repo = self._repositories[root] = ReplayHistoryRepository(
                    root, discover_current=False
                )
            self._repositories.move_to_end(root)
            while len(self._repositories) > 16:
                self._repositories.popitem(last=False)
            return repo

    def day_binding(self, path, day):
        # A published day pin is immutable for its frozen source revision.
        # Share only this small source selection, never rows or account state.
        # Do not retain misses: normal source preparation may publish it later.
        with self._guard:
            selected = self._day_bindings.get(path)
            if selected is not None:
                self._day_bindings.move_to_end(path)
                return selected
        try:
            payload = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        month = payload.get("month")
        if "month" in payload and month != day[:7]:
            raise ReplayHistoryArchiveError("official day binding has another month")
        selected = (_digest(payload["catalog_epoch"], "catalog_epoch"), month)
        with self._guard:
            self._day_bindings[path] = selected
            self._day_bindings.move_to_end(path)
            while len(self._day_bindings) > DAY_BINDING_CACHE_SIZE:
                self._day_bindings.popitem(last=False)
        return selected

    def ensure_day_source(self, daily_root, identity, day_start):
        provider = BinanceKlineArchiveProvider()
        refs = provider.plan_objects(
            market_type=identity.market_type,
            symbol=identity.symbol,
            interval="1m",
            start_ms=day_start,
            end_ms=day_start + DAY - 1,
            now_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        )
        monthly = next(
            (ref for ref in refs if ref.granularity is ArchiveGranularity.MONTHLY), None
        )
        if monthly is not None:
            month_root = self.month_root(identity, monthly.period)
            with self.own(month_root):
                writer = ReplayHistoryArchiveWriter(month_root)
                manifest = writer.current_manifest(identity, "1m")
                with self._guard:
                    retry_at = self._missing_months.get(monthly.object_key, 0)
                if manifest is None and monotonic() >= retry_at:
                    try:
                        self.download(month_root, identity, monthly)
                        manifest = writer.current_manifest(identity, "1m")
                    except ArchiveHttpStatusError as error:
                        if error.status not in {404, 410}:
                            raise
                        # A recent monthly publication can lag its daily files.
                        # Do not repeat one missing monthly request per day;
                        # also do not permanently disable later publication.
                        with self._guard:
                            self._missing_months[monthly.object_key] = monotonic() + 300
                            self._missing_months.move_to_end(monthly.object_key)
                            while len(self._missing_months) > 64:
                                self._missing_months.popitem(last=False)
                if _covers_day(manifest, day_start):
                    return month_root
        daily = next(
            (
                ref
                for ref in refs
                if ref.granularity is ArchiveGranularity.DAILY
                and ref.start_ms == day_start
            ),
            None,
        )
        if daily is None:
            raise ReplayHistoryArchiveError(
                "official chart history day is not published"
            )
        self.download(daily_root, identity, daily)
        return daily_root

    def download(self, root, identity, ref):
        # One shared cache owns active ZIP leases even when several charts
        # download different months on different worker event loops.
        with self._guard:
            if self._downloads is None:
                self._downloads = HistoricalArchiveCache(
                    self.root / "downloads", max_bytes=512 * 1024**2
                )
            cache = self._downloads

        async def materialize():
            provider = BinanceKlineArchiveProvider()
            # Load current persisted routing in this worker; shared HTTP admission
            # spans its temporary event loop and live backfill transports.
            from app.data_engine.ingestion.config import IngestionConfig
            from app.data_engine.ingestion.transport import TransportLayer
            transport = TransportLayer(IngestionConfig())
            http = AiohttpArchiveHttpClient(
                timeout_seconds=self.timeout_seconds,
                request_runner=transport.archive_http_request, exchange=ref.exchange,
                context=ArchiveRequestContext(ref.provider_id, ref.object_key, "foreground"),
            )
            async with cache.materialize(ref, provider, http) as cached:
                if cached.provider_checksum is None:
                    raise ReplayHistoryArchiveError(
                        "official K-lines require checksum verification"
                    )
                parsed = await run_archive(
                    provider.parse_bars_for_replay, cached.path, ref
                )
                # Store the complete verified object once, with its original
                # audit counts. Day queries filter it; no rows are silently
                # relabelled as a daily object or imported as an unverified tail.
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
                await run_archive(
                    # Display context/close seeds need no account extrema
                    # tree. Account range queries build it lazily if requested.
                    ReplayHistoryArchiveWriter(root, precompute_market_ranges=False).import_batches,
                    identity,
                    "1m",
                    [batch],
                )

        try:
            asyncio.run(materialize())
        except (TimeoutError, aiohttp.ClientError) as error:
            raise ArchiveTransportError(
                "official chart archive transport interrupted"
            ) from error
