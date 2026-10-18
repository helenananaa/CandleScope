"""Durable origins for on-demand replay context, independent of chart windows."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

from app.data_engine.ingestion.models import StreamDescriptor, StreamType
from app.exchanges.symbol_catalog import get_cached_symbol_metadata

from .models import PreparationError, fingerprint

MINUTE = 60_000
DAY = 86_400_000


@dataclass(frozen=True, slots=True)
class ReplayContextOrigin:
    key: str
    generation: int
    start_ms: int
    frozen_start_ms: int

    @property
    def revision(self):
        return fingerprint({"contract": "replay-context-origin.v1", **asdict(self)})


def source_key(binding, persisted):
    return fingerprint(
        {
            "session_id": binding["session_id"],
            "track_id": binding["track_id"],
            "data_epoch": persisted["data_epoch"],
        }
    )


class ReplayContextOrigins:
    def __init__(self, repository):
        self.repository = repository

    def get(self, key):
        with self.repository.connect() as db:
            row = db.execute(
                "SELECT * FROM preparation_context_origins WHERE key=?", (key,)
            ).fetchone()
            return ReplayContextOrigin(**dict(row)) if row is not None else None

    def generation(self):
        with self.repository.connect() as db:
            return int(
                db.execute(
                    "SELECT generation FROM preparation_context_state WHERE id=1"
                ).fetchone()[0]
            )

    def pin(self, key, generation, start_ms, frozen_start_ms):
        if (
            type(start_ms) is not int
            or start_ms < 0
            or start_ms % MINUTE
            or start_ms > frozen_start_ms
        ):
            raise PreparationError(
                "HISTORY_ORIGIN_INVALID", "Invalid replay history origin"
            )
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = int(
                db.execute(
                    "SELECT generation FROM preparation_context_state WHERE id=1"
                ).fetchone()[0]
            )
            if generation != current:
                raise PreparationError(
                    "HISTORY_ORIGIN_CHANGED",
                    "History cache was released during origin discovery",
                    retryable=True,
                )
            db.execute(
                "INSERT OR IGNORE INTO preparation_context_origins VALUES (?,?,?,?)",
                (key, generation, start_ms, frozen_start_ms),
            )
            row = db.execute(
                "SELECT * FROM preparation_context_origins WHERE key=?", (key,)
            ).fetchone()
            return ReplayContextOrigin(**dict(row))


class ReplayOriginResolver:
    """Use provider lifecycle metadata, or a provider with ascending first-page semantics.

    An arbitrary local cache edge is never a listing boundary. Providers without
    either contract remain explicit unknowns rather than silently using a tail.
    """

    def __init__(
        self, *, factory=None, policy=None, symbol_lookup=get_cached_symbol_metadata
    ):
        self.factory, self.policy, self.symbol_lookup = factory, policy, symbol_lookup

    async def __call__(self, identity, frozen_start_ms):
        metadata = (
            self.symbol_lookup(identity.exchange, identity.market_type, identity.symbol)
            or {}
        )
        listed = metadata.get("continuousTradingAtMs")
        if type(listed) is not int or listed < 0:
            listed = metadata.get("listedAtMs")
        bounds = [listed] if type(listed) is int and listed >= 0 else []
        if self.policy is not None:
            key = self.policy.series_key(
                exchange=identity.exchange,
                market_type=identity.market_type,
                symbol=identity.symbol,
                channel="kline",
                variant="1m",
            )
            availability = self.policy.resolve(key).availability
            if availability.rolling_retention_ms is not None:
                raise PreparationError(
                    "HISTORY_ORIGIN_UNKNOWN",
                    "Provider history has a rolling retention boundary",
                )
            bounds.extend(
                bound.value_ms
                for bound in (availability.data_start, availability.upstream_start)
                if bound is not None
                and bound.confirmed
                and not bound.dynamic
                and not bound.retryable
            )
        lower = ((max(bounds) + MINUTE - 1) // MINUTE) * MINUTE if bounds else 0
        if bounds and lower >= frozen_start_ms:
            return frozen_start_ms
        if identity.exchange == "binance" and self.factory is not None:
            # This provider's start-time page is ascending. Do not generalize
            # this probe to providers whose limit selects the newest rows.
            descriptor = StreamDescriptor(
                identity.symbol,
                StreamType.KLINE,
                interval="1m",
                exchange=identity.exchange,
                market_type=identity.market_type,
            )
            try:
                async with asyncio.timeout(10):
                    events = await self.factory.fetch_market(
                        descriptor,
                        limit=1,
                        start_ms=lower,
                        end_ms=frozen_start_ms + MINUTE - 1,
                        history=True,
                        defer_on_rate_limit=True,
                    )
            except Exception as exc:
                raise PreparationError(
                    "HISTORY_ORIGIN_UNAVAILABLE",
                    "Could not read the provider history boundary",
                    retryable=True,
                ) from exc
            times = [
                event.data.get("open_time")
                for event in events
                if event.exchange == identity.exchange
                and event.market_type == identity.market_type
                and event.symbol == identity.symbol
                and event.event_type == StreamType.KLINE
            ]
            if not times or any(
                type(value) is not int
                or value < lower
                or value > frozen_start_ms
                or value % MINUTE
                for value in times
            ):
                raise PreparationError(
                    "HISTORY_ORIGIN_UNAVAILABLE",
                    "Provider returned no verifiable first history bar",
                    retryable=True,
                )
            return min(times)
        if bounds:
            # A frozen local revision may legitimately begin before a current
            # provider retention/lifecycle declaration. Keep its known prefix.
            return min(lower, frozen_start_ms)
        raise PreparationError(
            "HISTORY_ORIGIN_UNKNOWN", "This provider has no verified history origin"
        )


def context_request_identity(requirement, origin):
    return fingerprint(
        {"requirement": requirement.model_dump(), "origin": origin.revision}
    )
