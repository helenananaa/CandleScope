"""Host entry point for the shared deterministic frozen event-source contract."""
from copy import deepcopy
from app.data_engine.interval_policy import parse_interval_spec

CONTRACT = "candlescope.pine-event-requests/1"


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
