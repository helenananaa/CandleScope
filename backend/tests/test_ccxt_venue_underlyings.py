"""Venue TradFi contract classification (ADR-DATA-002 D0b).

The rows below are trimmed copies of each venue's public market list as CCXT
4.5.60 loaded it on 2026-11-26 (``info`` of ``load_markets``). Only the fields
the classifier reads and a few neighbours are kept.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.generic import (
    HYPERLIQUID_HIP3_DEX_LIMIT,
    _create_exchange,
    load_ccxt_symbols,
)
from app.exchanges.ccxt_ext.runtime import close_ccxt_exchange
from app.exchanges.models import SymbolInfo
from app.exchanges.venue_underlyings import venue_contract_underlying

ROWS: dict[str, dict[str, dict[str, Any]]] = {
    "okx": {
        'BTC-USDT-SWAP': {'instId': 'BTC-USDT-SWAP', 'instType': 'SWAP', 'instFamily': 'BTC-USDT', 'uly': 'BTC-USDT', 'instCategory': '1', 'ruleType': 'normal', 'settleCcy': 'USDT', 'ctType': 'linear', 'state': 'live'},
        'XAU-USDT-SWAP': {'instId': 'XAU-USDT-SWAP', 'instType': 'SWAP', 'instFamily': 'XAU-USDT', 'uly': 'XAU-USDT', 'instCategory': '4', 'ruleType': 'normal', 'settleCcy': 'USDT', 'ctType': 'linear', 'state': 'live'},
        'CL-USDT-SWAP': {'instId': 'CL-USDT-SWAP', 'instType': 'SWAP', 'instFamily': 'CL-USDT', 'uly': 'CL-USDT', 'instCategory': '4', 'ruleType': 'normal', 'settleCcy': 'USDT', 'ctType': 'linear', 'state': 'live'},
        'AAPL-USDT-SWAP': {'instId': 'AAPL-USDT-SWAP', 'instType': 'SWAP', 'instFamily': 'AAPL-USDT', 'uly': 'AAPL-USDT', 'instCategory': '3', 'ruleType': 'normal', 'settleCcy': 'USDT', 'ctType': 'linear', 'state': 'live'},
        'OPENAI-USDT-SWAP': {'instId': 'OPENAI-USDT-SWAP', 'instType': 'SWAP', 'instFamily': 'OPENAI-USDT', 'uly': 'OPENAI-USDT', 'instCategory': '3', 'ruleType': 'pre_market', 'settleCcy': 'USDT', 'ctType': 'linear', 'state': 'live'},
    },
    "bybit": {
        'BTCUSDT': {'symbol': 'BTCUSDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'BTC', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': '', 'marketRegion': '', 'underlyingTicker': '', 'fullName': 'Bitcoin', 'displayName': 'BTCUSDT'},
        'XAUUSDT': {'symbol': 'XAUUSDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'XAU', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': 'commodity', 'marketRegion': '', 'underlyingTicker': '', 'fullName': 'XAU', 'displayName': 'XAUUSDT'},
        'CLUSDT': {'symbol': 'CLUSDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'CL', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': 'commodity', 'marketRegion': '', 'underlyingTicker': '', 'fullName': 'WTI Crude Oil', 'displayName': 'CLUSDT'},
        'AAPLUSDT': {'symbol': 'AAPLUSDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'AAPL', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': 'stock', 'marketRegion': 'US', 'underlyingTicker': 'AAPL', 'fullName': 'Apple', 'displayName': 'AAPLUSDT'},
        'BYDUSDT': {'symbol': 'BYDUSDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'BYD', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': 'stock', 'marketRegion': 'HK', 'underlyingTicker': '1211HK', 'fullName': 'BYD Company Limited', 'displayName': 'BYDUSDT'},
        'KODEX200USDT': {'symbol': 'KODEX200USDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'KODEX200', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': 'ETF', 'marketRegion': 'KR', 'underlyingTicker': '069500', 'fullName': 'Samsung KODEX 200 ETF', 'displayName': 'KODEX200USDT'},
        'EURUSDUSDT': {'symbol': 'EURUSDUSDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'EURUSD', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': 'forex', 'marketRegion': '', 'underlyingTicker': '', 'fullName': 'EURUSD', 'displayName': 'EURUSDUSDT'},
        'XAUTUSDT': {'symbol': 'XAUTUSDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'XAUT', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': '', 'marketRegion': '', 'underlyingTicker': '', 'fullName': 'Tether Gold', 'displayName': 'XAUTUSDT'},
        'SPXUSDT': {'symbol': 'SPXUSDT', 'contractType': 'LinearPerpetual', 'status': 'Trading', 'baseCoin': 'SPX', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'symbolType': '', 'marketRegion': '', 'underlyingTicker': '', 'fullName': 'SPX6900', 'displayName': 'SPXUSDT'},
    },
    "bitget": {
        'BTCUSDT': {'symbol': 'BTCUSDT', 'baseCoin': 'BTC', 'quoteCoin': 'USDT', 'symbolType': 'perpetual', 'symbolStatus': 'normal', 'isRwa': 'NO'},
        'XAUUSDT': {'symbol': 'XAUUSDT', 'baseCoin': 'XAU', 'quoteCoin': 'USDT', 'symbolType': 'perpetual', 'symbolStatus': 'normal', 'isRwa': 'YES'},
        'CLUSDT': {'symbol': 'CLUSDT', 'baseCoin': 'CL', 'quoteCoin': 'USDT', 'symbolType': 'perpetual', 'symbolStatus': 'normal', 'isRwa': 'YES'},
        'AAPLUSDT': {'symbol': 'AAPLUSDT', 'baseCoin': 'AAPL', 'quoteCoin': 'USDT', 'symbolType': 'perpetual', 'symbolStatus': 'normal', 'isRwa': 'YES'},
        'PAXGUSDT': {'symbol': 'PAXGUSDT', 'baseCoin': 'PAXG', 'quoteCoin': 'USDT', 'symbolType': 'perpetual', 'symbolStatus': 'normal', 'isRwa': 'YES'},
        'EURUSDUSDT': {'symbol': 'EURUSDUSDT', 'baseCoin': 'EURUSD', 'quoteCoin': 'USDT', 'symbolType': 'perpetual', 'symbolStatus': 'normal', 'isRwa': 'YES'},
    },
    "bingx": {
        'BTC-USDT': {'contractId': '100', 'symbol': 'BTC-USDT', 'currency': 'USDT', 'asset': 'BTC', 'status': 1, 'displayName': 'BTC-USDT'},
        'NCCOGOLD2USD-USDT': {'contractId': '101773', 'symbol': 'NCCOGOLD2USD-USDT', 'currency': 'USDT', 'asset': 'NCCOGOLD2USD', 'status': 1, 'displayName': 'GOLD(XAU)-USDT'},
        'NCCO1OILWTI2USD-USDT': {'contractId': '102399', 'symbol': 'NCCO1OILWTI2USD-USDT', 'currency': 'USDT', 'asset': 'NCCO1OILWTI2USD', 'status': 1, 'displayName': 'Oil WTI-USDT'},
        'NCSKAAPL2USD-USDT': {'contractId': '101959', 'symbol': 'NCSKAAPL2USD-USDT', 'currency': 'USDT', 'asset': 'NCSKAAPL2USD', 'status': 1, 'displayName': 'AAPL-USDT'},
        'NCFXEUR2USD-USDT': {'contractId': '101539', 'symbol': 'NCFXEUR2USD-USDT', 'currency': 'USDT', 'asset': 'NCFXEUR2USD', 'status': 1, 'displayName': 'EURUSD-USDT'},
        'NCSISP5002USD-USDT': {'contractId': '102082', 'symbol': 'NCSISP5002USD-USDT', 'currency': 'USDT', 'asset': 'NCSISP5002USD', 'status': 1, 'displayName': 'SP500-USDT'},
        'XAUT-USDT': {'contractId': '101109', 'symbol': 'XAUT-USDT', 'currency': 'USDT', 'asset': 'XAUT', 'status': 1, 'displayName': 'XAUT(GOLD)-USDT'},
    },
    "blofin": {
        'BTC-USDT': {'instId': 'BTC-USDT', 'baseCurrency': 'BTC', 'quoteCurrency': 'USDT', 'assetClass': 'Crypto', 'instType': 'SWAP', 'contractType': 'linear', 'state': 'live'},
        'XAU-USDT': {'instId': 'XAU-USDT', 'baseCurrency': 'XAU', 'quoteCurrency': 'USDT', 'assetClass': 'Crypto', 'instType': 'SWAP', 'contractType': 'linear', 'state': 'live'},
        'CL-USDT': {'instId': 'CL-USDT', 'baseCurrency': 'CL', 'quoteCurrency': 'USDT', 'assetClass': 'Commodities', 'instType': 'SWAP', 'contractType': 'linear', 'state': 'live'},
        'AAPL-USDT': {'instId': 'AAPL-USDT', 'baseCurrency': 'AAPL', 'quoteCurrency': 'USDT', 'assetClass': 'Stocks', 'instType': 'SWAP', 'contractType': 'linear', 'state': 'live'},
        'QQQ-USDT': {'instId': 'QQQ-USDT', 'baseCurrency': 'QQQ', 'quoteCurrency': 'USDT', 'assetClass': 'Indices', 'instType': 'SWAP', 'contractType': 'linear', 'state': 'live'},
    },
    "gate": {
        'BTC_USDT': {'name': 'BTC_USDT', 'contract_type': '', 'quanto_multiplier': '0.0001', 'status': 'trading', 'in_delisting': False},
        'XAU_USDT': {'name': 'XAU_USDT', 'contract_type': 'metals', 'quanto_multiplier': '0.0001', 'status': 'trading', 'in_delisting': False},
        'CL_USDT': {'name': 'CL_USDT', 'contract_type': 'commodities', 'quanto_multiplier': '0.01', 'status': 'trading', 'in_delisting': False},
        'AAPL_USDT': {'name': 'AAPL_USDT', 'contract_type': 'stocks', 'quanto_multiplier': '0.01', 'status': 'trading', 'in_delisting': False},
        'EURUSD_USDT': {'name': 'EURUSD_USDT', 'contract_type': 'forex', 'quanto_multiplier': '1', 'status': 'trading', 'in_delisting': False},
        'SPX500_USDT': {'name': 'SPX500_USDT', 'contract_type': 'indices', 'quanto_multiplier': '0.001', 'status': 'trading', 'in_delisting': False},
    },
    "kucoinfutures": {
        'XBTUSDTM': {'symbol': 'XBTUSDTM', 'baseCurrency': 'XBT', 'quoteCurrency': 'USDT', 'settleCurrency': 'USDT', 'marketType': 'CRYPTO', 'assetClass': 'CRYPTO', 'status': 'Open'},
        'XAGUSDTM': {'symbol': 'XAGUSDTM', 'baseCurrency': 'XAG', 'quoteCurrency': 'USDT', 'settleCurrency': 'USDT', 'marketType': 'CRYPTO', 'assetClass': 'METAL', 'status': 'Open'},
        'CLUSDTM': {'symbol': 'CLUSDTM', 'baseCurrency': 'CL', 'quoteCurrency': 'USDT', 'settleCurrency': 'USDT', 'marketType': 'CRYPTO', 'assetClass': 'COMMODITY', 'status': 'Open'},
        'AAPLUSDTM': {'symbol': 'AAPLUSDTM', 'baseCurrency': 'AAPL', 'quoteCurrency': 'USDT', 'settleCurrency': 'USDT', 'marketType': 'NASDAQ', 'assetClass': 'STOCK', 'status': 'Open'},
    },
    "xt": {
        'btc_usdt': {'symbol': 'btc_usdt', 'contractType': 'PERPETUAL', 'baseCoin': 'btc', 'quoteCoin': 'usdt', 'labels': ['HOT'], 'tags': None, 'businessName': None},
        'xau_usdt': {'symbol': 'xau_usdt', 'contractType': 'PERPETUAL', 'baseCoin': 'xau', 'quoteCoin': 'usdt', 'labels': ['METAL', 'HOT'], 'tags': ['METAL'], 'businessName': 'Gold'},
        'cl_usdt': {'symbol': 'cl_usdt', 'contractType': 'PERPETUAL', 'baseCoin': 'cl', 'quoteCoin': 'usdt', 'labels': ['COMMODITY'], 'tags': ['COMMODITY'], 'businessName': 'WTI Crude Oil'},
        'aaplx_usdt': {'symbol': 'aaplx_usdt', 'contractType': 'PERPETUAL', 'baseCoin': 'aaplx', 'quoteCoin': 'usdt', 'labels': ['STOCK'], 'tags': ['STOCK'], 'businessName': 'Apple'},
        'eur_usdt': {'symbol': 'eur_usdt', 'contractType': 'PERPETUAL', 'baseCoin': 'eur', 'quoteCoin': 'usdt', 'labels': ['FOREX'], 'tags': ['FOREX'], 'businessName': 'EURUSDT'},
        'nas100_usdt': {'symbol': 'nas100_usdt', 'contractType': 'PERPETUAL', 'baseCoin': 'nas100', 'quoteCoin': 'usdt', 'labels': ['INDEX'], 'tags': ['INDEX'], 'businessName': 'Nasdaq 100'},
        'openai_usdt': {'symbol': 'openai_usdt', 'contractType': 'PERPETUAL', 'baseCoin': 'openai', 'quoteCoin': 'usdt', 'labels': ['STOCK', 'Pre-M'], 'tags': ['STOCK', 'Pre-M'], 'businessName': 'OpenAI'},
    },
    "krakenfutures": {
        'PF_XBTUSD': {'symbol': 'PF_XBTUSD', 'type': 'flexible_futures', 'base': 'BTC', 'quote': 'USD', 'category': 'Layer 1', 'tradfi': False, 'isin': 'GB00BQ84JX13'},
        'PF_XAUUSD': {'symbol': 'PF_XAUUSD', 'type': 'flexible_futures', 'base': 'XAU', 'quote': 'USD', 'category': 'Commodities', 'tradfi': False, 'isin': 'GB00BW1TN221'},
        'PF_WTIOILUSD': {'symbol': 'PF_WTIOILUSD', 'type': 'flexible_futures', 'base': 'WTIOIL', 'quote': 'USD', 'category': 'Commodities', 'tradfi': False, 'isin': 'GB00BW1TMY78'},
        'PF_AAPLXUSD': {'symbol': 'PF_AAPLXUSD', 'type': 'flexible_futures', 'base': 'AAPLx', 'quote': 'USD', 'category': 'xStocks', 'tradfi': False, 'isin': 'GB00BW60FR98'},
        'PF_EURUSD': {'symbol': 'PF_EURUSD', 'type': 'flexible_futures', 'base': 'EUR', 'quote': 'USD', 'category': 'Forex', 'tradfi': True},
        'PF_PAXGUSD': {'symbol': 'PF_PAXGUSD', 'type': 'flexible_futures', 'base': 'PAXG', 'quote': 'USD', 'category': 'Stablecoin', 'tradfi': False, 'isin': 'GB00BQ84KJ42'},
        'PF_CFGUSD': {'symbol': 'PF_CFGUSD', 'type': 'flexible_futures', 'base': 'CFG', 'quote': 'USD', 'category': 'Real-world assets', 'tradfi': False, 'isin': 'GB00BV89RZ92'},
    },
    "deribit": {
        'BTC_USDC-PERPETUAL': {'instrument_name': 'BTC_USDC-PERPETUAL', 'kind': 'future', 'base_currency': 'BTC', 'quote_currency': 'USDC', 'product_group': 'BTC', 'underlying_type': 'crypto', 'settlement_period': 'perpetual'},
        'GOLD_USDC-PERPETUAL': {'instrument_name': 'GOLD_USDC-PERPETUAL', 'kind': 'future', 'base_currency': 'GOLD', 'quote_currency': 'USDC', 'product_group': 'RWA', 'underlying_type': 'commodity', 'settlement_period': 'perpetual'},
        'WTIOIL_USDC-PERPETUAL': {'instrument_name': 'WTIOIL_USDC-PERPETUAL', 'kind': 'future', 'base_currency': 'WTIOIL', 'quote_currency': 'USDC', 'product_group': 'RWA', 'underlying_type': 'commodity', 'settlement_period': 'perpetual'},
        'AAPL_USDC-PERPETUAL': {'instrument_name': 'AAPL_USDC-PERPETUAL', 'kind': 'future', 'base_currency': 'AAPL', 'quote_currency': 'USDC', 'product_group': 'RWA', 'underlying_type': 'equity', 'settlement_period': 'perpetual'},
        'SPY_USDC-PERPETUAL': {'instrument_name': 'SPY_USDC-PERPETUAL', 'kind': 'future', 'base_currency': 'SPY', 'quote_currency': 'USDC', 'product_group': 'RWA', 'underlying_type': 'equity_etf', 'settlement_period': 'perpetual'},
        'PAXG_USDC-PERPETUAL': {'instrument_name': 'PAXG_USDC-PERPETUAL', 'kind': 'future', 'base_currency': 'PAXG', 'quote_currency': 'USDC', 'product_group': 'TIER_2', 'underlying_type': 'crypto', 'settlement_period': 'perpetual'},
    },
    "cryptocom": {
        'BTCUSD-PERP': {'symbol': 'BTCUSD-PERP', 'inst_type': 'PERPETUAL_SWAP', 'display_name': 'BTCUSD Perpetual', 'base_ccy': 'BTC', 'quote_ccy': 'USD', 'underlying_symbol': 'BTCUSD-INDEX', 'product_type': 'DIGITAL_CURRENCIES'},
        'XAUUSD-PERP': {'symbol': 'XAUUSD-PERP', 'inst_type': 'PERPETUAL_SWAP', 'display_name': 'XAUUSD Perpetual', 'base_ccy': 'XAU', 'quote_ccy': 'USD', 'underlying_symbol': 'XAUUSD-INDEX', 'product_type': 'COMMODITIES'},
        'CLUSD-PERP': {'symbol': 'CLUSD-PERP', 'inst_type': 'PERPETUAL_SWAP', 'display_name': 'CLUSD Perpetual', 'base_ccy': 'CL', 'quote_ccy': 'USD', 'underlying_symbol': 'CLUSD-INDEX', 'product_type': 'COMMODITIES'},
        'AAPLUSD-PERP': {'symbol': 'AAPLUSD-PERP', 'inst_type': 'PERPETUAL_SWAP', 'display_name': 'AAPLUSD Perpetual', 'base_ccy': 'AAPL', 'quote_ccy': 'USD', 'underlying_symbol': 'AAPLUSD-INDEX', 'product_type': 'EQUITY'},
        'SPYUSD-PERP': {'symbol': 'SPYUSD-PERP', 'inst_type': 'PERPETUAL_SWAP', 'display_name': 'SPYUSD Perpetual', 'base_ccy': 'SPY', 'quote_ccy': 'USD', 'underlying_symbol': 'SPYUSD-INDEX', 'product_type': 'EQUITY_IND'},
    },
    "weex": {
        'BTCUSDT': {'symbol': 'BTCUSDT', 'baseAsset': 'BTC', 'quoteAsset': 'USDT', 'contractType': 'PERPETUAL', 'underlyingType': 'COIN', 'underlyingSubType': ['POW']},
        'XAUUSDT': {'symbol': 'XAUUSDT', 'baseAsset': 'XAU', 'quoteAsset': 'USDT', 'contractType': 'TRADIFI_PERPETUAL', 'underlyingType': 'Metals', 'underlyingSubType': ['TradFi']},
        'CLUSDT': {'symbol': 'CLUSDT', 'baseAsset': 'CL', 'quoteAsset': 'USDT', 'contractType': 'TRADIFI_PERPETUAL', 'underlyingType': 'Commodities', 'underlyingSubType': ['TradFi']},
        'AAPLUSDT': {'symbol': 'AAPLUSDT', 'baseAsset': 'AAPL', 'quoteAsset': 'USDT', 'contractType': 'TRADIFI_PERPETUAL', 'underlyingType': 'Stocks', 'underlyingSubType': ['TradFi']},
        'EURUSDT': {'symbol': 'EURUSDT', 'baseAsset': 'EUR', 'quoteAsset': 'USDT', 'contractType': 'TRADIFI_PERPETUAL', 'underlyingType': 'Forex', 'underlyingSubType': ['TradFi']},
        'OPENAIUSDT': {'symbol': 'OPENAIUSDT', 'baseAsset': 'OPENAI', 'quoteAsset': 'USDT', 'contractType': 'TRADIFI_PERPETUAL', 'underlyingType': 'Pre-IPO', 'underlyingSubType': ['TradFi']},
    },
    "phemex": {
        'BTCUSDT': {'symbol': 'BTCUSDT', 'type': 'PerpetualV2', 'perpProductSubType': 'Normal', 'contractUnderlyingAssets': 'BTC', 'baseCurrency': 'BTC', 'settleCurrency': 'USDT'},
        'XAUUSDT': {'symbol': 'XAUUSDT', 'type': 'PerpetualV2', 'perpProductSubType': 'TradFi', 'perpProductSubGroup': 'Metals', 'contractUnderlyingAssets': 'XAU', 'baseCurrency': 'XAU', 'settleCurrency': 'USDT'},
        'XTIUSDT': {'symbol': 'XTIUSDT', 'type': 'PerpetualV2', 'perpProductSubType': 'TradFi', 'perpProductSubGroup': 'Commodities', 'contractUnderlyingAssets': 'XTI', 'baseCurrency': 'XTI', 'settleCurrency': 'USDT'},
        'AAPLUSDT': {'symbol': 'AAPLUSDT', 'type': 'PerpetualV2', 'perpProductSubType': 'TradFi', 'perpProductSubGroup': 'Stocks', 'contractUnderlyingAssets': 'AAPL', 'baseCurrency': 'AAPL', 'settleCurrency': 'USDT'},
        'NAS100USDT': {'symbol': 'NAS100USDT', 'type': 'PerpetualV2', 'perpProductSubType': 'TradFi', 'perpProductSubGroup': 'Indices', 'contractUnderlyingAssets': 'NAS100', 'baseCurrency': 'NAS100', 'settleCurrency': 'USDT'},
        'SPACEXUSDT': {'symbol': 'SPACEXUSDT', 'type': 'PerpetualV2', 'perpProductSubType': 'PreMarket', 'contractUnderlyingAssets': 'SPACEX', 'baseCurrency': 'SPACEX', 'settleCurrency': 'USDT'},
    },
    "hibachi": {
        'BTC/USDT-P': {'symbol': 'BTC/USDT-P', 'category': 'CRYPTO', 'underlyingSymbol': 'BTC', 'settlementSymbol': 'USDT', 'status': 'LIVE'},
        'XAG/USDT-P': {'symbol': 'XAG/USDT-P', 'category': 'FX', 'underlyingSymbol': 'XAG', 'settlementSymbol': 'USDT', 'status': 'LIVE'},
        'EUR/USDT-P': {'symbol': 'EUR/USDT-P', 'category': 'FX', 'underlyingSymbol': 'EUR', 'settlementSymbol': 'USDT', 'status': 'LIVE'},
    },
    "bitget_v3": {
        'BTCUSDT': {'symbol': 'BTCUSDT', 'category': 'USDT-FUTURES', 'baseCoin': 'BTC', 'symbolType': 'crypto', 'fullName': 'Bitcoin', 'instrumentType': 'crypto', 'marketRegion': None, 'isin': None, 'isRwa': 'NO'},
        'XAUUSDT': {'symbol': 'XAUUSDT', 'category': 'USDT-FUTURES', 'baseCoin': 'XAU', 'symbolType': 'metal', 'fullName': 'Gold', 'instrumentType': 'metal', 'marketRegion': None, 'isin': None, 'isRwa': 'YES'},
        'CLUSDT': {'symbol': 'CLUSDT', 'category': 'USDT-FUTURES', 'baseCoin': 'CL', 'symbolType': 'commodity', 'fullName': 'West Texas Intermediate', 'instrumentType': 'energy', 'marketRegion': None, 'isin': 'US1941621039', 'isRwa': 'YES'},
        'AAPLUSDT': {'symbol': 'AAPLUSDT', 'category': 'USDT-FUTURES', 'baseCoin': 'AAPL', 'symbolType': 'stock', 'fullName': 'Apple', 'instrumentType': 'stock', 'marketRegion': 'US', 'isin': 'US0378331005', 'isRwa': 'YES'},
        'PAXGUSDT': {'symbol': 'PAXGUSDT', 'category': 'USDT-FUTURES', 'baseCoin': 'PAXG', 'symbolType': 'metal', 'fullName': 'Gold vs US Dollar', 'instrumentType': 'metal', 'marketRegion': None, 'isin': None, 'isRwa': 'YES'},
        'EURUSDUSDT': {'symbol': 'EURUSDUSDT', 'category': 'USDT-FUTURES', 'baseCoin': 'EURUSD', 'symbolType': 'crypto', 'fullName': 'EUR/USD', 'instrumentType': 'fx', 'marketRegion': None, 'isin': None, 'isRwa': 'YES'},
    },
}

# (venue, market id, class, region, underlying symbol, display name)
TRADFI = [
    ("okx", "XAU-USDT-SWAP", "commodity", "", "XAU", "Gold"),
    ("okx", "CL-USDT-SWAP", "commodity", "", "CL", "WTI Crude Oil"),
    ("okx", "AAPL-USDT-SWAP", "stock", "", "AAPL", None),
    ("okx", "OPENAI-USDT-SWAP", "stock", "", "OPENAI", None),
    ("bybit", "XAUUSDT", "commodity", "", "XAU", "Gold"),
    ("bybit", "CLUSDT", "commodity", "", "CL", "WTI Crude Oil"),
    ("bybit", "AAPLUSDT", "stock", "us", "AAPL", "Apple"),
    ("bybit", "BYDUSDT", "stock", "hk", "1211HK", "BYD Company Limited"),
    ("bybit", "KODEX200USDT", "etf", "kr", "069500", "Samsung KODEX 200 ETF"),
    ("bybit", "EURUSDUSDT", "forex", "", "EURUSD", None),
    ("bingx", "NCCOGOLD2USD-USDT", "commodity", "", "XAU", "GOLD(XAU)"),
    ("bingx", "NCCO1OILWTI2USD-USDT", "commodity", "", "OILWTI", "Oil WTI"),
    ("bingx", "NCSKAAPL2USD-USDT", "stock", "", "AAPL", "AAPL"),
    ("bingx", "NCFXEUR2USD-USDT", "forex", "", "EURUSD", "EURUSD"),
    ("bingx", "NCSISP5002USD-USDT", "index", "", "SP500", "SP500"),
    ("blofin", "CL-USDT", "commodity", "", "CL", "WTI Crude Oil"),
    ("blofin", "AAPL-USDT", "stock", "", "AAPL", None),
    ("blofin", "QQQ-USDT", "index", "", "QQQ", None),
    ("gate", "XAU_USDT", "commodity", "", "XAU", "Gold"),
    ("gate", "CL_USDT", "commodity", "", "CL", "WTI Crude Oil"),
    ("gate", "AAPL_USDT", "stock", "", "AAPL", None),
    ("gate", "EURUSD_USDT", "forex", "", "EURUSD", None),
    ("gate", "SPX500_USDT", "index", "", "SPX500", None),
    ("kucoinfutures", "XAGUSDTM", "commodity", "", "XAG", "Silver"),
    ("kucoinfutures", "CLUSDTM", "commodity", "", "CL", "WTI Crude Oil"),
    ("kucoinfutures", "AAPLUSDTM", "stock", "", "AAPL", None),
    ("xt", "xau_usdt", "commodity", "", "XAU", "Gold"),
    ("xt", "cl_usdt", "commodity", "", "CL", "WTI Crude Oil"),
    ("xt", "aaplx_usdt", "stock", "", "AAPLX", "Apple"),
    ("xt", "eur_usdt", "forex", "", "EUR", "EURUSDT"),
    ("xt", "nas100_usdt", "index", "", "NAS100", "Nasdaq 100"),
    ("xt", "openai_usdt", "stock", "", "OPENAI", None),
    ("krakenfutures", "PF_XAUUSD", "commodity", "", "XAU", "Gold"),
    ("krakenfutures", "PF_WTIOILUSD", "commodity", "", "WTIOIL", "WTI Crude Oil"),
    ("krakenfutures", "PF_AAPLXUSD", "stock", "", "AAPLX", None),
    ("krakenfutures", "PF_EURUSD", "forex", "", "EUR", None),
    ("deribit", "GOLD_USDC-PERPETUAL", "commodity", "", "GOLD", "Gold"),
    ("deribit", "WTIOIL_USDC-PERPETUAL", "commodity", "", "WTIOIL", "WTI Crude Oil"),
    ("deribit", "AAPL_USDC-PERPETUAL", "stock", "", "AAPL", None),
    ("deribit", "SPY_USDC-PERPETUAL", "etf", "", "SPY", None),
    ("cryptocom", "XAUUSD-PERP", "commodity", "", "XAU", "Gold"),
    ("cryptocom", "CLUSD-PERP", "commodity", "", "CL", "WTI Crude Oil"),
    ("cryptocom", "AAPLUSD-PERP", "stock", "", "AAPL", None),
    ("cryptocom", "SPYUSD-PERP", "index", "", "SPY", None),
    ("weex", "XAUUSDT", "commodity", "", "XAU", "Gold"),
    ("weex", "CLUSDT", "commodity", "", "CL", "WTI Crude Oil"),
    ("weex", "AAPLUSDT", "stock", "", "AAPL", None),
    ("weex", "EURUSDT", "forex", "", "EUR", None),
    ("weex", "OPENAIUSDT", "stock", "", "OPENAI", None),
    ("phemex", "XAUUSDT", "commodity", "", "XAU", "Gold"),
    ("phemex", "XTIUSDT", "commodity", "", "XTI", "WTI Crude Oil"),
    ("phemex", "AAPLUSDT", "stock", "", "AAPL", None),
    ("phemex", "NAS100USDT", "index", "", "NAS100", None),
    ("hibachi", "XAG/USDT-P", "forex", "", "XAG", None),
    ("hibachi", "EUR/USDT-P", "forex", "", "EUR", None),
]

# Crypto contracts, and contracts the venue itself files as crypto even when
# they track gold (tokenized gold, BloFin's metals) or carry a TradFi-looking
# name (SPX6900).
CRYPTO = [
    ("okx", "BTC-USDT-SWAP"),
    ("bybit", "BTCUSDT"),
    ("bybit", "XAUTUSDT"),
    ("bybit", "SPXUSDT"),
    ("bingx", "BTC-USDT"),
    ("bingx", "XAUT-USDT"),
    ("blofin", "BTC-USDT"),
    ("blofin", "XAU-USDT"),
    ("gate", "BTC_USDT"),
    ("kucoinfutures", "XBTUSDTM"),
    ("xt", "btc_usdt"),
    ("krakenfutures", "PF_XBTUSD"),
    ("krakenfutures", "PF_PAXGUSD"),
    ("krakenfutures", "PF_CFGUSD"),
    ("deribit", "BTC_USDC-PERPETUAL"),
    ("deribit", "PAXG_USDC-PERPETUAL"),
    ("cryptocom", "BTCUSD-PERP"),
    ("weex", "BTCUSDT"),
    ("phemex", "BTCUSDT"),
    ("phemex", "SPACEXUSDT"),
    ("hibachi", "BTC/USDT-P"),
]


def _classify(venue: str, market_id: str, *, market_type: str = "swap.linear", unknown: set[str] | None = None):
    extra = ROWS["bitget_v3"].get(market_id) if venue == "bitget" else None
    return venue_contract_underlying(venue, market_type, ROWS[venue][market_id], extra, unknown=unknown)


@pytest.mark.parametrize(("venue", "market_id", "underlying_class", "region", "symbol", "name"), TRADFI)
def test_venue_marker_files_contract_under_its_underlying(
    venue: str, market_id: str, underlying_class: str, region: str, symbol: str, name: str | None,
) -> None:
    fields = _classify(venue, market_id)

    assert fields is not None
    assert (fields["underlying_class"], fields["underlying_region"], fields["underlying_symbol"]) == (
        underlying_class, region, symbol,
    )
    assert fields.get("display_name") == name
    # The fields are SymbolInfo's own; identity stays crypto (ADR-DATA-002 Q1).
    info = SymbolInfo(symbol=market_id, base_asset="X", quote_asset="USDT", status="TRADING",
                      exchange=venue, market_type="futures", product_type="perpetual", **fields)
    assert info.asset_class == "crypto"
    assert info.to_dict()["underlyingClass"] == underlying_class


@pytest.mark.parametrize(("venue", "market_id"), CRYPTO)
def test_venue_marker_keeps_crypto_contracts_unlabelled(venue: str, market_id: str) -> None:
    assert _classify(venue, market_id) == {}


@pytest.mark.parametrize(("market_id", "underlying_class", "region", "name"), [
    ("XAUUSDT", "commodity", "", "Gold"),
    ("CLUSDT", "commodity", "", "West Texas Intermediate"),
    ("AAPLUSDT", "stock", "us", "Apple"),
    ("PAXGUSDT", "commodity", "", "Gold vs US Dollar"),
    ("EURUSDUSDT", "forex", "", "EUR/USD"),
])
def test_bitget_classifies_from_its_v3_instrument_row(
    market_id: str, underlying_class: str, region: str, name: str,
) -> None:
    fields = _classify("bitget", market_id)

    assert (fields["underlying_class"], fields["underlying_region"], fields["display_name"]) == (
        underlying_class, region, name,
    )
    assert _classify("bitget", "BTCUSDT") == {}


def _with(venue: str, market_id: str, **changes: Any) -> dict[str, Any]:
    row = copy.deepcopy(ROWS[venue][market_id])
    row.update(changes)
    return row


@pytest.mark.parametrize(("venue", "row", "extra", "label"), [
    ("okx", _with("okx", "XAU-USDT-SWAP", instCategory="6"), None, "instCategory=6"),
    ("bybit", _with("bybit", "AAPLUSDT", symbolType="bond"), None, "symbolType=bond"),
    ("bitget", ROWS["bitget"]["XAUUSDT"], None, "isRwa without a v3 instrument"),
    ("bitget", ROWS["bitget"]["XAUUSDT"], {**ROWS["bitget_v3"]["XAUUSDT"], "instrumentType": "bond"},
     "instrumentType=bond"),
    ("blofin", _with("blofin", "AAPL-USDT", assetClass="Bonds"), None, "assetClass=Bonds"),
    ("gate", _with("gate", "AAPL_USDT", contract_type="bonds"), None, "contract_type=bonds"),
    ("kucoinfutures", _with("kucoinfutures", "AAPLUSDTM", assetClass="BOND"), None, "assetClass=BOND"),
    ("xt", _with("xt", "aaplx_usdt", tags=["BOND"]), None, "tags=BOND"),
    ("deribit", _with("deribit", "AAPL_USDC-PERPETUAL", underlying_type="bond"), None, "underlying_type=bond"),
    ("cryptocom", _with("cryptocom", "AAPLUSD-PERP", product_type="BONDS"), None, "product_type=BONDS"),
    ("weex", _with("weex", "AAPLUSDT", underlyingType="Bonds"), None, "underlyingType=Bonds"),
    ("phemex", _with("phemex", "AAPLUSDT", perpProductSubGroup="Bonds"), None, "perpProductSubGroup=Bonds"),
    ("hibachi", _with("hibachi", "EUR/USDT-P", category="BOND"), None, "category=BOND"),
])
def test_traditional_contract_of_unknown_class_is_left_out(
    venue: str, row: dict[str, Any], extra: dict[str, Any] | None, label: str,
) -> None:
    unknown: set[str] = set()

    assert venue_contract_underlying(venue, "swap.linear", row, extra, unknown=unknown) is None
    assert unknown == {label}


def test_sector_fields_treat_new_values_as_crypto() -> None:
    # Kraken's category and Bybit's symbolType also name crypto sectors and
    # zones; a new one there is not a traditional class.
    assert venue_contract_underlying(
        "krakenfutures", "swap.linear", _with("krakenfutures", "PF_XBTUSD", category="Restaking"),
    ) == {}
    assert venue_contract_underlying(
        "bybit", "swap.linear", _with("bybit", "BTCUSDT", symbolType="adventure"),
    ) == {}
    # A BingX asset code outside the four TradFi namespaces stays crypto.
    assert venue_contract_underlying("bingx", "swap.linear", _with("bingx", "BTC-USDT", asset="NCXX1")) == {}


@pytest.mark.parametrize("market_type", ["spot", "option"])
def test_only_contracts_are_classified(market_type: str) -> None:
    assert _classify("okx", "XAU-USDT-SWAP", market_type=market_type) == {}


@pytest.mark.parametrize("market_type", ["futures", "swap", "swap.linear", "future.linear"])
def test_every_contract_family_is_classified(market_type: str) -> None:
    assert _classify("bybit", "XAUUSDT", market_type=market_type)["underlying_class"] == "commodity"


def test_unclassified_venue_keeps_every_contract_unlabelled() -> None:
    assert venue_contract_underlying("mexc", "swap.linear", {"symbol": "XAU_USDT", "baseCoin": "XAU"}) == {}


def _bitget_contract(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row["symbol"], "baseCoin": row["baseCoin"], "quoteCoin": "USDT", "symbolType": "perpetual",
        "symbolStatus": "normal", "isRwa": row["isRwa"], "pricePlace": "2", "priceEndStep": "1",
        "volumePlace": "2", "sizeMultiplier": "0.01", "minTradeNum": "0.01", "minTradeUSDT": "5",
        "supportMarginCoins": ["USDT"], "maxLever": "100", "minLever": "1", "launchTime": "",
        "deliveryTime": "", "deliveryStartTime": "", "deliveryPeriod": "", "offTime": "-1",
        "limitOpenTime": "-1", "fundInterval": "4", "makerFeeRate": "0.0002", "takerFeeRate": "0.0006",
    }


def _bitget_catalog(
    monkeypatch: Any, market_type: str, v3_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    from ccxt.async_support import bitget

    exchange = bitget({"options": {"defaultType": "swap", "fetchMarkets": {"types": ["swap"]}}})
    requests: list[dict[str, Any]] = []

    async def contracts(params: dict[str, Any]) -> dict[str, Any]:
        rows = [_bitget_contract(row) for row in ROWS["bitget"].values()]
        return {"code": "00000", "data": rows if params["productType"] == "USDT-FUTURES" else []}

    async def load_markets(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        exchange.set_markets(await exchange.fetch_default_markets({}))
        return exchange.markets

    monkeypatch.setattr(exchange, "publicMixGetV2MixMarketContracts", contracts)

    async def instruments(params: dict[str, Any]) -> dict[str, Any]:
        requests.append(params)
        return {"code": "00000", "msg": "success", "data": v3_rows}

    monkeypatch.setattr(exchange, "load_markets", load_markets)
    monkeypatch.setattr(exchange, "publicUtaGetV3MarketInstruments", instruments)
    monkeypatch.setattr("app.exchanges.ccxt_ext.generic._create_exchange", lambda *_args, **_kwargs: exchange)
    symbols = asyncio.run(load_ccxt_symbols(
        get_ccxt_catalog_entry("bitget"), market_type, IngestionConfig(proxy_mode="none"),
    ))
    return {item.symbol: item.to_dict() for item in symbols}, requests


def test_bitget_catalog_asks_the_v3_instrument_list_for_classes(monkeypatch: Any) -> None:
    rows, requests = _bitget_catalog(monkeypatch, "futures", list(ROWS["bitget_v3"].values()))

    assert requests == [{"category": "USDT-FUTURES"}]
    assert rows["XAU/USDT:USDT"]["underlyingClass"] == "commodity"
    assert rows["XAU/USDT:USDT"]["displayName"] == "Gold"
    assert (rows["AAPL/USDT:USDT"]["underlyingClass"], rows["AAPL/USDT:USDT"]["underlyingRegion"]) == ("stock", "us")
    assert rows["CL/USDT:USDT"]["assetClass"] == "crypto"
    assert "underlyingClass" not in rows["BTC/USDT:USDT"]


def test_bitget_rwa_contract_missing_from_v3_is_left_out(monkeypatch: Any, caplog: Any) -> None:
    caplog.set_level(logging.WARNING, logger="candlescope.exchange.underlyings")
    v3_rows = [row for row in ROWS["bitget_v3"].values() if row["symbol"] != "CLUSDT"]

    rows, _requests = _bitget_catalog(monkeypatch, "futures", v3_rows)

    assert "CL/USDT:USDT" not in rows
    assert rows["XAU/USDT:USDT"]["underlyingClass"] == "commodity"
    assert "isRwa without a v3 instrument" in caplog.text


def test_bitget_inverse_catalog_skips_the_v3_request(monkeypatch: Any) -> None:
    _rows, requests = _bitget_catalog(monkeypatch, "swap.inverse", list(ROWS["bitget_v3"].values()))

    assert requests == []


def test_hyperliquid_catalog_loads_every_hip3_dex() -> None:
    """CCXT stops at ``hip3.limit - 1`` dexes; Hyperliquid listed ten on 2026-11-26."""
    names = ["xyz", "flx", "vntl", "hyna", "km", "abcd", "cash", "para", "mkts", "io"]
    exchange = _create_exchange(
        get_ccxt_catalog_entry("hyperliquid"), IngestionConfig(proxy_mode="none"),
        market_type="swap.linear", websocket=False,
    )
    requested: list[str] = []

    async def post_info(request: dict[str, Any]) -> Any:
        if request["type"] == "perpDexs":
            return [None, *({"name": name, "fullName": name.upper()} for name in names)]
        requested.append(request["dex"])
        universe = [{"name": f"{request['dex']}:GOLD", "szDecimals": 4, "maxLeverage": 25}]
        return [{"universe": universe, "collateralToken": 0}, [{"markPx": "3576.5", "dayNtlVlm": "1"}]]

    exchange.publicPostInfo = post_info

    async def run() -> list[dict[str, Any]]:
        try:
            return await exchange.fetch_hip3_markets()
        finally:
            await close_ccxt_exchange(exchange)

    markets = asyncio.run(run())

    assert exchange.options["fetchMarkets"]["hip3"]["limit"] == HYPERLIQUID_HIP3_DEX_LIMIT
    assert exchange.options["fetchMarkets"]["types"] == ["spot", "swap", "hip3"]
    assert requested == names
    assert "IO-GOLD/USDC:USDC" in {market["symbol"] for market in markets}
