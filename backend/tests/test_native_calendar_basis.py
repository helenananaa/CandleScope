"""Real installed Pine candidate: DST closes, causal requests, durable replay."""
from datetime import datetime, timedelta
import json
import os
from zoneinfo import ZoneInfo

import pytest

from app.local_data import LocalImportOptions
from tests.test_backtest_chart_context import _runtime
from tests.test_native_backtests import terminal
from tests.test_native_replay import settle
from tests.test_native_strategy_plugins import plugin

pytestmark = pytest.mark.skipif(not os.environ.get("NATIVE_CALENDAR_TEST"), reason="requires host-bar-boundaries/1 candidate")


def test_real_pine_calendar_closes_requests_replay_and_restart(tmp_path):
    # Independent oracle from local dates, not the application bucket code.
    local = datetime(2024, 3, 8, tzinfo=ZoneInfo("America/New_York"))
    edges = [int((local + timedelta(days=i)).timestamp()*1000) for i in range(9)]
    runtime = _runtime(tmp_path)
    try:
        runtime.native.resolver = plugin
        csv = tmp_path / "hours.csv"
        csv.write_text("time,open,high,low,close,volume\n" + "\n".join(
            f"{at},{100+i},{103+i},{99+i},{102+i},1" for i, at in enumerate(range(edges[0], edges[-1], 3600000))))
        manifest = runtime.local_data.import_csv(csv, LocalImportOptions(name="Calendar", symbol="BTCUSDT", interval="1h", timestamp_unit="ms"))
        def reference(interval):
            ref = dict(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"], interval=interval,
                       start_time_ms=edges[0], end_time_ms=edges[-1]-1)
            return {**ref, "snapshot_hash": runtime.preview_snapshot(**ref)["snapshot_hash"]}
        source = '''//@version=6
strategy("DST")
if bar_index % 2 == 0
    strategy.entry("L", strategy.long, qty=1)
else
    strategy.close("L")
plot(time_close)
plot(request.security(syminfo.tickerid, timeframe.period, time_close))
plot(request.security(syminfo.tickerid, "2D", time_close))
plot(time_close("", 1))
'''
        request = {**reference("1d~c1~America/New_York"), "language": "pine", "source": source,
                   "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1D"},
                   "contexts": [{**reference("2d~c1~America/New_York"), "symbol": "BINANCE:BTCUSDT", "timeframe": "2D"}]}
        run = terminal(runtime.native, runtime.native.create(request, "dst-candidate")["run_id"])
        assert run["state"] == "COMPLETED", run.get("error")
        result = run["result"]
        assert result["orders"] and result["trades"]
        plots = result["graphics"]
        assert plots[0]["values"] == edges[1:]
        assert plots[1]["values"] == edges[1:]
        assert plots[2]["values"] == [None, edges[2], edges[2], edges[4], edges[4], edges[6], edges[6], edges[8]]
        assert plots[3]["values"] == edges[:-1]
        wire = json.loads(runtime.native.db.execute("SELECT wire FROM native_inputs WHERE id=?", (run["run_id"],)).fetchone()[0])
        assert wire["bar_boundaries"]["BINANCE:BTCUSDT:1D"]["definition"]["tzdb_version"] == "2026c"
        replay = runtime.native.replay
        record = replay.create(run["run_id"])
        replay.command(record["replay_id"], record["revision"], "seek", 3)
        partial = settle(replay, record["replay_id"])
        saved = replay.snapshot(record["replay_id"], partial["revision"])
        replay.command(saved["replay_id"], saved["revision"], "play")
        final = settle(replay, record["replay_id"])
        assert final["result"] == result
    finally:
        runtime.shutdown()
    restarted = _runtime(tmp_path)
    try:
        restarted.native.resolver = plugin
        assert restarted.native.get(run["run_id"])["result"] == result
        replay = restarted.native.replay
        current = replay.get(record["replay_id"])
        restored = replay.restore(current["replay_id"], current["revision"], saved["snapshots"][0]["snapshot_id"])
        replay.command(restored["replay_id"], restored["revision"], "play")
        assert settle(replay, restored["replay_id"])["result"] == result
    finally:
        restarted.shutdown()


def test_real_calendar_indicator_streaming_and_history_repair():
    from dataclasses import asdict
    import subprocess
    from app.indicator.runtime_service import IndicatorRuntimeRequest
    from tests.test_native_strategy_plugins import PYTHON
    local = datetime(2024, 3, 8, tzinfo=ZoneInfo("America/New_York"))
    edges = [int((local + timedelta(days=i)).timestamp()) for i in range(6)]
    bars = [dict(time=at, open=10+i, high=20+i, low=1, close=10+i, volume=1, is_closed=True)
            for i, at in enumerate(edges[:5])]
    source = '//@version=6\nindicator("DST indicator")\nplot(time_close)\nplot(ta.sma(close, 2))'
    snapshots = [bars[:2]+[{**bars[2], "is_closed": False}],
                 bars[:2]+[{**bars[2], "close": 16, "is_closed": False}],
                 bars, [{**bars[0], "close": 12}]+bars[1:]]
    requests = [asdict(IndicatorRuntimeRequest(language="pine", source=source, exchange="binance", market_type="spot",
                symbol="BTCUSDT", interval="1d~c1~America/New_York", bars=tuple(rows),
                options={"pineSessionId": "calendar-session"}).to_sdk_request()) for rows in snapshots]
    assert requests[0]["options"]["barBasis"] == requests[2]["options"]["barBasis"]
    script = '''import json,sys
from candlescope_plugin_sdk import ExecuteBatchRequest, Bar, MarketContext
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin
plugin=PineCompatRuntimePlugin()
results=[]
for r in json.load(sys.stdin):
    request=ExecuteBatchRequest(source=r["source"], context=MarketContext(**r["context"]), bars=tuple(Bar(**b) for b in r["bars"]), options=r["options"])
    result=plugin.execute_batch(request)
    assert result.ok, result.diagnostics
    results.append({"reset":result.meta["sessionReset"], "lines":[[p.value for p in line.points] for line in result.output.series]})
print(json.dumps(results))
'''
    result = subprocess.run([PYTHON, "-c", script], input=json.dumps(requests), text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    results = json.loads(result.stdout)
    assert [r["reset"] for r in results] == [True, False, False, True]
    assert results[2]["lines"][0] == [at*1000 for at in edges[1:]]
    assert results[2]["lines"][1] == [10.5, 11.5, 12.5, 13.5]
    assert results[3]["lines"][1] == [11.5, 11.5, 12.5, 13.5]
