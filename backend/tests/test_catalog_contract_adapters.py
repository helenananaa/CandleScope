import asyncio
from unittest.mock import AsyncMock

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


def test_native_okx_catalog_transports_contract_counts_and_base_contract_value():
    adapter=okx.OkxExchangeAdapter()
    adapter._fetch_public_data=AsyncMock(return_value=[
        dict(instId='ABC-USD-SWAP',baseCcy='ABC',settleCcy='USD',state='live',ctType='linear',
             ctVal='0.01',ctMult='100',ctValCcy='ABC',lotSz='0.25',minSz='2',tickSz='0.1')])
    symbol=asyncio.run(adapter._load_symbols('SWAP','futures','perpetual'))[0].to_dict()
    assert symbol['priceTickSize']=='0.1'
    assert symbol['contractMultiplier']=='0.01' and symbol['contractValueModel']=='linear'
    assert symbol['quantityStep']=='0.25' and symbol['minQuantity']=='2'
