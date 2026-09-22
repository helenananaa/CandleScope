import pytest

from app.replay.catalog import ReplaySeriesIdentity
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.history_archive import ReplayHistoryArchiveWriter, ReplayHistoryImportBatch, ReplayHistoryRepository
from app.replay.progressive_history import ProgressiveBarHistory
from tests.test_data_preparation import START, bars


def fixture(tmp_path):
    root = tmp_path / "archive"
    writer = ReplayHistoryArchiveWriter(root)
    identity = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")

    def publish(first, count):
        rows = [{**bars()[0], "open_time": START + index * 60_000,
                 "close_time": START + (index + 1) * 60_000 - 1} for index in range(first, first + count)]
        return writer.import_batches(identity, "1m", [ReplayHistoryImportBatch(rows=rows,
            source_provider="progressive_fixture", source_object_key=f"{first}:{count}", source_period="test")]).catalog_epoch

    archive = ReplayHistoryRepository(root)
    store = ProgressiveBarHistory(root / "progressive-index.sqlite3", archive)
    feed = store.create("progressive-request", identity, START, START + 6 * 60_000)
    return store, feed["id"], publish, archive, identity


def test_progressive_history_waits_for_contiguous_immutable_extension_and_survives_restart(tmp_path):
    store, feed_id, publish, archive, identity = fixture(tmp_path)
    first = publish(0, 2)
    store.publish(feed_id, first, START, START + 2 * 60_000)
    prefix = store.read(feed_id, START, START + 2 * 60_000)
    assert len(prefix) == 2
    with pytest.raises(ReplayDomainError) as pending:
        store.read(feed_id, START + 2 * 60_000, START + 3 * 60_000)
    assert pending.value.code is ReplayErrorCode.DATASET_PENDING
    assert not pending.value.details
    assert store.status(feed_id)["complete"] is False
    recovered = ProgressiveBarHistory(store.path, archive)
    assert recovered.create("progressive-request", identity, START, START + 6 * 60_000)["id"] == feed_id
    second = publish(2, 4)
    result = recovered.publish(feed_id, second, START + 2 * 60_000, START + 6 * 60_000)
    assert result["complete"] is True
    assert result["revision"] == 2
    assert recovered.read(feed_id, START, START + 6 * 60_000)[:2] == prefix
    assert recovered.publish(feed_id, second, START + 2 * 60_000, START + 6 * 60_000)["revision"] == 2
    with pytest.raises(ReplayDomainError, match="cannot be replaced"):
        recovered.publish(feed_id, second, START, START + 2 * 60_000)


def test_progressive_history_rejects_holes_changed_horizon_and_unverified_extension(tmp_path):
    store, feed_id, publish, archive, identity = fixture(tmp_path)
    first = publish(0, 2)
    store.publish(feed_id, first, START, START + 2 * 60_000)
    with pytest.raises(ReplayDomainError, match="different horizon"):
        store.create("progressive-request", identity, START, START + 7 * 60_000)
    later = publish(4, 2)
    with pytest.raises(ReplayDomainError) as gap:
        store.publish(feed_id, later, START + 4 * 60_000, START + 6 * 60_000)
    assert gap.value.code is ReplayErrorCode.DATA_GAP
    with pytest.raises(ReplayDomainError) as incomplete:
        store.publish(feed_id, later, START + 2 * 60_000, START + 6 * 60_000)
    assert incomplete.value.code is ReplayErrorCode.DATASET_INCOMPLETE
    assert store.status(feed_id)["ready_end_ms"] == START + 2 * 60_000


def test_progressive_source_keeps_pending_distinct_from_end_and_reuses_cursor_after_append(tmp_path):
    from dataclasses import replace
    from app.replay.sources.bar_source import BarReplaySource
    from app.replay.sources.progressive_bar_source import ProgressiveBarReplaySource
    from tests.fixtures.replay.bar_builder_fakes import make_bar_snapshot
    store, feed_id, publish, archive, identity = fixture(tmp_path)
    first = publish(0, 2)
    store.publish(feed_id, first, START, START + 2 * 60_000)
    snapshot = replace(make_bar_snapshot(replay_start_ms=START, replay_count=2),
                       rows=store.read(feed_id, START, START + 2 * 60_000))
    source = ProgressiveBarReplaySource(snapshot, history=store, feed_id=feed_id, page_rows=2)
    original_ref = dict(source.snapshot_ref())
    seen = [source.next(), source.next()]
    cursor = source.cursor()
    assert not source.exhausted()
    assert not cursor.at_end
    assert not source.ready()
    assert source.cursor() == cursor
    fork = source.fork_at_sequence(cursor.source_sequence, last_event_time_ms=cursor.last_event_time_ms)
    assert not fork.ready()
    with pytest.raises(ReplayDomainError) as pending:
        source.next()
    assert pending.value.code is ReplayErrorCode.DATASET_PENDING
    assert source.cursor() == cursor
    second = publish(2, 4)
    store.publish(feed_id, second, START + 2 * 60_000, START + 6 * 60_000)
    assert source.ready() and fork.ready()
    while not source.exhausted():
        seen.append(source.next())
    complete = replace(make_bar_snapshot(replay_start_ms=START, replay_count=6),
                       rows=store.read(feed_id, START, START + 6 * 60_000))
    reference = BarReplaySource(complete)
    assert tuple(seen) == reference.advance_until(START + 6 * 60_000)
    assert source.cursor() == reference.cursor()
    assert dict(source.snapshot_ref()) == original_ref
    assert fork.cursor() == cursor  # immutable market segments, independent consumer positions


def test_archive_gc_keeps_every_published_progressive_revision(tmp_path):
    store, feed_id, publish, archive, identity = fixture(tmp_path)
    first = publish(0, 2)
    store.publish(feed_id, first, START, START + 120_000)
    second = publish(2, 4)
    store.publish(feed_id, second, START + 120_000, START + 360_000)
    publish(6, 2)  # neither bound progressive revision is the current catalog now
    before = store.read(feed_id, START, START + 360_000)
    report = ReplayHistoryArchiveWriter(archive.root).collect_garbage(pinned_revisions=(), dry_run=False)
    assert report["pinned_revision_count"] == 2
    assert store.read(feed_id, START, START + 360_000) == before


def test_progressive_owners_release_independently_and_survive_restart(tmp_path):
    from app.replay.progressive_history import retained_revisions
    store, feed_id, publish, archive, _ = fixture(tmp_path)
    revision = publish(0, 2)
    store.publish(feed_id, revision, START, START + 120_000)
    store.pin(feed_id, "session:original")
    store.pin(feed_id, "session:fork")
    store.release("preparation:progressive-request")
    store.release("session:original")
    recovered = ProgressiveBarHistory(store.path, archive)
    assert retained_revisions(archive.root) == (revision,)
    recovered.release("session:fork")
    assert retained_revisions(archive.root) == ()
    recovered.release("session:fork")  # repeated deletion is harmless
    assert retained_revisions(archive.root) == ()
    publish(2, 2)  # supersede the now-unreferenced catalog revision
    report = ReplayHistoryArchiveWriter(archive.root).collect_garbage(pinned_revisions=(), dry_run=False)
    assert report["pinned_revision_count"] == 0
    assert report["stale_manifest_count"] == 1


def test_legacy_progressive_index_keeps_unclassified_consumers_pinned(tmp_path):
    from app.replay.progressive_history import retained_revisions
    store, feed_id, publish, archive, _ = fixture(tmp_path)
    revision = publish(0, 2)
    store.publish(feed_id, revision, START, START + 120_000)
    with store.connect() as db:
        db.execute("DROP TABLE progressive_bar_refs")
    assert retained_revisions(archive.root) == (revision,)
    recovered = ProgressiveBarHistory(store.path, archive)
    recovered.release("preparation:progressive-request")
    assert retained_revisions(archive.root) == (revision,)


def test_reconciliation_preserves_other_databases_and_unscoped_owners(tmp_path):
    store, feed_id, _publish, _archive, _ = fixture(tmp_path)
    for owner in ("session:local:ended", "session:local:degraded", "session:local:orphan",
                  "session:other:orphan", "session:old-unscoped", "legacy:unknown"):
        store.pin(feed_id, owner)
    assert store.reconcile_sessions("local", ("ended", "degraded")) == 1
    with store.connect() as db:
        owners = {row[0] for row in db.execute("SELECT owner FROM progressive_bar_refs")}
    assert "session:local:orphan" not in owners
    assert {"session:local:ended", "session:local:degraded", "session:other:orphan",
            "session:old-unscoped", "legacy:unknown", "preparation:progressive-request"} == owners
@pytest.mark.parametrize("interval", ["2m", "3m", "5m", "1M"])
@pytest.mark.parametrize("partial", [False, True])
def test_progressive_source_bucket_projection_matches_full_archive(tmp_path, monkeypatch, interval, partial):
    if interval == "1M":
        monkeypatch.setattr("tests.test_replay_progressive_history.START", 1_709_251_200_000)  # March 1 UTC
    from app.replay.progressive_history import ProgressiveHistoryRepository
    history, feed_id, publish, archive, _identity = fixture(tmp_path)
    initial = publish(0, 2)
    history.publish(feed_id, initial, START, START + 120_000)
    full = publish(2, 4)
    history.publish(feed_id, full, START + 120_000, START + 360_000)
    reader = ProgressiveHistoryRepository(history, feed_id, initial)
    options = dict(actual_start_ms=START, actual_end_ms=START + 360_000,
        actual_replay_start_ms=START + 120_000, public_replay_start_ms=946684800000,
        limit=20, include_partial=partial, exchange="binance", market_type="spot")
    expected = archive.query_source_bucket_bars_at_revision(full, "BTCUSDT", "1m", interval, **options)
    actual = reader.query_source_bucket_bars_at_revision(initial, "BTCUSDT", "1m", interval, **options)
    assert actual == expected
    if partial:
        assert actual["bars"]
