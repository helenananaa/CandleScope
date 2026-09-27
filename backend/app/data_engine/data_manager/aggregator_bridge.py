"""Bridge BarAggregator events into DataManager cache, storage, and bus."""
from __future__ import annotations

import logging
from collections.abc import Callable

from app.core.executors import run_storage
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.interval_policy import is_ephemeral_interval

from ..bar_aggregator import BarEvent, BarEventType, BarFinality, BarState
from .cache import BarCache
from .bar_delivery import DurableBarDelivery
from .event_bus import DataEventBus
from .models import BarData, DataEvent, DataEventType, SeriesKey, StorageBackend

logger = logging.getLogger("data_manager.aggregator_bridge")

StorageProvider = Callable[[], StorageBackend | None]
StartedProvider = Callable[[], bool]
StreamMarker = Callable[[SeriesKey], None]


class AggregatorBridge:
    """Owns BarAggregator output handling for DataManager."""

    def __init__(
        self,
        *,
        cache: BarCache,
        event_bus: DataEventBus,
        storage_provider: StorageProvider,
        mark_bar_received: StreamMarker,
        is_started: StartedProvider,
        recovery_lookback_bars: int = 500,
    ) -> None:
        self._cache = cache
        self._event_bus = event_bus
        self._storage_provider = storage_provider
        self._mark_bar_received = mark_bar_received
        self._is_started = is_started
        self.delivery = DurableBarDelivery(storage_provider, self._publish,
                                           recovery_lookback_bars=recovery_lookback_bars)

    async def on_bar_event(self, event: BarEvent) -> str | None:
        """Convert an aggregator event into cache updates and DataEvents."""
        if not self._is_started():
            return

        bar_state: BarState = event.bar
        key = SeriesKey(
            bar_state.symbol,
            bar_state.interval,
            exchange=bar_state.exchange,
            market_type=bar_state.market_type,
            **bar_state.identity.to_dict(),
        )

        dm_event_type = {
            BarEventType.CREATED: DataEventType.BAR_CREATED,
            BarEventType.UPDATED: DataEventType.BAR_UPDATED,
            BarEventType.CLOSED: DataEventType.BAR_CLOSED,
            BarEventType.AMENDED: DataEventType.BAR_AMENDED,
            BarEventType.EXPIRED: DataEventType.BAR_EXPIRED,
        }.get(event.event_type, DataEventType.BAR_UPDATED)
        bar_data = BarData.from_bar_state(
            bar_state,
            is_closed=dm_event_type in (DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED),
        )

        storage_source = self._authoritative_storage_source(bar_state, dm_event_type)
        if (
            dm_event_type in (DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED)
            and storage_source is None
        ):
            logger.warning(
                "Dropped non-authoritative %s for %s@%s bucket=%d finality=%s reason=%s",
                dm_event_type.value,
                key.symbol,
                key.interval,
                bar_state.bucket_start_ms,
                getattr(getattr(bar_state, "finality", None), "value", None),
                getattr(bar_state, "close_reason", None),
            )
            return
        if storage_source is not None and bar_data.source != storage_source:
            bar_data = bar_data.with_source(storage_source)

        cache_write_event = dm_event_type in (
            DataEventType.BAR_CREATED,
            DataEventType.BAR_UPDATED,
            DataEventType.BAR_CLOSED,
            DataEventType.BAR_AMENDED,
        )
        if cache_write_event:
            can_accept, canonical = self._cache.can_accept_upsert(key, bar_data)
            if not can_accept:
                logger.warning(
                    "Dropped lower-quality %s for %s bucket=%d before durable write "
                    "incoming_source=%s canonical_source=%s",
                    dm_event_type.value,
                    key,
                    bar_state.bucket_start_ms,
                    bar_data.source,
                    canonical.source if canonical is not None else None,
                )
                return

        dm_event = DataEvent(dm_event_type, key, bar_data, timestamp_ms=event.timestamp_ms)
        if event.previous_bar is not None:
            dm_event.previous_bar = BarData.from_bar_state(event.previous_bar)
        if storage_source is not None and not is_ephemeral_interval(key.interval) and self.delivery.journal is not None:
            # Snapshot mutable aggregator state before any thread/await boundary.
            fields = ("time", "open", "high", "low", "close", "volume", "is_closed", "source",
                      "quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
            payload = dm_event.to_dict()
            payload["bar"] = {name: getattr(bar_data, name) for name in fields}
            if dm_event.previous_bar is not None:
                payload["previous_bar"] = {name: getattr(dm_event.previous_bar, name) for name in fields}
            payload["storage_row"] = bar_state.to_storage_dict()
            return await self.delivery.submit(event.delivery_id, payload, key)

        durable_accepted = await self._persist_bar_event(bar_state, dm_event_type, storage_source)
        if durable_accepted is False:
            return "rejected"
        await self._publish(dm_event)
        return "accepted"

    async def _publish(self, event: DataEvent) -> None:
        if event.event_type in (DataEventType.BAR_CREATED, DataEventType.BAR_UPDATED,
                               DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED):
            accepted, _canonical = self._cache.upsert_if_accepted(event.key, event.bar)
            if not accepted:
                return
        self._mark_bar_received(event.key)
        await self._event_bus.emit(event)

    async def _persist_bar_event(
        self,
        bar_state: BarState,
        event_type: DataEventType,
        source: str | None,
    ) -> bool | None:
        """Persist a final bar and report durable quality acceptance.

        ``True`` means at least one row was accepted, ``False`` means the
        durable source-rank predicate rejected it, and ``None`` means storage
        was not applicable or the legacy backend did not expose a row count.
        Storage failures propagate; they are never quality rejections.
        """
        if is_ephemeral_interval(bar_state.interval):
            return None

        storage = self._storage_provider()
        if storage is None:
            return None

        if source is None:
            return None

        row = bar_state.to_storage_dict()
        try:
            affected = await run_storage(
                storage.upsert_bars,
                bar_state.symbol,
                bar_state.interval,
                [row],
                source,
                bar_state.exchange,
                bar_state.market_type,
                **(
                    {"series_identity": bar_state.identity}
                    if not bar_state.identity.is_legacy_default_for(bar_state.exchange)
                    else {}
                ),
            )
            if affected is None:
                return None
            return int(affected) > 0
        except Exception as exc:
            logger.warning(
                "Failed to persist %s for %s@%s %s: %s",
                event_type.value,
                bar_state.symbol,
                bar_state.interval,
                bar_state.bucket_start_ms,
                exc,
                exc_info=True,
            )
            raise BarDeliveryUnavailable(f"Final bar persistence failed: {exc}") from exc

    @staticmethod
    def _authoritative_storage_source(
        bar_state: BarState,
        event_type: DataEventType,
    ) -> str | None:
        """Return durable provenance only for a proven final bar."""
        if event_type not in (DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED):
            return None
        finality = getattr(bar_state, "finality", None)
        if getattr(finality, "value", finality) != BarFinality.AUTHORITATIVE.value:
            return None
        if event_type == DataEventType.BAR_AMENDED:
            return "data_manager_amended"
        return {
            "source_close": "data_manager_exchange_closed",
            "composite_close": "data_manager_composite_closed",
            "batch": "backfill_rest_verified",
        }.get(str(getattr(bar_state, "close_reason", "") or ""))
