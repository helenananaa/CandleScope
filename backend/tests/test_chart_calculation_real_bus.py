"""Keep the existing chart wire contract on the actual routed event bus."""
import json
import os
from pathlib import Path

import pytest

from app.data_engine.data_manager import DataManager
from tests import test_chart_calculation_transports as transport
from tests.test_chart_calculation_transports import wire  # noqa: F401
from tests.test_kline_revision_contract import storage  # noqa: F401


class RealBusSource(transport.Source):
    # BAR production/stream leases remain deterministic fixture ports. Queries,
    # cache, SQLite, subscription routing, delivery and disposal are real.
    subscribe = DataManager.subscribe
    unsubscribe = DataManager.unsubscribe

    async def emit(self, event):
        await self.event_bus.emit(event)

    async def shutdown(self):
        self.bus_before_shutdown = self.event_bus.snapshot()
        await super().shutdown()
        self.bus_after_shutdown = self.event_bus.snapshot()
        assert self.bus_after_shutdown["callback_subscriptions"] == 0
        assert self.bus_after_shutdown["queue_subscriptions"] == 0
        output = os.environ.get("CALCULATION_TRACE_DIR")
        if output:
            Path(output, "real-event-bus-shutdown.json").write_text(json.dumps({
                "before": self.bus_before_shutdown,
                "after": self.bus_after_shutdown,
            }, indent=2) + "\n")


@pytest.fixture
def real_bus_wire(monkeypatch, request):
    monkeypatch.setattr(transport, "Source", RealBusSource)
    return request.getfixturevalue("wire")


def test_real_bus_delivers_forming_updates_deletions_and_corrections(real_bus_wire):
    transport.test_http_reads_and_ws_share_one_real_calculation_and_correction_generation(real_bus_wire)
