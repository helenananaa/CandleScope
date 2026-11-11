from __future__ import annotations

import pytest

from app.data_engine.storage import klines_repo


def payload(close=2, event_type="bar.closed"):
    return {"event_type": event_type, "exchange": "binance", "market_type": "spot",
            "symbol": "BTCUSDT", "interval": "1m", "timestamp_ms": 120_000,
            "bar": {"time": 60, "open": 1, "high": 4, "low": 1, "close": close,
                    "volume": 10, "is_closed": True, "source": "data_manager_exchange_closed"},
            "storage_row": {"open_time": 60_000, "close_time": 119_999, "open": 1,
                "high": 4, "low": 1, "close": close, "volume": 10,
                "quote_volume": None, "trades": None, "taker_buy_base": None, "taker_buy_quote": None}}


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter().bar_delivery


def test_canonical_write_and_publication_record_rollback_together(journal, monkeypatch):
    journal.enqueue("event-a", payload())
    original = journal._write
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("after row write, before transaction commit")
    monkeypatch.setattr(journal, "_write", interrupted)
    with pytest.raises(OSError):
        journal.commit("event-a")
    assert klines_repo.query_klines("BTCUSDT", "1m") == []
    assert journal.pending()[0]["phase"] == "pending"
    recovered = klines_repo.KlinesRepoAdapter().bar_delivery
    result = recovered.commit("event-a")
    assert result["phase"] == "committed"
    assert klines_repo.query_klines("BTCUSDT", "1m")[0]["close"] == 2
    assert recovered.pending()[0]["phase"] == "committed"


def test_post_commit_restart_reuses_event_identity_and_does_not_rewrite(journal):
    journal.enqueue("event-a", payload())
    first = journal.commit("event-a")
    journal.enqueue("event-a", payload())
    recovered = klines_repo.KlinesRepoAdapter().bar_delivery
    second = recovered.commit("event-a")
    assert second["sequence"] == first["sequence"]
    assert len(recovered.pending()) == 1
    recovered.acknowledge("event-a")
    assert not recovered.pending()
    assert recovered.commit("event-a")["phase"] == "published"


def test_quality_rejection_is_not_a_storage_failure(journal):
    row = payload()["storage_row"]
    klines_repo.upsert_klines("BTCUSDT", "1m", [{**row, "close": 4}], source="repair_binance_rest_verified")
    journal.enqueue("event-a", payload())
    assert journal.commit("event-a")["phase"] == "rejected"
    assert not journal.pending()
    assert klines_repo.query_klines("BTCUSDT", "1m")[0]["close"] == 4


def test_known_predecessor_cannot_authorize_a_stale_compact_history_prefix(journal):
    journal.enqueue('source-close', payload())
    first = journal.commit('source-close')
    journal.acknowledge('source-close')
    journal.enqueue('source-amend', payload(3, 'bar.amended'))
    derived = payload()
    derived.update(interval='2m', derived=True,
                   acquisition_revision=first['committed_revision'],
                   history_prefix_revisions=[['1m', first['canonical_revision']]])
    journal.enqueue('stale-prefix-close', derived)
    # This native predecessor is durable and earlier in journal order, but the
    # old prefix did not include its amended value. The normal predecessor
    # exception must not grant this old summary a new source revision.
    journal.commit('source-amend')
    result = klines_repo.KlinesRepoAdapter().bar_delivery.commit('stale-prefix-close')
    assert result['phase'] == 'rejected' and result['recovery_required'] == 1
    assert klines_repo.query_klines('BTCUSDT', '2m') == []


def test_current_compact_history_prefix_commits_under_same_source_transaction(journal):
    journal.enqueue('source-close', payload())
    first = journal.commit('source-close')
    derived = payload()
    derived.update(interval='2m', derived=True,
                   acquisition_revision=first['committed_revision'],
                   history_prefix_revisions=[['1m', first['canonical_revision']]])
    journal.enqueue('current-prefix-close', derived)
    assert journal.commit('current-prefix-close')['phase'] == 'committed'


@pytest.mark.parametrize("interference", ["disjoint", "overlap", "missing_receipt"])
def test_derived_close_requires_complete_disjoint_footprints(journal, interference):
    old_source = payload()["storage_row"]
    old_target = {**old_source, "open_time": 0}
    klines_repo.upsert_klines("BTCUSDT", "1m", [old_source], source="backfill")
    klines_repo.upsert_klines("BTCUSDT", "2m", [old_target], source="backfill_aggregated")

    derived = payload()
    derived.update(interval="2m", derived=True)
    derived["storage_row"].update(open_time=240_000, close_time=359_999)
    derived["bar"]["time"] = 240
    journal.enqueue("derived-close", derived)
    sibling = {**derived, "interval": "4m", "storage_row": {**derived["storage_row"], "close_time": 479_999}}
    journal.enqueue("sibling-close", sibling)

    if interference == "overlap":
        # An overlapping source write remains relevant even when the last
        # change to that same source came from an older historical bucket.
        inside = {**old_source, "open_time": 240_000, "close_time": 299_999}
        klines_repo.upsert_klines("BTCUSDT", "1m", [inside], source="backfill")
    klines_repo.upsert_klines("BTCUSDT", "1m", [{**old_source, "volume": 11}], source="backfill")
    klines_repo.upsert_klines("BTCUSDT", "2m", [{**old_target, "volume": 11}], source="backfill_aggregated")
    if interference == "missing_receipt":
        with klines_repo._connect() as conn:
            conn.execute("DELETE FROM kline_block_changes WHERE revision=(SELECT MAX(revision) FROM kline_block_changes)")

    reopened = klines_repo.KlinesRepoAdapter().bar_delivery
    result = reopened.commit("derived-close")
    if interference != "disjoint":
        assert result["phase"] == "rejected" and result["recovery_required"] == 1
        assert result["canonical_row"] is None
        return
    assert result["phase"] == "committed" and result["canonical_row"]["volume"] == 10
    reopened.acknowledge("derived-close")
    retry = reopened.commit("derived-close")
    assert retry["phase"] == "published"
    assert retry["committed_revision"] == result["committed_revision"]
    assert reopened.commit("sibling-close")["phase"] == "committed"


@pytest.mark.parametrize("delete_open", [0, 240_000])
def test_prior_sibling_proof_survives_only_a_disjoint_later_deletion(journal, delete_open):
    source = payload()["storage_row"]
    klines_repo.upsert_klines("BTCUSDT", "1m", [source], source="backfill")
    klines_repo.upsert_klines("BTCUSDT", "2m", [{**source, "open_time": 0}], source="backfill_aggregated")
    with klines_repo._connect() as conn:
        acquired = klines_repo.current_revision(conn)
    sibling = payload()
    sibling.update(interval="2m", derived=True)
    sibling["storage_row"].update(open_time=240_000, close_time=359_999)
    sibling["bar"]["time"] = 240
    journal.enqueue("earlier-sibling", sibling)
    first = journal.commit("earlier-sibling")
    assert first["phase"] == "committed" and first["written_revision"] > acquired
    journal.acknowledge("earlier-sibling")
    journal.enqueue("same-row", sibling)
    replay = journal.commit("same-row")
    assert replay["phase"] == "committed" and replay["written_revision"] == 0
    journal.acknowledge("same-row")

    klines_repo.KlinesRepoAdapter().delete_bars(
        "BTCUSDT", "2m", start_ms=delete_open, end_ms=delete_open + 119_999,
    )
    later = {**sibling, "interval": "4m", "acquisition_revision": acquired,
             "storage_row": {**sibling["storage_row"], "close_time": 479_999}}
    journal.enqueue("later-close", later)
    result = journal.commit("later-close")
    assert result["phase"] == ("rejected" if delete_open else "committed")


@pytest.mark.parametrize("mutation", ["repair", "delete"])
@pytest.mark.parametrize("other_open", [0, 120_000])
def test_disjoint_history_change_does_not_reject_a_fresh_native_close(journal, mutation, other_open):
    journal.enqueue("forming-before-repair", payload())
    if mutation == "repair":
        other = {**payload(4)["storage_row"], "open_time": other_open, "close_time": other_open + 59_999}
        klines_repo.upsert_klines("BTCUSDT", "1m", [other], source="repair_binance_rest_verified")
    else:
        klines_repo.KlinesRepoAdapter().delete_bars("BTCUSDT", "1m", start_ms=other_open, end_ms=other_open + 59_999)
    # Reopening exercises the durable conservative range, not transient state.
    result = klines_repo.KlinesRepoAdapter().bar_delivery.commit("forming-before-repair")
    assert result["phase"] == "committed"
    assert result["canonical_row"]["close"] == 2


@pytest.mark.parametrize("mutation", ["repair", "delete"])
def test_later_disjoint_change_cannot_hide_an_overlapping_mutation(journal, mutation):
    journal.enqueue("old", payload())
    if mutation == "repair":
        klines_repo.upsert_klines("BTCUSDT", "1m", [payload(4)["storage_row"]], source="repair_binance_rest_verified")
    else:
        klines_repo.KlinesRepoAdapter().delete_bars("BTCUSDT", "1m", start_ms=60_000, end_ms=119_999)
    other = {**payload(4)["storage_row"], "open_time": 120_000, "close_time": 179_999}
    klines_repo.upsert_klines("BTCUSDT", "1m", [other], source="repair_binance_rest_verified")
    result = klines_repo.KlinesRepoAdapter().bar_delivery.commit("old")
    assert result["phase"] == "rejected" and result["recovery_required"] == 1


def test_pending_journal_has_finite_admission(journal):
    journal.max_pending = 2
    journal.enqueue("event-a", payload())
    journal.enqueue("event-b", payload(3))
    with pytest.raises(RuntimeError, match="capacity"):
        journal.enqueue("event-c", payload(4))
    assert len(journal.pending()) == 2


def test_recovery_pagination_survives_deleted_cursor_and_preserves_range(journal):
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        journal.watch("previous-owner", {"symbol": symbol, "interval": "1m"}, 60_000)
    journal.watch("current-owner", {"symbol": "ACTIVEUSDT", "interval": "1m"}, 0)
    first = journal.recovery_watches("current-owner", 180_000, limit=1)[0]
    assert first["series"]["symbol"] == "BTCUSDT"
    cursor = (first["from_ms"], first["watch_id"])
    journal.finish_recovery(first["watch_id"])

    remaining = journal.recovery_watches("current-owner", 240_000, after=cursor)
    assert [watch["series"]["symbol"] for watch in remaining] == ["ETHUSDT", "SOLUSDT"]
    assert all(watch["through_ms"] == 180_000 for watch in remaining)
    assert journal.recovery_pending_count("current-owner") == 2
