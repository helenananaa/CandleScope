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
