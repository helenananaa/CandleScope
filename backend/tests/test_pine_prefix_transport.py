import os
import threading

import pytest
from app.backtest.native import PROTOCOL, encoded, invoke
from app.backtest.native_session import SessionWorker
from app.backtest.strategy.pine_engine import plugin

pytestmark = pytest.mark.skipif(
    not os.environ.get("NATIVE_TEST_PINE_PYTHON"),
    reason="requires installed Pine candidate",
)


@pytest.mark.parametrize("clocked", [False, True])
def test_real_worker_append_transport_matches_batch_and_reduces_input_bytes(clocked):
    runtime = plugin()
    identity = invoke(runtime, {"operation": "describe"})["identity"]
    source = '//@version=6\nstrategy("prefix")\nif close>15\n    strategy.entry("L",strategy.long,qty=2)\nplot(close)\n'
    if clocked:
        assert identity["external_execution_times"] is True
        source += "plot(timenow)\n"
    wire = {
        "protocol": PROTOCOL,
        "identity": identity,
        "source": source,
        "parameters": {},
        "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"},
    }
    cancelled = threading.Event()
    worker = SessionWorker(runtime, wire, cancelled, evaluator=True)
    full_bytes = 0
    try:
        for count in range(1, 41):
            bars = [
                {
                    "time": 1700000000 + i * 60,
                    "open": i + 10,
                    "high": i + 11,
                    "low": i + 9,
                    "close": i + 10,
                    "volume": 1,
                }
                for i in range(count)
            ]
            accounts = [
                {
                    "time": bar["time"],
                    "position_size": 0,
                    "position_avg_price": None,
                    "equity": 10000,
                    "initial_capital": 10000,
                    "netprofit": 0,
                    "openprofit": 0,
                }
                for bar in bars
            ]
            request = {**wire, "bars": bars, "accounts": accounts}
            if clocked:
                request["execution_times"] = [bar["time"] * 1000 + 59999 for bar in bars]
            full_bytes += len((encoded(request) + "\n").encode())
            result = worker.request(request, cancelled)
        assert result == invoke(runtime, request)
        assert worker.input_bytes < full_bytes * 0.3
        # A historical correction goes through a full rebase, never an append.
        request["bars"][0] = {**request["bars"][0], "close": 10.5}
        assert worker.request(request, cancelled) == invoke(runtime, request)
        if clocked:
            request["execution_times"][0] += 1
            corrected = worker.request(request, cancelled)
            assert corrected == invoke(runtime, request)
            assert corrected["raw_output"]["plots"][-1]["values"][0] == request["execution_times"][0]
    finally:
        worker.close()
