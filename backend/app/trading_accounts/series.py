"""The kline series a practice market follows (ADR-DATA-002 D1c).

A ledger instrument stays ``(exchange, market_type, symbol)``. Each one follows
a single series: the exchange's own (stored as NULL, so ledgers written before
D1c read unchanged) or a provider series such as Twelve Data's AAPL:NASDAQ
regular session. Orders, fills and the practice cursor record it as canonical
JSON so matching, marks and excursions read the bars the trader saw.
"""
from __future__ import annotations

import json
from typing import Any

from app.data_engine.series_identity import KlineSeriesIdentity, requested_series_identity

from .models import invalid


def requested_series(exchange: str, value: Any) -> KlineSeriesIdentity | None:
    """The optional ``identity`` of an order or fill; the exchange's own is ``None``."""
    try:
        return requested_series_identity(exchange, value)
    except ValueError as exc:
        raise invalid(f"identity is invalid: {exc}") from exc


def series_text(series: KlineSeriesIdentity | None) -> str | None:
    if series is None:
        return None
    return json.dumps(series.to_dict(), sort_keys=True, separators=(",", ":"))


def stored_series(exchange: str, text: str | None) -> KlineSeriesIdentity | None:
    if not text:
        return None
    return requested_series_identity(exchange, json.loads(text))


def series_view(text: str | None) -> dict[str, Any]:
    """``{"identity": {...}}`` for a provider series; nothing for the exchange's own."""
    return {"identity": json.loads(text)} if text else {}


def market_series(series: KlineSeriesIdentity | None) -> dict[str, Any]:
    """Keyword arguments for market reads; none for the exchange's own series."""
    return {} if series is None else {"series_identity": series}
