"""Host entry point for the shared deterministic frozen event-source contract."""
from copy import deepcopy
import json
from app.data_engine.interval_policy import parse_interval_spec

CONTRACT = "candlescope.pine-event-requests/1"


def realtime_plan(opening, identity):
    from .errors import BacktestError
    from .pine_stream import REALTIME_WINDOW_CONTRACT,WINDOW_FEEDBACK_CONTRACT
    if (identity.get("realtime_window_plan_contract")!=REALTIME_WINDOW_CONTRACT
            or identity.get("window_feedback_contract")!=WINDOW_FEEDBACK_CONTRACT):
        raise BacktestError("EXTERNAL_UNSUPPORTED","event realtime requests require observed realtime windows")
    opening.update(plan_state="realtime",realtime_window_plan_contract=REALTIME_WINDOW_CONTRACT,
                   window_feedback_contract=WINDOW_FEEDBACK_CONTRACT)


def chart_realtime_context(config,events,*,max_bars,max_bytes):
    """Freeze completed chart rows for validation without preloading prices."""
    if not config.get("pine_realtime_ticks") or not json.loads(config["strategy_source"]).get("eventRequestContract"):
        return {}
    from .pine_chart_bar import fixed_history
    from .chart_book import derive_chart_bars
    from app.simulation.trade_bar_builder import derive_complete_trade_bars
    rows=(derive_chart_bars(events,config["signal_interval"],int(config["end_time_ms"]))
          if config["fidelity_mode"] in {"BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED"}
          else derive_complete_trade_bars(events,config["signal_interval"]))
    _,plan=fixed_history(rows,max_bars=max_bars,max_bytes=max_bytes)
    if not plan:
        from .errors import BacktestError
        raise BacktestError("DATA_GAP_REJECTED","event window discovery requires completed chart history")
    return {"pineHistoricalBars":plan}


def trial_events(events,context,pending):
    """A tentative pass ends at the last known close before live extension."""
    if not pending or not context.get("pineRealtimeTicks"):
        return events,None
    rows=context["pineHistoricalBars"]
    if not rows:
        from .errors import BacktestError
        raise BacktestError("DATA_GAP_REJECTED","event window discovery requires completed chart history")
    cutoff=parse_interval_spec(context["pineChartInterval"]).next_ms(rows[-1]["time"]*1000)-1
    return tuple(event for event in events if event.event_time_ms<=cutoff),cutoff


def renko_descriptor(symbol):
    from candlescope_plugin_sdk.event_requests import renko_descriptor as decode
    return decode(symbol)


def build_renko_stream(symbol,timeframe,physical_streams):
    from candlescope_plugin_sdk.event_requests import build_renko_stream as build
    return build(symbol,timeframe,physical_streams)

def frozen_sources(context, bars, interval, requested):
    spec = parse_interval_spec(interval)
    root = dict(symbol=context["symbol"], timeframe=context["timeframe"], bars=deepcopy(bars),
        closes=[spec.next_ms(row["time"]*1000)-1 for row in bars],
        **({"metadata":deepcopy(context["metadata"])} if context.get("metadata") else {}))
    result = [root]
    for stream in requested:
        if (stream["symbol"],stream["timeframe"]) == (root["symbol"],root["timeframe"]):
            if stream["bars"]!=root["bars"] or stream["closes"]!=root["closes"]:
                raise ValueError("PINE_EVENT_SOURCE_INVALID: chart alias differs from frozen physical source")
        else:
            result.append(deepcopy(stream))
    return result


def attach(opening, identity, contract, bars, interval, requested):
    if contract is None:
        return
    if contract != CONTRACT or identity.get("event_request_contract") != CONTRACT:
        raise ValueError("PINE_EVENT_REQUEST_UNSUPPORTED: compiled event contract differs from runtime")
    opening.update(event_request_contract=CONTRACT,
        event_sources=frozen_sources(opening["context"],bars,interval,requested))


def attach_workbench(opening, wire):
    if not wire.get("event_request_contract"):
        return
    requested=[]
    for context, interval in zip(wire.get("contexts",[]),wire.get("context_intervals",[]),strict=True):
        spec=parse_interval_spec(interval)
        requested.append({**context,"closes":[spec.next_ms(row["time"]*1000)-1 for row in context["bars"]]})
    attach(opening,wire["identity"],wire["event_request_contract"],wire["bars"],wire["interval"],requested)


__all__ = ["CONTRACT", "build_renko_stream", "renko_descriptor", "frozen_sources", "attach", "attach_workbench"]
