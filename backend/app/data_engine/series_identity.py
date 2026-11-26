"""Canonical identity for one durable K-line series.

``exchange + market_type + symbol + interval`` is retained as the routing
identity used by existing CandleScope integrations.  Traditional-finance
feeds need additional dimensions because the same instrument and timestamp
can legitimately have different vendor, adjustment, session, and volume
semantics.  This module owns those additive dimensions and their legacy
defaults so cache, storage, and API layers do not invent incompatible values.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


DEFAULT_ASSET_CLASS = "crypto"
DEFAULT_SERIES_VARIANT = "native"
DEFAULT_PRICE_ADJUSTMENT = "raw"
DEFAULT_SESSION_VARIANT = "continuous"
DEFAULT_VOLUME_SEMANTICS = "base_asset"
SERIES_IDENTITY_METADATA_KEY = "series_identity"


def _normalized_dimension(value: object, *, default: str, field_name: str) -> str:
    normalized = str(value if value is not None else default).strip().lower()
    if not normalized:
        normalized = default
    if len(normalized) > 64:
        raise ValueError(f"{field_name} must not exceed 64 characters")
    return normalized


@dataclass(frozen=True, slots=True)
class KlineSeriesIdentity:
    """Vendor and semantic dimensions that distinguish durable bar series.

    ``provider_id`` identifies the dataset vendor, while ``venue`` identifies
    where the instrument trades.  They intentionally remain separate: a
    consolidated feed can serve several venues and two vendors can publish
    different revisions of the same venue's bars.
    """

    provider_id: str
    venue: str
    asset_class: str = DEFAULT_ASSET_CLASS
    series_variant: str = DEFAULT_SERIES_VARIANT
    price_adjustment: str = DEFAULT_PRICE_ADJUSTMENT
    session_variant: str = DEFAULT_SESSION_VARIANT
    volume_semantics: str = DEFAULT_VOLUME_SEMANTICS

    def __post_init__(self) -> None:
        for field_name, default in (
            ("provider_id", "unknown"),
            ("venue", "unknown"),
            ("asset_class", DEFAULT_ASSET_CLASS),
            ("series_variant", DEFAULT_SERIES_VARIANT),
            ("price_adjustment", DEFAULT_PRICE_ADJUSTMENT),
            ("session_variant", DEFAULT_SESSION_VARIANT),
            ("volume_semantics", DEFAULT_VOLUME_SEMANTICS),
        ):
            object.__setattr__(
                self,
                field_name,
                _normalized_dimension(
                    getattr(self, field_name),
                    default=default,
                    field_name=field_name,
                ),
            )

    @classmethod
    def for_exchange(
        cls,
        exchange: str,
        *,
        provider_id: str | None = None,
        venue: str | None = None,
        asset_class: str = DEFAULT_ASSET_CLASS,
        series_variant: str = DEFAULT_SERIES_VARIANT,
        price_adjustment: str = DEFAULT_PRICE_ADJUSTMENT,
        session_variant: str = DEFAULT_SESSION_VARIANT,
        volume_semantics: str = DEFAULT_VOLUME_SEMANTICS,
    ) -> "KlineSeriesIdentity":
        normalized_exchange = _normalized_dimension(
            exchange,
            default="unknown",
            field_name="exchange",
        )
        return cls(
            provider_id=provider_id or normalized_exchange,
            venue=venue or normalized_exchange,
            asset_class=asset_class,
            series_variant=series_variant,
            price_adjustment=price_adjustment,
            session_variant=session_variant,
            volume_semantics=volume_semantics,
        )

    @property
    def storage_values(self) -> tuple[str, ...]:
        return (
            self.provider_id,
            self.venue,
            self.asset_class,
            self.series_variant,
            self.price_adjustment,
            self.session_variant,
            self.volume_semantics,
        )

    def is_legacy_default_for(self, exchange: str) -> bool:
        return self == self.for_exchange(exchange)

    def to_dict(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "venue": self.venue,
            "asset_class": self.asset_class,
            "series_variant": self.series_variant,
            "price_adjustment": self.price_adjustment,
            "session_variant": self.session_variant,
            "volume_semantics": self.volume_semantics,
        }

    def to_camel_dict(self) -> dict[str, str]:
        return {
            "providerId": self.provider_id,
            "venue": self.venue,
            "assetClass": self.asset_class,
            "seriesVariant": self.series_variant,
            "priceAdjustment": self.price_adjustment,
            "sessionVariant": self.session_variant,
            "volumeSemantics": self.volume_semantics,
        }


def resolve_kline_series_identity(
    exchange: str,
    identity: KlineSeriesIdentity | None,
) -> KlineSeriesIdentity:
    """Resolve absent identity to the one backward-compatible crypto series."""

    return identity or KlineSeriesIdentity.for_exchange(exchange)


def identity_from_mapping(
    exchange: str,
    values: dict[str, Any] | None,
) -> KlineSeriesIdentity:
    """Build an identity from a snake_case mapping with legacy defaults."""

    payload = values or {}
    return KlineSeriesIdentity.for_exchange(
        exchange,
        provider_id=payload.get("provider_id"),
        venue=payload.get("venue"),
        asset_class=payload.get("asset_class", DEFAULT_ASSET_CLASS),
        series_variant=payload.get("series_variant", DEFAULT_SERIES_VARIANT),
        price_adjustment=payload.get("price_adjustment", DEFAULT_PRICE_ADJUSTMENT),
        session_variant=payload.get("session_variant", DEFAULT_SESSION_VARIANT),
        volume_semantics=payload.get("volume_semantics", DEFAULT_VOLUME_SEMANTICS),
    )


IDENTITY_FIELDS = (
    "provider_id",
    "venue",
    "asset_class",
    "series_variant",
    "price_adjustment",
    "session_variant",
    "volume_semantics",
)


def requested_series_identity(
    exchange: str,
    values: object,
) -> KlineSeriesIdentity | None:
    """The series a request names beyond its route, or ``None`` for the exchange's own.

    Requests carry an optional snake_case ``identity`` object next to
    ``exchange/market_type/symbol``. An absent identity and an explicit default
    name the same legacy series, so both resolve to ``None``: a request that
    hashes its fields keeps the hash it had before identities existed
    (ADR-DATA-002 §3).
    """

    if values is None:
        return None
    if not isinstance(values, Mapping):
        raise ValueError("identity must be an object")
    unknown = set(values) - set(IDENTITY_FIELDS)
    if unknown:
        raise ValueError(f"identity has unknown fields: {', '.join(sorted(map(str, unknown)))}")
    if any(value is not None and not isinstance(value, str) for value in values.values()):
        raise ValueError("identity fields must be strings")
    identity = identity_from_mapping(exchange, dict(values))
    return None if identity.is_legacy_default_for(exchange) else identity


def identity_from_metadata(
    exchange: str,
    metadata: dict[str, Any] | None,
) -> KlineSeriesIdentity | None:
    """Read an explicitly attached series identity without inventing one."""

    if not isinstance(metadata, dict):
        return None
    raw = metadata.get(SERIES_IDENTITY_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    return identity_from_mapping(exchange, raw)


__all__ = [
    "DEFAULT_ASSET_CLASS",
    "DEFAULT_PRICE_ADJUSTMENT",
    "DEFAULT_SERIES_VARIANT",
    "DEFAULT_SESSION_VARIANT",
    "DEFAULT_VOLUME_SEMANTICS",
    "KlineSeriesIdentity",
    "IDENTITY_FIELDS",
    "SERIES_IDENTITY_METADATA_KEY",
    "identity_from_mapping",
    "identity_from_metadata",
    "requested_series_identity",
    "resolve_kline_series_identity",
]
