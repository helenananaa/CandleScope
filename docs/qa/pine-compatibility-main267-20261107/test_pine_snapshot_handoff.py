"""Check an explicit client handoff using the existing Pine sidecar and BAR source."""
import json
import os
from pathlib import Path

from tests import test_chart_calculation_transports as transport
from tests.test_chart_calculation_real_bus import real_bus_wire, storage, wire  # noqa: F401


def test_closed_chart_owner_can_be_replaced_by_explicit_snapshot_client(real_bus_wire):
    wire = real_bus_wire
    initial = wire.client.post("/indicators/calculations", json=transport.open_request()).json()
    assert initial["ok"] and transport.value(initial) == 500
    position = transport.ref(initial)
    domain = "/indicators/calculations/" + position["domainId"]

    with wire.client.websocket_connect("/ws") as active:
        transport.subscribe(active, position)
        assert transport.receive(active, "indicator.subscribed")["ok"]
        assert transport.value(transport.receive(active, "indicator.snapshot")) == 500
        assert wire.client.post("/fixture/tick/501?close=103").json()["ok"]
        first = transport.receive(active, "indicator.replace_range")
        assert transport.value(first) == 501
        assert wire.client.post("/fixture/tick/501?close=104").json()["ok"]
        second = transport.receive(active, "indicator.replace_range")
        assert transport.value(second) == 502
        assert wire.client.delete(domain).json()["state"] == "closed"
        assert transport.receive(active, "error")["code"] == "INDICATOR_CALCULATION_CLOSED"
    assert wire.service.calculations.snapshot()["holders"] == 0
    assert not wire.source.leases

    requests = wire.host.diagnostics()["runtimes"][0]["requests"]
    with wire.client.websocket_connect("/ws") as stale:
        transport.subscribe(stale, position)
        failure = transport.receive(stale, "indicator.subscribed")
        assert failure["ok"] is False
    assert wire.host.diagnostics()["runtimes"][0]["requests"] == requests

    range_request = transport.open_request()
    history = wire.client.post("/indicators/range/batch", json={"requests": [range_request]}).json()
    assert history["ok"], history
    snapshot = history["results"][0]["payload"]
    assert snapshot["ok"], snapshot
    assert snapshot.get("calculation") is None
    assert transport.value(snapshot) == 500
    def counter(payload):
        return next(line["data"] for line in payload["lines"] if line.get("title", line.get("name")) == "counter")
    assert counter(snapshot) == counter(initial)
    message = transport.open_request(historyLimit=501)
    for key in ("schemaVersion", "start", "end"):
        del message[key]
    with wire.client.websocket_connect("/ws") as snapshot_client:
        snapshot_client.send_json({**message, "action": "subscribe"})
        acknowledgement = transport.receive(snapshot_client, "indicator.subscribed")
        assert acknowledgement["ok"], acknowledgement
        assert acknowledgement["seeded"] is False
        assert wire.service.calculations.snapshot()["holders"] == 0
        assert wire.client.post("/fixture/tick/501?close=105").json()["ok"]
        update = transport.receive(snapshot_client, "indicator.patch", "indicator.snapshot", "indicator.replace_range")
        assert update.get("calculation") is None
        assert transport.value(update) == 501
        snapshot_client.send_json({"action": "unsubscribe", "clientId": message["clientId"]})
        transport.receive(snapshot_client, "indicator.unsubscribed")
    assert not wire.source.leases
    Path(os.environ["CALCULATION_TRACE_DIR"], "handoff.json").write_text(json.dumps({
        "sameConfirmedCounterSeries": True,
        "retiredReferenceCode": failure["code"],
        "requestsOnStaleReference": 0,
        "chartObservedValues": [500, 501, 502],
        "snapshotObservedValues": [500, 501],
        "compatibilityFrame": update["type"],
        "chartOwnerHoldersAfterSwitch": wire.service.calculations.snapshot()["holders"],
    }, indent=2) + "\n")
