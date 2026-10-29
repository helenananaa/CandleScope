from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.klines as api
from app.data_engine.data_manager import DataManager
from app.data_engine.interval_policy import compute_bucket_start_ms, parse_interval_ms
from app.data_engine.interval_resolution import IntervalPurpose
from app.data_engine.storage import klines_repo


@pytest.mark.parametrize("interval", ["45m", "90m", "2d", "3d", "4d", "5d", "10007m"])
@pytest.mark.parametrize("transport", ["single", "batch"])
def test_materialized_history_reads_only_target_sqlite(
    monkeypatch, tmp_path, interval, transport,
):
    _exercise_probe(monkeypatch, tmp_path, interval, transport, "complete")


@pytest.mark.parametrize("state", ["empty", "gap", "untrusted"])
@pytest.mark.parametrize("transport", ["single", "batch"])
def test_materialized_probe_miss_never_derives_repairs_waits_or_prewarms(
    monkeypatch, tmp_path, state, transport,
):
    _exercise_probe(monkeypatch, tmp_path, "10007m", transport, state)


def _exercise_probe(monkeypatch, tmp_path, interval, transport, state):
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(api.time, "time", lambda: now_ms / 1000)
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "klines.sqlite")
    klines_repo.init_klines_storage()
    width = parse_interval_ms(interval)
    assert width is not None
    end = compute_bucket_start_ms(now_ms, width, interval=interval) - width
    count = 500 if interval == "10007m" else 8
    rows = [dict(
        open_time=end - index * width,
        close_time=end - index * width + width - 1,
        open=1, high=2, low=1, close=2, volume=3,
        quote_volume=6, trades=3, taker_buy_base=1, taker_buy_quote=2,
    ) for index in range(count)]
    if state == "empty":
        rows = []
    elif state == "gap":
        rows.pop(count // 2)
    klines_repo.upsert_klines(
        "BTCUSDT", interval, rows,
        source="unknown" if state == "untrusted" else "backfill_aggregated",
        exchange="binance", market_type="futures",
    )
    reads = []

    target_interval = interval

    class Storage(klines_repo.KlinesRepoAdapter):
        def query_bar_components(self, symbol, interval, **kwargs):
            assert interval == target_interval, "probe expanded base history"
            reads.append(interval)
            return super().query_bar_components(symbol, interval, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("materialized-only probe admitted additional work")

    dm = DataManager()
    dm.set_storage(Storage())
    monkeypatch.setattr(dm.query_engine.custom_intervals, "query_from_base", forbidden)
    monkeypatch.setattr(dm, "_submit_missing_ranges", forbidden)
    monkeypatch.setattr(api, "_submit_verification_repairs", forbidden)
    monkeypatch.setattr(api, "_schedule_related_interval_warmup", forbidden)
    monkeypatch.setattr(api, "_poll_backfill_storage", forbidden)
    app = FastAPI()
    app.state.data_manager = dm
    app.include_router(api.router, prefix="/api/v1")
    # Even callers requesting background admission and a wait must get a probe.
    params = dict(symbol="BTCUSDT", interval=interval, count_back=count,
                  exchange="binance", market_type="futures",
                  materialized_only=True, intent="active_hydration", max_wait_ms=8000)
    with TestClient(app) as client:
        if transport == "single":
            response = client.get("/api/v1/klines/history/materialized", params=params)
            assert response.status_code == 200, response.text
            payload = response.json()
        else:
            response = client.post("/api/v1/klines/history/batch", json={
                "requests": [{"request_id": "probe", **params}],
            })
            assert response.status_code == 200, response.text
            item = response.json()["results"][0]
            assert item["ok"] is True, item
            payload = item["payload"]
    assert reads and set(reads) == {interval}
    assert payload["materialized_only"] is True
    assert payload["cache"]["target_materialized_only"] is True
    assert payload["backfill_triggered"] is False
    assert payload["count"] == len(rows)
    if state == "complete":
        assert reads == [interval]
        assert payload["complete"] is True
        assert payload["verified_contiguous"] is True
        assert payload["all_rows_final"] is True
        assert payload["missing_ranges"] == []
        assert payload["data"][0]["volume"] == 3
        assert payload["data"][0]["trades"] == 3
    else:
        assert payload["complete"] is False
        assert payload["history_state"] != "exhausted"


def test_probe_does_not_fall_back_to_older_manager_query():
    class OlderManager:
        def query(self, *args, **kwargs):
            raise AssertionError("an older manager must not expand the probe")

    app = FastAPI()
    app.state.data_manager = OlderManager()
    app.include_router(api.router, prefix="/api/v1")
    with TestClient(app) as client:
        response = client.get("/api/v1/klines/history", params={
            "interval": "10007m", "count_back": 500, "materialized_only": True,
        })
    assert response.status_code == 503


@pytest.mark.parametrize("interval,base,factor", [
    ("45m", "15m", 3), ("90m", "30m", 3), ("2d", "1d", 2),
    ("3d", "3d", 1), ("4d", "1d", 4), ("5d", "1d", 5),
])
def test_regular_history_keeps_coarse_source_math_and_materialization(
    monkeypatch, tmp_path, interval, base, factor,
):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "regular.sqlite")
    klines_repo.init_klines_storage()
    dm = DataManager()
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    route = dm.interval_resolver.resolve(
        exchange="binance", market_type="futures", interval=interval,
        purpose=IntervalPurpose.HISTORY,
    )
    assert route.source_interval == base
    source_width = parse_interval_ms(base)
    target_width = parse_interval_ms(interval)
    assert source_width is not None and target_width is not None
    count = 8
    klines_repo.upsert_klines("BTCUSDT", base, [dict(
        open_time=index * source_width, close_time=(index + 1) * source_width - 1,
        open=1, high=2, low=1, close=2, volume=3,
        quote_volume=6, trades=3, taker_buy_base=1, taker_buy_quote=2,
    ) for index in range(count * factor)], source="backfill",
        exchange="binance", market_type="futures")
    kwargs = dict(start_ms=0, end_ms=(count - 1) * target_width, limit=count,
                  exchange="binance", market_type="futures", auto_backfill=False)
    # D126 may intentionally defer a read inside the adoption polling window.
    # This fixture tests coarse-source math on the already committed revision.
    dm.cache.revision_consumer.sync(force=True)
    result = dm.query("BTCUSDT", interval, **kwargs)
    assert result.complete and len(result.bars) == count
    assert all(bar.trusted_final for bar in result.bars)
    assert [bar.volume for bar in result.bars] == [3 * factor] * count
    assert [bar.trades for bar in result.bars] == [3 * factor] * count
    if factor > 1:
        assert result.metadata["derived_from"] == base
        assert result.metadata["target_materialized_written"] == count
        # A fresh manager proves reuse from SQLite rather than the old cache.
        fresh = DataManager()
        fresh.set_storage(klines_repo.KlinesRepoAdapter())
        reused = fresh.query("BTCUSDT", interval, **kwargs)
        assert reused.metadata["target_materialized"] is True
        assert reused.metadata["base_storage_reads"] == 0
        assert reused.bars == result.bars
