"""Immutable semantic series identity shared across DataEngine owners.

DataManager re-exports this same type for existing consumers. The key owns no
cache, query, storage, scheduler or aggregation behavior.
"""
from __future__ import annotations
from dataclasses import dataclass
from app.data_engine.interval_policy import parse_interval_spec
from app.data_engine.series_identity import (
    DEFAULT_ASSET_CLASS, DEFAULT_PRICE_ADJUSTMENT, DEFAULT_SERIES_VARIANT,
    DEFAULT_SESSION_VARIANT, DEFAULT_VOLUME_SEMANTICS, KlineSeriesIdentity,
)


@dataclass(frozen=True, slots=True)
class SeriesKey:
    """Immutable identifier for one routed and semantically distinct series.

    Usable as a dict key and set member.

    Examples::

        key = SeriesKey("BTCUSDT", "1m")
        key = SeriesKey("BTCUSDT", "1m", market_type="futures")
        cache[key] = bars
    """
    symbol: str
    interval: str
    exchange: str = "binance"
    market_type: str = "spot"  # "spot" or "futures"
    provider_id: str | None = None
    venue: str | None = None
    asset_class: str = DEFAULT_ASSET_CLASS
    series_variant: str = DEFAULT_SERIES_VARIANT
    price_adjustment: str = DEFAULT_PRICE_ADJUSTMENT
    session_variant: str = DEFAULT_SESSION_VARIANT
    volume_semantics: str = DEFAULT_VOLUME_SEMANTICS

    @classmethod
    def create(
        cls,
        symbol: str,
        interval: str,
        *,
        exchange: str = "binance",
        market_type: str = "spot",
        identity: KlineSeriesIdentity | None = None,
    ) -> "SeriesKey":
        resolved = identity or KlineSeriesIdentity.for_exchange(exchange)
        return cls(
            symbol,
            interval,
            exchange=exchange,
            market_type=market_type,
            **resolved.to_dict(),
        )

    def __post_init__(self) -> None:
        # Normalize symbol to uppercase
        object.__setattr__(self, "symbol", self.symbol.upper().strip())
        requested_interval = self.interval.strip()
        interval_spec = parse_interval_spec(requested_interval)
        object.__setattr__(
            self,
            "interval",
            interval_spec.canonical if interval_spec is not None else requested_interval,
        )
        object.__setattr__(self, "exchange", self.exchange.strip().lower())
        object.__setattr__(self, "market_type", self.market_type.strip().lower())
        identity = KlineSeriesIdentity.for_exchange(
            self.exchange,
            provider_id=self.provider_id,
            venue=self.venue,
            asset_class=self.asset_class,
            series_variant=self.series_variant,
            price_adjustment=self.price_adjustment,
            session_variant=self.session_variant,
            volume_semantics=self.volume_semantics,
        )
        for field_name, value in identity.to_dict().items():
            object.__setattr__(self, field_name, value)

    @property
    def identity(self) -> KlineSeriesIdentity:
        return KlineSeriesIdentity(
            provider_id=str(self.provider_id),
            venue=str(self.venue),
            asset_class=self.asset_class,
            series_variant=self.series_variant,
            price_adjustment=self.price_adjustment,
            session_variant=self.session_variant,
            volume_semantics=self.volume_semantics,
        )

    @property
    def topic(self) -> str:
        """Event bus topic string, e.g. ``'BTCUSDT@1m'`` or ``'okx:futures:BTCUSDT@1m'``."""
        base = f"{self.symbol}@{self.interval}"
        prefixes: list[str] = []
        if self.exchange != "binance":
            prefixes.append(self.exchange)
        if self.market_type != "spot":
            prefixes.append(self.market_type)
        routed = f"{':'.join(prefixes)}:{base}" if prefixes else base
        if not self.identity.is_legacy_default_for(self.exchange):
            semantic = ":".join(self.identity.storage_values)
            return f"series:{semantic}:{routed}"
        if prefixes:
            return routed
        return base

    def __str__(self) -> str:
        return self.topic

