"""Chart provider lifecycle over the negotiated external observation stream."""
from copy import deepcopy

from app.backtest.native_session import STREAM_CONTRACT
from app.backtest.pine_stream import PineStream
from .protocol import StrategyProviderError


def ensure(provider, runtime, symbol, timeframe, contexts):
    opening={key:value for key,value in provider.wire.items() if key not in {
        "protocol","identity","execution_schedule_contract"}}
    opening.update(context={"symbol":symbol,"timeframe":timeframe,
        **({"metadata":provider.context["pineChartMetadata"]} if provider.context.get("pineChartMetadata") else {})},
        contexts=contexts)
    if provider.stream is None:
        provider._stream_environment=deepcopy(opening)
        if not provider.realtime_streaming:
            opening["historical_plan"]=provider.context["pineHistoricalBars"]
        provider.stream=PineStream(runtime,{key:provider.wire[key] for key in ("protocol","identity")},
            opening,provider.cancelled)
    elif provider._stream_environment!=opening:
        raise StrategyProviderError("IDENTITY_MUTATION","Pine stream environment changed during execution")
    return provider.stream


def observe(provider,runtime,symbol,timeframe,contexts,index,pass_index):
    stream=ensure(provider,runtime,symbol,timeframe,contexts)
    if index<stream.input_skip:
        return {**stream.last,"intents":[],"intent_base":len(provider.history)}
    if pass_index==0:
        if stream.bar_open: stream.commit()
        if stream.cursor!=index-stream.input_skip:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION","chart and Pine stream cursors differ")
        stream.begin(provider.bars[index] if provider.realtime_streaming else provider.context["pineHistoricalBars"][index],
                     bar_state="realtime" if provider.realtime_streaming else "historical")
    observation=dict(evaluation=provider.execution_passes[index][-1],context=provider.execution_contexts[index][-1])
    return stream.observe(observation)


def snapshot(provider):
    stream=provider.stream
    if stream is None: return deepcopy(provider._closed_stream_checkpoint)
    if stream.bar_open and provider.execution_passes[-1][-1]["confirmed"]:
        stream.commit()
    return stream.checkpoint()


def restore(provider,payload,runtime):
    saved=payload.get("stream_checkpoint")
    if saved is None:
        if provider.bars:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION","Pine stream checkpoint is missing")
        return
    if (saved.get("wire")!={key:provider.wire[key] for key in ("protocol","identity")}
            or saved.get("opening",{}).get("historical_plan")!=provider.context.get("pineHistoricalBars")
            or saved.get("intents")!=len(provider.history)):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION","Pine stream checkpoint environment differs")
    for key,value in provider.wire.items():
        if key not in {"protocol","identity","execution_schedule_contract"} and saved["opening"].get(key)!=value:
            raise StrategyProviderError("IDENTITY_MUTATION","restored Pine stream source or settings differ")
    if saved["opening"].get("context",{}).get("metadata")!=provider.context.get("pineChartMetadata"):
        raise StrategyProviderError("IDENTITY_MUTATION","restored Pine stream metadata differs")
    count=len(provider.bars)
    if saved.get("cursor")!=max(0,count-saved["input_skip"]-int(saved["bar_open"])):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION","restored chart and stream cursors differ")
    observed=[]
    def verify(command,result):
        if command["operation"]=="stream_observe": observed.extend(result["intents"])
    provider.stream=PineStream.restore(runtime,deepcopy(saved),provider.cancelled,verify=verify)
    if observed!=provider.history:
        provider.stream.close()
        provider.stream=None
        raise StrategyProviderError("LOOKAHEAD_VIOLATION","restored chart intents differ from the Pine transcript")
    provider._stream_environment={key:value for key,value in saved["opening"].items() if key!="historical_plan"}
