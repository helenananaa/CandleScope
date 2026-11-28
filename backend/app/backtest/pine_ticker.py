"""Pine ticker ids name a chart as ``EXCHANGE:SYMBOL``.

The symbol itself may contain ``:`` (Twelve Data's ``AAPL:NASDAQ``, ADR-DATA-002
D1), so only the first ``:`` separates the exchange, as the Pine indicator host
reads it.
"""


def pine_ticker_symbol(tickerid: str) -> str:
    """The exchange symbol of a ticker id; an unprefixed id is already the symbol."""
    _exchange, separator, symbol = tickerid.partition(":")
    return symbol if separator else tickerid


def venue_pine_ticker(exchange: str, market_type: str, symbol: str) -> str:
    """The venue's Pine name for a storage symbol (ADR-DATA-002 D3c)."""
    from app.exchanges.roles import venue_symbol_normalizer

    naming = getattr(venue_symbol_normalizer(exchange), "pine_ticker", None)
    return naming(symbol, market_type) if callable(naming) else symbol


def venue_storage_symbol(exchange: str, market_type: str, ticker: str) -> str:
    """The storage symbol a venue's Pine ticker names."""
    from app.exchanges.roles import venue_symbol_normalizer

    naming = getattr(venue_symbol_normalizer(exchange), "storage_symbol_from_pine", None)
    return naming(ticker, market_type) if callable(naming) else ticker
