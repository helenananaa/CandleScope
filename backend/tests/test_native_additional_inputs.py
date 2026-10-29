import pytest
from app.local_data.service import LocalImportOptions
from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_native_replay import settle
from tests.test_native_strategy_plugins import PINE


def additional(host, name, symbol, interval, duration_ms, prices):
    path = host.settings.db_path.parent / (name+".csv")
    path.write_text("time,open,high,low,close,volume\n"+"\n".join(
        f"{i*duration_ms},{value},{value+1},{value-1},{value},100" for i,value in enumerate(prices)), encoding="utf-8")
    manifest = host.local_data.import_csv(path, LocalImportOptions(name=name, symbol=symbol, interval=interval, timestamp_unit="ms"))
    reference = dict(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
        start_time_ms=0, end_time_ms=len(prices)*duration_ms-1, interval=interval)
    snapshot = host.preview_snapshot(**reference)
    return {**reference, "snapshot_hash":snapshot["snapshot_hash"]}


@pytest.mark.parametrize("language", ["pine"])
def test_requested_data_stateful_replay_has_no_early_htf_value(runtime, language):
    host, payload = runtime
    context = {**additional(host,"higher","ETHUSDT","2m",120000,[100,200,300,400,500]),
        "symbol":"BINANCE:ETHUSDT", "timeframe":"2"}
    source = """//@version=6
strategy("Requested history")
remote = request.security("BINANCE:ETHUSDT", "2", close)
if remote > 100
    strategy.entry("L", strategy.long, qty=1)
plot(remote)
"""
    origin = terminal(host.native, host.native.create({**payload,"language":language,"source":source,"contexts":[context]}, "context")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    replay=host.native.replay
    record=replay.create(origin["run_id"])
    replay.command(record["replay_id"],0,"step")
    first=settle(replay,record["replay_id"])
    assert first["method"] == "FIXED_HORIZON_INCREMENTAL"
    assert not first["result"]["orders"]
    replay.command(record["replay_id"],first["revision"],"seek",2)
    middle=settle(replay,record["replay_id"])
    assert not middle["result"]["orders"]
    replay.command(record["replay_id"],middle["revision"],"play")
    final=settle(replay,record["replay_id"])
    assert final["result"] == origin["result"]
    assert final["result"]["orders"]


def test_pine_magnifier_and_library_replay_matches_batch(runtime):
    host,payload=runtime
    prices=[v for v in [10,10,10,20,20,5,5,15,15,8] for _ in range(2)]
    lower=additional(host,"lower","BTCUSDT","30s",30000,prices)
    source=PINE.replace('initial_capital=10000','initial_capital=10000, use_bar_magnifier=true')
    source=source.replace('//@version=6','//@version=6\nimport user/lib/1 as helper')+'\nplot(helper.scale(close))\n'
    libraries={"user/lib/1":'//@version=6\nlibrary("lib")\nexport scale(float value) => value * 2\n'}
    origin=terminal(host.native,host.native.create({**payload,"source":source,"magnifier":lower,"libraries":libraries},"magnifier")["run_id"])
    assert origin["state"] == "COMPLETED",origin.get("error")
    replay=host.native.replay
    record=replay.create(origin["run_id"])
    replay.command(record["replay_id"],0,"seek",5)
    middle=settle(replay,record["replay_id"])
    assert middle["method"] == "FIXED_HORIZON_INCREMENTAL"
    assert middle["result"]["fill_model"] == "pine-native-bar-magnifier"
    checkpoint=replay.snapshot(record["replay_id"],middle["revision"])
    replay.command(record["replay_id"],checkpoint["revision"],"step")
    later=settle(replay,record["replay_id"])
    restored=replay.restore(record["replay_id"],later["revision"],checkpoint["snapshots"][0]["snapshot_id"])
    replay.command(record["replay_id"],restored["revision"],"play")
    assert settle(replay,record["replay_id"])["result"] == origin["result"]


def test_pine_effective_currency_rates_are_frozen_for_batch_replay_and_seek(runtime):
    host, payload = runtime
    rates = {"schemaVersion": 1, "pairs": [{"from": "USD", "to": "EUR", "rates": [
        {"effectiveTime": 0, "rate": .8}, {"effectiveTime": 120000, "rate": .9}]}]}
    source = '//@version=6\nstrategy("FX")\nplot(request.currency_rate("USD", "EUR"))'
    origin = terminal(host.native, host.native.create({**payload, "source": source, "currency_rates": rates}, "fx")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    assert origin["result"]["raw_output"]["plots"][0]["values"][:3] == [.8, .8, .9]
    replay = host.native.replay
    record = replay.create(origin["run_id"])
    replay.command(record["replay_id"], 0, "seek", 2)
    first = settle(replay, record["replay_id"])
    assert first["result"]["raw_output"]["plots"][0]["values"] == [.8, .8]
    replay.command(record["replay_id"], first["revision"], "play")
    assert settle(replay, record["replay_id"])["result"] == origin["result"]


def test_pine_host_matching_accepts_frozen_library_sources(runtime):
    host, payload = runtime
    library = '//@version=6\nlibrary("Math")\nexport threshold() => 12.0'
    source = PINE.replace('strategy("Native threshold", initial_capital=10000)', 'strategy("Native threshold", initial_capital=10000)\nimport local/Math/1 as math').replace('close > 12', 'close > math.threshold()')
    result = terminal(host.native, host.native.create({**payload, "source": source,
        "libraries": {"local/Math/1": library}, "execution_mode": "CANDLESCOPE", "execution_fidelity": "BAR_APPROX",
        "host_settings": {"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 0}}, "host-import")["run_id"])
    assert result["state"] == "COMPLETED", result.get("error")
    assert result["result"]["account_authority"] == "candlescope"
    assert result["result"]["orders"]


@pytest.mark.parametrize("execution_mode", ["NATIVE", "CANDLESCOPE"])
def test_pine_bar_close_execution_clock_matches_batch_replay_and_seek(runtime, execution_mode):
    host, payload = runtime
    source = ('//@version=6\nstrategy("Clock")\n'
        'if timenow >= 179999\n    strategy.entry("L",strategy.long,qty=1)\nplot(timenow)')
    request = {**payload, "source": source, "execution_mode": execution_mode}
    if execution_mode == "CANDLESCOPE":
        request.update(execution_fidelity="BAR_APPROX",
            host_settings={"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 0})
    origin = terminal(host.native, host.native.create(request, "clock-" + execution_mode)["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    expected = [i * 60000 + 59999 for i in range(10)]
    def clock_values(result):
        raw = result["raw_output"]
        return raw.get("strategy_output", raw)["plots"][0]["values"]
    assert clock_values(origin["result"]) == expected
    replay = host.native.replay
    if execution_mode == "CANDLESCOPE":
        repeated = terminal(host.native, host.native.create(request, "clock-host-repeat")["run_id"])
        assert repeated["state"] == "COMPLETED", repeated.get("error")
        assert clock_values(repeated["result"]) == expected
        assert repeated["result"]["trades"] == origin["result"]["trades"]
    record = replay.create(origin["run_id"])
    replay.command(record["replay_id"], 0, "seek", 2)
    first = settle(replay, record["replay_id"])
    assert clock_values(first["result"]) == expected[:2]
    replay.command(record["replay_id"], first["revision"], "play")
    assert settle(replay, record["replay_id"])["result"] == origin["result"]
