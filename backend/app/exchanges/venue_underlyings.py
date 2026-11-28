"""What a crypto-venue contract tracks, when it tracks a traditional market.

Crypto venues list perpetuals on gold, crude oil, stocks, indices and currency
pairs next to their crypto perpetuals. They trade on the same endpoints,
streams and archives, so they stay ordinary crypto-venue series (ADR-DATA-002
Q1). The underlying fields only say what the contract tracks, which the symbol
search uses for grouping and the "contract price" label. Both the native
Binance catalog and the CCXT catalog classify through here.

Each venue is classified from the marker it publishes in its own market rows,
never from the symbol name. A venue without a reliable marker is not listed
here, and its contracts stay unlabelled. When a venue marks a contract as
traditional but the class is one we do not know, the contract is left out of
the catalog and logged instead of being shown as crypto.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("candlescope.exchange.underlyings")

BINANCE_TRADFI_CONTRACT_TYPE = "TRADIFI_PERPETUAL"

# CCXT lists the same USD-M contracts under both "binance" and "binanceusdm".
_BINANCE_USDM_SOURCES = frozenset({"binance", "binanceusdm"})
_CONTRACT_FAMILIES = frozenset({"futures", "swap", "future"})

_BINANCE_TRADFI_UNDERLYINGS: dict[str, tuple[str, str]] = {
    "EQUITY": ("stock", "us"),
    "HK_EQUITY": ("stock", "hk"),
    "KR_EQUITY": ("stock", "kr"),
    "CN_EQUITY": ("stock", "cn"),
    # Pre-IPO company contracts: no listed share or region to point at.
    "PREMARKET": ("stock", ""),
    "COMMODITY": ("commodity", ""),
    "FX": ("forex", ""),
}

# Commodity contracts use exchange codes as base assets; a name makes "gold" or
# "crude" findable. Stocks already use their ticker. The class always comes
# from the venue; this table only names a code the venue already filed as a
# commodity.
_COMMODITY_NAMES = {
    **dict.fromkeys(("XAU", "GOLD"), "Gold"),
    **dict.fromkeys(("XAG", "SILVER"), "Silver"),
    **dict.fromkeys(("XPT", "PLATINUM"), "Platinum"),
    **dict.fromkeys(("XPD", "PALLADIUM"), "Palladium"),
    **dict.fromkeys(("COPPER", "XCU"), "Copper"),
    **dict.fromkeys(("CL", "WTI", "WTIOIL", "USOIL", "XTI"), "WTI Crude Oil"),
    **dict.fromkeys(("BZ", "BRENT", "BRENTOIL", "UKOIL", "XBR"), "Brent Crude Oil"),
    **dict.fromkeys(("NATGAS", "NG", "NGAS"), "Natural Gas"),
}


@dataclass(frozen=True, slots=True)
class _Unknown:
    """A contract the venue marks as traditional, with a class we do not know."""

    label: str


_Result = dict[str, str] | _Unknown
_CRYPTO: dict[str, str] = {}


def _underlying(
    underlying_class: str,
    region: str = "",
    *,
    symbol: str,
    name: str = "",
    base: str = "",
) -> dict[str, str]:
    """``name`` is the venue's own name; it is dropped when it only repeats the
    base asset the search already shows (``base``, default ``symbol``)."""
    symbol = str(symbol or "").strip().upper()
    name = " ".join(str(name or "").split())
    if name.upper() == str(base or symbol).strip().upper():
        name = ""
    if not name and underlying_class == "commodity":
        name = _COMMODITY_NAMES.get(symbol, "")
    fields = {
        "underlying_class": underlying_class,
        "underlying_region": str(region or "").strip().lower(),
        "underlying_symbol": symbol,
    }
    if name:
        fields["display_name"] = name
    return fields


def _text(info: Mapping[str, Any], key: str) -> str:
    return str(info.get(key) or "").strip()


def binance_futures_underlying(info: Mapping[str, Any]) -> dict[str, str] | None:
    """SymbolInfo fields for one Binance USD-M ``exchangeInfo`` row.

    Returns ``{}`` for a crypto contract, the underlying fields for a known
    TradFi contract, and ``None`` for a TradFi contract whose underlyingType is
    unknown: such a row is left out rather than shown as crypto.
    """
    result = _binance_usdm(info)
    return None if isinstance(result, _Unknown) else result


def _binance_usdm(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    if info.get("contractType") != BINANCE_TRADFI_CONTRACT_TYPE:
        return _CRYPTO
    underlying_type = _text(info, "underlyingType").upper()
    underlying = _BINANCE_TRADFI_UNDERLYINGS.get(underlying_type)
    if underlying is None:
        return _Unknown(underlying_type)
    return _underlying(*underlying, symbol=_text(info, "baseAsset"))


# OKX ``instCategory``: 1 crypto, 3 equities, 4 commodities, 5 FX, 6 debt.
_OKX_CATEGORIES = {"3": "stock", "4": "commodity", "5": "forex"}


def okx_underlying(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    category = _text(info, "instCategory")
    if category in {"", "1"}:
        return _CRYPTO
    if category not in _OKX_CATEGORIES:
        return _Unknown(f"instCategory={category}")
    family = _text(info, "instFamily") or _text(info, "uly") or _text(info, "instId")
    return _underlying(_OKX_CATEGORIES[category], symbol=family.split("-")[0])


# Bybit ``symbolType``; crypto rows have "" or a crypto zone such as
# "innovation". Stocks and ETFs also carry ``marketRegion``.
_BYBIT_TYPES = {"stock": "stock", "etf": "etf", "commodity": "commodity", "forex": "forex"}


def bybit_underlying(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    symbol_type = _text(info, "symbolType")
    region = _text(info, "marketRegion")
    underlying_class = _BYBIT_TYPES.get(symbol_type.lower())
    if underlying_class is None:
        return _Unknown(f"symbolType={symbol_type}") if region else _CRYPTO
    return _underlying(
        underlying_class,
        region,
        symbol=_text(info, "underlyingTicker") or _text(info, "baseCoin"),
        name=_text(info, "fullName"),
    )


# Bitget's v2 contract list, which CCXT loads, only says ``isRwa``. The v3
# instrument list (``extra``) gives the class and the market region.
_BITGET_TYPES = {
    "stock": "stock",
    "etf": "etf",
    "index": "index",
    "metal": "commodity",
    "energy": "commodity",
    "commodity": "commodity",
    "fx": "forex",
}


def bitget_underlying(info: Mapping[str, Any], extra: Mapping[str, Any] | None = None) -> _Result:
    rwa = _text(info, "isRwa").upper() == "YES"
    instrument_type = _text(extra, "instrumentType").lower() if extra else ""
    if instrument_type in {"", "crypto"}:
        if rwa and not extra:
            return _Unknown("isRwa without a v3 instrument")
        return _CRYPTO
    underlying_class = _BITGET_TYPES.get(instrument_type)
    if underlying_class is None:
        return _Unknown(f"instrumentType={instrument_type}")
    return _underlying(
        underlying_class,
        _text(extra, "marketRegion"),
        symbol=_text(info, "baseCoin"),
        name=_text(extra, "fullName"),
    )


# BingX publishes no class field. Its TradFi contracts live in an asset-code
# namespace of their own: NC + class + underlying + "2" + currency, such as
# NCSKAAPL2USD or NCCOGOLD2USD; the display name drops the prefix.
_BINGX_PREFIXES = {"NCSK": "stock", "NCCO": "commodity", "NCFX": "forex", "NCSI": "index"}


def bingx_underlying(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    asset = _text(info, "asset").upper()
    underlying_class = _BINGX_PREFIXES.get(asset[:4])
    if underlying_class is None or len(asset) <= 4:
        return _CRYPTO
    display = _text(info, "displayName")
    quote = _text(info, "currency")
    if quote and display.upper().endswith(f"-{quote.upper()}"):
        display = display[: -len(quote) - 1]
    display = display.strip()
    code = display[display.find("(") + 1 : display.find(")")] if "(" in display and ")" in display else ""
    return _underlying(
        underlying_class,
        symbol=(code or display).replace(" ", ""),
        name=display,
        base=asset,
    )


def _class_field(
    key: str,
    classes: Mapping[str, str],
    crypto: frozenset[str],
    *,
    tradfi_unknown: bool = True,
) -> Callable[[Mapping[str, Any], Mapping[str, Any] | None], _Result]:
    """Classifier for a venue that files every contract under one field.

    An unknown value is a new traditional class when the field is the venue's
    asset class (``tradfi_unknown``), and a crypto sector when the field mixes
    crypto sectors with traditional classes.
    """

    def classify(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
        value = _text(info, key)
        if not value or value in crypto:
            return _CRYPTO
        underlying_class = classes.get(value)
        if underlying_class is None:
            return _Unknown(f"{key}={value}") if tradfi_unknown else _CRYPTO
        return _underlying(underlying_class, symbol=_base(info))

    return classify


_BASE_KEYS = ("baseCurrency", "baseCoin", "baseAsset", "base_currency", "base_ccy", "underlyingSymbol", "base")


def _base(info: Mapping[str, Any]) -> str:
    for key in _BASE_KEYS:
        if value := _text(info, key):
            return value
    return ""


def _gate_base(info: Mapping[str, Any]) -> str:
    return _text(info, "name").split("_")[0]


def gate_underlying(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    # Gate ``contract_type``: "" for crypto, otherwise the traditional class.
    contract_type = _text(info, "contract_type")
    if not contract_type:
        return _CRYPTO
    underlying_class = {
        "stocks": "stock",
        "indices": "index",
        "metals": "commodity",
        "commodities": "commodity",
        "forex": "forex",
    }.get(contract_type)
    if underlying_class is None:
        return _Unknown(f"contract_type={contract_type}")
    return _underlying(underlying_class, symbol=_gate_base(info))


def xt_underlying(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    # XT ``tags`` exist only on traditional contracts; "Pre-M" marks a pre-IPO stock.
    tags = info.get("tags")
    if not isinstance(tags, list) or not tags:
        return _CRYPTO
    tag_set = {str(tag).strip().upper() for tag in tags}
    for tag, underlying_class in (
        ("STOCK", "stock"),
        ("INDEX", "index"),
        ("FOREX", "forex"),
        ("METAL", "commodity"),
        ("COMMODITY", "commodity"),
    ):
        if tag in tag_set:
            return _underlying(underlying_class, symbol=_text(info, "baseCoin"), name=_text(info, "businessName"))
    return _Unknown("tags=" + ",".join(sorted(tag_set)))


def weex_underlying(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    # WEEX copies Binance's layout: contractType TRADIFI_PERPETUAL + underlyingType.
    if info.get("contractType") != BINANCE_TRADFI_CONTRACT_TYPE:
        return _CRYPTO
    underlying_type = _text(info, "underlyingType")
    underlying_class = {
        "Stocks": "stock",
        "Pre-IPO": "stock",
        "Indices": "index",
        "Metals": "commodity",
        "Commodities": "commodity",
        "Forex": "forex",
    }.get(underlying_type)
    if underlying_class is None:
        return _Unknown(f"underlyingType={underlying_type}")
    return _underlying(underlying_class, symbol=_text(info, "baseAsset"))


def phemex_underlying(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    # Phemex: perpProductSubType TradFi, then perpProductSubGroup. Its separate
    # "PreMarket" sub type also lists pre-launch tokens, so it stays crypto.
    if _text(info, "perpProductSubType") != "TradFi":
        return _CRYPTO
    group = _text(info, "perpProductSubGroup")
    underlying_class = {
        "Stocks": "stock",
        "Indices": "index",
        "Metals": "commodity",
        "Commodities": "commodity",
        "Forex": "forex",
    }.get(group)
    if underlying_class is None:
        return _Unknown(f"perpProductSubGroup={group}")
    return _underlying(underlying_class, symbol=_text(info, "contractUnderlyingAssets") or _base(info))


def deribit_underlying(info: Mapping[str, Any], _extra: Mapping[str, Any] | None = None) -> _Result:
    underlying_type = _text(info, "underlying_type")
    if underlying_type in {"", "crypto", "crypto_index"}:
        return _CRYPTO
    underlying_class = {
        "equity": "stock",
        "preipo": "stock",
        "equity_etf": "etf",
        "commodity": "commodity",
    }.get(underlying_type)
    if underlying_class is None:
        if _text(info, "product_group") == "RWA":
            return _Unknown(f"underlying_type={underlying_type}")
        return _CRYPTO
    return _underlying(underlying_class, symbol=_text(info, "base_currency"))


_VENUES: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any] | None], _Result]] = {
    "okx": okx_underlying,
    "bybit": bybit_underlying,
    "bitget": bitget_underlying,
    "bingx": bingx_underlying,
    # BloFin files gold, silver, platinum, palladium and copper under "Crypto";
    # only what it marks as traditional is labelled.
    "blofin": _class_field(
        "assetClass",
        {"Stocks": "stock", "Commodities": "commodity", "Indices": "index"},
        frozenset({"Crypto"}),
    ),
    "gate": gate_underlying,
    "kucoinfutures": _class_field(
        "assetClass",
        {"STOCK": "stock", "METAL": "commodity", "COMMODITY": "commodity"},
        frozenset({"CRYPTO"}),
    ),
    "xt": xt_underlying,
    # Kraken's category mixes crypto sectors (DeFi, Meme, Stablecoin, ...)
    # with traditional classes; xStocks are perpetuals on tokenized shares.
    "krakenfutures": _class_field(
        "category",
        {
            "xStocks": "stock",
            "Equities": "stock",
            "Pre-IPO": "stock",
            "Commodities": "commodity",
            "Forex": "forex",
            "Indices": "index",
        },
        frozenset(),
        tradfi_unknown=False,
    ),
    "deribit": deribit_underlying,
    "cryptocom": _class_field(
        "product_type",
        {
            "EQUITY": "stock",
            "PRE_IPO": "stock",
            "EQUITY_IND": "index",
            "COMMODITIES": "commodity",
        },
        frozenset({"DIGITAL_CURRENCIES"}),
    ),
    "weex": weex_underlying,
    "phemex": phemex_underlying,
    "hibachi": _class_field("category", {"FX": "forex"}, frozenset({"CRYPTO"})),
}

# Venues whose market list lacks the class; the CCXT catalog asks for these
# rows once per load and passes the matching one as ``extra``.
VENUES_WITH_EXTRA_ROWS = frozenset({"bitget"})


def venue_contract_underlying(
    exchange_id: str,
    market_type: str,
    info: Any,
    extra: Mapping[str, Any] | None = None,
    *,
    unknown: set[str] | None = None,
) -> dict[str, str] | None:
    """Underlying fields for a venue's raw contract row.

    Returns ``{}`` for a crypto contract or an unclassified venue, the
    underlying fields for a known traditional contract, and ``None`` for a
    contract the venue marks as traditional with a class we do not know; its
    marker is added to ``unknown`` for the catalog's warning.
    """
    if not isinstance(info, Mapping):
        return {}
    if str(market_type or "").split(".", 1)[0] not in _CONTRACT_FAMILIES:
        return {}
    if exchange_id in _BINANCE_USDM_SOURCES:
        if market_type not in {"futures", "swap.linear"}:
            return {}
        classify = _binance_usdm
    else:
        classify = _VENUES.get(exchange_id)
        if classify is None:
            return {}
    result = classify(info, extra)
    if isinstance(result, _Unknown):
        if unknown is not None:
            unknown.add(result.label)
        return None
    return dict(result)


def warn_unknown_underlyings(exchange_id: str, unknown: set[str]) -> None:
    if unknown:
        logger.warning(
            "%s catalog left out TradFi contracts with unknown underlying type: %s",
            exchange_id,
            ", ".join(sorted(unknown)),
        )


__all__ = [
    "BINANCE_TRADFI_CONTRACT_TYPE",
    "VENUES_WITH_EXTRA_ROWS",
    "binance_futures_underlying",
    "bingx_underlying",
    "bitget_underlying",
    "bybit_underlying",
    "deribit_underlying",
    "gate_underlying",
    "okx_underlying",
    "phemex_underlying",
    "venue_contract_underlying",
    "warn_unknown_underlyings",
    "weex_underlying",
    "xt_underlying",
]
