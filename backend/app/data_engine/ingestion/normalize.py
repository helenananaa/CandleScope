"""L4 Normalize Layer - raw exchange payloads to MarketEvent.

The layer owns pipeline metrics, callback delivery, and malformed payload
handling. Exchange-specific schema mapping lives under
``app.data_engine.ingestion.normalizers``.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from .config import IngestionConfig
from .metrics import LayerMetrics
from .models import DataSource, MarketEvent, RawMessage, StreamDescriptor, StreamType
from .normalizers import create_normalizer, truncate_payload

logger = logging.getLogger("ingestion.L4_Normalize")


class NormalizeLayer:
    """Converts ``RawMessage`` to ``MarketEvent``."""

    def __init__(
        self,
        config: IngestionConfig,
        descriptor: StreamDescriptor,
    ) -> None:
        self._cfg = config
        self._descriptor = descriptor
        self._metrics = LayerMetrics("L4_Normalize")
        self._normalizer = create_normalizer(config, descriptor)
        self._bar_contracts = {}
        self._on_event: Callable[[MarketEvent], Awaitable[None]] | None = None

    @property
    def metrics(self) -> LayerMetrics:
        return self._metrics

    def snapshot(self) -> dict:
        return {
            "layer": "L4_Normalize",
            "stream_key": self._descriptor.key,
            "normalizer": self._normalizer.__class__.__name__,
            "metrics": self._metrics.snapshot(),
        }

    def on_event(self, callback: Callable[[MarketEvent], Awaitable[None]]) -> None:
        """Register upstream callback consumed by L5 Continuity."""
        self._on_event = callback

    async def ingest(self, msg: RawMessage) -> None:
        """Normalize a raw message and forward the resulting MarketEvent."""
        self._metrics.inc("messages_received")
        try:
            events = self.parse_all(msg)
        except Exception as exc:
            self._metrics.inc("parse_errors")
            logger.warning(
                "Failed to parse raw message: %s - payload: %s",
                exc,
                truncate_payload(msg.payload),
            )
            return

        if not events:
            self._metrics.inc("messages_skipped")
            return

        for event in events:
            self._metrics.inc("events_emitted")
            self._metrics.mark("last_event_at")
            if self._on_event:
                await self._on_event(event)

    def parse_raw(self, msg: RawMessage) -> MarketEvent | None:
        """Parse a raw message into a MarketEvent without triggering callbacks."""
        events = self.parse_all(msg)
        return events[-1] if events else None

    def parse_all(self, msg: RawMessage) -> list[MarketEvent]:
        parse_many = getattr(self._normalizer, "parse_many", None)
        if callable(parse_many):
            events = list(parse_many(msg) or [])
        else:
            event = self._normalizer.parse(msg)
            events = [] if event is None else [event]
        for event in events:
            if event.event_type is not StreamType.KLINE:
                continue
            purpose = "history" if msg.source == DataSource.HTTP_BACKFILL else "realtime"
            interval = event.data["interval"]
            key = (purpose, interval)
            if key not in self._bar_contracts:
                from app.exchanges import get_exchange_registry
                from app.data_engine.bar_basis import native_bar_spec
                caps = get_exchange_registry().get_capabilities(event.exchange)
                factory = getattr(caps, "bar_spec", None)
                self._bar_contracts[key] = (factory(event.market_type, interval, purpose) if callable(factory)
                                            else native_bar_spec(event.exchange, event.market_type, interval, purpose))
            contract = self._bar_contracts[key]
            try:
                contract.validate(int(event.data["open_time"]), int(event.data["close_time"]))
            except ValueError:
                self._metrics.inc("boundary_errors")
                raise
            event.data["basis_id"] = contract.to_dict()["basis"]["basis_id"]
            event.data["basis_qualification"] = contract.qualification
        return events
