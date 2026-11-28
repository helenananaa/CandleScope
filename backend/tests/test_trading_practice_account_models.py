"""Practice accounts follow the symbol's declared account model (ADR-DATA-002 D5b)."""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from app.trading_accounts.account_models import market_rules
from app.trading_accounts.models import TradingAccountError
from app.trading_accounts.practice_runtime import DataManagerMarket
from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore
from tests.test_trading_accounts import T0, Clock, FakeMarket

GATE = {"exchange": "gate", "marketType": "swap.linear", "symbol": "BTC/USDT:USDT"}
OKX_INVERSE = {"exchange": "okx", "marketType": "futures", "symbol": "BTC-USD-SWAP"}
APPLE = {"exchange": "twelvedata", "marketType": "stock", "symbol": "AAPL:NASDAQ"}


class CatalogMarket(FakeMarket):
    """A market whose catalog rows declare account models."""

    def __init__(self) -> None:
        super().__init__()
        self.models: dict[tuple[str, str, str], str] = {}

    def symbol_info(self, exchange, market_type, symbol):
        model = self.models.get((exchange, market_type, symbol))
        return None if model is None else {"symbol": symbol, "accountModel": model}


@pytest.fixture()
def practice(tmp_path: Path):
    market = CatalogMarket()
    market.models.update({
        ("gate", "swap.linear", "BTC/USDT:USDT"): "crypto_linear",
        ("okx", "futures", "BTC-USD-SWAP"): "crypto_inverse",
        ("twelvedata", "stock", "AAPL:NASDAQ"): "cash",
    })
    store = TradingStore(tmp_path / "trading.sqlite3")
    service = TradingAccountService(store, snapshot_dir=tmp_path / "snaps", market=market, clock=Clock(T0 + 30_000))
    account = service.create_account({"kind": "practice", "name": "Models", "settings": {
        "initialBalance": "10000", "leverage": "10", "takerFeeRate": "0", "makerFeeRate": "0", "slippageBps": "0",
    }})["id"]
    yield service, market, account
    store.close()


def place(service, account, market, price, **fields):
    return service.place_order(account, {**market, "type": "market", "referencePrice": str(price), **fields})


def test_linear_swaps_on_any_venue_get_leverage_shorting_and_hedge(practice):
    service, _, account = practice
    # Before D5b only market type "futures" could short; Gate's swap.linear was fully paid and long only.
    short = place(service, account, GATE, 100, qty="2", positionSide="SHORT", positionEffect="open")["order"]
    assert short["status"] == "filled" and short["side"] == "sell"
    summary = service.account_summary(account)
    assert D(summary["usedMargin"]) == D("20")  # 2 x 100 / leverage 10
    assert service.market_rules(GATE) == {**GATE, "accountModel": "crypto_linear", "declared": True,
                                          "leverage": True, "shorting": True, "hedge": True, "opensPositions": True}


def test_cash_markets_are_fully_paid_long_only_without_hedge_intent(practice):
    service, _, account = practice
    with pytest.raises(TradingAccountError, match="hedge order intent"):
        place(service, account, APPLE, 300, qty="1", positionSide="LONG", positionEffect="open")
    with pytest.raises(TradingAccountError) as refused:
        place(service, account, APPLE, 300, qty="1", side="sell")
    assert refused.value.code == "TRADING_INSUFFICIENT_POSITION"
    place(service, account, APPLE, 300, qty="3", side="buy")
    assert D(service.account_summary(account)["usedMargin"]) == D("900")
    with pytest.raises(TradingAccountError, match="Not enough available balance"):
        place(service, account, APPLE, 300, qty="31", side="buy")


def test_coin_settled_contracts_open_nothing_but_close_what_is_open(practice):
    service, market, account = practice
    with pytest.raises(TradingAccountError) as refused:
        place(service, account, OKX_INVERSE, 100, qty="1", positionSide="LONG", positionEffect="open")
    assert refused.value.code == "TRADING_ACCOUNT_MODEL_UNSUPPORTED" and refused.value.status == 409
    assert "coin-settled" in str(refused.value)

    # A position opened before the catalog declared the model can still be closed.
    del market.models[("okx", "futures", "BTC-USD-SWAP")]
    place(service, account, OKX_INVERSE, 100, qty="1", positionSide="LONG", positionEffect="open")
    market.models[("okx", "futures", "BTC-USD-SWAP")] = "crypto_inverse"
    with pytest.raises(TradingAccountError):
        place(service, account, OKX_INVERSE, 100, qty="1", positionSide="LONG", positionEffect="open")
    closed = place(service, account, OKX_INVERSE, 100, qty="1", positionSide="LONG", positionEffect="close")
    assert closed["order"]["status"] == "filled"
    assert service.account_summary(account)["positions"] == []


def test_undeclared_markets_keep_the_rules_from_before(practice):
    service, market, account = practice
    assert market_rules(market, ("binance", "futures", "BTCUSDT")).account_model == "crypto_linear"
    assert market_rules(market, ("binance", "spot", "BTCUSDT")).account_model == "cash"
    assert not market_rules(market, ("binance", "spot", "BTCUSDT")).declared
    assert market_rules(object(), ("acme", "swap.linear", "X")).account_model == "cash"
    market.models[("acme", "spot", "X")] = "margin"  # not a model: ignored
    assert market_rules(market, ("acme", "spot", "X")).to_dict()["declared"] is False
    futures = {"exchange": "binance", "marketType": "futures", "symbol": "BTCUSDT"}
    assert place(service, account, futures, 100, qty="1", positionSide="SHORT",
                 positionEffect="open")["order"]["status"] == "filled"


def test_data_manager_market_reads_catalog_rows_and_retries_missing_ones():
    calls = []
    rows = {("gate", "swap.linear", "BTC/USDT:USDT"): {"accountModel": "crypto_linear"}}

    def lookup(exchange, market_type, symbol):
        calls.append(symbol)
        return rows.get((exchange, market_type, symbol))

    market = DataManagerMarket(object(), symbol_metadata=lookup)
    assert market.symbol_info("gate", "swap.linear", "BTC/USDT:USDT") == {"accountModel": "crypto_linear"}
    assert market.symbol_info("gate", "swap.linear", "BTC/USDT:USDT") == {"accountModel": "crypto_linear"}
    assert market.symbol_info("gate", "swap.linear", "ETH/USDT:USDT") is None
    assert market.symbol_info("gate", "swap.linear", "ETH/USDT:USDT") is None
    assert calls == ["BTC/USDT:USDT", "ETH/USDT:USDT", "ETH/USDT:USDT"]
