"""Compatibility imports for venue policies; acquisition is owned by CcxtProvider."""
from .venue_strategies import CcxtPrimaryNormalizer as CcxtPrimaryNormalizer
from .venue_strategies import OkxCombinedSummaryProfile as OkxCombinedSummaryProfile


def create_binance_ccxt_plugin():
    from .provider import CcxtProvider
    return CcxtProvider().bind("binance")


def create_okx_ccxt_plugin():
    from .provider import CcxtProvider
    return CcxtProvider().bind("okx")
