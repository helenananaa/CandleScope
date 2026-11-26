"""Pine ticker ids name a chart as ``EXCHANGE:SYMBOL``.

The symbol itself may contain ``:`` (Twelve Data's ``AAPL:NASDAQ``, ADR-DATA-002
D1), so only the first ``:`` separates the exchange, as the Pine indicator host
reads it.
"""


def pine_ticker_symbol(tickerid: str) -> str:
    """The exchange symbol of a ticker id; an unprefixed id is already the symbol."""
    _exchange, separator, symbol = tickerid.partition(":")
    return symbol if separator else tickerid
