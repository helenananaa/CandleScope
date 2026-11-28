"""Practice accounts follow the symbol's declared account model (ADR-DATA-002 D5b, D5c, D5d)."""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from app.exchanges.models import SymbolInfo
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
        self.rows: dict[tuple[str, str, str], dict] = {}

    def symbol_info(self, exchange, market_type, symbol):
        key = (exchange, market_type, symbol)
        model = self.models.get(key)
        return None if model is None else {"symbol": symbol, **self.rows.get(key, {}), "accountModel": model}


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


WHOLE_SHARES = {"currency": "USD", "quantityStep": "1", "quantityOrigin": "0", "minQuantity": "1",
                "quantityRuleModel": "fixed_step"}


def test_cash_stocks_trade_whole_shares_and_say_what_currency_they_are_priced_in(practice):
    service, market, account = practice
    market.rows[("twelvedata", "stock", "AAPL:NASDAQ")] = WHOLE_SHARES
    for qty, reason in (("1.5", "multiple of 1"), ("0.5", "at least 1")):
        with pytest.raises(TradingAccountError) as refused:
            place(service, account, APPLE, 300, qty=qty, side="buy")
        assert refused.value.code == "TRADING_QUANTITY_RULE" and refused.value.status == 422
        assert reason in str(refused.value)
    place(service, account, APPLE, 300, qty="3", side="buy")
    with pytest.raises(TradingAccountError, match="multiple of 1"):
        place(service, account, APPLE, 300, qty="1.5", side="sell")
    assert place(service, account, APPLE, 300, qty="3", side="sell")["order"]["status"] == "filled"
    assert service.market_rules(APPLE) == {**APPLE, "accountModel": "cash", "declared": True, "leverage": False,
                                           "shorting": False, "hedge": False, "opensPositions": True,
                                           "currency": "USD", "quantityStep": "1", "minQuantity": "1"}


def test_a_position_from_before_the_grid_can_still_be_closed_whole(practice):
    service, market, account = practice
    place(service, account, APPLE, 300, qty="2.5", side="buy")
    market.rows[("twelvedata", "stock", "AAPL:NASDAQ")] = WHOLE_SHARES
    place(service, account, APPLE, 300, qty="1", side="sell")
    with pytest.raises(TradingAccountError, match="at least 1"):
        place(service, account, APPLE, 300, qty="0.7", side="sell")
    assert place(service, account, APPLE, 300, qty="1.5", side="sell")["order"]["status"] == "filled"
    assert service.account_summary(account)["positions"] == []


def test_grids_with_an_origin_a_minimum_or_only_significant_digits(practice):
    service, market, account = practice
    spot = {"exchange": "acme", "marketType": "spot", "symbol": "XYZ"}
    market.models[("acme", "spot", "XYZ")] = "cash"
    # Binance LOT_SIZE: quantity = minQty + k * stepSize.
    market.rows[("acme", "spot", "XYZ")] = {"quoteAsset": "usdt", "quantityStep": "0.25", "quantityOrigin": "2",
                                             "minQuantity": "2", "quantityRuleModel": "fixed_step"}
    with pytest.raises(TradingAccountError, match="at least 2"):
        place(service, account, spot, 10, qty="1.75", side="buy")
    with pytest.raises(TradingAccountError, match="multiple of 0.25"):
        place(service, account, spot, 10, qty="2.1", side="buy")
    place(service, account, spot, 10, qty="2.25", side="buy")
    assert service.market_rules(spot)["currency"] == "USDT"
    fine = market_rules(market, ("acme", "spot", "XYZ"))
    assert fine.quantity_error(D("1" + "0" * 30 + ".1")) == "Quantity must be a multiple of 0.25"  # no Decimal overflow
    # A step with no minimum starts at the step; significant digits fix no step.
    market.rows[("acme", "spot", "XYZ")] = {"quantityStep": "0.001"}
    assert market_rules(market, ("acme", "spot", "XYZ")).to_dict()["minQuantity"] == "0.001"
    market.rows[("acme", "spot", "XYZ")] = {"quantityStep": "0.001", "minQuantity": "0.5",
                                             "quantityRuleModel": "significant_digits"}
    rules = market_rules(market, ("acme", "spot", "XYZ")).to_dict()
    assert "quantityStep" not in rules and rules["minQuantity"] == "0.5"
    place(service, account, spot, 10, qty="0.5123", side="buy")


def test_linear_contract_grids_count_contracts_of_their_size(practice):
    service, market, account = practice
    # Gate counts BTC/USDT:USDT in whole contracts of 0.0001 BTC; practice quantities are BTC.
    market.rows[("gate", "swap.linear", "BTC/USDT:USDT")] = {"quantityStep": "1", "minQuantity": "1",
                                                              "contractMultiplier": "0.0001", "quoteAsset": "USDT"}
    for qty, reason in (("0.00005", "at least 0.0001"), ("0.00015", "multiple of 0.0001")):
        with pytest.raises(TradingAccountError) as refused:
            place(service, account, GATE, 100, qty=qty, positionSide="LONG", positionEffect="open")
        assert refused.value.code == "TRADING_QUANTITY_RULE" and reason in str(refused.value)
    order = place(service, account, GATE, 100, qty="0.0003", positionSide="LONG", positionEffect="open")["order"]
    assert order["status"] == "filled"
    market.rows[("gate", "swap.linear", "BTC/USDT:USDT")]["baseAsset"] = "btc"
    rules = service.market_rules(GATE)
    assert {key: rules[key] for key in ("quantityStep", "minQuantity", "contractSize", "baseAsset")} == {
        "quantityStep": "0.0001", "minQuantity": "0.0001", "contractSize": "0.0001", "baseAsset": "BTC"}
    # OKX: lots of 0.01 contracts of 0.01 BTC; the grid's origin scales with the size too.
    market.rows[("gate", "swap.linear", "BTC/USDT:USDT")] = {"quantityStep": "0.01", "minQuantity": "0.01",
                                                              "quantityOrigin": "0.02", "contractMultiplier": "0.01"}
    okx = market_rules(market, ("gate", "swap.linear", "BTC/USDT:USDT"))
    assert (okx.quantity_step, okx.quantity_origin, okx.min_quantity) == (D("0.0001"), D("0.0002"), D("0.0002"))
    # Without a contract size there is no grid; coin-settled sizes are quote amounts, so none either.
    market.rows[("gate", "swap.linear", "BTC/USDT:USDT")] = {"quantityStep": "1", "minQuantity": "1"}
    assert "quantityStep" not in service.market_rules(GATE)
    market.rows[("okx", "futures", "BTC-USD-SWAP")] = {"quantityStep": "1", "contractMultiplier": "100"}
    inverse = service.market_rules(OKX_INVERSE)
    assert "quantityStep" not in inverse and "contractSize" not in inverse


ES = {"exchange": "acme", "marketType": "futures", "symbol": "ESZ6"}
ES_ROW = {"quoteAsset": "USD", "contractMultiplier": "50", "quantityStep": "1", "minQuantity": "1"}


@pytest.fixture()
def futures(practice):
    service, market, _ = practice
    market.models[("acme", "futures", "ESZ6")] = "futures_margin"
    market.rows[("acme", "futures", "ESZ6")] = dict(ES_ROW)
    account = service.create_account({"kind": "practice", "name": "Futures", "settings": {
        "initialBalance": "100000", "leverage": "10", "takerFeeRate": "0", "makerFeeRate": "0", "slippageBps": "0",
    }})["id"]
    return service, market, account


def test_futures_hold_a_fixed_margin_per_contract_and_profit_by_the_multiplier(futures):
    service, market, account = futures
    market.rows[("acme", "futures", "ESZ6")]["marginPerContract"] = "12000"
    assert service.market_rules(ES) == {
        **ES, "accountModel": "futures_margin", "declared": True, "leverage": False, "shorting": True,
        "hedge": True, "opensPositions": True, "currency": "USD", "quantityStep": "50", "minQuantity": "50",
        "contractSize": "50", "marginPerContract": "12000", "marginSource": "catalog"}
    # One contract is 50 units of the index; half a contract is off the grid.
    with pytest.raises(TradingAccountError, match="multiple of 50"):
        place(service, account, ES, 5000, qty="75", positionSide="LONG", positionEffect="open")
    # Eight contracts hold 8 x 12,000, not notional over leverage (8 x 50 x 5,000 / 10 = 200,000).
    place(service, account, ES, 5000, qty="400", positionSide="LONG", positionEffect="open")
    summary = service.account_summary(account)
    assert D(summary["usedMargin"]) == D("96000")
    with pytest.raises(TradingAccountError) as refused:
        place(service, account, ES, 5000, qty="50", positionSide="SHORT", positionEffect="open")
    assert refused.value.code == "TRADING_INSUFFICIENT_BALANCE"
    # Ten index points on eight contracts of 50: 10 x 50 x 8. Once the seeded
    # practice price is no longer fresh, the order takes the chart's price.
    service.clock.now += 20_000
    place(service, account, ES, 5010, qty="400", positionSide="LONG", positionEffect="close")
    trade = service.list_trades(account)["trades"][0]
    assert D(trade["realizedPnl"]) == D("4000")
    assert D(service.account_summary(account)["usedMargin"]) == 0


def test_futures_without_a_published_margin_take_the_users_figure(futures):
    service, market, account = futures
    rules = service.market_rules({**ES, "accountId": account})
    assert rules["opensPositions"] is False and rules["contractSize"] == "50" and "marginPerContract" not in rules
    with pytest.raises(TradingAccountError) as refused:
        place(service, account, ES, 5000, qty="50", positionSide="LONG", positionEffect="open")
    assert refused.value.code == "TRADING_MARGIN_REQUIRED" and refused.value.status == 409
    for bad in ("-1", "0", "abc"):
        with pytest.raises(TradingAccountError) as invalid:
            service.set_contract_margin(account, {**ES, "marginPerContract": bad})
        assert invalid.value.status == 422

    saved = service.set_contract_margin(account, {**ES, "marginPerContract": "15000"})
    assert (saved["marginPerContract"], saved["marginSource"], saved["opensPositions"]) == ("15000", "account", True)
    assert "marginPerContract" not in service.market_rules(ES)  # the figure belongs to the account
    place(service, account, ES, 5000, qty="100", positionSide="LONG", positionEffect="open")
    assert D(service.account_summary(account)["usedMargin"]) == D("30000")
    view = service.update_account(account, {"settings": {"leverage": "5"}})
    assert view["contractMargins"] == [{**ES, "marginPerContract": "15000"}]
    assert "contractMargins" not in view["settings"]
    # The figure can change while a position is open, but not be cleared.
    service.set_contract_margin(account, {**ES, "marginPerContract": "16000"})
    assert D(service.account_summary(account)["usedMargin"]) == D("32000")
    with pytest.raises(TradingAccountError) as held:
        service.set_contract_margin(account, {**ES, "marginPerContract": None})
    assert held.value.code == "TRADING_POSITION_OPEN"
    place(service, account, ES, 5000, qty="100", positionSide="LONG", positionEffect="close")
    service.set_contract_margin(account, {**ES, "marginPerContract": ""})
    assert "contractMargins" not in service.account_view(service._account(account))

    # Markets that publish their margin, or hold none per contract, take no figure.
    market.rows[("acme", "futures", "ESZ6")]["marginPerContract"] = "12000"
    for other in (ES, GATE):
        with pytest.raises(TradingAccountError) as refused:
            service.set_contract_margin(account, {**other, "marginPerContract": "1"})
        assert refused.value.code == "TRADING_MARGIN_NOT_APPLICABLE"


def test_futures_without_a_contract_size_open_nothing(futures):
    service, market, account = futures
    market.rows[("acme", "futures", "ESZ6")] = {"marginPerContract": "12000"}
    assert service.market_rules(ES)["opensPositions"] is False
    with pytest.raises(TradingAccountError) as refused:
        place(service, account, ES, 5000, qty="50", positionSide="LONG", positionEffect="open")
    assert refused.value.code == "TRADING_ACCOUNT_MODEL_UNSUPPORTED" and "declared size" in str(refused.value)


def test_symbol_rows_carry_a_margin_per_contract():
    row = dict(symbol="ESZ6", base_asset="ES", quote_asset="USD", status="TRADING", exchange="acme",
               market_type="futures", product_type="futures", account_model="futures_margin")
    assert SymbolInfo(**row, margin_per_contract="12000").to_dict()["marginPerContract"] == "12000"
    assert "marginPerContract" not in SymbolInfo(**row).to_dict()
    with pytest.raises(ValueError):
        SymbolInfo(**row, margin_per_contract="-5")
