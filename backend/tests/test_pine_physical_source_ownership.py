"""Physical facts may be shared inside one run, never its tentative ledger."""
from copy import deepcopy

import pytest

from app.backtest import pine_print_tick_execution as execution
from app.backtest.errors import BacktestError
from app.backtest.native import encoded
from tests.test_native_backtests import runtime as runtime,terminal,pytestmark as pytestmark
from tests.test_pine_event_realtime import SOURCE
from tests.test_pine_print_account import wire
from tests.test_pine_print_ticks import config


def test_physical_source_is_lazy_detached_and_recreated_for_the_next_execution(monkeypatch):
    value=wire()
    value["execution_events"][0]["payload"].update(bids=[["100","5"]],asks=[["101","6"]])
    original=deepcopy(value)
    build=execution.physical_events
    calls=[]
    def built(source):
        calls.append(source)
        return build(source)
    monkeypatch.setattr(execution,"physical_events",built)
    first=execution._physical_source(value)
    second=execution._physical_source(value)
    assert calls==[]
    rows=first()
    assert first() is rows and len(calls)==1
    other=second()
    assert other==rows and other is not rows and len(calls)==2
    book=next(row for row in rows if row.role=="ORDER_BOOK")
    book.payload["bids"][0][1]="changed-private-copy"
    assert value==original
    assert next(row for row in other if row.role=="ORDER_BOOK").payload["bids"]==[["100","5"]]
    value["execution_events"][0]["payload"]["bids"][0][1]="9"
    later=execution._physical_source(value)()
    assert next(row for row in later if row.role=="ORDER_BOOK").payload["bids"]==[["100","9"]]
    assert next(row for row in other if row.role=="ORDER_BOOK").payload["bids"]==[["100","5"]]


def test_lazy_physical_source_keeps_existing_admission_errors():
    value=wire();value["pine_v2_print_contract"]="unknown"
    source=execution._physical_source(value)
    for _ in range(2):
        with pytest.raises(BacktestError,match="invalid Pine V2"):
            source()


@pytest.mark.parametrize("mode",["TRADE_TAPE","BOOK_DEPTH"])
def test_window_trials_share_only_unchanged_source_facts_with_exact_complete_result(runtime,monkeypatch,mode):
    host,main=runtime
    value=config(main,mode,False,"LINEAR_PERP_ONE_WAY_V2")
    value["source"]=SOURCE
    run_clock=execution.run_clock
    def separate_sources(*args,**kwargs):
        kwargs.pop("_event_source",None)
        return run_clock(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(execution,"run_clock",separate_sources)
        control=terminal(host.native,host.native.create(value,"separate-physical-facts")["run_id"],timeout=90)
    assert control["state"]=="COMPLETED",control.get("error")
    witnesses=[]
    sources=[]
    build=execution.physical_events
    def built(wire):
        rows=build(wire)
        sources.append(rows)
        return rows
    def checked(*args,**kwargs):
        source=kwargs["_event_source"]
        rows=source()
        before=deepcopy(rows)
        witnesses.append((source,rows,kwargs.get("discovery_only",False)))
        try:return run_clock(*args,**kwargs)
        finally:assert rows==before
    with monkeypatch.context() as patch:
        patch.setattr(execution,"physical_events",built)
        patch.setattr(execution,"run_clock",checked)
        actual=terminal(host.native,host.native.create(value,"shared-physical-facts")["run_id"],timeout=90)
    assert actual["state"]=="COMPLETED",actual.get("error")
    assert encoded(actual["result"])==encoded(control["result"])
    assert any(discovery for _,_,discovery in witnesses) and not witnesses[-1][2]
    assert len(witnesses)>=3 and len(sources)==1
    assert all(source is witnesses[0][0] and rows is sources[0] for source,rows,_ in witnesses)
    # A second logical run must not inherit a mutable source retained by callers.
    sources[0][0].payload["rule_version"]="caller-mutation-after-completion"
    again=terminal(host.native,host.native.create(value,"new-physical-facts")["run_id"],timeout=90)
    assert again["state"]=="COMPLETED",again.get("error")
    assert encoded(again["result"])==encoded(control["result"])
