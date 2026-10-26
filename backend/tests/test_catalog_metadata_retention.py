import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

import pytest

from app.replay.metadata_retention import (
    detach_obsolete_generations,
    remove_retired_generations,
)
from app.replay.official_trade_catalog import OfficialAggTradeArchive
from app.replay.remote_history import ReplayHistoryOriginUnavailable


def archive(tmp_path, monkeypatch):
    import app.replay.remote_trade_archive as remote

    monkeypatch.setattr(
        remote,
        "list_official_agg_trade_days",
        lambda **_: (date(2025, 1, 1), date(2025, 1, 2)),
    )
    return OfficialAggTradeArchive(
        tmp_path / "cache", symbols=("BTCUSDT", "DOGEUSDT"), refresh_seconds=0
    )


def generations(root):
    return list((root / "generations").iterdir())


def test_repeated_refresh_is_bounded_and_offline_restart_keeps_all_markets(
    tmp_path, monkeypatch
):
    item = archive(tmp_path, monkeypatch)
    from tests.fixtures.replay.trade_service_fakes import (
        INTERVAL_MS,
        TRADE_REPLAY_MINUTES,
        TRADE_REPLAY_START_MS,
        verified_trade_archive,
    )

    trades = verified_trade_archive(item.root)
    frozen = trades.freeze_dataset(
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        start_time_ms=TRADE_REPLAY_START_MS,
        end_time_ms=TRADE_REPLAY_START_MS + TRADE_REPLAY_MINUTES * INTERVAL_MS - 1,
    )
    body = item.root / "verified-user-history.parquet"
    body.write_bytes(b"untouched market body")
    for _ in range(8):
        item.refresh_official_catalog()
        assert len(item.list_verified_identities()) == 2
        item.prune_metadata_cache()
        assert len(generations(item.catalog_root)) <= 2
        assert len(generations(item.root / "_remote_metadata")) <= 2
    expected = item.list_verified_identities()
    item.prune_metadata_cache()
    monkeypatch.setattr(
        item.origin,
        "read_json",
        lambda *a, **k: (_ for _ in ()).throw(
            ReplayHistoryOriginUnavailable("offline")
        ),
    )
    assert item.list_verified_identities() == expected
    assert item.diagnostics()["remote_metadata_fallback"]
    restored = OfficialAggTradeArchive(
        item.root, symbols=item.symbols, defer_refresh=True
    )
    assert restored.list_verified_identities() == expected
    assert body.read_bytes() == b"untouched market body"
    restored.cache.validate_dataset(frozen)


def test_failed_refresh_does_not_accumulate_staging_directories(tmp_path, monkeypatch):
    import app.replay.remote_trade_archive as remote

    item = archive(tmp_path, monkeypatch)
    original = (item.catalog_root / "trade-index.json").read_bytes()

    def offline(**_):
        raise OSError("offline")

    monkeypatch.setattr(remote, "list_official_agg_trade_days", offline)
    for _ in range(5):
        item.catalog_failed = 0  # Exercise real failing writes, not the retry shortcut.
        item.refresh_official_catalog()
        assert len(generations(item.catalog_root)) <= 2
    assert (item.catalog_root / "trade-index.json").read_bytes() == original
    assert len(item.list_verified_identities()) == 2


def test_origin_reader_finishes_before_publisher_can_retire_its_generation(
    tmp_path, monkeypatch
):
    item = archive(tmp_path, monkeypatch)
    entered, release, published = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    read = item._read_bound_remote_json

    def paused(obj):
        entered.set()
        assert release.wait(5)
        return read(obj)

    monkeypatch.setattr(item, "_read_bound_remote_json", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(item.list_verified_identities)
        assert entered.wait(5)

        def refresh():
            item.refresh_official_catalog()
            published.set()

        writer = pool.submit(refresh)
        try:
            assert not published.wait(0.05)
        finally:
            release.set()
        assert len(reader.result(timeout=5)) == 2
        writer.result(timeout=5)
    assert len(generations(item.catalog_root)) <= 2


def test_warm_reader_uses_existing_snapshot_during_inflight_refresh(
    tmp_path, monkeypatch
):
    item = archive(tmp_path, monkeypatch)
    expected = item.list_verified_identities()
    entered, release = threading.Event(), threading.Event()
    read = item._load_origin_metadata

    def paused():
        entered.set()
        assert release.wait(5)
        return read()

    monkeypatch.setattr(item, "_load_origin_metadata", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        refreshing = pool.submit(item._refresh)
        assert entered.wait(5)
        try:
            assert (
                pool.submit(item.list_verified_identities).result(timeout=1) == expected
            )
        finally:
            release.set()
        refreshing.result(timeout=5)


def test_offline_cache_reader_finishes_before_retirement(tmp_path, monkeypatch):
    item = archive(tmp_path, monkeypatch)
    for _ in range(3):
        item.refresh_official_catalog()
        item.list_verified_identities()
    entered, release, retired = threading.Event(), threading.Event(), threading.Event()
    read = item._read_bound_cached_json

    def paused(*args):
        entered.set()
        assert release.wait(5)
        return read(*args)

    monkeypatch.setattr(item, "_read_bound_cached_json", paused)
    monkeypatch.setattr(
        item.origin,
        "read_json",
        lambda *a, **k: (_ for _ in ()).throw(
            ReplayHistoryOriginUnavailable("offline")
        ),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(item.list_verified_identities)
        assert entered.wait(5)

        def prune():
            item.prune_metadata_cache()
            retired.set()

        pruning = pool.submit(prune)
        try:
            assert not retired.wait(0.05)
        finally:
            release.set()
        assert len(reader.result(timeout=5)) == 2
        pruning.result(timeout=5)
    assert len(generations(item.root / "_remote_metadata")) <= 2


def test_retirement_is_narrow_and_resumes_after_interruption(tmp_path):
    root = tmp_path / "metadata"
    paths = []
    for i in range(6):
        path = root / "generations" / f"{i:032x}" / "availability.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        paths.append(path.relative_to(root).as_posix())
    external = tmp_path / "external"
    external.mkdir()
    (external / "body.parquet").write_text("keep")
    (root / "generations" / ("f" * 32)).symlink_to(external, target_is_directory=True)
    unknown = root / "generations" / "user-notes"
    unknown.mkdir()
    detach_obsolete_generations(root, [paths[0]], active=(f"{1:032x}",))
    assert (root / paths[0]).exists() and (root / paths[1]).exists()
    assert len(list((root / "_retired_generations").iterdir())) == 3
    remove_retired_generations(root)
    remove_retired_generations(root)
    assert not list((root / "_retired_generations").iterdir())
    assert unknown.is_dir() and (external / "body.parquet").read_text() == "keep"


def test_invalid_current_index_does_not_retire_previous_metadata(tmp_path, monkeypatch):
    item = archive(tmp_path, monkeypatch)
    item.refresh_official_catalog()
    path = item.catalog_root / "trade-index.json"
    payload = json.loads(path.read_text())
    payload["index_epoch"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(payload))
    before = generations(item.catalog_root)
    item.prune_metadata_cache()
    assert generations(item.catalog_root) == before


def test_missing_current_metadata_preserves_every_generation(tmp_path):
    root = tmp_path / "metadata"
    for index in range(4):
        (root / "generations" / f"{index:032x}").mkdir(parents=True)
    before = generations(root)
    detach_obsolete_generations(root, ["generations/" + "0" * 32 + "/missing.json"])
    assert generations(root) == before


@pytest.mark.anyio
async def test_background_remote_retention_retries_io_failure_and_stops_on_shutdown(
    tmp_path, monkeypatch
):
    from app.replay import runtime as runtime_module
    from app.replay.remote_trade_archive import RemoteRawAggTradeArchive
    from tests.fixtures.replay.service_fakes import replay_settings

    completed = asyncio.Event()
    real_sleep = asyncio.sleep

    class Remote(RemoteRawAggTradeArchive):
        def __init__(self):
            self.calls = 0

        def prune_metadata_cache(self):
            self.calls += 1
            if self.calls == 1:
                raise OSError("transient retirement failure")

    remote = Remote()

    async def maintenance_sleep(delay):
        if delay != 60:
            return await real_sleep(delay)
        if remote.calls >= 2:
            completed.set()
            await asyncio.Event().wait()
        await real_sleep(0)

    class Service:
        def __init__(self, **kwargs):
            self.store = kwargs["store"]

        async def start(self):
            pass

        async def shutdown(self, **_kwargs):
            await self.store.close()

    monkeypatch.setattr(runtime_module.asyncio, "sleep", maintenance_sleep)
    settings = replace(
        replay_settings(tmp_path / "runtime.db"),
        replay_history_archive_dir=tmp_path / "history",
    )
    runtime = await runtime_module.start_replay_runtime(
        settings, raw_trade_archive=remote, service_factory=Service
    )
    task = runtime.catalog_refresh_task
    try:
        await asyncio.wait_for(completed.wait(), 5)
        assert remote.calls == 2
        assert task is not None and not task.done()
    finally:
        await runtime.shutdown()
    assert task.cancelled()
    assert runtime.catalog_refresh_task is None
