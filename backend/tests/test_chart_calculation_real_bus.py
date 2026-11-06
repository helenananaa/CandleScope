"""Keep the existing chart wire contract on the actual routed event bus."""
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import BarData
from tests import test_chart_calculation_transports as transport
from tests.test_chart_calculation_transports import wire  # noqa: F401
from tests.test_kline_revision_contract import storage  # noqa: F401


class RealBusSource(transport.Source):
    # BAR production/stream leases remain deterministic fixture ports. Queries,
    # cache, SQLite, subscription routing, delivery and disposal are real.
    subscribe = DataManager.subscribe
    unsubscribe = DataManager.unsubscribe

    async def emit(self, event):
        def source_bar(bar):
            if bar is None or isinstance(bar, BarData):
                return bar
            return BarData(**{name: getattr(bar, name) for name in (
                "time", "open", "high", "low", "close", "volume", "is_closed",
            )}, source=transport.QUALITY if bar.is_closed else "ws_native")

        # The SDK's lightweight Bar has no source-quality contract. Real bus
        # middleware requires the same BarData shape used by the fixture store.
        event = replace(event, bar=source_bar(event.bar), previous_bar=source_bar(event.previous_bar))
        await self.event_bus.emit(event)

    async def shutdown(self):
        self.bus_before_shutdown = self.event_bus.snapshot()
        await super().shutdown()
        self.bus_after_shutdown = self.event_bus.snapshot()
        assert self.bus_after_shutdown["callback_subscriptions"] == 0
        assert self.bus_after_shutdown["queue_subscriptions"] == 0
        assert self.bus_after_shutdown["callback_errors"] == 0
        output = os.environ.get("CALCULATION_TRACE_DIR")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            Path(output, "real-event-bus-shutdown.json").write_text(json.dumps({
                "before": self.bus_before_shutdown,
                "after": self.bus_after_shutdown,
            }, indent=2) + "\n")


@pytest.fixture
def real_bus_wire(monkeypatch, request):
    monkeypatch.setattr(transport, "Source", RealBusSource)
    return request.getfixturevalue("wire")


def test_real_bus_delivers_forming_updates_deletions_and_corrections(real_bus_wire, caplog):
    transport.test_http_reads_and_ws_share_one_real_calculation_and_correction_generation(real_bus_wire)
    assert not [record for record in caplog.records if record.levelno >= 40]
