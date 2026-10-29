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
from .models import MarketEvent, RawMessage, StreamDescriptor
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
        if isinstance(msg.payload, dict) and self._cfg.ccxt_fork_kline_enabled:
            from app.exchanges.ccxt_ext.fork_kline import SCHEMA, prepare_source_messages

            if msg.payload.get("schema") == SCHEMA:
                try:
                    await prepare_source_messages([msg], self._descriptor)
                except ValueError as exc:
                    self._metrics.inc("parse_errors")
                    logger.warning("Rejected invalid fork source candle: %s", exc)
                    return
                if msg.payload["_source_receipt"]["status"] == "reconcile":
                    await self._reconcile_source(msg)
                    return
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

    async def _reconcile_source(self, message: RawMessage) -> None:
        from app.exchanges import get_exchange_registry
        from .models import TransportRequest

        plugin = get_exchange_registry().get_plugin(self._descriptor.exchange)
        opened = int(message.payload["timestamp"])
        messages = await plugin.fetch_history_with_config(
            TransportRequest(self._descriptor, limit=1, start_ms=opened, end_ms=opened), self._cfg
        )
        if not messages:
            raise RuntimeError("source reconciliation returned no candle")
        self._metrics.inc("source_reconciliations")
        for resolved in messages:
            await self.ingest(resolved)

    async def replay_source_pending(self) -> None:
        if not self._cfg.ccxt_fork_kline_enabled:
            return
        from app.core.executors import run_storage
        from app.data_engine.storage import kline_sources

        while True:
            messages = await run_storage(kline_sources.pending, self._descriptor)
            if not messages:
                return
            for message in messages:
                await self.ingest(message)
            remaining = await run_storage(kline_sources.pending, self._descriptor, 1)
            if remaining and remaining[0].payload["_source_receipt"]["ref"] == messages[0].payload["_source_receipt"]["ref"]:
                return  # Recovery may buffer until its missing range is available.

    def parse_raw(self, msg: RawMessage) -> MarketEvent | None:
        """Parse a raw message into a MarketEvent without triggering callbacks."""
        events = self.parse_all(msg)
        return events[-1] if events else None

    def parse_all(self, msg: RawMessage) -> list[MarketEvent]:
        parse_many = getattr(self._normalizer, "parse_many", None)
        if callable(parse_many):
            return list(parse_many(msg) or [])
        event = self._normalizer.parse(msg)
        return [] if event is None else [event]
