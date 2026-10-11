"""Built-in Binance history discovery; bodies remain lazy and checksum verified."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from .canonical import canonical_sha256
from .history_archive import _atomic_write_json
from .remote_trade_archive import (
    RemoteAggTradeIndex,
    RemoteAggTradeMetadataObject,
    RemoteRawAggTradeArchive,
    publish_remote_agg_trade_index,
    sync_official_agg_trade_availability,
)
from .trade_import import OfficialTradeHistoryEmpty, list_official_agg_trade_symbols

logger = logging.getLogger(__name__)


class OfficialAggTradeArchive(RemoteRawAggTradeArchive):
    def __init__(self, cache_root, *, symbols=(), defer_refresh=False, **kwargs):
        self.catalog_root = Path(cache_root) / "_official_origin"
        self.symbols = tuple(symbols)
        self.catalog_timeout = kwargs.get("download_timeout_seconds", 60)
        self._catalog_guard = threading.Lock()
        self.catalog_refreshing = False
        self.catalog_discovered = 0
        self.catalog_completed = 0
        self.catalog_failed = 0
        if not defer_refresh and self.needs_catalog_refresh():
            self.refresh_official_catalog()
        if not (self.catalog_root / "trade-index.json").exists():
            empty = self._empty_index()
            _atomic_write_json(self.catalog_root / "trade-index.json", empty.to_dict())
        super().__init__(cache_root, self.catalog_root, **kwargs)

    @staticmethod
    def _empty_index():
        empty = RemoteAggTradeIndex(
            index_epoch="sha256:" + "0" * 64,
            generated_at_ms=0,
            compatibility_indexes=(),
            verified_receipts=(),
        )
        return replace(empty, index_epoch=canonical_sha256(empty.hash_payload()))

    def needs_catalog_refresh(self):
        try:
            state = json.loads((self.catalog_root / "discovery.json").read_text())
            return (state["symbols"] != list(self.symbols)
                    or time.time() - state["completed_at"] > 3600)
        except (OSError, ValueError, KeyError):
            return True

    def _load_origin_metadata(self):
        payload = self.origin.read_json("trade-index.json", max_bytes=1024 * 1024)
        empty = self._empty_index()
        if payload == empty.to_dict():
            return empty, {}, {}, {}
        return super()._load_origin_metadata()

    def _publish(self, stage):
        index = publish_remote_agg_trade_index(stage)
        generation = stage.relative_to(self.catalog_root).as_posix()
        index = replace(
            index,
            official_availability_indexes=tuple(
                RemoteAggTradeMetadataObject(
                    path=generation + "/" + item.path, sha256=item.sha256
                ) for item in index.official_availability_indexes
            ),
        )
        index = replace(index, index_epoch=canonical_sha256(index.hash_payload()))
        _atomic_write_json(self.catalog_root / "trade-index.json", index.to_dict())
        if hasattr(self, "_lock"):
            with self._lock:
                self._next_refresh = 0.0

    def refresh_official_catalog(self):
        if not self._catalog_guard.acquire(blocking=False):
            return
        self.catalog_refreshing = True
        retrying = self.catalog_failed > 0
        self.catalog_completed = self.catalog_failed = 0
        stage = self.catalog_root / "generations" / uuid.uuid4().hex
        try:
            symbols = self.symbols or list_official_agg_trade_symbols(
                timeout_seconds=self.catalog_timeout
            )
            self.catalog_discovered = len(symbols)
            # Publish familiar markets early while the full historical catalog
            # continues in the background. This is ordering, never a whitelist.
            priority = {symbol: i for i, symbol in enumerate(
                ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "XRPUSDT", "LTCUSDT")
            )}
            symbols = tuple(sorted(symbols, key=lambda symbol: (priority.get(symbol, 100), symbol)))
            # Retain previously validated availability if one instrument's
            # listing is temporarily unavailable. Never erase the whole catalog.
            current = self.catalog_root / "trade-index.json"
            if current.exists():
                payload = json.loads(current.read_text())
                for item in payload.get("official_availability_indexes", []):
                    source = self.catalog_root / item["path"]
                    relative = item["path"].split("_official_availability/", 1)[-1]
                    if Path(relative).parts[-2].removeprefix("symbol=") not in symbols:
                        continue
                    destination = stage / "_official_availability" / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)

            def sync(symbol):
                cached = stage / "_official_availability" / "exchange=binance" / "market_type=futures" / ("symbol=" + symbol) / "availability.json"
                if retrying and cached.exists() and time.time() - cached.stat().st_mtime < 3600:
                    return
                return sync_official_agg_trade_availability(
                    stage, exchange="binance", market_type="futures",
                    symbol=symbol, timeout_seconds=self.catalog_timeout,
                )

            # Bounded concurrency keeps full discovery practical without
            # blocking the application's event loop or fetching trade bodies.
            successes = 0
            last_publish = time.monotonic()
            with ThreadPoolExecutor(max_workers=16, thread_name_prefix="replay-catalog") as pool:
                futures = {pool.submit(sync, symbol): symbol for symbol in symbols}
                for future in as_completed(futures):
                    self.catalog_completed += 1
                    try:
                        future.result()
                        successes += 1
                    except OfficialTradeHistoryEmpty:
                        pass
                    except Exception:
                        self.catalog_failed += 1
                        logger.warning("Official history listing unavailable for %s", futures[future], exc_info=True)
                    if successes and time.monotonic() - last_publish >= 15:
                        # Worker files are replaced atomically. Copy into an
                        # immutable generation before exposing a partial update.
                        snapshot = self.catalog_root / "generations" / uuid.uuid4().hex
                        shutil.copytree(stage, snapshot)
                        self._publish(snapshot)
                        last_publish = time.monotonic()
            if successes:
                self._publish(stage)
            if not self.catalog_failed:
                _atomic_write_json(self.catalog_root / "discovery.json", {
                    "symbols": list(self.symbols), "completed_at": int(time.time()),
                    "discovered_count": len(symbols),
                })
        except Exception:
            logger.warning("Could not refresh official replay history catalog; retaining cached availability", exc_info=True)
        finally:
            self.catalog_refreshing = False
            self._catalog_guard.release()

    def historical_instrument_metadata(self, exchange, market_type, symbol):
        identity = {"exchange": exchange, "market_type": market_type, "symbol": symbol}
        if identity not in self.list_verified_identities():
            return None
        # The verified USD-M archive namespace establishes the instrument;
        # quote suffixes only split its identity, never fabricate trading rules.
        for quote in ("USDT", "USDC", "BUSD", "USD1"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                return {"exchange": exchange, "marketType": market_type,
                        "symbol": symbol, "baseAsset": symbol[:-len(quote)],
                        "quoteAsset": quote, "metadataSource": "binance-official-history"}
        return None

    def diagnostics(self):
        result = super().diagnostics()
        return {**result, "catalog_refreshing": self.catalog_refreshing,
                "catalog_discovered": self.catalog_discovered,
                "catalog_completed": self.catalog_completed,
                "catalog_failed": self.catalog_failed}
