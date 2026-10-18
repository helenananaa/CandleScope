from __future__ import annotations

import pytest

from app.data_engine.history import (
    BoundaryReason,
    BoundarySide,
    BoundaryState,
    HistoryAvailability,
    HistoryAvailabilityService,
    HistoryBoundaryRepository,
    HistorySeriesKey,
    TimeBound,
)


def _key(*, variant: str = "1m", params: dict | None = None) -> HistorySeriesKey:
    return HistorySeriesKey.from_params(
        exchange="Binance",
        market_type="future",
        symbol="btcusdt",
        channel="open_interest",
        variant=variant,
        params=params,
    )


def test_series_key_is_normalised_and_parameter_hash_is_deterministic() -> None:
    first = _key(params={"period": "5m", "limit": 10})
    second = _key(params={"limit": 10, "period": "5m"})
    assert first == second
    assert first.exchange == "binance"
    assert first.symbol == "BTCUSDT"
    assert len(first.params_hash) == 64


def test_repository_records_candidate_evidence_and_confirmation(tmp_path) -> None:
    repository = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    key = _key()
    candidate = TimeBound(
        1_000,
        BoundaryReason.SOURCE_EXHAUSTED,
        state=BoundaryState.CANDIDATE,
        revision="v1",
    )
    first = repository.upsert(key, BoundarySide.LEFT, candidate, observed_at_ms=10)
    second = repository.upsert(key, BoundarySide.LEFT, candidate, observed_at_ms=20)
    assert first.evidence_count == 1
    assert second.evidence_count == 2
    assert second.last_seen_at_ms == 20
    confirmed = repository.confirm(key, BoundarySide.LEFT, observed_at_ms=30)
    assert confirmed is not None
    assert confirmed.bound.state is BoundaryState.CONFIRMED
    assert confirmed.evidence_count == 3

    with pytest.raises(ValueError, match="candidate boundary"):
        repository.upsert(
            key,
            BoundarySide.LEFT,
            TimeBound(2_000, BoundaryReason.SOURCE_EXHAUSTED, state=BoundaryState.CANDIDATE),
        )


def test_repository_filters_revision_and_revalidation_and_separates_variants(tmp_path) -> None:
    repository = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    first_key = _key(variant="5m")
    second_key = _key(variant="1h")
    bound = TimeBound(
        1_000,
        BoundaryReason.SOURCE_EXHAUSTED,
        revision="cap-v1",
        revalidate_at_ms=5_000,
    )
    repository.upsert(first_key, "left", bound, observed_at_ms=100)
    repository.upsert(second_key, "left", TimeBound(2_000, BoundaryReason.MANUAL))
    assert repository.get(first_key, "left", now_ms=4_999, revision="cap-v1") is not None
    assert repository.get(first_key, "left", now_ms=5_000, revision="cap-v1") is None
    assert repository.get(first_key, "left", now_ms=4_000, revision="cap-v2") is None
    assert repository.get(first_key, "left", include_stale=True) is not None
    assert repository.get(second_key, "left", include_stale=True).bound.value_ms == 2_000
    assert repository.delete_stale(now_ms=5_000) == 1


def test_dynamic_rolling_bound_cannot_be_persisted(tmp_path) -> None:
    repository = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    with pytest.raises(ValueError, match="rolling-retention"):
        repository.upsert(
            _key(),
            "left",
            TimeBound(
                1_000,
                BoundaryReason.PROVIDER_RETENTION,
                dynamic=True,
            ),
        )


def test_load_availability_uses_only_confirmed_nonretryable_boundaries(tmp_path) -> None:
    repository = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    key = _key()
    repository.upsert(
        key,
        "left",
        TimeBound(2_000, BoundaryReason.SOURCE_EXHAUSTED, revision="v1"),
    )
    repository.upsert(
        key,
        "right",
        TimeBound(
            8_000,
            BoundaryReason.TEMPORARY_UNAVAILABLE,
            retryable=True,
            revision="v1",
        ),
    )
    resolved = repository.load_availability(
        key,
        HistoryAvailability(
            upstream_start=TimeBound(1_000, BoundaryReason.UPSTREAM_START, revision="v1"),
            rolling_retention_ms=30_000,
            revision="v1",
        ),
        now_ms=5_000,
    )
    assert resolved.upstream_start.value_ms == 2_000
    assert resolved.upstream_end is None
    assert resolved.rolling_retention_ms == 30_000


def test_service_requires_repeated_evidence_before_promotion(tmp_path) -> None:
    service = HistoryAvailabilityService(
        boundaries=HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    )
    key = _key()
    first = service.record_boundary(
        key,
        "left",
        value_ms=1_000,
        reason=BoundaryReason.SOURCE_EXHAUSTED,
        promote_after=2,
    )
    second = service.record_boundary(
        key,
        "left",
        value_ms=1_000,
        reason=BoundaryReason.SOURCE_EXHAUSTED,
        promote_after=2,
    )
    assert first.bound.state is BoundaryState.CANDIDATE
    assert second.bound.state is BoundaryState.CONFIRMED


@pytest.fixture
def sqlite_opens(monkeypatch) -> list[object]:
    """Record every SQLite connection the boundary repository opens."""
    import app.data_engine.history.repository as repository_module

    opened: list[object] = []
    original = repository_module.open_sqlite

    def _open_sqlite(*args, **kwargs):
        opened.append(args[0] if args else kwargs.get("db_path"))
        return original(*args, **kwargs)

    monkeypatch.setattr(repository_module, "open_sqlite", _open_sqlite)
    return opened


def test_reads_are_served_without_opening_sqlite(tmp_path, sqlite_opens) -> None:
    repository = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    key = _key()
    repository.upsert(
        key,
        "left",
        TimeBound(
            2_000,
            BoundaryReason.SOURCE_EXHAUSTED,
            revision="v1",
            revalidate_at_ms=9_000,
        ),
    )
    sqlite_opens.clear()

    base = HistoryAvailability(revision="v1")
    for _ in range(3):
        resolved = repository.load_availability(key, base, now_ms=5_000)
        assert resolved.upstream_start.value_ms == 2_000
    # Revision and revalidation still filter cached rows on every read.
    assert repository.get(key, "left", now_ms=9_000, revision="v1") is None
    assert repository.get(key, "left", now_ms=5_000, revision="v2") is None
    assert repository.get(_key(variant="5m"), "left") is None
    assert [record.side for record in repository.list_for_series(key)] == [
        BoundarySide.LEFT
    ]
    assert sqlite_opens == []


def test_upsert_refreshes_cached_boundaries(tmp_path, sqlite_opens) -> None:
    repository = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    key = _key()
    base = HistoryAvailability(revision="v1")
    assert repository.load_availability(key, base).upstream_start is None

    repository.upsert(
        key,
        "left",
        TimeBound(
            1_000,
            BoundaryReason.SOURCE_EXHAUSTED,
            state=BoundaryState.CANDIDATE,
            revision="v1",
        ),
        observed_at_ms=10,
    )
    candidate = repository.get(key, "left")
    assert candidate is not None
    assert candidate.bound.state is BoundaryState.CANDIDATE
    # Candidates are cached but never clamp availability.
    assert repository.load_availability(key, base).upstream_start is None

    repository.confirm(key, "left", observed_at_ms=20)
    assert repository.load_availability(key, base).upstream_start.value_ms == 1_000

    repository.upsert(
        key,
        "left",
        TimeBound(3_000, BoundaryReason.SOURCE_EXHAUSTED, revision="v1"),
        observed_at_ms=30,
    )
    record = repository.get(key, "left")
    assert record.bound.value_ms == 3_000
    assert record.evidence_count == 1
    assert record.first_seen_at_ms == 30
    assert repository.load_availability(key, base).upstream_start.value_ms == 3_000

    # A rejected candidate rolls back without touching the cached row.
    opens_before = len(sqlite_opens)
    with pytest.raises(ValueError, match="candidate boundary"):
        repository.upsert(
            key,
            "left",
            TimeBound(
                4_000,
                BoundaryReason.SOURCE_EXHAUSTED,
                state=BoundaryState.CANDIDATE,
                revision="v1",
            ),
        )
    assert repository.get(key, "left").bound.value_ms == 3_000
    assert len(sqlite_opens) == opens_before + 1

    # The cache matches what a fresh process would read from disk.
    reopened = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    assert reopened.get(key, "left") == repository.get(key, "left")


def test_repositories_on_the_same_file_share_cached_rows(
    tmp_path,
    sqlite_opens,
) -> None:
    writer = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    reader = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    other_file = HistoryBoundaryRepository(tmp_path / "other.sqlite3")
    key = _key()

    writer.upsert(key, "right", TimeBound(8_000, BoundaryReason.UPSTREAM_END))
    sqlite_opens.clear()

    assert reader.get(key, "right").bound.value_ms == 8_000
    assert other_file.get(key, "right") is None
    assert sqlite_opens == []

    assert reader.delete(key, "right") == 1
    assert writer.get(key, "right") is None


def test_delete_paths_refresh_cached_boundaries(tmp_path) -> None:
    repository = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    first = _key(variant="5m")
    second = _key(variant="1h")
    repository.upsert(
        first,
        "left",
        TimeBound(1_000, BoundaryReason.SOURCE_EXHAUSTED, revalidate_at_ms=5_000),
    )
    repository.upsert(first, "right", TimeBound(9_000, BoundaryReason.UPSTREAM_END))
    repository.upsert(second, "left", TimeBound(2_000, BoundaryReason.MANUAL))

    assert repository.delete_stale(now_ms=5_000) == 1
    assert repository.get(first, "left", include_stale=True) is None
    assert repository.get(first, "right") is not None

    assert repository.delete(first) == 1
    assert repository.list_for_series(first, include_stale=True) == ()
    assert repository.get(second, "left").bound.value_ms == 2_000


def test_failed_cache_refresh_reloads_from_sqlite(tmp_path, monkeypatch) -> None:
    repository = HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    key = _key()

    def _fail_refresh(*args, **kwargs):
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(repository._cache, "replace_series", _fail_refresh)
    with pytest.raises(RuntimeError, match="refresh failed"):
        repository.upsert(key, "left", TimeBound(1_000, BoundaryReason.MANUAL))
    monkeypatch.undo()

    # The write committed, so the next read must reload it rather than
    # answer from the pre-write cache.
    assert repository.get(key, "left").bound.value_ms == 1_000


def test_backfill_planning_reads_learned_boundaries_from_memory(
    tmp_path,
    sqlite_opens,
) -> None:
    from app.data_engine.data_manager.backfill_coordinator import RepairRequest
    from app.data_engine.data_manager.backfill_history import (
        BackfillHistoryPlanner,
    )

    service = HistoryAvailabilityService(
        boundaries=HistoryBoundaryRepository(tmp_path / "history.sqlite3")
    )
    planner = BackfillHistoryPlanner(
        service,
        policy_resolver=lambda request: service.resolve_availability(
            planner.series_key(request),
            HistoryAvailability(calendar_id="crypto.24x7.utc", revision="v1"),
        ),
    )
    request = RepairRequest(
        symbol="BTCUSDT",
        interval="1m",
        start_ms=0,
        end_ms=600_000,
        exchange="binance",
        market_type="spot",
    )
    sqlite_opens.clear()

    first, _context = planner.plan(request)
    assert first.fetch_ranges[0].start_ms == 0
    assert sqlite_opens == []

    service.record_boundary(
        planner.series_key(request),
        "left",
        value_ms=300_000,
        reason=BoundaryReason.SOURCE_EXHAUSTED,
        state=BoundaryState.CONFIRMED,
        revision="v1",
    )
    sqlite_opens.clear()

    second, _context = planner.plan(request)
    assert second.fetch_ranges[0].start_ms == 300_000
    assert sqlite_opens == []


def test_symlinked_database_paths_share_boundary_writes_and_deletes(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    first = HistoryBoundaryRepository(real / "history.sqlite3")
    second = HistoryBoundaryRepository(alias / "history.sqlite3")
    key = _key()
    written = first.upsert(
        key, "left", TimeBound(1_000, BoundaryReason.SOURCE_EXHAUSTED),
    )
    assert second.get(key, "left", include_stale=True) == written
    assert second.delete(key, "left") == 1
    assert first.get(key, "left", include_stale=True) is None
