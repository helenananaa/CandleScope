"""Persistent content-addressed cache for official K-line ZIP objects."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import weakref
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import aiohttp

from app.core.executors import run_archive
from app.data_engine.ingestion.metrics import LayerMetrics
from app.exchanges.archive import (
    ArchiveDataError,
    ArchiveHttpResponse,
    ArchiveHttpStatusError,
    ArchiveObjectRef,
    ArchiveRequestContext,
    HistoricalArchiveProvider,
)

logger = logging.getLogger("backfill.ArchiveCache")


class _CacheLeases:
    """Shared by cache instances/worker loops owning the same profile root."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.objects: dict[str, int] = {}
        self.paths: dict[Path, int] = {}


_ROOT_LEASES: weakref.WeakValueDictionary[str, _CacheLeases] = weakref.WeakValueDictionary()
_ROOT_LEASES_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class CachedArchiveObject:
    ref: ArchiveObjectRef
    path: Path
    content_sha256: str
    provider_checksum: str | None
    size_bytes: int
    cache_hit: bool
    revision_changed: bool
    etag: str | None = None
    last_modified: str | None = None
    download_elapsed_ms: int = 0
    verify_elapsed_ms: int = 0
    cache_generation: str = ""


class AiohttpArchiveHttpClient:
    """Bounded binary requests with immutable exchange context and route leases."""

    def __init__(
        self, *, timeout_seconds: float = 60.0,
        proxy_resolver: Callable[[], str | None] | None = None,
        request_runner=None, exchange: str = "", context: ArchiveRequestContext | None = None,
    ) -> None:
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._proxy_resolver = proxy_resolver
        self._request_runner = request_runner
        self._exchange = exchange
        self._context = context or ArchiveRequestContext()

    def for_exchange(self, exchange: str, *, context: ArchiveRequestContext | None = None) -> "AiohttpArchiveHttpClient":
        # Concurrent Binance/OKX downloads never mutate a shared routing field.
        return AiohttpArchiveHttpClient(
            timeout_seconds=self._timeout_seconds, proxy_resolver=self._proxy_resolver,
            request_runner=self._request_runner, exchange=exchange, context=context or self._context,
        )

    async def get_bytes(self, url: str, *, allowed_hosts: tuple[str, ...],
                        max_bytes: int) -> ArchiveHttpResponse:
        return await self._request("GET", url, allowed_hosts=allowed_hosts, max_bytes=max_bytes)

    async def download(self, url: str, destination: Path, *, allowed_hosts: tuple[str, ...],
                       max_bytes: int) -> ArchiveHttpResponse:
        return await self._request("GET", url, allowed_hosts=allowed_hosts,
                                   max_bytes=max_bytes, destination=destination)

    async def head(self, url: str, *, allowed_hosts: tuple[str, ...]) -> ArchiveHttpResponse:
        return await self._request("HEAD", url, allowed_hosts=allowed_hosts, max_bytes=64 * 1024)

    async def post_json(self, url: str, payload: dict[str, Any], *,
                        allowed_hosts: tuple[str, ...], max_bytes: int) -> tuple[ArchiveHttpResponse, Any]:
        response = await self._request("POST", url, allowed_hosts=allowed_hosts,
                                       max_bytes=max_bytes, payload=payload)
        try:
            parsed = json.loads(response.body.decode("utf-8")) if response.body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        return response, parsed

    async def _request(self, method: str, url: str, *, allowed_hosts: tuple[str, ...],
                       max_bytes: int, destination: Path | None = None,
                       payload: dict[str, Any] | None = None) -> ArchiveHttpResponse:
        _validate_url(url, allowed_hosts)
        async def attempt(proxy: str | None, observe: Callable[[int], None]) -> ArchiveHttpResponse:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.request(method, url, proxy=proxy, allow_redirects=False,
                                           json=payload) as response:
                    if 300 <= response.status < 400:
                        location = response.headers.get("Location")
                        if location:
                            _validate_url(urljoin(url, location), allowed_hosts)
                        return _response(response)
                    if method == "HEAD":
                        return _response(response)
                    if destination is None or response.status != 200:
                        body = await _read_bounded(response, max_bytes=(max_bytes if destination is None
                                                   else 64 * 1024), observe=observe)
                        return _response(response, body)
                    length = response.headers.get("Content-Length")
                    if length and int(length) > max_bytes:
                        raise ArchiveDataError("archive download exceeds configured size limit")
                    total = 0
                    # Each route retry truncates the partial download. The cache
                    # owns the temporary path and checksum/publication boundary.
                    with destination.open("wb", buffering=0) as output:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            observe(len(chunk))
                            total += len(chunk)
                            if total > max_bytes:
                                raise ArchiveDataError("archive download exceeds configured size limit")
                            await run_archive(output.write, chunk)
                    return _response(response)
        if self._request_runner is not None:
            return await self._request_runner(self._exchange, url, attempt,
                                              timeout_seconds=self._timeout_seconds, context=self._context)
        proxy = self._proxy_resolver() if self._proxy_resolver else None
        return await attempt(proxy, lambda size: None)


class HistoricalArchiveCache:
    """Bounded persistent ZIP cache independent from the K-line database."""

    def __init__(
        self,
        root: Path | str,
        *,
        max_bytes: int,
        revalidate_seconds: int = 86_400,
        max_download_bytes: int = 256 * 1024**2,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.objects_dir = self.root / "objects"
        self.tmp_dir = self.root / "tmp"
        self.index_path = self.root / "history_archive_cache.sqlite"
        self.max_bytes = max(1, int(max_bytes))
        self.revalidate_ms = max(0, int(revalidate_seconds)) * 1_000
        self.max_download_bytes = max(1, int(max_download_bytes))
        with _ROOT_LEASES_LOCK:
            self._leases = _ROOT_LEASES.setdefault(str(self.root), _CacheLeases())
        self._lock = self._leases.lock
        self._active = self._leases.objects
        self.metrics = LayerMetrics("HistoricalArchiveCache")
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self._init_index()

    @asynccontextmanager
    async def materialize(
        self,
        ref: ArchiveObjectRef,
        provider: HistoricalArchiveProvider,
        http,
    ):
        path: Path | None = None
        with self._lock:
            self._active[ref.object_key] = self._active.get(ref.object_key, 0) + 1
        try:
            value = await self._materialize(ref, provider, http)
            path = value.path.resolve()
            with self._lock:
                self._leases.paths[path] = self._leases.paths.get(path, 0) + 1
            yield value
        finally:
            with self._lock:
                _release_count(self._active, ref.object_key)
                if path is not None:
                    _release_count(self._leases.paths, path)
            # A download may temporarily exceed the budget while every
            # candidate is leased.  Re-run eviction after releasing a lease
            # so the persistent cache converges to its configured bound.
            await run_archive(self._evict)
            await run_archive(self._drain_blob_cleanup)

    async def _materialize(
        self,
        ref: ArchiveObjectRef,
        provider: HistoricalArchiveProvider,
        http,
    ) -> CachedArchiveObject:
        if not ref.url:
            raise ArchiveDataError("archive object has no resolved download URL")
        now_ms = _now_ms()
        validation_started = time.monotonic()
        existing = await run_archive(self._lookup, ref.object_key)
        if existing is not None and not Path(existing["path"]).is_file():
            await run_archive(self._remove_record, ref.object_key)
            existing = None

        if existing is not None and now_ms - int(existing["validated_at_ms"]) <= self.revalidate_ms:
            await run_archive(self._touch, ref.object_key, None, now_ms)
            self.metrics.inc("archive_cache_hits")
            self.metrics.mark("last_cache_hit_at")
            logger.info("archive_cache_hit object=%s", ref.object_key)
            return _cached_object(
                ref,
                existing,
                cache_hit=True,
                revision_changed=False,
            )

        provider_checksum: str | None = None
        checksum_response: ArchiveHttpResponse | None = None
        if ref.checksum_url:
            checksum_response = await http.get_bytes(
                ref.checksum_url,
                allowed_hosts=ref.allowed_hosts,
                max_bytes=16 * 1024,
            )
            if checksum_response.status != 200:
                raise ArchiveHttpStatusError(checksum_response.status, "checksum request")
            provider_checksum = provider.parse_checksum(checksum_response.body, ref)
            if (
                existing is not None
                and provider_checksum == existing["provider_checksum"]
            ):
                await run_archive(self._touch, ref.object_key, now_ms, now_ms)
                self.metrics.inc("archive_cache_revalidated_hits")
                logger.info("archive_cache_hit object=%s revalidated=checksum", ref.object_key)
                verify_elapsed_ms = int(
                    (time.monotonic() - validation_started) * 1_000
                )
                self.metrics.set("last_verify_elapsed_ms", verify_elapsed_ms)
                return _cached_object(
                    ref,
                    existing,
                    cache_hit=True,
                    revision_changed=False,
                    verify_elapsed_ms=verify_elapsed_ms,
                )
        elif existing is not None:
            head = await http.head(ref.url, allowed_hosts=ref.allowed_hosts)
            if head.status == 200 and _metadata_matches(existing, head.headers):
                await run_archive(self._touch, ref.object_key, now_ms, now_ms)
                self.metrics.inc("archive_cache_revalidated_hits")
                logger.info("archive_cache_hit object=%s revalidated=metadata", ref.object_key)
                verify_elapsed_ms = int(
                    (time.monotonic() - validation_started) * 1_000
                )
                self.metrics.set("last_verify_elapsed_ms", verify_elapsed_ms)
                return _cached_object(
                    ref,
                    existing,
                    cache_hit=True,
                    revision_changed=False,
                    verify_elapsed_ms=verify_elapsed_ms,
                )

        temporary = self.tmp_dir / f".{uuid4().hex}.zip.tmp"
        try:
            preflight_elapsed_ms = int(
                (time.monotonic() - validation_started) * 1_000
            )
            download_started = time.monotonic()
            response = await http.download(
                ref.url,
                temporary,
                allowed_hosts=ref.allowed_hosts,
                max_bytes=self.max_download_bytes,
            )
            if response.status != 200:
                raise ArchiveHttpStatusError(response.status, "download")
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise ArchiveDataError("archive download is empty")
            download_elapsed_ms = int(
                (time.monotonic() - download_started) * 1_000
            )
            digest_started = time.monotonic()
            content_sha256 = await run_archive(_file_sha256, temporary)
            if provider_checksum is not None and content_sha256 != provider_checksum:
                raise ArchiveDataError("archive SHA-256 does not match provider checksum")
            verify_elapsed_ms = preflight_elapsed_ms + int(
                (time.monotonic() - digest_started) * 1_000
            )
            destination = self._content_path(content_sha256)
            size_bytes = temporary.stat().st_size
            revision_changed = bool(
                existing is not None
                and existing["content_sha256"] != content_sha256
            )
            record = {
                "object_key": ref.object_key,
                "provider_id": ref.provider_id,
                "exchange": ref.exchange,
                "market_type": ref.market_type,
                "symbol": ref.symbol,
                "interval": ref.interval,
                "granularity": ref.granularity.value,
                "period": ref.period,
                "start_ms": ref.start_ms,
                "end_ms": ref.end_ms,
                "source_url": ref.url,
                "checksum_url": ref.checksum_url,
                "provider_checksum": provider_checksum,
                "content_sha256": content_sha256,
                "size_bytes": size_bytes,
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "path": str(destination),
                "validated_at_ms": now_ms,
                "last_access_ms": now_ms,
                "state": "ready",
                "cache_generation": uuid4().hex,
                "retain_until_ms": 0,
                "cleanup_pending": 0,
                "cleanup_attempts": 0,
                "cleanup_retry_at_ms": 0,
                "cleanup_error": None,
            }
            await run_archive(self._publish_download, temporary, destination, record)
            if (
                existing is not None
                and existing.get("content_sha256") != content_sha256
            ):
                await run_archive(self._discard_superseded_blob, existing)
            await run_archive(self._evict)
            self.metrics.inc("archive_cold_downloads")
            self.metrics.inc("archive_download_bytes", size_bytes)
            self.metrics.set("last_download_elapsed_ms", download_elapsed_ms)
            self.metrics.set("last_verify_elapsed_ms", verify_elapsed_ms)
            self.metrics.mark("last_download_at")
            logger.info(
                "archive_cold_download object=%s bytes=%d revision_changed=%s",
                ref.object_key,
                size_bytes,
                revision_changed,
            )
            return CachedArchiveObject(
                ref=ref,
                path=destination,
                content_sha256=content_sha256,
                provider_checksum=provider_checksum,
                size_bytes=size_bytes,
                cache_hit=False,
                revision_changed=revision_changed,
                etag=record["etag"],
                last_modified=record["last_modified"],
                download_elapsed_ms=download_elapsed_ms,
                verify_elapsed_ms=verify_elapsed_ms,
                cache_generation=record["cache_generation"],
            )
        except BaseException:
            self.metrics.inc("archive_download_errors")
            self.metrics.mark("last_error_at")
            raise
        finally:
            temporary.unlink(missing_ok=True)

    async def invalidate(self, object_key: str) -> None:
        await run_archive(self._invalidate_sync, object_key)
        self.metrics.inc("archive_invalidations")

    async def has_fresh(self, ref: ArchiveObjectRef) -> bool:
        """Return whether *ref* can be opened without any network validation.

        The router uses this inexpensive index check to keep a genuinely cold
        archive download behind the foreground REST request while still
        allowing an empty K-line database to rebuild directly from a warm ZIP.
        A stale or missing file deliberately returns ``False``; the normal
        materialization path remains responsible for revalidation and repair.
        """
        existing = await run_archive(self._lookup, ref.object_key)
        if existing is None:
            return False
        if not Path(existing["path"]).is_file():
            await run_archive(self._remove_record, ref.object_key)
            return False
        return (
            _now_ms() - int(existing["validated_at_ms"])
            <= self.revalidate_ms
        )

    async def resolve_fresh(self, ref: ArchiveObjectRef) -> ArchiveObjectRef | None:
        """Recover a fresh object's URL locally, including OKX resolver refs."""
        existing = await run_archive(self._lookup, ref.object_key)
        if (existing is None or not Path(existing["path"]).is_file()
                or _now_ms() - int(existing["validated_at_ms"]) > self.revalidate_ms):
            return None
        return replace(ref, url=existing["source_url"], checksum_url=existing["checksum_url"])

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS object_count, COALESCE(SUM(size_bytes), 0) AS bytes "
                "FROM archive_objects WHERE state = 'ready'"
            ).fetchone()
            cleanup = connection.execute(
                "SELECT COALESCE(SUM(cleanup_pending), 0) AS pending, "
                "COALESCE(SUM(pinned), 0) AS pinned, "
                "COALESCE(SUM(cleanup_error IS NOT NULL), 0) AS errors "
                "FROM archive_objects"
            ).fetchone()
            pending_blobs = connection.execute(
                "SELECT COUNT(*) FROM archive_blob_cleanup"
            ).fetchone()[0]
        with self._lock:
            active = sum(self._active.values())
        return {
            "root": str(self.root),
            "max_bytes": self.max_bytes,
            "object_count": int(row["object_count"] if row else 0),
            "bytes": int(row["bytes"] if row else 0),
            "active_leases": active,
            "cleanup_pending_objects": int(cleanup["pending"]),
            "cleanup_errors": int(cleanup["errors"]),
            "pinned_objects": int(cleanup["pinned"]),
            "pending_blob_deletions": int(pending_blobs),
            "revalidate_ms": self.revalidate_ms,
            "metrics": self.metrics.snapshot(),
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.index_path), timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_index(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS archive_objects (
                    object_key TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    granularity TEXT NOT NULL,
                    period TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    source_url TEXT NOT NULL,
                    checksum_url TEXT,
                    provider_checksum TEXT,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    etag TEXT,
                    last_modified TEXT,
                    path TEXT NOT NULL,
                    validated_at_ms INTEGER NOT NULL,
                    last_access_ms INTEGER NOT NULL,
                    state TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_archive_objects_lru
                ON archive_objects(state, last_access_ms);
                CREATE TABLE IF NOT EXISTS archive_blob_cleanup (
                    content_sha256 TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    last_error TEXT
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(archive_objects)")}
            for name, definition in (
                ("pinned", "INTEGER NOT NULL DEFAULT 0"),
                ("retain_until_ms", "INTEGER NOT NULL DEFAULT 0"),
                ("cleanup_pending", "INTEGER NOT NULL DEFAULT 0"),
                ("cleanup_attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("cleanup_retry_at_ms", "INTEGER NOT NULL DEFAULT 0"),
                ("cleanup_error", "TEXT"),
                ("cache_generation", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE archive_objects ADD COLUMN {name} {definition}")

    async def set_pinned(self, object_key: str, pinned: bool) -> None:
        """Protect an explicitly retained object from both import cleanup and LRU."""
        def update() -> None:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "UPDATE archive_objects SET pinned = ? WHERE object_key = ?",
                    (int(pinned), object_key),
                )
        await run_archive(update)

    async def cleanup_candidates(self, after: str = "", limit: int = 128) -> list[dict[str, Any]]:
        def read() -> list[dict[str, Any]]:
            with self._lock, self._connect() as connection:
                return [dict(row) for row in connection.execute(
                    "SELECT object_key, content_sha256, cache_generation FROM archive_objects "
                    "WHERE state = 'ready' AND object_key > ? ORDER BY object_key LIMIT ?",
                    (after, min(128, max(1, limit))),
                )]
        return await run_archive(read)

    async def cleanup_imported(self, proofs: list[dict[str, Any]], *, retain_seconds: int = 0) -> int:
        """Retire only the exact cached versions confirmed by the storage owner."""
        return await run_archive(self._cleanup_imported, proofs, retain_seconds=retain_seconds)

    def _cleanup_imported(self, proofs: list[dict[str, Any]], *, retain_seconds: int = 0) -> int:
        retired = 0
        for proof in proofs:
            object_key, digest = str(proof["object_key"]), str(proof["content_sha256"])
            with self._lock, self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM archive_objects WHERE object_key = ? AND content_sha256 = ? "
                    "AND cache_generation = ?",
                    (object_key, digest, str(proof.get("cache_generation") or "")),
                ).fetchone()
                if row is None:
                    continue  # Already evicted, or a newer revision now owns this key.
                if retain_seconds and not proof.get("imported_at_ms"):
                    continue  # No stable retention origin: never substitute wall-clock now.
                retain_until = int(proof.get("imported_at_ms") or 0) + retain_seconds * 1000 if retain_seconds else 0
                connection.execute(
                    "UPDATE archive_objects SET cleanup_pending = 1, retain_until_ms = ? WHERE object_key = ?",
                    (retain_until, object_key),
                )
                if (
                    retain_until > _now_ms() or row["pinned"] or self._active.get(object_key, 0)
                    or self._leases.paths.get(Path(row["path"]).resolve(), 0)
                    or int(row["cleanup_retry_at_ms"]) > _now_ms()
                ):
                    continue
                try:
                    connection.execute("DELETE FROM archive_objects WHERE object_key = ?", (object_key,))
                    self._delete_unreferenced_path(connection, row["path"], digest, strict=True)
                except OSError as exc:
                    # Keep the index/path for retry. Never turn a committed
                    # import into a download failure because unlink failed.
                    connection.rollback()
                    attempts = int(row["cleanup_attempts"]) + 1
                    delay_ms = min(300_000, 1_000 * 2 ** min(attempts, 8))
                    connection.execute(
                        "UPDATE archive_objects SET cleanup_pending = 1, cleanup_attempts = ?, "
                        "cleanup_retry_at_ms = ?, cleanup_error = ? "
                        "WHERE object_key = ? AND content_sha256 = ?",
                        (attempts, _now_ms() + delay_ms, str(exc)[:500], object_key, digest),
                    )
                    self.metrics.inc("archive_cleanup_errors")
                    continue
                retired += 1
                self.metrics.inc("archive_objects_cleaned_after_import")
        return retired

    def _lookup(self, object_key: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM archive_objects WHERE object_key = ? AND state = 'ready'",
                (object_key,),
            ).fetchone()
        return dict(row) if row is not None else None

    def _upsert(self, record: dict[str, Any]) -> None:
        columns = tuple(record)
        values = tuple(record[column] for column in columns)
        assignments = ", ".join(
            f"{column}=excluded.{column}" for column in columns if column != "object_key"
        )
        placeholders = ",".join("?" for _ in columns)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"INSERT INTO archive_objects ({','.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(object_key) DO UPDATE SET {assignments}",
                values,
            )
            connection.commit()

    def _publish_download(self, temporary: Path, destination: Path, record: dict[str, Any]) -> None:
        # A cleanup of another key sharing this hash must not unlink the blob
        # between publication and registration of its new index reference.
        with self._lock:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                temporary.unlink(missing_ok=True)
            else:
                os.replace(temporary, destination)
            self._upsert(record)

    def _touch(self, object_key: str, validated_at_ms: int | None, access_ms: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE archive_objects SET validated_at_ms = COALESCE(?, validated_at_ms), last_access_ms = ? "
                "WHERE object_key = ?",
                (validated_at_ms, access_ms, object_key),
            )
            connection.commit()

    def _remove_record(self, object_key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM archive_objects WHERE object_key = ?", (object_key,))
            connection.commit()

    def _invalidate_sync(self, object_key: str) -> None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT path, content_sha256 FROM archive_objects WHERE object_key = ?",
                (object_key,),
            ).fetchone()
            connection.execute("DELETE FROM archive_objects WHERE object_key = ?", (object_key,))
            connection.commit()
            if row is not None:
                self._delete_unreferenced_path(connection, row["path"], row["content_sha256"])

    def _discard_superseded_blob(self, previous: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            self._delete_unreferenced_path(
                connection,
                str(previous["path"]),
                str(previous["content_sha256"]),
            )

    def _evict(self) -> None:
        with self._lock, self._connect() as connection:
            total_row = connection.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) AS bytes FROM archive_objects "
                "WHERE state = 'ready'"
            ).fetchone()
            total = int(total_row["bytes"] if total_row else 0)
            if total <= self.max_bytes:
                return
            rows = connection.execute(
                "SELECT object_key, path, content_sha256, size_bytes, pinned, retain_until_ms FROM archive_objects "
                "WHERE state = 'ready' ORDER BY last_access_ms ASC"
            ).fetchall()
            for row in rows:
                if total <= self.max_bytes:
                    break
                if row["object_key"] in self._active or row["pinned"] or int(row["retain_until_ms"]) > _now_ms():
                    continue
                connection.execute(
                    "DELETE FROM archive_objects WHERE object_key = ?",
                    (row["object_key"],),
                )
                total -= int(row["size_bytes"])
                self._delete_unreferenced_path(
                    connection,
                    row["path"],
                    row["content_sha256"],
                )
                self.metrics.inc("archive_evictions")
            connection.commit()

    def _delete_unreferenced_path(
        self,
        connection: sqlite3.Connection,
        raw_path: str,
        content_sha256: str,
        *,
        strict: bool = False,
    ) -> None:
        remaining = connection.execute(
            "SELECT 1 FROM archive_objects WHERE content_sha256 = ? LIMIT 1",
            (content_sha256,),
        ).fetchone()
        if remaining is not None:
            return
        candidate = Path(raw_path).resolve()
        root = self.objects_dir.resolve()
        if candidate != root and root in candidate.parents:
            if self._leases.paths.get(candidate, 0):
                connection.execute(
                    "INSERT OR IGNORE INTO archive_blob_cleanup (content_sha256, path) VALUES (?, ?)",
                    (content_sha256, str(candidate)),
                )
                return
            try:
                candidate.unlink(missing_ok=True)
            except OSError as exc:
                if strict:
                    raise
                connection.execute(
                    "INSERT OR REPLACE INTO archive_blob_cleanup (content_sha256, path, last_error) "
                    "VALUES (?, ?, ?)", (content_sha256, str(candidate), str(exc)[:500]),
                )
                self.metrics.inc("archive_blob_cleanup_errors")
                return
            connection.execute(
                "DELETE FROM archive_blob_cleanup WHERE content_sha256 = ?", (content_sha256,),
            )

    def _drain_blob_cleanup(self) -> None:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM archive_blob_cleanup LIMIT 128").fetchall()
            for row in rows:
                self._delete_unreferenced_path(connection, row["path"], row["content_sha256"])

    def _content_path(self, digest: str) -> Path:
        return self.objects_dir / digest[:2] / f"{digest}.zip"


async def _read_bounded(response: aiohttp.ClientResponse, *, max_bytes: int,
                        observe: Callable[[int], None] = lambda size: None) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > max_bytes:
        raise ArchiveDataError("archive HTTP response exceeds configured size limit")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(64 * 1024):
        observe(len(chunk))
        total += len(chunk)
        if total > max_bytes:
            raise ArchiveDataError("archive HTTP response exceeds configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _response(response: aiohttp.ClientResponse, body: bytes = b"") -> ArchiveHttpResponse:
    return ArchiveHttpResponse(
        status=int(response.status),
        headers={str(key).lower(): str(value) for key, value in response.headers.items()},
        body=body,
    )


def _validate_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlparse(str(url or ""))
    hosts = {str(host).strip().lower() for host in allowed_hosts}
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in hosts:
        raise ArchiveDataError("archive URL is outside the provider allowlist")
    if parsed.username or parsed.password:
        raise ArchiveDataError("archive URL must not contain credentials")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_matches(existing: dict[str, Any], headers: dict[str, str]) -> bool:
    etag = headers.get("etag")
    modified = headers.get("last-modified")
    length = headers.get("content-length")
    if etag and existing.get("etag"):
        return etag == existing["etag"]
    if modified and existing.get("last_modified"):
        return modified == existing["last_modified"]
    if length and str(existing.get("size_bytes")) == str(length):
        return True
    return False


def _cached_object(
    ref: ArchiveObjectRef,
    record: dict[str, Any],
    *,
    cache_hit: bool,
    revision_changed: bool,
    verify_elapsed_ms: int = 0,
) -> CachedArchiveObject:
    return CachedArchiveObject(
        ref=ref,
        path=Path(record["path"]),
        content_sha256=str(record["content_sha256"]),
        provider_checksum=record.get("provider_checksum"),
        size_bytes=int(record["size_bytes"]),
        cache_hit=cache_hit,
        revision_changed=revision_changed,
        etag=record.get("etag"),
        last_modified=record.get("last_modified"),
        verify_elapsed_ms=verify_elapsed_ms,
        cache_generation=str(record.get("cache_generation") or ""),
    )


def _release_count(counts: dict, key: Any) -> None:
    remaining = counts.get(key, 0) - 1
    if remaining > 0:
        counts[key] = remaining
    else:
        counts.pop(key, None)


def _now_ms() -> int:
    return int(time.time() * 1_000)


__all__ = [
    "AiohttpArchiveHttpClient",
    "CachedArchiveObject",
    "HistoricalArchiveCache",
]
