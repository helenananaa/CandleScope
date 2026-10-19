"""Installed Pine Workbench controls use the actual Host matcher and replay."""
from copy import deepcopy
from decimal import Decimal

import pytest

from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_external_replay import payload as replay_payload
from tests.test_native_replay import settle

MODES=["BAR_APPROX","TRADE_TAPE","BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED"]
PROFILES=[("BAR_APPROX",False), *[(mode,callback) for mode in MODES[1:] for callback in (False,True)]]


def value(main,mode,*,callbacks=False,closing=False,rule='max_intraday_filled_orders(1)',fresh=True):
    result=replay_payload(main,mode,callbacks)
    result["host_settings"].update(taker_fee_bps=0)
    result["source"]='''//@version=6
strategy("Workbench control",pyramiding=2%s%s)
varip bool sent=false
if false
    strategy.risk.%s
if barstate.isconfirmed and bar_index==0 and not sent
    sent:=true
    strategy.entry("A",strategy.long,qty=4)
    strategy.entry("pending",strategy.long,qty=2,limit=1)
if barstate.isconfirmed and bar_index>1
    strategy.order("halted",strategy.long,qty=2)
plot(strategy.position_size)
''' % (',calc_on_order_fills=true' if callbacks else '',',process_orders_on_close=true' if closing else '',rule)
    if closing and mode.startswith("BOOK") and fresh:
        events=result["execution_data"]["events"]
        last_print = {row["time_ms"]//60000: row["time_ms"] for row in events if row["role"]=="TRADES"}
        # Move next-bucket sampled quotes after its first print, so the fresh
        # closing quote remains the latest causally usable sample at the close.
        if mode=="BOOK_SAMPLED":
            for row in events:
                if row["role"]=="ORDER_BOOK" and row["time_ms"]%60000==59999:
                    row["time_ms"]+=2
                    row["payload"]["sample_time_ms"]=row["time_ms"]
        rewritten=[]
        for index,event in enumerate(events):
            rewritten.append(event)
            if event["role"]=="ORDER_BOOK":
                last=event
            if event["role"]=="TRADES" and event["time_ms"]==last_print[event["time_ms"]//60000]:
                quote=deepcopy(last)
                quote["time_ms"]=(event["time_ms"]//60000+1)*60000-2
                if mode=="BOOK_SAMPLED":
                    quote["payload"]["sample_time_ms"]=quote["time_ms"]
                rewritten.append(quote)
        rewritten.sort(key=lambda row: row["time_ms"])
        number=0
        for event in rewritten:
            if event["role"]=="ORDER_BOOK":
                number+=1
                event["payload"]["sample_index" if mode=="BOOK_SAMPLED" else "book_sequence"]=number
        result["execution_data"]["events"]=rewritten
    return result


@pytest.mark.parametrize("mode,callbacks",PROFILES)
def test_workbench_stop_cancels_and_closes_through_actual_matching(runtime,mode,callbacks):
    host,main=runtime
    record=terminal(host.native,host.native.create(value(main,mode,callbacks=callbacks),"stop")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    report=record["result"]
    stop=report["pine_risk_stops"]
    assert stop["blocked"] and not stop["flatten_requested"]
    assert Decimal(stop["residual_position"])==0
    assert len(stop["trips"])==1
    assert [row["script_order_id"] for row in report["trades"]]==["A","$host:pine-risk-close"]
    assert report["trades"][-1]["event_time_ms"]>report["trades"][0]["event_time_ms"]
    assert report["raw_output"]["entry_allocation"]["open_entries"]==[]
    assert all(order["status"] not in {"OPEN","PARTIAL"} for order in report["orders"])


@pytest.mark.parametrize("mode,callbacks",PROFILES)
def test_workbench_closing_tick_then_risk_close_waits_for_actual_future_tick(runtime,mode,callbacks):
    host,main=runtime
    record=terminal(host.native,host.native.create(value(main,mode,callbacks=callbacks,closing=True),"closing-stop")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    report=record["result"]
    first=report["trades"][0]
    assert first["reason"]=="PINE_BAR_CLOSE" and first["event_time_ms"]==59999
    assert report["trades"][-1]["event_time_ms"]>59999
    assert report["pine_risk_stops"]["blocked"] and Decimal(report["position"]["position_qty"])==0
    if mode in {"BOOK_DEPTH","BOOK_SAMPLED"}:
        assert report["raw_output"]["depth_model"]["taker_clock"]=="next_trade_print_or_explicit_script_close"
    if callbacks:
        group=report["raw_output"]["execution_passes"][0]
        assert len(group)==2 and all(frame["confirmed"] for frame in group)
        assert group[1]["account"]["position_size"]>0


@pytest.mark.parametrize("mode,callbacks",[("BAR_APPROX",False),("TRADE_TAPE",True),("BOOK_DEPTH",True),("BOOK_SAMPLED",True)])
def test_workbench_risk_and_closing_state_restore_to_identical_endpoint(runtime,mode,callbacks):
    host,main=runtime
    origin=terminal(host.native,host.native.create(value(main,mode,callbacks=callbacks,closing=True),"restore")["run_id"])
    assert origin["state"]=="COMPLETED",origin.get("error")
    replay=host.native.replay
    created=replay.create(origin["run_id"])
    key=created["replay_id"]
    def seek(target):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        result=settle(replay,key)
        assert result.get("error") is None,result
        return result
    first=seek(1)
    assert first["result"]["pine_risk_stops"]["flatten_requested"]
    with host.native.lock:
        saved=replay._host_state(key)
    assert saved["pine_risk_stops"]["state"]["trips"]
    snapshot=replay.snapshot(key,first["revision"])["snapshots"][0]["snapshot_id"]
    third=seek(3)
    replay.restore(key,third["revision"],snapshot)
    assert seek(3)["result"]==third["result"]
    assert seek(created["total"])["result"]==origin["result"]


def test_workbench_resolves_input_entry_limits_before_any_matching(runtime):
    host,main=runtime
    payload=value(main,"BAR_APPROX",rule='max_position_size(input.int(2,"Cap"))')
    payload["parameters"]={"Cap":3}
    # Do not let the diagnostic post-entry order alter the final position.
    payload["source"]=payload["source"].replace('strategy.order("halted",strategy.long,qty=2)','strategy.cancel("pending")')
    created=host.native.create(payload,"entry-limit")
    record=terminal(host.native,created["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    assert float(record["result"]["trades"][0]["qty"])==3


def test_workbench_unknown_daily_calendar_is_rejected_before_queueing(runtime):
    host,main=runtime
    payload=value(main,"BAR_APPROX")
    payload["exchange"]="unknown"
    with pytest.raises(ValueError,match="continuous-market"):
        host.native.create(payload,"unknown-calendar")


@pytest.mark.parametrize("name",["max_drawdown","max_intraday_loss"])
@pytest.mark.parametrize("mode",MODES)
def test_workbench_equity_stops_observe_marks_without_fill_callbacks(runtime,name,mode):
    host,main=runtime
    payload=value(main,mode,rule=f'{name}(1,strategy.cash)')
    record=terminal(host.native,host.native.create(payload,"equity-stop")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    report=record["result"]
    assert report["pine_risk_stops"]["blocked"] and Decimal(report["position"]["position_qty"])==0
    assert report["pine_risk_stops"]["trips"][0]["function"]=="strategy.risk."+name


def test_workbench_consecutive_loss_days_close_and_block_at_next_utc_session(runtime):
    from tests.test_native_additional_inputs import additional
    host,main=runtime
    payload=value(main,"BAR_APPROX",rule='max_cons_loss_days(1)')
    payload.update(additional(host,"daily-loss","BTCUSDT","1d",86400000,[100,100,90,90,90,90]))
    payload["context"]={"symbol":"BINANCE:BTCUSDT","timeframe":"1D"}
    payload["source"]='''//@version=6
strategy("Loss days")
if false
    strategy.risk.max_cons_loss_days(1)
if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if bar_index==1
    strategy.close_all()
if bar_index>=2
    strategy.order("ignored",strategy.long,qty=2,limit=1)
'''
    record=terminal(host.native,host.native.create(payload,"loss-days")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    stop=record["result"]["pine_risk_stops"]
    assert stop["blocked"] and stop["trips"][0]["consecutive_loss_days"]==1
    assert [row["script_order_id"] for row in record["result"]["trades"]]==["L",""]


def test_stale_sampled_quote_cannot_create_a_synthetic_closing_fill(runtime):
    host,main=runtime
    payload=value(main,"BOOK_SAMPLED",closing=True,fresh=False)
    record=terminal(host.native,host.native.create(payload,"stale-close")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    first=record["result"]["trades"][0]
    assert first["reason"]=="DEPTH_WALK" and first["event_time_ms"]==60000


def test_workbench_entry_direction_reduces_owned_position_without_opening_a_disallowed_side(runtime):
    host,main=runtime
    payload=value(main,"BAR_APPROX",rule='allow_entry_in(strategy.direction.long)')
    payload["source"]='''//@version=6
strategy("Direction")
if false
    strategy.risk.allow_entry_in(strategy.direction.long)
if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if bar_index==1 or bar_index==3
    strategy.entry("S",strategy.short,qty=7)
'''
    record=terminal(host.native,host.native.create(payload,"direction")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    assert [float(row["qty"]) for row in record["result"]["trades"]]==[2,2]
    assert Decimal(record["result"]["position"]["position_qty"])==0
