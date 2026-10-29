from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.data_engine.backfill import BackfillEngine
from app.data_engine.backfill.archive_cache import HistoricalArchiveCache
from app.data_engine.backfill.archive_cleanup import ArchiveImportCleanup
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.models import BackfillPlan, BackfillStatus, BackfillTask
from app.data_engine.backfill.source_router import HistoricalSourceRouter
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.transport import TransportLayer
from app.data_engine.storage import klines_repo
from app.exchanges import bootstrap_default_adapters
from app.exchanges.archive import ArchiveHttpResponse
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider


DAY = 86_400_000
START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


class ArchiveHttp:
    def __init__(self, ref, *, close=105):
        self.ref = ref
        self.checksums = self.downloads = 0
        out = io.BytesIO()
        rows = "".join(
            f"{at},100,110,90,{close},1.5,{at + DAY - 1},157.5,10,0.75,78.75,0\n"
            for at in range(ref.start_ms, ref.end_ms + 1, DAY)
        )
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(ref.expected_filename.removesuffix(".zip") + ".csv", rows)
        self.payload = out.getvalue()

    async def get_bytes(self, url, **kwargs):
        self.checksums += 1
        digest = hashlib.sha256(self.payload).hexdigest()
        return ArchiveHttpResponse(200, {}, f"{digest}  {self.ref.expected_filename}\n".encode())

    async def download(self, url, destination, **kwargs):
        self.downloads += 1
        destination.write_bytes(self.payload)
        return ArchiveHttpResponse(200, {})

    async def post_json(self, *args, **kwargs):
        raise AssertionError("Unexpected OKX directory request")


def fixture_object(tmp_path):
    provider = BinanceKlineArchiveProvider()
    ref = next(ref for ref in provider.plan_objects(
        market_type="futures", symbol="BTCUSDT", interval="1d",
        start_ms=START, end_ms=START + 31 * DAY - 1, now_ms=START + 90 * DAY,
    ) if ref.granularity.value == "monthly")
    config = BackfillConfig(
        history_archive_cache_dir=str(tmp_path / "zip-cache"),
        reconcile_generate_custom=False, reconcile_enable_cache_push=False,
        publish_mode="log",
    )
    return config, provider, ref, ArchiveHttp(ref)


def storage_at(monkeypatch, tmp_path):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "klines.sqlite")
    klines_repo.init_klines_storage()
    return klines_repo.AsyncKlinesRepoAdapter()


def import_object(value):
    return klines_repo.import_history_archive(
        value.ref.symbol, value.ref.interval,
        [bar.to_storage_dict() for bar in value.bars], value.receipt(),
        exchange=value.ref.exchange, market_type=value.ref.market_type,
    )


def test_default_ccxt_entry_fetches_imports_and_cleans_zip(monkeypatch, tmp_path):
    """Real bootstrap, factory, fetch/reconcile/storage and cleanup worker.

    Only remote HTTP is replaced; no injected plugin/registry can hide a lost
    archive factory on the production CCXT entry point.
    """
    async def run():
        config, _, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        ingestion = IngestionConfig(proxy_mode="none")
        transport = TransportLayer(ingestion)
        engine = BackfillEngine(config, storage, transport, ingestion_config=ingestion)
        router = engine.fetcher._source_router
        assert router is not None
        router._http = http

        async def unexpected_rest(*args, **kwargs):
            raise AssertionError("Complete closed month should be served by the archive")
        monkeypatch.setattr(transport, "http_fetch", unexpected_rest)
        task = BackfillTask(ref.symbol, ref.interval, ref.start_ms, ref.end_ms,
                            exchange=ref.exchange, market_type=ref.market_type)
        try:
            results = await engine.fetcher.fetch([task])
            assert results[0].status == BackfillStatus.COMPLETED
            assert len(results[0].bars) == 31
            assert http.downloads == 1
            path = Path(router._cache._lookup(ref.object_key)["path"])
            assert path.exists()
            reconciled = await engine.reconciler.reconcile(results, BackfillPlan(gaps=[], tasks=[task]))
            assert not reconciled.errors
            assert reconciled.archive_objects_imported == 1

            cleaned = asyncio.Event()
            original = router._cache.cleanup_imported
            async def observe(proofs):
                count = await original(proofs)
                if count:
                    cleaned.set()
                return count
            monkeypatch.setattr(router._cache, "cleanup_imported", observe)
            engine.start_archive_cleanup()
            await asyncio.wait_for(cleaned.wait(), 5)
            assert not path.exists()
            stored = klines_repo.query_klines(ref.symbol, ref.interval,
                                              exchange=ref.exchange, market_type=ref.market_type)
            assert len(stored) == 31
            assert stored[0]["trades"] == 10
            assert stored[0]["taker_buy_quote"] == 78.75
            assert len(await storage.get_history_archive_import_proofs(results[0].metadata["archive_objects"])) == 1
            plugin = bootstrap_default_adapters().get_plugin("binance")
            assert plugin.history_transport_snapshot(ingestion)["clients_created"] == 0
        finally:
            await engine.close()
        assert not router._cleanup.snapshot()["running"]
    asyncio.run(run())


def test_pool_mode_defers_archives_to_rest_without_using_first_route(tmp_path):
    async def run():
        config, _, ref, _ = fixture_object(tmp_path)
        ingestion = IngestionConfig(proxy_mode="pool", proxy_routes=[
            {"id": "okx-only", "url": "http://127.0.0.1:51001", "enabled": True, "exchanges": ["okx"]},
            {"id": "binance", "url": "http://127.0.0.1:51002", "enabled": True, "exchanges": ["binance"]},
        ])
        transport = TransportLayer(ingestion)
        engine = BackfillEngine(config=config, transport=transport, ingestion_config=ingestion)
        router = engine.fetcher._source_router
        plan = await router.prepare([BackfillTask(ref.symbol, ref.interval, ref.start_ms, ref.end_ms)])
        assert not plan.futures
        assert router.snapshot()["routing_unavailable_reason"] == "proxy_pool_archive_transport_unavailable"
        with pytest.raises(ValueError, match="proxy_pool_archive_transport_unavailable"):
            transport.resolve_archive_proxy()
        # A settings change is checked again at the HTTP boundary.
        ingestion.proxy_mode = "none"
        assert transport.resolve_archive_proxy() is None
        ingestion.proxy_mode = "pool"
        with pytest.raises(ValueError):
            router._http._proxy()
        await engine.close()
    asyncio.run(run())


@pytest.mark.parametrize("flag", [False, True])
def test_okx_default_entry_preserves_flag_and_probe_failure(tmp_path, flag):
    async def run():
        config = BackfillConfig(history_archive_cache_dir=str(tmp_path), history_archive_okx_enabled=flag)
        class Http:
            calls = 0
            async def post_json(self, *args, **kwargs):
                self.calls += 1
                return ArchiveHttpResponse(503, {}), None
        http = Http()
        router = HistoricalSourceRouter(config, http=http)
        result = await router.probe_enabled_capabilities()
        assert not result["okx"]["enabled"]
        assert http.calls == int(flag)
        assert not router.snapshot()["okx_probe_passed"]
        plan = await router.prepare([BackfillTask("BTC-USDT", "1m", START, START + 31 * DAY,
                                                  exchange="okx")])
        assert not plan.futures
        assert http.calls == int(flag)
        await router.close()
    asyncio.run(run())


def test_advisory_receipt_never_authorizes_cleanup(monkeypatch, tmp_path):
    async def run():
        config, provider, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        router = HistoricalSourceRouter(config, http=http)
        value = await router._load_object(provider, ref)
        path = Path(router._cache._lookup(ref.object_key)["path"])
        klines_repo.record_history_archive_imports([value.receipt()])
        cleanup = ArchiveImportCleanup(config, router._cache, storage.get_history_archive_import_proofs)
        await cleanup.sweep_page()
        assert path.exists()
        assert await storage.get_history_archive_import_proofs([value.receipt()]) == []
        import_object(value)
        await cleanup.sweep_page()
        assert not path.exists()
    asyncio.run(run())


@pytest.mark.parametrize("cut", ["before_proof", "after_commit"])
def test_process_exit_recovers_commit_boundary(monkeypatch, tmp_path, cut):
    async def run():
        config, provider, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        router = HistoricalSourceRouter(config, http=http)
        value = await router._load_object(provider, ref)
        path = Path(router._cache._lookup(ref.object_key)["path"])
        payload = {"receipt": value.receipt(), "rows": [bar.to_storage_dict() for bar in value.bars]}
        script = '''
import json, os, sys
from app.data_engine.storage import klines_repo as k
payload = json.load(sys.stdin)
k.init_klines_storage()
if sys.argv[1] == 'before_proof':
    original = k._connect
    def connect():
        connection = original()
        def trace(sql):
            if 'INSERT OR REPLACE INTO history_archive_import_commits' in sql:
                os._exit(73)
        connection.set_trace_callback(trace)
        return connection
    k._connect = connect
r = payload['receipt']
k.import_history_archive(r['symbol'], r['interval'], payload['rows'], r,
                         exchange=r['exchange'], market_type=r['market_type'])
os._exit(74)
'''
        env = dict(os.environ, KLINES_DB_PATH=str(klines_repo.KLINES_DB_PATH),
                   CANDLE_DATA_DIR=str(tmp_path / "child-data"))
        child = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", script, cut],
                                        input=json.dumps(payload), text=True, env=env,
                                        capture_output=True, timeout=45)
        assert child.returncode == (73 if cut == "before_proof" else 74), child.stderr
        # Fresh objects: no in-memory ack, worker, or cache lease survives.
        restarted = HistoricalArchiveCache(config.history_archive_cache_dir, max_bytes=10**7)
        cleanup = ArchiveImportCleanup(config, restarted, storage.get_history_archive_import_proofs)
        await cleanup.sweep_page()
        assert path.exists() == (cut == "before_proof")
        rows = klines_repo.query_klines(ref.symbol, ref.interval,
                                       exchange=ref.exchange, market_type=ref.market_type)
        assert len(rows) == (0 if cut == "before_proof" else 31)
        with klines_repo._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM history_archive_import_commits").fetchone()[0] == int(cut == "after_commit")
    asyncio.run(run())


def test_delete_failure_is_persistent_and_retryable(monkeypatch, tmp_path):
    async def run():
        config, provider, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        router = HistoricalSourceRouter(config, http=http)
        value = await router._load_object(provider, ref)
        import_object(value)
        path = Path(router._cache._lookup(ref.object_key)["path"])
        cleanup = ArchiveImportCleanup(config, router._cache, storage.get_history_archive_import_proofs)
        original = Path.unlink
        def locked(file, *args, **kwargs):
            if file == path:
                raise PermissionError("fixture file is in use")
            return original(file, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", locked)
            await cleanup.sweep_page()
        assert path.exists()
        pending = router._cache._lookup(ref.object_key)
        assert pending["cleanup_pending"] == 1
        assert pending["cleanup_attempts"] == 1
        assert "file is in use" in pending["cleanup_error"]
        restarted = HistoricalArchiveCache(config.history_archive_cache_dir, max_bytes=10**7)
        cleanup = ArchiveImportCleanup(config, restarted, storage.get_history_archive_import_proofs)
        await cleanup.sweep_page()  # Backoff survives a restart.
        assert path.exists()
        monkeypatch.setattr("app.data_engine.backfill.archive_cache._now_ms", lambda: pending["cleanup_retry_at_ms"] + 1)
        await cleanup.sweep_page()
        assert not path.exists()
        assert len(klines_repo.query_klines(ref.symbol, ref.interval, exchange=ref.exchange,
                                          market_type=ref.market_type)) == 31
    asyncio.run(run())


def test_policy_pin_shared_blob_and_duplicate_leases(monkeypatch, tmp_path):
    async def run():
        config, provider, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        router = HistoricalSourceRouter(config, http=http)
        value = await router._load_object(provider, ref)
        import_object(value)
        cache = router._cache
        path = Path(cache._lookup(ref.object_key)["path"])
        cleanup = ArchiveImportCleanup(config, cache, storage.get_history_archive_import_proofs)
        config.update(history_archive_cleanup_policy="bounded_cache")
        await cleanup.sweep_page()
        assert path.exists()
        config.update(history_archive_cleanup_policy="delete_after_import")
        await cache.set_pinned(ref.object_key, True)
        cache.max_bytes = 1
        await asyncio.to_thread(cache._evict)
        await cleanup.sweep_page()
        assert path.exists()
        cache.max_bytes = 10**7
        await cache.set_pinned(ref.object_key, False)

        second_cache = HistoricalArchiveCache(config.history_archive_cache_dir, max_bytes=10**7)
        async with cache.materialize(ref, provider, http):
            async with second_cache.materialize(ref, provider, http):
                assert cache.snapshot()["active_leases"] == 2
            await cleanup.sweep_page()
            assert path.exists()
            assert cache.snapshot()["active_leases"] == 1

        # Distinct object records can share the same physical bytes. An
        # unimported, pinned alias retains the blob after the first is retired.
        alias = replace(ref, provider_id="fixture-second-vendor")
        async with cache.materialize(alias, provider, http):
            pass
        await cache.set_pinned(alias.object_key, True)
        await cleanup.sweep_page()
        assert cache._lookup(ref.object_key) is None
        assert path.exists()
        assert cache._lookup(alias.object_key) is not None
    asyncio.run(run())


def test_revision_cannot_be_deleted_by_old_import_proof(monkeypatch, tmp_path):
    async def run():
        config, provider, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        cache = HistoricalArchiveCache(config.history_archive_cache_dir, max_bytes=10**7, revalidate_seconds=0)
        router = HistoricalSourceRouter(config, cache=cache, http=http)
        clock = [1000]
        monkeypatch.setattr("app.data_engine.backfill.archive_cache._now_ms", lambda: clock[0])
        value = await router._load_object(provider, ref)
        import_object(value)
        async with cache.materialize(ref, provider, http) as old:
            clock[0] += 1
            revised = ArchiveHttp(ref, close=106)
            async with cache.materialize(ref, provider, revised) as new:
                assert new.revision_changed
                assert old.path.exists()
                assert new.path != old.path
            # Replacing the index must not delete a version still being read.
            assert old.path.exists()
        assert not old.path.exists()
        cleanup = ArchiveImportCleanup(config, cache, storage.get_history_archive_import_proofs)
        await cleanup.sweep_page()
        assert new.path.exists()
    asyncio.run(run())


def test_cache_hit_does_not_extend_checksum_validation(monkeypatch, tmp_path):
    async def run():
        _, provider, ref, http = fixture_object(tmp_path)
        cache = HistoricalArchiveCache(tmp_path / "cache", max_bytes=10**7, revalidate_seconds=1)
        clock = [10000]
        monkeypatch.setattr("app.data_engine.backfill.archive_cache._now_ms", lambda: clock[0])
        for now in [10000, 10900, 11800, 12700]:
            clock[0] = now
            async with cache.materialize(ref, provider, http):
                pass
        assert http.checksums == 2
        assert http.downloads == 1
        assert cache._lookup(ref.object_key)["validated_at_ms"] == 11800
    asyncio.run(run())


def test_identical_redownload_requires_its_own_committed_import(monkeypatch, tmp_path):
    async def run():
        config, provider, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        router = HistoricalSourceRouter(config, http=http)
        first = await router._load_object(provider, ref)
        import_object(first)
        cleanup = ArchiveImportCleanup(config, router._cache, storage.get_history_archive_import_proofs)
        await cleanup.sweep_page()
        second = await router._load_object(provider, ref)
        assert second.content_sha256 == first.content_sha256
        assert second.cache_generation != first.cache_generation
        path = Path(router._cache._lookup(ref.object_key)["path"])
        assert await storage.get_history_archive_import_proofs([second.receipt()]) == []
        await cleanup.sweep_page()
        assert path.exists()
        # Even a proof fetched before the new download cannot retire it.
        stale = await storage.get_history_archive_import_proofs([first.receipt()])
        assert await router._cache.cleanup_imported(stale) == 0
        assert import_object(second)["imported"]
        await cleanup.sweep_page()
        assert not path.exists()
        assert http.downloads == 2
    asyncio.run(run())


def test_process_exit_after_unlink_recovers_index(monkeypatch, tmp_path):
    async def run():
        config, provider, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        router = HistoricalSourceRouter(config, http=http)
        value = await router._load_object(provider, ref)
        import_object(value)
        path = Path(router._cache._lookup(ref.object_key)["path"])
        script = '''
import asyncio, os, sys
from pathlib import Path
from app.data_engine.backfill.archive_cache import HistoricalArchiveCache
from app.data_engine.storage import klines_repo as k
cache = HistoricalArchiveCache(sys.argv[1], max_bytes=10**7)
original = Path.unlink
def unlink(file, *args, **kwargs):
    original(file, *args, **kwargs)
    if str(file) == sys.argv[2]:
        os._exit(75)
Path.unlink = unlink
async def run():
    proofs = k.get_history_archive_import_proofs(await cache.cleanup_candidates())
    await cache.cleanup_imported(proofs)
asyncio.run(run())
'''
        env = dict(os.environ, KLINES_DB_PATH=str(klines_repo.KLINES_DB_PATH),
                   CANDLE_DATA_DIR=str(tmp_path / "child-data"))
        child = await asyncio.to_thread(
            subprocess.run, [sys.executable, "-c", script, config.history_archive_cache_dir, str(path)],
            text=True, env=env, capture_output=True, timeout=45,
        )
        assert child.returncode == 75, child.stderr
        assert not path.exists()
        restarted = HistoricalArchiveCache(config.history_archive_cache_dir, max_bytes=10**7)
        assert restarted._lookup(ref.object_key) is not None  # SQLite rolled back.
        cleanup = ArchiveImportCleanup(config, restarted, storage.get_history_archive_import_proofs)
        await cleanup.sweep_page()
        assert restarted._lookup(ref.object_key) is None
        assert len(klines_repo.query_klines(ref.symbol, ref.interval, exchange=ref.exchange,
                                          market_type=ref.market_type)) == 31
    asyncio.run(run())


def test_legacy_cache_migration_preserves_objects_without_granting_cleanup(monkeypatch, tmp_path):
    async def run():
        config, provider, ref, http = fixture_object(tmp_path)
        storage = storage_at(monkeypatch, tmp_path)
        router = HistoricalSourceRouter(config, http=http)
        value = await router._load_object(provider, ref)
        path = Path(router._cache._lookup(ref.object_key)["path"])
        klines_repo.record_history_archive_imports([value.receipt()])
        with router._cache._connect() as connection:
            for name in ("pinned", "cleanup_pending", "cleanup_attempts", "cleanup_retry_at_ms",
                         "cleanup_error", "cache_generation"):
                connection.execute(f"ALTER TABLE archive_objects DROP COLUMN {name}")
            connection.execute("DROP TABLE archive_blob_cleanup")
        restarted = HistoricalArchiveCache(config.history_archive_cache_dir, max_bytes=10**7)
        cleanup = ArchiveImportCleanup(config, restarted, storage.get_history_archive_import_proofs)
        await cleanup.sweep_page()
        assert path.exists()
        assert restarted._lookup(ref.object_key)["cache_generation"] == ""
        router = HistoricalSourceRouter(config, cache=restarted, http=http)
        imported = await router._load_object(provider, ref)
        assert imported.cache_hit
        import_object(imported)
        await cleanup.sweep_page()
        assert not path.exists()
    asyncio.run(run())
