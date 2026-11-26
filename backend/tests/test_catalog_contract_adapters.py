import asyncio
from unittest.mock import AsyncMock

import pytest

from app.exchanges.plugins.binance import adapter as binance
from app.exchanges.plugins.okx import adapter as okx


def test_native_binance_catalog_transports_base_quantity_rules():
    adapter = binance.BinanceExchangeAdapter()
    adapter._fetch_exchange_info = AsyncMock(return_value={'symbols': [
        dict(symbol='ABCUSD',baseAsset='ABC',quoteAsset='USD',status='TRADING',contractType='PERPETUAL',
             filters=[dict(filterType='PRICE_FILTER',tickSize='0.1'),dict(filterType='LOT_SIZE',stepSize='0.25',minQty='2')])
    ]})
    symbol = asyncio.run(adapter._load_futures_symbols())[0].to_dict()
    assert symbol['contractMultiplier']=='1' and symbol['contractValueModel']=='linear'
    assert symbol['quantityStep']=='0.25' and symbol['minQuantity']=='2'
    assert symbol['quantityOrigin']=='2' and symbol['quantityRuleModel']=='fixed_step'



def _futures_row(symbol, base, contract_type="PERPETUAL", status="TRADING", **extra):
    return dict(symbol=symbol, baseAsset=base, quoteAsset="USDT", status=status, contractType=contract_type,
                deliveryDate=4133404800000, onboardDate=1767225600000,
                filters=[dict(filterType="PRICE_FILTER", tickSize="0.01"),
                         dict(filterType="LOT_SIZE", stepSize="0.001", minQty="0.001")], **extra)


def test_native_binance_catalog_admits_tradfi_perpetuals_as_crypto_venue_series(caplog):
    adapter = binance.BinanceExchangeAdapter()
    adapter._fetch_exchange_info = AsyncMock(return_value={"symbols": [
        _futures_row("BTCUSDT", "BTC", underlyingType="COIN"),
        _futures_row("XAUUSDT", "XAU", "TRADIFI_PERPETUAL", underlyingType="COMMODITY"),
        _futures_row("AAPLUSDT", "AAPL", "TRADIFI_PERPETUAL", underlyingType="EQUITY"),
        _futures_row("HK0700USDT", "HK0700", "TRADIFI_PERPETUAL", underlyingType="HK_EQUITY"),
        _futures_row("OPENAIUSDT", "OPENAI", "TRADIFI_PERPETUAL", underlyingType="PREMARKET"),
        _futures_row("USDBRLUSDT", "USDBRL", "TRADIFI_PERPETUAL", underlyingType="FX"),
        _futures_row("BONDUSDT", "BOND", "TRADIFI_PERPETUAL", underlyingType="RATES"),
        _futures_row("XIAOMIUSDT", "XIAOMI", "TRADIFI_PERPETUAL", status="PENDING_TRADING", underlyingType="HK_EQUITY"),
        _futures_row("BTCUSDT_261225", "BTC", "CURRENT_QUARTER", underlyingType="COIN"),
    ]})
    rows = {item.symbol: item.to_dict() for item in asyncio.run(adapter._load_futures_symbols())}

    assert set(rows) == {"BTCUSDT", "XAUUSDT", "AAPLUSDT", "HK0700USDT", "OPENAIUSDT", "USDBRLUSDT"}
    assert "RATES" in caplog.text
    gold = rows["XAUUSDT"]
    # Same series identity as any Binance perpetual; only the underlying differs.
    assert {key: gold[key] for key in ("assetClass", "sessionVariant", "volumeSemantics")} == {
        key: rows["BTCUSDT"][key] for key in ("assetClass", "sessionVariant", "volumeSemantics")}
    assert gold["assetClass"] == "crypto" and gold["productType"] == "perpetual"
    assert gold["contractType"] == "TRADIFI_PERPETUAL" and gold["expiryAtMs"] is None
    assert gold["underlyingClass"] == "commodity" and "underlyingRegion" not in gold
    assert gold["underlyingSymbol"] == "XAU" and gold["displayName"] == "Gold"
    assert gold["contractValueModel"] == "linear" and gold["quantityStep"] == "0.001"
    assert (rows["AAPLUSDT"]["underlyingClass"], rows["AAPLUSDT"]["underlyingRegion"]) == ("stock", "us")
    assert rows["AAPLUSDT"]["displayName"] == ""
    assert rows["HK0700USDT"]["underlyingRegion"] == "hk"
    assert rows["OPENAIUSDT"]["underlyingClass"] == "stock" and "underlyingRegion" not in rows["OPENAIUSDT"]
    assert rows["USDBRLUSDT"]["underlyingClass"] == "forex"
    assert "underlyingClass" not in rows["BTCUSDT"] and rows["BTCUSDT"]["underlyingSymbol"] == ""


def test_tradfi_perpetual_with_a_real_delivery_date_keeps_its_expiry():
    adapter = binance.BinanceExchangeAdapter()
    adapter._fetch_exchange_info = AsyncMock(return_value={"symbols": [
        _futures_row("SPCXUSDT", "SPCX", "TRADIFI_PERPETUAL", underlyingType="EQUITY") | {"deliveryDate": 1794913200000},
    ]})
    assert asyncio.run(adapter._load_futures_symbols())[0].expiry_at_ms == 1794913200000


def test_symbol_underlying_fields_are_validated():
    from app.exchanges.models import SymbolInfo

    base = dict(symbol="XAUUSDT", base_asset="XAU", quote_asset="USDT", status="TRADING",
                exchange="binance", market_type="futures", product_type="perpetual")
    assert SymbolInfo(**base, underlying_class=" Commodity ").underlying_class == "commodity"
    for bad in (dict(underlying_class="bond"), dict(underlying_class="crypto"),
                dict(underlying_region="us"), dict(underlying_class="stock", underlying_region="u-s")):
        with pytest.raises(ValueError):
            SymbolInfo(**base, **bad)

def test_native_okx_catalog_transports_contract_counts_and_base_contract_value():
    adapter=okx.OkxExchangeAdapter()
    adapter._fetch_public_data=AsyncMock(return_value=[
        dict(instId='ABC-USD-SWAP',baseCcy='ABC',settleCcy='USD',state='live',ctType='linear',
             ctVal='0.01',ctMult='100',ctValCcy='ABC',lotSz='0.25',minSz='2',tickSz='0.1')])
    symbol=asyncio.run(adapter._load_symbols('SWAP','futures','perpetual'))[0].to_dict()
    assert symbol['priceTickSize']=='0.1'
    assert symbol['contractMultiplier']=='0.01' and symbol['contractValueModel']=='linear'
    assert symbol['quantityStep']=='0.25' and symbol['minQuantity']=='2'
