"""Practice markets on a non-exchange kline series (ADR-DATA-002 D1c)."""
from __future__ import annotations

import asyncio
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.data_engine.series_identity import KlineSeriesIdentity, identity_from_mapping
from app.trading_accounts.models import TradingAccountError
from app.trading_accounts.practice_runtime import PracticeRuntime
from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import SCHEMA_VERSION, TradingStore

D = Decimal
STOCK = {"provider_id": "twelvedata", "venue": "xngs", "asset_class": "stock", "series_variant": "ohlcv",
         "price_adjustment": "raw", "session_variant": "regular", "volume_semantics": "shares"}
STOCK_SERIES = identity_from_mapping("twelvedata", STOCK)
EXTENDED = {**STOCK, "session_variant": "extended"}
APPLE = {"exchange": "twelvedata", "marketType": "stock", "symbol": "AAPL:NASDAQ"}
BITCOIN = {"exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT"}


def bar(time_s: int, price: str) -> dict[str, Any]:
    return {"time": time_s, "open": D(price), "high": D(price), "low": D(price), "close": D(price)}


class SeriesMarket:
    """Records which series every market read asked for."""

    def __init__(self) -> None:
        self.bar: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        self.reads: list[tuple[str, str, KlineSeriesIdentity | None]] = []

    def latest_bar(self, exchange, market_type, symbol, **kwargs):
        self.reads.append(("latest", symbol, kwargs.get("series_identity")))
        return self.bar

    def bars(self, exchange, market_type, symbol, interval, start_ms, end_ms, limit, **kwargs):
        self.reads.append(("bars", symbol, kwargs.get("series_identity")))
        return [item for item in self.history if start_ms // 1000 <= item["time"]], True


class SeriesDataManager:
    def __init__(self) -> None:
        self.streams: list[tuple[str, str, KlineSeriesIdentity | None]] = []
        self.subscribed: list[KlineSeriesIdentity | None] = []

    async def ensure_stream(self, symbol, interval, **kwargs):
        self.streams.append(("ensure", symbol, kwargs.get("series_identity")))

    async def release_stream(self, symbol, interval, **kwargs):
        self.streams.append(("release", symbol, kwargs.get("series_identity")))

    def subscribe(self, callback, symbol=None, interval=None, exchange="binance", market_type="spot",
                  event_types=None, *, on_recovery=None, series_identity=None):
        self.subscribed.append(series_identity)
        return object()

    def unsubscribe(self, handle):
        pass


@pytest.fixture()
def practice(tmp_path: Path):
    market = SeriesMarket()
    minute = int(time.time()) // 60 * 60
    market.bar = bar(minute, "350")
    market.history = [market.bar]
    store = TradingStore(tmp_path / "trading.sqlite3")
    service = TradingAccountService(store, snapshot_dir=tmp_path / "snaps", market=market)
    account = service.create_account({"kind": "practice", "name": "Stocks"})
    yield service, market, account["id"]
    store.close()


def test_a_stock_order_records_its_series_everywhere(practice):
    service, market, account_id = practice
    placed = service.place_order(account_id, {**APPLE, "identity": STOCK, "side": "buy", "type": "market", "qty": "2"})

    order = placed["order"]
    assert order["status"] == "filled" and order["identity"] == STOCK and placed["referencePrice"] == "350"
    assert market.reads and all(series == STOCK_SERIES for _, _, series in market.reads)
    assert service.instrument_series(("twelvedata", "stock", "AAPL:NASDAQ")) == STOCK_SERIES
    [fill] = service.store.fills(account_id)
    assert fill["series_identity"] is not None
    summary = service.account_summary(account_id)
    [position] = summary["positions"]
    assert position["identity"] == STOCK and position["markPrice"] == "350"
    assert all(feed["identity"] == STOCK for feed in summary["feeds"])
    # A stock is fully paid and long-only until D5 adds its own rules.
    assert summary["usedMargin"] == "700"
    with pytest.raises(TradingAccountError) as refused:
        service.place_order(account_id, {**APPLE, "side": "sell", "type": "market", "qty": "3"})
    assert refused.value.code == "TRADING_INSUFFICIENT_POSITION"


def test_the_exchange_series_keeps_its_ledger_form(practice):
    service, market, account_id = practice
    default = KlineSeriesIdentity.for_exchange("binance").to_dict()
    placed = service.place_order(account_id, {**BITCOIN, "identity": default, "side": "buy", "type": "market", "qty": "1"})

    assert "identity" not in placed["order"]
    assert all(series is None for _, _, series in market.reads)
    row = service.store.one("SELECT series_identity FROM orders WHERE id = ?", (placed["order"]["id"],))
    assert row == {"series_identity": None}
    summary = service.account_summary(account_id)
    assert "identity" not in summary["positions"][0] and "identity" not in summary["feeds"][0]


def test_an_active_market_keeps_the_series_it_follows(practice):
    service, market, account_id = practice
    service.place_order(account_id, {**APPLE, "identity": STOCK, "side": "buy", "type": "limit",
                                     "qty": "1", "limitPrice": "300"})
    other = service.create_account({"kind": "practice", "name": "Other"})["id"]

    # Every account matches the market on one cursor, so another series is refused ...
    with pytest.raises(TradingAccountError) as refused:
        service.place_order(other, {**APPLE, "identity": EXTENDED, "side": "buy", "type": "limit",
                                    "qty": "1", "limitPrice": "300"})
    assert refused.value.code == "TRADING_SERIES_MISMATCH"
    # ... and an order that names only the route follows the market's series.
    follower = service.place_order(other, {**APPLE, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "300"})
    assert follower["order"]["identity"] == STOCK


def test_an_idle_market_starts_again_on_the_series_it_is_ordered_on(practice):
    service, market, account_id = practice
    first = service.place_order(account_id, {**APPLE, "identity": STOCK, "side": "buy", "type": "limit",
                                             "qty": "1", "limitPrice": "300"})
    service.cancel_order(account_id, first["order"]["id"])
    extended = identity_from_mapping("twelvedata", EXTENDED)
    market.bar = {**market.bar, "close": D("351")}
    market.reads.clear()

    second = service.place_order(account_id, {**APPLE, "identity": EXTENDED, "side": "buy", "type": "limit",
                                              "qty": "1", "limitPrice": "300"})
    assert second["order"]["identity"] == EXTENDED
    assert service.instrument_series(("twelvedata", "stock", "AAPL:NASDAQ")) == extended
    # The still-fresh cursor priced the old series (350), so the new series is read.
    assert (second["priceSource"], second["referencePrice"]) == ("market_feed", "351")
    assert market.reads[0] == ("latest", "AAPL:NASDAQ", extended)


def test_the_matcher_streams_and_reads_the_followed_series(practice):
    service, market, account_id = practice
    service.place_order(account_id, {**APPLE, "identity": STOCK, "side": "buy", "type": "limit",
                                     "qty": "1", "limitPrice": "300"})
    dm = SeriesDataManager()
    runtime = PracticeRuntime(service, dm, tick_seconds=60, market=market)
    market.reads.clear()

    async def scenario() -> None:
        await runtime.tick()
        assert dm.streams == [("ensure", "AAPL:NASDAQ", STOCK_SERIES)] and dm.subscribed == [STOCK_SERIES]
        assert ("bars", "AAPL:NASDAQ", STOCK_SERIES) in market.reads
        # The market went idle and came back on another series between two sweeps.
        [order] = service.store.orders(account_id, status="working")
        service.cancel_order(account_id, order["id"])
        service.place_order(account_id, {**APPLE, "identity": EXTENDED, "side": "buy", "type": "limit",
                                         "qty": "1", "limitPrice": "300"})
        await runtime.tick()
        extended = identity_from_mapping("twelvedata", EXTENDED)
        assert dm.streams[1:] == [("release", "AAPL:NASDAQ", STOCK_SERIES), ("ensure", "AAPL:NASDAQ", extended)]
        await runtime.stop()

    asyncio.run(scenario())


def test_a_market_without_a_stream_backs_off_and_still_matches_from_history(practice):
    service, market, account_id = practice
    service.place_order(account_id, {**APPLE, "identity": STOCK, "side": "buy", "type": "limit",
                                     "qty": "1", "limitPrice": "300"})
    instrument = ("twelvedata", "stock", "AAPL:NASDAQ")

    class HistoryOnly(SeriesDataManager):
        async def ensure_stream(self, symbol, interval, **kwargs):
            self.streams.append(("ensure", symbol, kwargs.get("series_identity")))
            raise RuntimeError("K-line realtime is unavailable for market 'stock'")

    dm = HistoryOnly()
    runtime = PracticeRuntime(service, dm, tick_seconds=60, market=market)
    market.reads.clear()

    async def scenario() -> None:
        await runtime.tick()
        await runtime.tick()
        # Twelve Data has no 1m stream: one attempt per back-off, not per sweep ...
        assert len(dm.streams) == 1 and runtime._stream_retry[instrument][1] == 1.0
        # ... while every sweep still reads the market's series from history.
        assert [read for read in market.reads if read[0] == "bars"] == [("bars", "AAPL:NASDAQ", STOCK_SERIES)] * 2
        runtime._stream_retry[instrument] = (0.0, runtime._stream_retry[instrument][1])
        await runtime.tick()
        assert len(dm.streams) == 2 and runtime._stream_retry[instrument][1] == 2.0
        # The history steps, not the failed retry, say whether the market is matching.
        [summary_feed] = service.account_summary(account_id)["feeds"]
        assert summary_feed["status"] == "live"
        await runtime.stop()

    asyncio.run(scenario())


def test_excursions_and_manual_fills_use_the_trade_series(practice):
    service, market, account_id = practice
    service.place_order(account_id, {**APPLE, "identity": STOCK, "side": "buy", "type": "market", "qty": "1"})
    [trade] = service.list_trades(account_id)["trades"]
    market.reads.clear()
    service.trade_excursion(account_id, trade["id"])
    assert market.reads and market.reads[0][2] == STOCK_SERIES

    manual = service.create_account({"kind": "manual", "name": "Broker"})["id"]
    recorded = service.add_fill(manual, {**APPLE, "identity": STOCK, "side": "buy", "qty": "1", "price": "349"})
    assert recorded["fill"]["identity"] == STOCK
    market.reads.clear()
    [position] = service.account_summary(manual)["positions"]
    assert position["identity"] == STOCK
    assert all(series == STOCK_SERIES for _, _, series in market.reads)


def test_an_unknown_identity_field_is_refused(practice):
    service, _market, account_id = practice
    with pytest.raises(TradingAccountError) as refused:
        service.place_order(account_id, {**APPLE, "identity": {"exchange": "x"}, "side": "buy",
                                         "type": "market", "qty": "1"})
    assert refused.value.status == 422


def test_a_v4_ledger_upgrades_without_changing_its_rows(tmp_path: Path):
    path = tmp_path / "trading.sqlite3"
    store = TradingStore(path)
    service = TradingAccountService(store, snapshot_dir=tmp_path / "snaps", market=SeriesMarket())
    account = service.create_account({"kind": "manual", "name": "Old"})["id"]
    service.add_fill(account, {**BITCOIN, "side": "buy", "qty": "1", "price": "100"})
    store.close()
    with sqlite3.connect(path) as conn:
        for table in ("orders", "fills", "practice_cursors"):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN series_identity")
        conn.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")

    reopened = TradingStore(path)
    try:
        assert reopened.one("SELECT value FROM meta WHERE key = 'schema_version'")["value"] == str(SCHEMA_VERSION) == "5"
        assert (tmp_path / "trading.sqlite3.pre-trading-accounts-v4-to-v5.sqlite").is_file()
        [fill] = reopened.fills(account)
        assert fill["series_identity"] is None
        service = TradingAccountService(reopened, snapshot_dir=tmp_path / "snaps", market=SeriesMarket())
        assert "identity" not in service.list_fills(account)["fills"][0]
    finally:
        reopened.close()
