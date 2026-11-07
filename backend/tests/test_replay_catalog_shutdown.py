"""Real stalled TLS must not outlive replay's SQLite and archive owner."""
import asyncio
import threading
from dataclasses import replace
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from app.replay.official_trade_catalog import OfficialAggTradeArchive
from app.replay.runtime import start_replay_runtime
from tests.fixtures.replay.service_fakes import replay_settings


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["tls", "body", "discovery"])
async def test_shutdown_drains_real_catalog_tls_before_releasing_runtime(tmp_path, monkeypatch, phase):
    import app.replay.trade_import as trade_import
    import app.replay.remote_trade_archive as remote

    release = asyncio.Event()
    saturated = asyncio.Event()
    handlers = set()
    accepted = 0

    async def hold_tls(reader, writer):
        nonlocal accepted
        task = asyncio.current_task()
        handlers.add(task)
        try:
            assert await reader.read(8192)  # Real ClientHello or HTTP headers.
            if phase == "body":
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n<List")
                await writer.drain()
            accepted += 1
            if accepted >= (1 if phase == "discovery" else 16):
                saturated.set()
            await release.wait()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.remove(task)

    server = await asyncio.start_server(hold_tls, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    scheme = "http" if phase == "body" else "https"
    monkeypatch.setattr(trade_import, "BINANCE_PUBLIC_DATA_LISTING_ORIGIN", f"{scheme}://127.0.0.1:{port}/")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    symbols = () if phase == "discovery" else tuple(f"TEST{i}USDT" for i in range(40))
    archive = OfficialAggTradeArchive(tmp_path / "trades", symbols=symbols, defer_refresh=True)
    if symbols:
        with monkeypatch.context() as cached:
            cached.setattr(remote, "list_official_agg_trade_days", lambda **_: (date(2025, 1, 1),))
            archive.refresh_official_catalog()
        (archive.catalog_root / "discovery.json").unlink()
    original_index = (archive.catalog_root / "trade-index.json").read_bytes()
    original_identities = archive.list_verified_identities()
    worker_done = threading.Event()
    refresh = archive.refresh_official_catalog

    def observed_refresh(**kwargs):
        try:
            return refresh(**kwargs)
        finally:
            worker_done.set()

    monkeypatch.setattr(archive, "refresh_official_catalog", observed_refresh)
    settings = replace(replay_settings(tmp_path / "runtime.db"), replay_history_archive_dir=tmp_path / "history")
    runtime = await start_replay_runtime(settings, raw_trade_archive=archive)
    service = runtime.service
    lease = runtime.archive_lease
    original_release = lease.release
    release_observations = []

    def observed_release():
        release_observations.append(worker_done.is_set())
        original_release()

    monkeypatch.setattr(lease, "release", observed_release)
    try:
        await asyncio.wait_for(saturated.wait(), 5)
        await asyncio.wait_for(runtime.shutdown(), 3)
        assert worker_done.is_set(), "cancelled awaiter released the runtime with physical catalog TLS still active"
        assert release_observations == [True]
        assert not any(t.name.startswith("replay-catalog") for t in threading.enumerate())
        assert service.store.closed
        assert runtime.catalog_refresh_task is None and runtime.archive_lease is None
        assert accepted == (1 if phase == "discovery" else 16), "cancellation must not admit queued markets"
        assert not (archive.catalog_root / "discovery.json").exists()
        assert (archive.catalog_root / "trade-index.json").read_bytes() == original_index
        assert archive.list_verified_identities() == original_identities
    finally:
        # Release the deliberately stalled peer even on the old-code failure;
        # the counterexample must not strand test/executor threads itself.
        release.set()
        if handlers:
            await asyncio.gather(*tuple(handlers), return_exceptions=True)
        for _ in range(500):
            if worker_done.is_set():
                break
            await asyncio.sleep(0.01)
        await runtime.shutdown()
        server.close()
        await server.wait_closed()


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["prune_metadata_cache", "_publish"])
async def test_repeated_shutdown_cancellation_owns_physical_metadata_work(tmp_path, monkeypatch, phase):
    import app.replay.remote_trade_archive as remote

    monkeypatch.setattr(remote, "list_official_agg_trade_days", lambda **_: (date(2025, 1, 1),))
    archive = OfficialAggTradeArchive(tmp_path / "trades", symbols=("BTCUSDT",), defer_refresh=True)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    operation = getattr(archive, phase)

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        try:
            return operation(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(archive, phase, blocked)
    settings = replace(replay_settings(tmp_path / "runtime.db"), replay_history_archive_dir=tmp_path / "history")
    runtime = await start_replay_runtime(settings, raw_trade_archive=archive)
    service = runtime.service
    shutdown = None
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        shutdown = asyncio.create_task(runtime.shutdown())
        await asyncio.sleep(0.01)
        shutdown.cancel()
        await asyncio.sleep(0.01)
        shutdown.cancel()
        await asyncio.sleep(0.01)
        assert not shutdown.done()
        assert not service.store.closed
        assert runtime.archive_lease is not None
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(shutdown, 3)
        assert finished.is_set()
        assert service.store.closed
        assert runtime.service is None and runtime.archive_lease is None
    finally:
        release.set()
        if shutdown is not None:
            await asyncio.gather(shutdown, return_exceptions=True)
        await runtime.shutdown()


@pytest.mark.anyio
async def test_async_transport_keeps_full_paginated_symbol_and_day_catalog(tmp_path, monkeypatch):
    import app.replay.trade_import as trade_import

    prefix = "data/futures/um/daily/aggTrades/"
    symbols = tuple(f"DELISTED{i}USDT" for i in range(40))
    requests = []
    handlers = set()

    async def listing(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            target = head.split(b" ", 2)[1].decode()
            query = parse_qs(urlsplit(target).query)
            requests.append(query)
            selected = query["prefix"][0]
            marker = query.get("marker")
            if selected == prefix:
                group = symbols[20:] if marker else symbols[:20]
                body = "".join(f"<CommonPrefixes><Prefix>{prefix}{symbol}/</Prefix></CommonPrefixes>" for symbol in group)
                truncated = "false" if marker else "true"
            else:
                symbol = selected[len(prefix):-1]
                assert symbol in symbols
                suffix = ".zip.CHECKSUM" if marker else ".zip"
                body = f"<Contents><Key>{selected}{symbol}-aggTrades-2025-01-01{suffix}</Key></Contents>"
                truncated = "false" if marker else "true"
            encoded = f"<ListBucketResult>{body}<IsTruncated>{truncated}</IsTruncated><NextMarker>page2</NextMarker></ListBucketResult>".encode()
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Length: {len(encoded)}\r\nConnection: close\r\n\r\n".encode() + encoded)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.remove(task)

    server = await asyncio.start_server(listing, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(trade_import, "BINANCE_PUBLIC_DATA_LISTING_ORIGIN", f"http://127.0.0.1:{port}/")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    archive = OfficialAggTradeArchive(tmp_path / "trades", defer_refresh=True)
    try:
        await asyncio.wait_for(archive.refresh_official_catalog_async(), 5)
        assert {item["symbol"] for item in archive.list_verified_identities()} == set(symbols)
        assert archive.catalog_completed == 40 and archive.catalog_failed == 0
        assert len(requests) == 82  # Two universe pages, two daily pages for every symbol.
        assert all(query["delimiter"] == ["/"] for query in requests)
        assert not archive.needs_catalog_refresh()
        assert not any(t.name.startswith("replay-catalog") for t in threading.enumerate())
    finally:
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.gather(*tuple(handlers), return_exceptions=True)
