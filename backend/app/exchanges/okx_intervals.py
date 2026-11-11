"""The UTC candle protocol used by CandleScope's OKX series.

Keep REST parameters, WS subscriptions and reverse lookup on one mapping.
The unsuffixed OKX 6H+ channels have different boundaries.
"""

OKX_UTC_INTERVALS = {
    "1s": "1s", "1m": "1m", "3m": "3m", "5m": "5m",
    "15m": "15m", "30m": "30m", "1h": "1H", "2h": "2H", "4h": "4H",
    "6h": "6Hutc", "12h": "12Hutc", "1d": "1Dutc", "2d": "2Dutc",
    "3d": "3Dutc", "1w": "1Wutc", "1M": "1Mutc", "3M": "3Mutc",
}

# The contract statistics endpoint exposes a different set from candles.
OKX_OI_HISTORY_PERIODS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")
OKX_OI_HISTORY_LIMIT = 100
OKX_FUNDING_HISTORY_LIMIT = 400


def okx_utc_interval(interval: str) -> str:
    try:
        return OKX_UTC_INTERVALS[interval]
    except KeyError:
        raise ValueError(f"Unsupported native OKX UTC interval: {interval!r}") from None
