"""Reuse verified official day imports and the engine's immutable trade references."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial
import shutil
import zipfile
from weakref import WeakValueDictionary

from app.data_engine.storage.raw_trade_archive import RawAggTradeDatasetRef
from app.replay.trade_import import import_official_date_range, ReplayTradeImportError

from .models import PreparationError

DAY_MS = 86_400_000


class TradePreparationAdapter:
    def __init__(self, archive, *, importer=import_official_date_range):
        self.archive = archive
        self.importer = importer
        self._days: WeakValueDictionary = WeakValueDictionary()

    def validate(self, requirement, now_ms):
        if self.archive is None or not getattr(self.archive, "enabled", False):
            raise PreparationError("TRADE_ARCHIVE_UNAVAILABLE", "Verified trade archive is unavailable")
        if not hasattr(self.archive, "root"):
            raise PreparationError("TRADE_ARCHIVE_READ_ONLY", "Automatic trade imports require a local archive")
        if (requirement.exchange != "binance" or requirement.market_type != "futures"
                or not requirement.symbol.isalnum()):
            raise PreparationError("TRADE_PROVIDER_UNSUPPORTED", "Automatic verified trades support Binance USD-M futures")
        if requirement.end_ms > now_ms // DAY_MS * DAY_MS:
            raise PreparationError("TRADE_DAY_UNPUBLISHED", "Select completed UTC days for official trade history")

    def _covered(self, requirement):
        return any(window.start_time_ms <= requirement.start_ms
                   and window.end_time_ms >= requirement.end_ms - 1
                   for window in self.archive.list_verified_windows(
                       exchange=requirement.exchange, market_type=requirement.market_type,
                       symbol=requirement.symbol))

    def _import_day(self, requirement, date, repository):
        token = None
        download_limit = 256 * 1024**2
        if repository is not None:
            download_limit = min(download_limit, (repository.publication_available_bytes() - 2 * 1024**2) // 2)
            if download_limit < 64 * 1024:
                raise PreparationError("STORAGE_BUDGET", "Insufficient storage budget for an official trade download")
            # Download plus possible quarantine copy, checksum and metadata.
            token = repository.reserve_publication(2 * download_limit + 2 * 1024**2)

        def before_import(metadata, zip_path):
            if token is None:
                return
            with zipfile.ZipFile(zip_path) as archive:
                uncompressed = sum(item.file_size for item in archive.infolist())
            estimate = 2 * zip_path.stat().st_size + 3 * uncompressed + metadata.row_count * 512 + 2 * 1024**2
            if shutil.disk_usage(self.archive.root).free < estimate:
                raise PreparationError("STORAGE_BUDGET", "Insufficient free space for verified trade archive expansion")
            repository.resize_publication(token, estimate)

        try:
            self.importer(archive_dir=self.archive.root,
                exchange=requirement.exchange, market_type=requirement.market_type,
                symbol=requirement.symbol, start=date, end=date, require_checksum=True,
                staging_dir=self.archive.root / "_preparation_downloads",
                max_download_bytes=download_limit, before_archive_import=before_import)
            if token is not None:
                partition = self.archive._partition_path((requirement.exchange, requirement.market_type,
                    requirement.symbol, date.isoformat()))
                repository.register_publications(
                    ((path, "trade_archive") for path in partition.rglob("*") if path.is_file()), reservation=token)
                repository.check_physical_budget()
        except BaseException as exc:
            if token is not None:
                repository.abandon_publication(token)
            if (download_limit < 256 * 1024**2 and isinstance(exc, ReplayTradeImportError)
                    and str(exc) == "official aggregate-trade object exceeds its byte limit"):
                raise PreparationError("STORAGE_BUDGET", "Official trade package exceeds the remaining download allowance") from exc
            raise

    async def acquire(self, requirement, storage_call, *, repository=None):
        # Orchestrator fragments never cross UTC days. Different partial requests
        # in the same day share the official day package, even when disjoint.
        day = requirement.start_ms // DAY_MS
        key = (requirement.exchange, requirement.market_type, requirement.symbol, day)
        lock = self._days.setdefault(key, asyncio.Lock())
        async with lock:
            if not await storage_call(self._covered, requirement):
                self.archive.root.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(self.archive.root).free < 1024**3:
                    raise PreparationError("STORAGE_BUDGET", "Trade import requires 1 GiB of free working space")
                date = datetime.fromtimestamp(day * DAY_MS / 1000, timezone.utc).date()
                try:
                    await storage_call(self._import_day, requirement, date, repository)
                except ReplayTradeImportError as exc:
                    retryable = str(exc).startswith("failed to download official object:") or "time budget" in str(exc)
                    raise PreparationError("TRADE_IMPORT_FAILED", str(exc), retryable=retryable) from exc
            if not await storage_call(self._covered, requirement):
                raise PreparationError("TRADE_COVERAGE_INCOMPLETE", "Verified daily trade coverage is incomplete")
            reference = await storage_call(partial(self.archive.freeze_dataset,
                exchange=requirement.exchange, market_type=requirement.market_type,
                symbol=requirement.symbol, start_time_ms=requirement.start_ms,
                end_time_ms=requirement.end_ms - 1))
        # These files belong to the engine archive. Cache GC may forget the
        # acquisition receipt, but must never unlink engine-owned trade objects.
        byte_count = sum((self.archive.root / item.object_id).stat().st_size
                         for item in reference.objects)
        receipt = {"kind": "verified_trades", "dataset": reference.to_dict()}
        if repository is not None:
            await storage_call(repository.map_trade_receipt, receipt)
        return receipt, byte_count

    def validate_receipt(self, chunk):
        reference = RawAggTradeDatasetRef.from_dict(chunk["receipt"]["dataset"])
        source = chunk.get("source_requirement", chunk["requirement"])
        if (reference.exchange, reference.market_type, reference.symbol,
                reference.start_time_ms, reference.end_time_ms + 1) != (
                source["exchange"], source["market_type"], source["symbol"],
                source["start_ms"], source["end_ms"]):
            raise PreparationError("INPUT_CORRUPT", "Trade input identity does not match the preparation")
        self.archive.validate_dataset(reference)
        return reference
