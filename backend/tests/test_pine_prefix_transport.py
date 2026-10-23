import os
import threading

import pytest
from app.backtest.native import PROTOCOL, encoded, invoke
from app.backtest.native_session import SessionWorker
from app.backtest.errors import BacktestError
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
        print(f"prefix input bytes: clocked={clocked} actual={worker.input_bytes} full={full_bytes} ratio={worker.input_bytes/full_bytes:.6f}")
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


def test_account_delta_transport_keeps_changed_equity_positions_nulls_and_full_rebases():
    runtime=plugin()
    identity=invoke(runtime,{"operation":"describe"})["identity"]
    assert identity["prefix_append"]=="candlescope.pine-prefix/2"
    wire=dict(protocol=PROTOCOL,identity=identity,parameters={},context=dict(symbol="A",timeframe="1"),
        source='//@version=6\nstrategy("account deltas")\nplot(strategy.position_size)\nplot(strategy.position_avg_price)\nplot(strategy.equity)\nplot(strategy.netprofit)')
    cancel=threading.Event();worker=SessionWorker(runtime,wire,cancel,evaluator=True)
    bars=[];accounts=[]
    try:
        for i in range(8):
            bars.append(dict(time=i*60,open=10,high=10,low=10,close=10,volume=1))
            accounts.append(dict(time=i*60,position_size=i%3,position_avg_price=10 if i%3 else None,
                equity=1000+i,initial_capital=1000,netprofit=i,openprofit=0))
            request={**wire,"bars":bars,"accounts":accounts}
            assert worker.request(request,cancel)==invoke(runtime,request)
        accounts[0]["equity"]=1000.5;accounts[0]["netprofit"]=.5
        assert worker.request(request,cancel)==invoke(runtime,request)
        # Python bool equality with integer zero must never hide bad feedback.
        bars.append(dict(time=480,open=10,high=10,low=10,close=10,volume=1))
        accounts.append({**accounts[-1],"time":480,"openprofit":False})
        with pytest.raises(BacktestError): worker.request(request,cancel)
    finally: worker.close()
