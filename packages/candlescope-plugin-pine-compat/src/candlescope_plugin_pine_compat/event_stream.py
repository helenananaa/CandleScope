"""Causal event requests inside the explicit whole-trial restart protocol."""
from bisect import bisect_right
from copy import deepcopy
from functools import lru_cache

import pine_compat
CONTRACT = "candlescope.pine-event-requests/1"


@lru_cache(maxsize=1)
def available():
    """Do not advertise new feed semantics on older same-version binaries."""
    try:
        if not callable(getattr(getattr(pine_compat,"ExternalSession",None),"failed_request_context",None)):
            return False
        from candlescope_plugin_sdk.event_requests import CONTRACT as SDK_CONTRACT, build_renko_stream
        if SDK_CONTRACT != CONTRACT or not callable(build_renko_stream):
            return False
        key='{"chart":"renko","style":"Traditional","param":1,"symbol":"B"}'
        def row(time, value):
            return dict(time=time,open=value,high=value,low=value,close=value,volume=1)
        source='//@version=6\nindicator("event capability")\nr=ticker.renko("B","Traditional",1)\nplot(request.security(r,"1",ta.cum(close),calc_bars_count=1))'
        value=pine_compat.compile_script(source).run([row(0,10),row(60000,10),row(120000,10)],
            chart_symbol="A",chart_timeframe="1",request_bars={key+":1":[row(0,1),row(60000,2),row(60000,3)]})
        if value.get("diagnostics") or value["plots"][0]["values"] != [None,3,3]:
            return False
        native=pine_compat.create_realtime_session(source.replace(',calc_bars_count=1',''),
            chart_symbol="A",chart_timeframe="1",request_bars={key+":1":[row(0,1)]})
        native.seed([row(0,10)])
        native.apply_request_feed_updates([dict(symbol=key,timeframe="1",kind="confirmed",bar=row(60000,n)) for n in (2,3)])
        native.update_confirmed(row(60000,10),execution_time=119999)
        return native.result()["plots"][0]["values"] == [1,6]
    except (AttributeError,ImportError,KeyError,TypeError,ValueError):
        return False


def capabilities():
    return {"event_request_contract":CONTRACT} if available() else {}


def required(analysis):
    features={item.get("feature","") for item in analysis.get("compatibility",{}).get("supported",[])}
    return "ticker.renko" in features and all(not name.startswith("ticker.") or name=="ticker.renko"
        for name in features) and available()


class EventRequests:
    def __init__(self, request):
        if request.get("event_request_contract") != CONTRACT or not available():
            raise ValueError("PINE_EVENT_REQUEST_UNSUPPORTED: qualified event feed runtime required")
        if "historical_plan" not in request or not request.get("window_feedback_contract"):
            raise ValueError("PINE_EVENT_REQUEST_UNSUPPORTED: frozen history and whole-trial feedback required")
        if any(context.get("bars") for context in request.get("contexts",[])):
            raise ValueError("PINE_EVENT_SOURCE_INVALID: causal contexts must start with empty prices")
        self.sources=deepcopy(request.get("event_sources"))
        if (not isinstance(self.sources,list) or not 1 <= len(self.sources) <= 17
                or sum(len(item.get("bars",[])) for item in self.sources)>200_000):
            raise ValueError("PINE_EVENT_SOURCE_INVALID: bounded frozen physical contexts required")
        keys=[(item.get("symbol"),item.get("timeframe")) for item in self.sources]
        if len(keys)!=len(set(keys)):
            raise ValueError("PINE_EVENT_SOURCE_INVALID: duplicate physical contexts")
        self.root=next((item for item in self.sources if (item["symbol"],item["timeframe"])
            == (request["context"]["symbol"],request["context"]["timeframe"])),None)
        if self.root is None or self.root["bars"]!=request["historical_plan"]:
            raise ValueError("PINE_EVENT_SOURCE_INVALID: physical chart history differs")
        self.streams={}
        self.reset()

    def reset(self):
        self.cursors={key:0 for key in self.streams}
        self.pending=False
        self.discovery=True

    def augment(self, opening):
        value=deepcopy(opening)
        contexts=value.setdefault("contexts",[])
        history=value.setdefault("requested_history",[])
        for stream in self.streams.values():
            contexts.append(dict(symbol=stream["symbol"],timeframe=stream["timeframe"],bars=[],
                **({"metadata":stream["metadata"]} if stream.get("metadata") else {})))
            history.append(dict(symbol=stream["symbol"],timeframe=stream["timeframe"],
                times_ms=[bar["time"]*1000 for bar in stream["bars"]]))
        return value

    def resolve(self, missing):
        if missing is None:
            return False
        if (not isinstance(missing,(tuple,list)) or len(missing)!=2
                or any(not isinstance(item,str) or not item for item in missing)):
            raise ValueError("PINE_EVENT_REQUEST_INVALID: invalid typed provider failure")
        symbol,timeframe=missing
        from candlescope_plugin_sdk.event_requests import renko_descriptor, build_renko_stream
        if renko_descriptor(symbol) is None:
            return False
        key=(symbol,timeframe)
        if key in self.streams or len(self.streams)>=16:
            raise ValueError("PINE_EVENT_REQUEST_INVALID: repeated missing context or discovery budget")
        stream=build_renko_stream(symbol,timeframe,self.sources)
        if sum(len(item["bars"]) for item in self.streams.values())+len(stream["bars"])>200_000:
            raise ValueError("PINE_EVENT_REQUEST_INVALID: combined event row budget")
        self.streams[key]=stream
        self.cursors[key]=0
        self.pending=True
        self.discovery=True
        return True

    def observe(self, observation, cursor, skip):
        value=deepcopy(observation)
        evaluation=value["evaluation"]
        legacy=evaluation.pop("request_data",None)
        if legacy:
            raise ValueError("PINE_EVENT_REQUEST_INVALID: legacy requested prices cannot mix with causal events")
        observed=evaluation.get("request_observed_at_ms",evaluation["event_time_ms"])
        if value["context"]["bar_state"]=="historical":
            observed=self.root["closes"][cursor+skip]
        updates=list(evaluation.get("request_updates",[]))
        for key,stream in self.streams.items():
            stop=bisect_right(stream["closes"],observed)
            start=self.cursors[key]
            if stop<start:
                raise ValueError("PINE_EVENT_REQUEST_INVALID: observation clock regressed")
            updates.extend(dict(symbol=stream["symbol"],timeframe=stream["timeframe"],kind="confirmed",
                bar=stream["bars"][index],available_at_ms=stream["closes"][index]) for index in range(start,stop))
            self.cursors[key]=stop
        evaluation.update(request_updates=sorted(updates,key=lambda item:item["available_at_ms"]),
                          request_observed_at_ms=observed)
        return value

    def status(self):
        return dict(contract=CONTRACT,pending=self.pending,requires_discovery=self.discovery,
            streams=[dict(symbol=key[0],timeframe=key[1],recipe_hash=stream["recipe_hash"],
                cursor=self.cursors[key]) for key,stream in self.streams.items()])
