"""A second socket must not inherit another chart's intrabar history."""
import json
import os
from pathlib import Path

from tests import test_chart_calculation_transports as transport
from tests.test_chart_calculation_real_bus import real_bus_wire, storage, wire  # noqa: F401


def test_snapshot_clients_with_same_client_id_do_not_share_pine_state(real_bus_wire):
    wire = real_bus_wire
    message = transport.open_request(historyLimit=501)
    for key in ("schemaVersion", "start", "end"):
        del message[key]
    message["action"] = "subscribe"

    def next_value(ws):
        return transport.value(transport.receive(ws, "indicator.snapshot", "indicator.replace_range", "indicator.patch"))

    with wire.client.websocket_connect("/ws") as first:
        first.send_json(message)
        assert transport.receive(first, "indicator.subscribed")["ok"]
        assert wire.client.post("/fixture/tick/501?close=103").json()["ok"]
        assert next_value(first) == 501
        assert wire.client.post("/fixture/tick/501?close=104").json()["ok"]
        assert next_value(first) == 502
        with wire.client.websocket_connect("/ws") as second:
            second.send_json(message)
            assert transport.receive(second, "indicator.subscribed")["ok"]
            assert wire.client.post("/fixture/tick/501?close=105").json()["ok"]
            observed = [next_value(first), next_value(second)]
            Path(os.environ["CALCULATION_TRACE_DIR"], "same-client-id.json").write_text(json.dumps({
                "expected": [503, 501],
                "observed": observed,
                "sameClientId": True,
                "sameInstrumentAndScript": True,
            }, indent=2) + "\n")
            assert observed == [503, 501]
