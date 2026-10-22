"""Workbench historical tick lifecycle, checkpoint replay and ledger ownership."""
from copy import deepcopy
import time

from .errors import BacktestError
from .native_session import STREAM_CONTRACT
from .pine_history_tick_clock import HistoryTickClock
from .pine_stream import PineStream
from .pine_workbench import bar_event

CONTRACT="candlescope.pine-history-tick/1"


class ReplayWorker:
    supported=True

    def __init__(self,plugin,wire):
        self.plugin,self.wire,self.stream=plugin,wire,None

    def execute(self,runner,cancelled,*,resume,target):
        deadline=time.monotonic()+120
        saved=(resume or {}).get("clock",{}).get("stream")
        reusable=(self.stream is not None and isinstance(saved,dict)
                  and not self.stream.bar_open and self.stream.checkpoint()==saved)
        if not reusable:
            self.close()
            self.stream=open_stream(self.plugin,self.wire,cancelled,deadline,resume=resume)
        self.stream.cancelled,self.stream.deadline=cancelled,deadline
        from .external import _run_external_host
        return _run_external_host(self.plugin,self.wire,runner,cancelled,resume=resume,target=target,
            deadline=deadline,_scenario_runner=runner,_pine_stream=self.stream)

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream=None


def open_stream(plugin,wire,cancelled,deadline,*,resume=None):
    if (wire.get("pine_history_tick_contract")!=CONTRACT or wire.get("execution_fidelity")!="BAR_APPROX"
            or wire["identity"].get("external_stream_contract")!=STREAM_CONTRACT):
        raise BacktestError("EXTERNAL_UNSUPPORTED","historical Pine ticks require the negotiated BAR stream")
    names={"protocol","identity","source","parameters","libraries","context","contexts","host_settings",
           "risk_contract","closing_ticks","order_metadata_contract","currency_rates","request_update_contract"}
    opening={key:deepcopy(value) for key,value in wire.items() if key in names and key not in {"protocol","identity"}}
    if wire.get("request_update_contract"):
        opening["contexts"]=[{**item,"bars":[]} for item in opening.get("contexts",[])]
    opening["historical_plan"]=deepcopy(wire["bars"])
    transport={"protocol":wire["protocol"],"identity":wire["identity"]}
    if resume is None:
        return PineStream(plugin,transport,opening,cancelled,deadline=deadline)
    from .external_replay import validate_state
    validate_state(wire,resume)
    saved=(resume.get("clock") or {}).get("stream")
    if not isinstance(saved,dict) or saved.get("opening")!=opening or saved.get("wire")!=transport:
        raise BacktestError("NATIVE_IDENTITY_MISMATCH","historical Pine stream checkpoint differs")
    return PineStream.restore(plugin,saved,cancelled,deadline=deadline)


def run_clock(stream,kernel,orders,wire,*,state=None,target=None):
    state=deepcopy(state or {})
    cursor=state.get("bar_cursor",0)
    target=len(wire["bars"]) if target is None else target
    if (stream.bar_open or stream.cursor+stream.input_skip!=max(cursor,stream.input_skip)
            or state.get("last_sequence",0)!=kernel.path_sequence):
        raise BacktestError("NATIVE_IDENTITY_MISMATCH","historical Pine stream and ledger cursors differ")
    clock=HistoryTickClock(stream,kernel,orders,wire,state=state)
    if wire.get("pine_v2_bar_contract"):
        from .pine_workbench_v2 import events
        last=bar_event(wire,target-1,0).event_time_ms
        remaining=[event for event in events(wire) if event.sequence>kernel.source_sequence and event.event_time_ms<=last]
        def committed(source):
            nonlocal cursor
            if source.role=="BARS": cursor+=1
        kernel.run(remaining,lambda window,source:clock.close(source),fill_callback=lambda *_:[],
                   vertex_callback=clock.vertex,checkpoint_callback=committed,finalize=target==len(wire["bars"]))
    else:
        while cursor<target:
            source=bar_event(wire,cursor,cursor+1)
            def close(point):
                clock.close(source)
                if wire.get("closing_ticks"): kernel.closing_tick()
            kernel.walk_bar(source,close,on_vertex=lambda point,index:clock.vertex(source,point,index))
            cursor+=1
        if target==len(wire["bars"]): kernel.finalize_orders()
    latest=clock.output()
    latest["intents"]=deepcopy(clock.history)
    saved=dict(contract=wire["pine_bar_path_contract"],history_tick_contract=CONTRACT,bar_cursor=cursor,
               last_sequence=kernel.path_sequence,groups=clock.groups,accounts=clock.accounts,history=clock.history,
               stream=stream.checkpoint(),latest=latest)
    if clock.feed is not None: saved["request_feed"]=clock.feed.snapshot()
    if wire.get("pine_v2_bar_contract"): saved["source_sequence"]=kernel.source_sequence
    last_request=dict(bars=deepcopy(wire["bars"][:cursor]),execution_schedule=deepcopy(clock.groups))
    passes=[[item["evaluation"] for item in group] for group in clock.groups]
    return latest,clock.history,clock.accounts,passes,saved,last_request
