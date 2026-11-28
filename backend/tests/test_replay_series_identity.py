"""Replay markets on a non-exchange kline series (ADR-DATA-002 D1b)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.api.v1.data_preparation import ReplayMarketPreparationPayload, ReplayPreparationPayload
from app.data_engine.series_identity import KlineSeriesIdentity, identity_from_mapping
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.history_archive import (
    ReplayHistoryArchiveError,
    ReplayHistoryArchiveWriter,
    ReplayHistoryImportBatch,
    ReplayHistoryRepository,
    _symbol_path_component,
)
from tests.fixtures.replay.fakes import make_bar

INTERVAL_MS = 60_000
START_MS = 1_795_617_000_000  # 2026-11-25 14:30 UTC, a regular NASDAQ session
NOW_MS = START_MS + 60 * INTERVAL_MS
STOCK = {"provider_id": "twelvedata", "venue": "xngs", "asset_class": "stock", "series_variant": "ohlcv",
         "price_adjustment": "raw", "session_variant": "regular", "volume_semantics": "shares"}
STOCK_SERIES = identity_from_mapping("twelvedata", STOCK)
APPLE = ReplaySeriesIdentity("twelvedata", "stock", "AAPL:NASDAQ", series=STOCK_SERIES)


def _batch(offsets, *, key="fixture", price=350):
    return ReplayHistoryImportBatch(
        rows=[make_bar(START_MS + offset * INTERVAL_MS, price=str(price + offset), source="twelvedata")
              for offset in offsets],
        source_provider="automatic_host_history_snapshot", source_object_key=key, source_period=key,
    )


def test_an_exchange_series_keeps_its_replay_identity_form():
    plain = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")
    explicit = ReplaySeriesIdentity("binance", "spot", "BTCUSDT", series=KlineSeriesIdentity.for_exchange("binance"))

    assert explicit.series is None
    assert plain.to_dict() == explicit.to_dict() == {"exchange": "binance", "market_type": "spot", "symbol": "BTCUSDT"}
    assert ReplaySeriesIdentity.from_dict(plain.to_dict()) == plain


def test_a_replay_market_records_its_series_without_changing_its_route():
    payload = APPLE.to_dict()

    assert payload["series_identity"] == STOCK
    restored = ReplaySeriesIdentity.from_dict(payload)
    assert restored.series == STOCK_SERIES
    # Runs keep addressing markets by route: equality, ordering and key ignore the series.
    assert restored == ReplaySeriesIdentity("twelvedata", "stock", "AAPL:NASDAQ")
    assert APPLE.key == "twelvedata:stock:AAPL:NASDAQ"
    with pytest.raises(ValueError):
        ReplaySeriesIdentity.from_dict({**payload, "unknown": 1})


def test_symbols_with_a_venue_get_distinct_archive_paths():
    assert _symbol_path_component("BTCUSDT") == "BTCUSDT"
    assert _symbol_path_component("BTC-PERP") == "BTC-PERP"
    assert _symbol_path_component("AAPL:NASDAQ") == "_AAPL-3aNASDAQ"
    # '-' always starts an escape inside the encoded form, so no two symbols meet.
    encoded = {_symbol_path_component(symbol) for symbol in ("A:B-C", "A:B:C", "A-3aB:C", "A:B_C")}
    assert len(encoded) == 4
    assert all(item.startswith("_") for item in encoded)


def test_the_archive_holds_a_venue_symbol_and_its_series(tmp_path: Path):
    root = tmp_path / "replay-history"
    writer = ReplayHistoryArchiveWriter(root, now_ms=lambda: NOW_MS)
    manifest = writer.import_batches(APPLE, "1m", [_batch(range(5))])

    assert manifest.identity.series == STOCK_SERIES
    assert (root / "catalogs" / "twelvedata" / "stock" / "_AAPL-3aNASDAQ" / "1m" / "current.json").is_file()
    repository = ReplayHistoryRepository(root)
    [listed] = repository.list_all_series()
    assert listed["symbol"] == "AAPL:NASDAQ" and listed["series_identity"] == STOCK
    assert repository.describe_catalog("AAPL:NASDAQ", "1m", exchange="twelvedata",
                                       market_type="stock")["identity"]["series_identity"] == STOCK
    rows = repository.query_bars("AAPL:NASDAQ", "1m", exchange="twelvedata", market_type="stock")
    assert [row["open_time"] for row in rows] == [START_MS + index * INTERVAL_MS for index in range(5)]


def test_a_replay_market_never_mixes_two_series(tmp_path: Path):
    writer = ReplayHistoryArchiveWriter(tmp_path / "replay-history", now_ms=lambda: NOW_MS)
    writer.import_batches(APPLE, "1m", [_batch(range(3), key="first")])

    other = identity_from_mapping("twelvedata", {**STOCK, "session_variant": "extended"})
    with pytest.raises(ReplayHistoryArchiveError, match="another kline series"):
        writer.import_batches(ReplaySeriesIdentity("twelvedata", "stock", "AAPL:NASDAQ", series=other),
                              "1m", [_batch(range(3, 6), key="second")])
    # A caller that only knows the route extends the market and keeps its series.
    manifest = writer.import_batches(ReplaySeriesIdentity("twelvedata", "stock", "AAPL:NASDAQ"),
                                     "1m", [_batch(range(3, 6), key="third")])
    assert manifest.identity.series == STOCK_SERIES and manifest.total_count == 6


def test_replay_preparation_carries_the_series_and_keeps_old_submissions():
    # Both replay routes share this identity handling (ReplayPreparationPayload too).
    assert issubclass(ReplayPreparationPayload, ReplayMarketPreparationPayload.__mro__[1])
    for payload in (ReplayMarketPreparationPayload(run_id="run", exchange="binance", market_type="spot", symbol="BTCUSDT"),
                    ReplayMarketPreparationPayload(run_id="run", exchange="binance", market_type="spot",
                                                   symbol="BTCUSDT", identity=KlineSeriesIdentity.for_exchange("binance").to_dict())):
        assert payload.identity is None
        assert "identity" not in payload.model_dump(mode="json")
    apple = ReplayMarketPreparationPayload(run_id="run", exchange="twelvedata", market_type="stock",
                                           symbol="AAPL:NASDAQ", identity={**STOCK, "venue": "XNGS"})
    assert apple.identity == STOCK and apple.model_dump(mode="json")["identity"] == STOCK
    with pytest.raises(ValueError):
        ReplayMarketPreparationPayload(run_id="run", exchange="twelvedata", market_type="stock",
                                       symbol="AAPL:NASDAQ", identity={"unknown": "x"})


def test_replay_hashes_see_the_series_only_when_it_is_not_the_exchange_default():
    from app.replay.canonical import canonical_json

    assert canonical_json(ReplaySeriesIdentity("binance", "spot", "BTCUSDT")) == (
        '{"exchange":"binance","market_type":"spot","symbol":"BTCUSDT"}')
    assert '"series":{"asset_class":"stock"' in canonical_json(APPLE)


def test_a_searched_provider_symbol_has_metadata_for_replay(monkeypatch):
    import asyncio

    from app.exchanges import symbol_catalog

    searches = []

    async def search(*, exchange, market_type, search):
        searches.append(search)
        rows = [{"symbol": "AAPL:NASDAQ", "baseAsset": "AAPL", "quoteAsset": "USD", "exchange": exchange,
                 "marketType": market_type}] if search == "AAPL" else []
        symbol_catalog._remember_provider_rows(exchange, market_type, rows)
        return rows

    monkeypatch.setattr(symbol_catalog, "search_provider_symbols", search)
    monkeypatch.setattr(symbol_catalog, "_provider_search_rows", type(symbol_catalog._provider_search_rows)())
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "stock", "AAPL:NASDAQ") is None

    found = asyncio.run(symbol_catalog.ensure_provider_symbol_metadata("twelvedata", "stock", "AAPL:NASDAQ"))
    assert found["baseAsset"] == "AAPL" and found["quoteAsset"] == "USD"
    assert searches == ["AAPL:NASDAQ", "AAPL"]
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "stock", "aapl:nasdaq")["symbol"] == "AAPL:NASDAQ"
    symbol_catalog.evict_exchange_metadata("twelvedata")
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "stock", "AAPL:NASDAQ") is None


def test_a_search_across_all_markets_files_rows_under_their_own_market(monkeypatch):
    """The symbol picker may search every market at once; lookups ask by the row's market (D5c)."""
    from app.exchanges import symbol_catalog

    monkeypatch.setattr(symbol_catalog, "_provider_search_rows", type(symbol_catalog._provider_search_rows)())
    symbol_catalog._remember_provider_rows("twelvedata", "", [
        {"symbol": "AAPL:NASDAQ", "marketType": "stock", "accountModel": "cash", "quantityStep": "1"},
        {"symbol": "AAPB:NASDAQ", "marketType": "etf"},
        {"symbol": "LEGACY"},
    ])
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "stock", "AAPL:NASDAQ")["quantityStep"] == "1"
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "etf", "AAPB:NASDAQ") is not None
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "stock", "AAPB:NASDAQ") is None
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "", "LEGACY") is not None
    # A filtered search keeps answering under the market it asked for.
    symbol_catalog._remember_provider_rows("twelvedata", "stock", [{"symbol": "X:NYSE", "marketType": "etf"}])
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "stock", "X:NYSE") is not None
    assert symbol_catalog.get_cached_symbol_metadata("twelvedata", "etf", "X:NYSE") is not None
