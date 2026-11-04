"""Default-series empty-window evidence participates in the D126 ledger.

These tables describe verified absence, not OHLCV rows. Their changes still
invalidate history views and must obey the same acquisition/deletion fences.
"""
from __future__ import annotations

from .revisions import RevisionStore, series_values


def default_identity_sql(alias: str, exchange: str) -> str:
    return (f"{alias}.provider_id={exchange} AND {alias}.venue={exchange} "
            f"AND {alias}.asset_class='crypto' AND {alias}.series_variant='native' "
            f"AND {alias}.price_adjustment='raw' AND {alias}.session_variant='continuous' "
            f"AND {alias}.volume_semantics='base_asset'")




def version(exchange, market_type, symbol, interval):
    from .klines_repo import _connect
    return RevisionStore(_connect).read_versions((series_values(symbol, interval, exchange, market_type),))[1][0]
