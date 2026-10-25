"""Workbench observed-print Pine streams over authoritative tape/book accounts."""
from copy import deepcopy
from decimal import Decimal
import time

from app.data_engine.interval_policy import parse_interval_spec
from app.market_dataset.snapshot import MarketEvent
from app.market_dataset.trades import assert_trade_stream
from .errors import BacktestError
from .native_session import STREAM_CONTRACT
from .pine_print_account import events as physical_events,apply_account,observe_market,record_decision,AUXILIARY,FIDELITIES
from .pine_request_updates import from_wire,pass_observations,validate_replay
from .pine_stream import PineStream,observations_match,seal_observation_group,materialize_observation_groups

CONTRACT="candlescope.pine-print-tick/1"


class _PhysicalSource:
    """One private source for a logical execution's read-only clock passes.

    Discovery discards its ledger, never changes these physical facts, and
    can reuse the same detached V2 payloads. A new execution/seek gets a new
    source. Materialize lazily at the original admission/deadline boundary.
    """
    def __init__(self,wire):
        self.wire,self.rows=wire,None

    def __call__(self):
        if self.rows is None:
            self.rows=physical_events(self.wire)
        return self.rows

    def release(self):
        self.rows=None


def _physical_source(wire):
    return _PhysicalSource(wire)


def open_stream(plugin,wire,cancelled,deadline,*,resume=None,_resume_owned=False,_event_source=None,
                _resume_validation=None):
    if (wire.get("pine_print_tick_contract")!=CONTRACT or wire.get("execution_fidelity") not in FIDELITIES
            or wire["identity"].get("external_stream_contract")!=STREAM_CONTRACT):
        raise BacktestError("EXTERNAL_UNSUPPORTED","physical Pine ticks require the negotiated print stream")
    names={"source","parameters","libraries","context","contexts","host_settings","risk_contract",
           "closing_ticks","order_metadata_contract","currency_rates","request_update_contract","event_request_contract"}
    opening={key:deepcopy(value) for key,value in wire.items() if key in names}
    if opening.get("contexts") and not wire.get("request_update_contract"):
        raise BacktestError("EXTERNAL_UNSUPPORTED","physical tick requests require observed append-only feeds")
    if wire.get("request_update_contract"):
        opening["contexts"]=[{**item,"bars":[]} for item in opening.get("contexts",[])]
    if wire.get("event_request_contract"):
        from .pine_event_requests import realtime_plan,attach_workbench
        realtime_plan(opening,wire["identity"])
        opening["historical_plan"]=deepcopy(wire["bars"])
        if wire.get("request_update_contract"):
            from .pine_request_updates import WINDOW_CONTRACT,window_history
            if wire["identity"].get("request_window_plan_contract")!=WINDOW_CONTRACT:
                raise BacktestError("EXTERNAL_UNSUPPORTED","event print requests require window planning")
            opening["requested_history"]=window_history(wire.get("contexts",[]))
        attach_workbench(opening,wire)
    transport={"protocol":wire["protocol"],"identity":wire["identity"]}
    if resume is None:
        stream=PineStream(plugin,transport,opening,cancelled,deadline=deadline)
        try:
            from .pine_history_tick_execution import prepare_window
            prepare_window(stream,plugin,wire,cancelled,deadline,_event_source=_event_source)
            return stream
        except Exception:
            stream.close()
            raise
    from .external_replay import validate_state,_OwnedResumeValidation
    if _resume_validation is None:
        validate_state(wire,resume)
    else:
        if type(_resume_validation) is not _OwnedResumeValidation or not _resume_owned:
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR","owned validation requires an exclusive Pine resume")
        _resume_validation.check(wire,resume)
    saved=(resume.get("clock") or {}).get("stream")
    if not isinstance(saved,dict) or saved.get("opening")!=opening or saved.get("wire")!=transport:
        raise BacktestError("NATIVE_IDENTITY_MISMATCH","physical Pine stream checkpoint differs")
    observed=[]
    def verify(command,result):
        if command["operation"]=="stream_rebase": observed.clear()
        elif command["operation"]=="stream_observe": observed.extend(result["intents"])
    stream=PineStream.restore(plugin,saved,cancelled,deadline=deadline,verify=verify,_owned_checkpoint=_resume_owned)
    if observed!=resume["history"] or stream.last.get("window_status",{}).get("requires_discovery"):
        stream.close()
        raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX","physical Pine replayed intents differ")
    return stream


class ReplayWorker:
    supported=True

    def __init__(self,plugin,wire):
        self.plugin,self.wire,self.stream=plugin,wire,None
        self.history=None

    def execute(self,runner,cancelled,*,resume,target,resume_owned=False,capture_owned=False):
        deadline=time.monotonic()+120
        from .external_replay import _OwnedResumeValidation
        validation=_OwnedResumeValidation(self.wire,resume) if resume_owned and resume is not None else None
        source=_physical_source(self.wire)
        saved=(resume or {}).get("clock",{}).get("stream")
        if not (self.stream is not None and isinstance(saved,dict)
                and not self.stream.bar_open and self.stream.matches_checkpoint(saved)
                and self.history==resume.get("history")):
            self.close()
            self.stream=open_stream(self.plugin,self.wire,cancelled,deadline,resume=resume,_resume_owned=resume_owned,
                _event_source=source,_resume_validation=validation)
        self.stream.cancelled,self.stream.deadline=cancelled,deadline
        del saved
        from .external import _run_external_host
        result,state=_run_external_host(self.plugin,self.wire,runner,cancelled,resume=resume,target=target,
            deadline=deadline,_scenario_runner=runner,_pine_stream=self.stream,
            _consume_resume=resume_owned and resume is not None,_capture_owned=capture_owned,_event_source=source,
            _resume_validation=validation)
        self.history=deepcopy(state["history"])
        return result,state

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream=None
        self.history=None


def validate_state(wire,state):
    from .native_replay_storage import same_json
    clock=state.get("clock") or {}
    saved=clock.get("stream") or {}
    groups=clock.get("groups")
    cursor=state["cursor"]
    skip=saved.get("input_skip")
    if (clock.get("contract")!=CONTRACT or type(skip) is not int or not 0<=skip<=len(wire["bars"])
            or saved.get("cursor")!=max(0,cursor-skip) or saved.get("bar_open") is not False
            or saved.get("intents")!=len(state["history"])
            or not isinstance(groups,list) or len(groups)!=cursor
            or not same_json(groups,state["last_request"].get("execution_schedule"))
            or not same_json(clock.get("accounts"),state["accounts"])
            or not same_json(clock.get("history"),state["history"])):
        raise BacktestError("NATIVE_IDENTITY_MISMATCH","physical Pine tick checkpoint cursors differ")
    if not observations_match(saved,groups) or any(
            bool(group) if index<skip else (not group or group[-1]["evaluation"].get("account")!=state["accounts"][index]
            or group[-1]["evaluation"].get("confirmed") is not True) for index,group in enumerate(groups)):
        raise BacktestError("NATIVE_IDENTITY_MISMATCH","physical Pine transcript differs from its stream journal")


class PrintTickClock:
    def __init__(self,stream,kernel,orders,wire,*,state=None,_compact_groups=False,_owned_state=False,
                 _chain_commits=True):
        self.stream,self.kernel,self.orders,self.wire=stream,kernel,orders,wire
        self._compact_groups=_compact_groups
        self._chain_commits=_chain_commits
        self._pending_commit=False
        restoring=bool(state)
        state={key:value for key,value in (state or {}).items()
            if key in {"groups","accounts","history","bar_cursor","last_sequence","event_cursor","request_feed"}}
        if not _owned_state:
            state=deepcopy(state)
        self.groups,self.accounts,self.history=(state.get(key,[]) for key in ("groups","accounts","history"))
        self.cursor=state.get("bar_cursor",0)
        self.last_sequence=state.get("last_sequence",0)
        self.event_cursor=state.get("event_cursor",0)
        self.visible=None
        # Checkpoints are taken at closed bars; an open bar's exact quantity
        # accumulator is reconstructed only by replaying its physical prints.
        self.visible_volume=Decimal(0)
        self.feed=from_wire(wire)
        if self.feed is not None and restoring:
            validate_replay(self.feed,state.get("request_feed"),pass_observations(self.groups,scheduled=True))
        if stream.bar_open or stream.cursor!=max(0,self.cursor-stream.input_skip):
            raise BacktestError("NATIVE_IDENTITY_MISMATCH","physical Pine and ledger cursors differ")

    def observe(self,event,*,confirmed=False,trigger="realtime_tick"):
        from .external import account_feedback_profit
        from .pine_workbench import check_risk_response
        from .workbench_sensitivity import check_control
        check_control(self.stream.cancelled,self.stream.deadline)
        first=len(self.groups)==self.cursor
        skipped=self.cursor<self.stream.input_skip
        self.orders.feedback()
        account=self.kernel.account
        feedback=dict(time=self.visible["time"],position_size=float(account.position_qty),
            position_avg_price=None if account.entry_price is None else float(account.entry_price),
            equity=float(account.equity()),initial_capital=float(self.kernel.initial_balance),
            netprofit=float(account_feedback_profit(account,self.kernel.initial_balance)),openprofit=float(account.unrealized()))
        if skipped:
            if confirmed:
                self.groups.append([])
                self.accounts.append(feedback)
            return
        # Visible bars contain only scalar OHLCV values. Each observation owns
        # its mapping while subsequent prints advance the clock's mapping.
        evaluation=dict(bar=dict(self.visible),account=feedback,event_time_ms=event.event_time_ms,confirmed=confirmed)
        if self.feed is not None:
            evaluation.update(request_observed_at_ms=event.event_time_ms,request_updates=self.feed.advance(event.event_time_ms))
        observation=dict(evaluation=evaluation,context=dict(bar_state="realtime",trigger=trigger,is_new=first))
        result=(self.stream.begin_and_observe(self.visible,bar_state="realtime",observation=observation,_owned=True,
                    _commit_previous=self._pending_commit)
                if first else self.stream.observe(observation,_owned=True))
        self._pending_commit=False
        current=result["intents"]
        if len(current)>64:
            raise BacktestError("BUDGET_EXCEEDED","at most 64 intents per observed Pine tick")
        self.orders.configure(result.get("pyramiding",1))
        check_risk_response(self.orders,self.wire,result)
        if first:
            self.groups.append([])
            self.accounts.append(None)
        # This new observation already owns its bar, scalar feedback and feed
        # deltas; the evaluator journal encodes the command before returning.
        self.groups[-1].append(observation)
        self.accounts[-1]=feedback
        self.history.extend(current)
        intents=self.orders.translate(current,event.sequence)
        record_decision(self.kernel,dict(sequence=event.sequence,watermark_ms=event.event_time_ms,intents=intents,
            signal_bar=self.cursor,pass_index=len(self.groups[-1])-1,trigger=trigger.upper()))
        self.kernel._enqueue_many(intents,current_sequence=event.sequence)

    def flush_commit(self):
        if self._pending_commit:
            self.stream.commit()
            self._pending_commit=False

    def close_bar(self):
        if self.visible is None:
            raise BacktestError("DATA_GAP_REJECTED","physical Pine chart bar has no observed prints")
        from .pine_workbench import bar_event
        source=bar_event(self.wire,self.cursor,self.last_sequence)
        self.visible=deepcopy(self.wire["bars"][self.cursor])
        event=MarketEvent(self.last_sequence,source.event_time_ms,"TRADES",dict(price=str(self.visible["close"]),qty="0"))
        self.kernel._last_event=event
        observe_market(self.kernel,event)
        self.observe(event,confirmed=True,trigger="bar_close")
        if self.wire.get("closing_ticks"):
            from app.simulation.closing_tick import match_closing_tick
            match_closing_tick(self.kernel,source,self.last_sequence,
                on_fill=(lambda _bar,tick:self.observe(tick,confirmed=True,trigger="closing_fill"))
                    if self.wire.get("fill_recalculation") else None)
            self.kernel._record_equity_point(dict(sequence=self.last_sequence,event_time_ms=source.event_time_ms,
                equity=str(self.kernel.account.equity()),position_qty=str(self.kernel.account.position_qty)))
        if self.cursor>=self.stream.input_skip:
            if self._chain_commits:
                # All closing observations/callbacks have finished. Commit
                # takes no account input and produces no intents. Defer only
                # its transport until the next begin/observe, preserving the
                # complete command order and each checked acknowledgement.
                self._pending_commit=True
            else:
                self.stream.commit()
        if self._compact_groups:
            seal_observation_group(self.groups)
        self.cursor+=1
        self.visible=None


def run_clock(stream,kernel,orders,wire,*,state=None,target=None,discovery_only=False,capture_checkpoint=True,
              compact_groups=True,_capture_owned=False,_consume_state=False,_chain_commits=True,_event_source=None):
    clock=PrintTickClock(stream,kernel,orders,wire,state=state,_compact_groups=compact_groups,
        _owned_state=_consume_state,_chain_commits=_chain_commits)
    interval=parse_interval_spec(wire["interval"])
    events=physical_events(wire) if _event_source is None else _event_source()
    kernel.source_kind=assert_trade_stream(tuple(event for event in events if event.role=="TRADES"))
    target=len(wire["bars"]) if target is None else target
    end=interval.next_ms(wire["bars"][target-1]["time"]*1000)
    from .workbench_sensitivity import check_control
    for event in events[clock.event_cursor:]:
        if event.event_time_ms>=end: break
        check_control(stream.cancelled,stream.deadline)
        while interval.next_ms(wire["bars"][clock.cursor]["time"]*1000)<=event.event_time_ms:
            clock.close_bar()
        kernel._last_event=event
        if event.role in AUXILIARY:
            apply_account(kernel,event,record_equity=kernel._market_event_count>0)
        elif event.role=="ORDER_BOOK":
            kernel._apply_book(event)
            if kernel.market_observer is not None: kernel.market_observer(event)
        else:
            price=float(event.payload["price"])
            qty=Decimal(str(event.payload["qty"]))
            if clock.visible is None:
                clock.visible_volume=qty
                clock.visible=dict(time=wire["bars"][clock.cursor]["time"],open=price,high=price,low=price,close=price,volume=float(qty))
            else:
                clock.visible_volume+=qty
                clock.visible.update(high=max(clock.visible["high"],price),low=min(clock.visible["low"],price),
                    close=price,volume=float(clock.visible_volume))
            if wire.get("pine_v2_print_contract"): kernel._market_event_count+=1
            observe_market(kernel,event)
            kernel._match(event)
            clock.observe(event)
            kernel.equity_curve.append(dict(sequence=event.sequence,event_time_ms=event.event_time_ms,
                equity=str(kernel.account.equity()),position_qty=str(kernel.account.position_qty)))
        clock.last_sequence=event.sequence
        clock.event_cursor+=1
    while clock.cursor<target: clock.close_bar()
    # Only discovery needs the source again. Drop the finished execution's
    # cache and local reference before materializing its complete output and
    # checkpoint graphs; a later seek always creates another private source.
    if not discovery_only and _event_source is not None:
        _event_source.release()
    del events
    # No pending command may cross finalization, output, checkpoint or discovery
    # handoff. A restored clock always starts with the exact committed cursor.
    clock.flush_commit()
    if target==len(wire["bars"]): kernel.finalize_orders()
    output=stream.output()
    if discovery_only:
        return None
    materialize_observation_groups(clock.groups)
    latest={**output,"raw_output":output["output"],"graphics":output["output"].get("plots",[]),"intents":deepcopy(clock.history)}
    passes=[[item["evaluation"] for item in group] for group in clock.groups]
    if not capture_checkpoint:
        return latest,clock.history,clock.accounts,passes,{"groups":clock.groups},None
    saved=dict(contract=CONTRACT,bar_cursor=clock.cursor,last_sequence=clock.last_sequence,event_cursor=clock.event_cursor,
        groups=clock.groups,accounts=clock.accounts,history=clock.history,
        stream=stream.checkpoint(detached=_capture_owned,compact=True),latest=latest)
    if clock.feed is not None: saved["request_feed"]=clock.feed.snapshot()
    # Exclusive replay capture transfers the finished clock graphs and freezes
    # the live stream header here. Default capture detaches all values later.
    last_request=dict(bars=wire["bars"][:clock.cursor],execution_schedule=clock.groups)
    return latest,clock.history,clock.accounts,passes,saved,last_request
