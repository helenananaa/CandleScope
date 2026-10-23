"""Workbench historical tick lifecycle, checkpoint replay and ledger ownership."""
from copy import deepcopy
import time

from .errors import BacktestError
from .native_session import STREAM_CONTRACT
from .pine_history_tick_clock import HistoryTickClock
from .pine_stream import PineStream, WINDOW_FEEDBACK_CONTRACT, WindowRebaseRequired
from .pine_workbench import bar_event

CONTRACT="candlescope.pine-history-tick/1"


class ReplayWorker:
    supported=True

    def __init__(self,plugin,wire):
        self.plugin,self.wire,self.stream=plugin,wire,None

    def execute(self,runner,cancelled,*,resume,target,resume_owned=False):
        deadline=time.monotonic()+120
        saved=(resume or {}).get("clock",{}).get("stream")
        reusable=(self.stream is not None and isinstance(saved,dict)
                  and not self.stream.bar_open and self.stream.matches_checkpoint(saved))
        if not reusable:
            self.close()
            self.stream=open_stream(self.plugin,self.wire,cancelled,deadline,resume=resume,_resume_owned=resume_owned)
        self.stream.cancelled,self.stream.deadline=cancelled,deadline
        del saved
        from .external import _run_external_host
        return _run_external_host(self.plugin,self.wire,runner,cancelled,resume=resume,target=target,
            deadline=deadline,_scenario_runner=runner,_pine_stream=self.stream,
            _consume_resume=resume_owned and resume is not None)

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream=None


def open_stream(plugin,wire,cancelled,deadline,*,resume=None,_resume_owned=False):
    if (wire.get("pine_history_tick_contract")!=CONTRACT or wire.get("execution_fidelity")!="BAR_APPROX"
            or wire["identity"].get("external_stream_contract")!=STREAM_CONTRACT):
        raise BacktestError("EXTERNAL_UNSUPPORTED","historical Pine ticks require the negotiated BAR stream")
    names={"protocol","identity","source","parameters","libraries","context","contexts","host_settings",
           "risk_contract","closing_ticks","order_metadata_contract","currency_rates","request_update_contract","event_request_contract"}
    opening={key:deepcopy(value) for key,value in wire.items() if key in names and key not in {"protocol","identity"}}
    if wire.get("request_update_contract"):
        opening["contexts"]=[{**item,"bars":[]} for item in opening.get("contexts",[])]
    opening["historical_plan"]=deepcopy(wire["bars"])
    if wire["identity"].get("window_feedback_contract")==WINDOW_FEEDBACK_CONTRACT:
        opening["window_feedback_contract"]=WINDOW_FEEDBACK_CONTRACT
    if wire.get("request_update_contract"):
        from .pine_request_updates import WINDOW_CONTRACT,window_history
        if wire["identity"].get("request_window_plan_contract")!=WINDOW_CONTRACT:
            raise BacktestError("EXTERNAL_UNSUPPORTED","historical requested streams require window planning")
        opening["requested_history"]=window_history(wire.get("contexts",[]))
    from .pine_event_requests import attach_workbench
    attach_workbench(opening,wire)
    transport={"protocol":wire["protocol"],"identity":wire["identity"]}
    if resume is None:
        stream=PineStream(plugin,transport,opening,cancelled,deadline=deadline)
        try:
            prepare_window(stream,plugin,wire,cancelled,deadline)
            return stream
        except Exception:
            stream.close()
            raise
    from .external_replay import validate_state
    validate_state(wire,resume)
    saved=(resume.get("clock") or {}).get("stream")
    if not isinstance(saved,dict) or saved.get("opening")!=opening or saved.get("wire")!=transport:
        raise BacktestError("NATIVE_IDENTITY_MISMATCH","historical Pine stream checkpoint differs")
    observed=[]
    def verify(command,result):
        if command["operation"]=="stream_rebase": observed.clear()
        elif command["operation"]=="stream_observe": observed.extend(result["intents"])
    stream=PineStream.restore(plugin,saved,cancelled,deadline=deadline,verify=verify,_owned_checkpoint=_resume_owned)
    if observed!=resume["history"] or stream.last.get("window_status",{}).get("requires_discovery"):
        stream.close()
        raise BacktestError("LOOKAHEAD_VIOLATION","restored historical Pine window or intents differ")
    return stream


def prepare_window(stream,plugin,wire,cancelled,deadline):
    """Use disposable real Host ledgers; only the stable plan survives.

    No account state, fees, orders or requested prices from a tentative run are
    reused by the final execution. Journal replay reconstructs Pine only.
    """
    if not stream.last.get("window_status",{}).get("requires_discovery"):
        return
    from .external import _run_external_host
    from .native import invoke
    from .workbench_sensitivity import check_control
    for _attempt in range(64):
        check_control(cancelled,deadline)
        try:
            _run_external_host(plugin,wire,invoke,cancelled,deadline=deadline,
                _cost_scenario=True,_pine_stream=stream,_discovery_only=True)
        except WindowRebaseRequired:
            stream.rebase()
        else:
            stream.rebase(seal=True)
            return
    raise BacktestError("BUDGET_EXCEEDED","at most 64 observed Pine window discovery attempts")


def run_clock(stream,kernel,orders,wire,*,state=None,target=None,discovery_only=False,capture_checkpoint=True):
    from .workbench_sensitivity import check_control
    state=state or {}
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
            check_control(stream.cancelled,stream.deadline)
            if source.role=="BARS": cursor+=1
        kernel.run(remaining,lambda window,source:clock.close(source),fill_callback=lambda *_:[],
                   vertex_callback=clock.vertex,checkpoint_callback=committed,finalize=target==len(wire["bars"]))
    else:
        while cursor<target:
            check_control(stream.cancelled,stream.deadline)
            source=bar_event(wire,cursor,cursor+1)
            def close(point):
                clock.close(source)
                if wire.get("closing_ticks"): kernel.closing_tick()
            kernel.walk_bar(source,close,on_vertex=lambda point,index:clock.vertex(source,point,index))
            cursor+=1
        if target==len(wire["bars"]): kernel.finalize_orders()
    latest=clock.output()
    if discovery_only:
        return None
    latest["intents"]=deepcopy(clock.history)
    passes=[[item["evaluation"] for item in group] for group in clock.groups]
    if not capture_checkpoint:
        return latest,clock.history,clock.accounts,passes,{"groups":clock.groups},None
    saved=dict(contract=wire["pine_bar_path_contract"],history_tick_contract=CONTRACT,bar_cursor=cursor,
               last_sequence=kernel.path_sequence,groups=clock.groups,accounts=clock.accounts,history=clock.history,
               stream=stream.checkpoint(detached=False),latest=latest)
    if clock.feed is not None: saved["request_feed"]=clock.feed.snapshot()
    if wire.get("pine_v2_bar_contract"): saved["source_sequence"]=kernel.source_sequence
    # The coordinator's make_state JSON boundary detaches these values before
    # another command can advance this worker-owned stream.
    last_request=dict(bars=wire["bars"][:cursor],execution_schedule=clock.groups)
    return latest,clock.history,clock.accounts,passes,saved,last_request
