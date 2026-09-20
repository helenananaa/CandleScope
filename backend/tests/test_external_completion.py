import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_external_strategy_v2 import source, tape


def run(host, payload, language, body, *, pyramiding=2, mode="BAR_APPROX", tick=0.5):
    script = source(language, body.replace(":", "") if language == "pine" else body)
    if language == "pyne":
        script = script.replace('plot(syminfo.mintick)', 'ctx.plot("tick", ctx.syminfo.mintick)')
    script = script.replace('strategy("Orders")', f'strategy("Orders", pyramiding={pyramiding})')
    script = script.replace('ctx.strategy.configure()', f'ctx.strategy.configure(pyramiding={pyramiding})')
    settings = {"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}
    if tick is not None:
        settings["price_tick"] = tick
    config = {**payload,"source":script,"language":language,"execution_mode":"CANDLESCOPE",
              "execution_fidelity":mode,"host_settings":settings}
    if mode != "BAR_APPROX":
        data = tape()
        if mode == "BOOK_ASSISTED":
            events=[]
            for i,event in enumerate(data["events"]):
                price=event["payload"]["price"]
                events.append({"time_ms":event["time_ms"],"role":"ORDER_BOOK","payload":{
                    "book_sequence":i+1,"snapshot":i==0,"bid":price,"ask":price}})
                events.append(event)
            data["events"]=events
        config["execution_data"]=data
    created = host.native.create(config, str(hash(str(config))))
    return terminal(host.native, created["run_id"])


@pytest.mark.parametrize("language", ["pine","pyne"])
@pytest.mark.parametrize("mode", ["BAR_APPROX","TRADE_TAPE","BOOK_ASSISTED"])
def test_installed_multiple_entries_named_partial_close(runtime, language, mode):
    host,payload=runtime
    record=run(host,payload,language,'''if bar_index == 0:
    strategy.entry("A", strategy.long, qty=2)
    strategy.entry("B", strategy.long, qty=3)
if bar_index == 1:
    strategy.close("B", qty=1)
if bar_index == 2:
    strategy.close("A")
''',mode=mode)
    assert record["state"] == "COMPLETED", record.get("error")
    report=record["result"]
    assert [float(fill["qty"]) for fill in report["trades"]] == [2,3,1,2]
    allocation=report["raw_output"]["entry_allocation"]
    assert [(lot["entry_id"],float(lot["qty"])) for lot in allocation["open_entries"]] == [("B",2)]
    assert [row["closed"][0]["entry_id"] for row in allocation["fill_allocations"] if row["closed"]] == ["B","A"]
    assert report["account_authority"] == "candlescope"
    assert not report["raw_output"]["strategy_output"].get("strategy")


@pytest.mark.parametrize("language", ["pine","pyne"])
def test_installed_tick_bracket_and_symbol_tick_agree(runtime, language):
    host,payload=runtime
    record=run(host,payload,language,'''if bar_index == 0:
    strategy.entry("A", strategy.long, qty=1)
    strategy.exit("X", "A", profit=2, loss=2)
plot(syminfo.mintick)
''')
    assert record["state"] == "COMPLETED", record.get("error")
    report=record["result"]
    assert [float(fill["price"]) for fill in report["trades"]] == [10,9]
    graphic = report["graphics"][0]
    values = graphic["values"] if language == "pine" else [row["value"] for row in graphic["data"]]
    assert values == [0.5]*10


@pytest.mark.parametrize("language", ["pine","pyne"])
@pytest.mark.parametrize("mode", ["TRADE_TAPE","BOOK_ASSISTED"])
def test_installed_trailing_exit_tracks_real_prints(runtime, language, mode):
    host,payload=runtime
    record=run(host,payload,language,'''if bar_index == 0:
    strategy.entry("A", strategy.long, qty=2)
    strategy.exit("X", "A", trail_points=2, trail_offset=2)
''',mode=mode)
    assert record["state"] == "COMPLETED", record.get("error")
    assert [fill["event_time_ms"] for fill in record["result"]["trades"]] == [60000,80000]
    assert float(record["result"]["trades"][-1]["position_after"]) == 0


@pytest.mark.parametrize("language", ["pine","pyne"])
@pytest.mark.parametrize("arguments,tick,error", [
    ("profit=2",None,"price_tick"),
    ("trail_points=2, trail_offset=1",0.5,"trade events"),
    ("profit=2, limit=11",0.5,"absolute price"),
])
def test_installed_unsupported_price_contract_fails_closed(runtime, language, arguments, tick, error):
    host,payload=runtime
    record=run(host,payload,language,f'''if bar_index == 0:
    strategy.entry("A", strategy.long, qty=1)
    strategy.exit("X", "A", {arguments})
''',tick=tick)
    assert record["state"] == "FAILED", record
    assert record["result"] is None
    # Pine rejects the ambiguous pair during semantic analysis, before the
    # host's equivalent admission check; both must fail without a report.
    expected = "combined trigger families are not supported" if language == "pine" and "limit=11" in arguments else error
    assert expected in str(record["error"])
