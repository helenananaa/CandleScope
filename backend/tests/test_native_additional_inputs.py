import pytest
from app.local_data.service import LocalImportOptions
from tests.test_native_backtests import runtime, terminal, pytestmark
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


@pytest.mark.parametrize("language", ["pine", "pyne"])
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
""" if language == "pine" else """def init(ctx):
    ctx.strategy.configure()
def on_bar(ctx, bar):
    remote = ctx.request.security("BINANCE:ETHUSDT", "2", "close")
    if remote is not None and remote > 100:
        ctx.strategy.entry("L", ctx.strategy.long, qty=1)
    ctx.plot("remote", remote)
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
