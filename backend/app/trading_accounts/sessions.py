"""Trading sessions of a practice market (ADR-DATA-002 D2).

A market on a session calendar, such as Twelve Data's US equities on XNYS,
has no candles while it is closed. The matcher and valuation ask its calendar
whether the market traded in between, so a closure is not read as missing
data or a stale price. Always-open markets have no session calendar (None)
and keep the plain minute grid.
"""
from __future__ import annotations

import logging
from typing import Any

from app.data_engine.history.calendar import TradingCalendar

from .series import market_series

logger = logging.getLogger("trading_accounts.practice")

INTERVAL = "1m"


def market_calendar(market: Any, instrument: tuple[str, str, str], series: Any) -> TradingCalendar | None:
    """The session calendar ``market`` knows for ``instrument``; None when it has none."""
    calendar = getattr(market, "calendar", None)
    if calendar is None:
        return None
    try:
        return calendar(*instrument, **market_series(series))
    except Exception:
        logger.debug("Practice calendar unavailable for %s", instrument, exc_info=True)
        return None


def closed_between(calendar: TradingCalendar | None, start_ms: int, end_ms: int) -> bool:
    """Whether ``calendar`` has no trading minute in ``[start_ms, end_ms]``."""
    if calendar is None:
        return False
    if end_ms < start_ms:
        return True
    try:
        return calendar.first_expected_open(start_ms, end_ms, INTERVAL) is None
    except (LookupError, ValueError):
        return False
