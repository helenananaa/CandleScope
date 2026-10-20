"""Host-owned replay checkpoints; interpreter reconstruction never rematches fills."""
import json
from .errors import BacktestError

CONTRACT="candlescope.external-replay/1"


def validate_state(wire,state):
    from .native import digest
    from .external import host_identity
    content={key:value for key,value in state.items() if key!="checksum"}
    cursor=state.get("cursor")
    if (state.get("contract")!=CONTRACT or state.get("input_hash")!=digest(wire)
            or state.get("host_runtime_identity")!=wire["host_runtime_identity"]
            or wire["host_runtime_identity"]!=host_identity()
            or state.get("checksum")!=digest(content) or type(cursor) is not int
            or not 1<=cursor<=len(wire["bars"]) or len(state.get("accounts",[]))!=cursor
            or len((state.get("last_request") or {}).get("bars",[]))!=cursor):
        raise BacktestError("NATIVE_IDENTITY_MISMATCH","external account checkpoint identity differs")
    if wire["execution_fidelity"]!="BAR_APPROX":
        clock=state.get("clock") or {}
        event_cursor=clock.get("event_cursor")
        events=wire["execution_events"]
        if (clock.get("bar_cursor")!=cursor or type(event_cursor) is not int
                or not 1<=event_cursor<=len(events)
                or clock.get("last_sequence")!=events[event_cursor-1]["sequence"]):
            raise BacktestError("NATIVE_IDENTITY_MISMATCH","external execution cursor differs")
    if wire.get("pine_bar_path_contract"):
        clock = state.get("clock") or {}
        path = state.get("kernel", {}).get("pine_bar_path") or {}
        from .native_replay_storage import same_json
        if (clock.get("contract") != wire["pine_bar_path_contract"] or clock.get("bar_cursor") != cursor
                or len(clock.get("groups", [])) != cursor
                or path.get("contract") != wire["pine_bar_path_contract"]
                or clock.get("last_sequence") != path.get("sequence")
                or not same_json(clock.get("groups"), state["last_request"].get("execution_schedule"))):
            raise BacktestError("NATIVE_IDENTITY_MISMATCH", "Pine BAR path replay cursor differs")


def make_state(wire,cursor,kernel,orders,accounts,history,latest,clock,last_request,*,risk_stops=None):
    from .native import MAX_BYTES,digest,encoded
    value=json.loads(json.dumps(dict(contract=CONTRACT,input_hash=digest(wire),
        host_runtime_identity=wire["host_runtime_identity"],cursor=cursor,
        kernel=kernel.snapshot(),orders=orders.snapshot(),accounts=accounts,history=history,
        latest=latest,clock=clock,last_request=last_request,
        **({"pine_risk_stops":risk_stops.snapshot()} if risk_stops is not None and risk_stops.state is not None else {})),default=str,allow_nan=False))
    value["checksum"]=digest(value)
    if len(encoded(value).encode("utf-8"))>MAX_BYTES:
        raise BacktestError("BUDGET_EXCEEDED","external account checkpoint exceeds 64 MiB")
    validate_state(wire,value)
    return value
