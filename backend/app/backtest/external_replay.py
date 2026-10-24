"""Host-owned replay checkpoints; interpreter reconstruction never rematches fills."""
from .errors import BacktestError

CONTRACT="candlescope.external-replay/1"


def validate_state(wire,state):
    from .native import digest
    from .native_checkpoint import checkpoint_digest
    from .external import host_identity
    content={key:value for key,value in state.items() if key!="checksum"}
    cursor=state.get("cursor")
    if (state.get("contract")!=CONTRACT or state.get("input_hash")!=digest(wire)
            or state.get("host_runtime_identity")!=wire["host_runtime_identity"]
            or wire["host_runtime_identity"]!=host_identity()
            or state.get("checksum")!=checkpoint_digest(content) or type(cursor) is not int
            or not 1<=cursor<=len(wire["bars"]) or len(state.get("accounts",[]))!=cursor
            or len((state.get("last_request") or {}).get("bars",[]))!=cursor):
        raise BacktestError("NATIVE_IDENTITY_MISMATCH","external account checkpoint identity differs")
    if wire["execution_fidelity"]!="BAR_APPROX":
        clock=state.get("clock") or {}
        event_cursor=clock.get("event_cursor")
        events = wire["execution_events"]
        if wire.get("pine_v2_print_contract"):
            from .pine_print_account import event_coordinates
            events = event_coordinates(wire)
        if (clock.get("bar_cursor")!=cursor or type(event_cursor) is not int
                or not 1<=event_cursor<=len(events)
                or clock.get("last_sequence")!=events[event_cursor-1]["sequence"]):
            raise BacktestError("NATIVE_IDENTITY_MISMATCH","external execution cursor differs")
        if wire.get("pine_v2_print_contract"):
            from app.data_engine.interval_policy import parse_interval_spec
            end = parse_interval_spec(wire["interval"]).next_ms(wire["bars"][cursor - 1]["time"] * 1000)
            expected_cursor = sum(row["event_time_ms"] < end for row in events)
            expected_prints = sum(row["role"] == "TRADES" for row in events[:expected_cursor])
            if event_cursor != expected_cursor or state.get("kernel", {}).get("market_event_count") != expected_prints:
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "V2 physical/account checkpoint horizon differs")
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
        if wire.get("pine_history_tick_contract"):
            stream=clock.get("stream") or {}
            skip=stream.get("input_skip")
            if (clock.get("history_tick_contract")!=wire["pine_history_tick_contract"]
                    or type(skip) is not int or not 0<=skip<=len(wire["bars"])
                    or type(stream.get("cursor")) is not int or stream["cursor"]!=max(0,cursor-skip)
                    or stream.get("bar_open") is not False
                    or not same_json(clock.get("accounts"),state.get("accounts"))
                    or not same_json(clock.get("history"),state.get("history"))
                    or any(len(group)!=(0 if index<skip else 4) for index,group in enumerate(clock["groups"]))):
                raise BacktestError("NATIVE_IDENTITY_MISMATCH","historical Pine tick checkpoint differs")
            from .pine_stream import observations_match
            if not observations_match(stream,clock["groups"]):
                raise BacktestError("NATIVE_IDENTITY_MISMATCH","historical Pine observations differ from its stream journal")
        if wire.get("pine_v2_bar_contract"):
            chart = state.get("kernel", {}).get("pine_chart_bar") or {}
            v2 = state.get("kernel", {}).get("pine_v2_bar") or {}
            from .pine_workbench_v2 import events as v2_events
            expected = [row for row in v2_events(wire) if row.role == "BARS"][cursor - 1]
            if (chart.get("bar_count") != cursor or chart.get("sequence") != clock.get("source_sequence")
                    or chart.get("sequence") != expected.sequence or chart.get("time_ms") != expected.event_time_ms
                    or v2.get("contract") != wire["pine_v2_bar_contract"]):
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "Pine V2 account source cursor differs")
    if wire.get("pine_print_tick_contract"):
        from .pine_print_tick_execution import validate_state as validate_print_ticks
        validate_print_ticks(wire,state)
    if wire.get("request_update_contract"):
        from .pine_request_updates import from_wire, pass_observations, validate_replay
        try:
            feed = from_wire(wire)
            last = state.get("last_request") or {}
            if wire.get("pine_bar_path_contract") or wire.get("pine_print_tick_contract"):
                observations = pass_observations(last.get("execution_schedule", []), scheduled=True)
            elif wire.get("fill_recalculation"):
                observations = pass_observations(last.get("execution_passes", []), scheduled=False)
            else:
                observations = last.get("request_updates", [])
                if len(observations) != cursor:
                    raise ValueError("requested transcript count differs")
            validate_replay(feed, (state.get("clock") or {}).get("request_feed"), observations)
        except (KeyError, ValueError, TypeError) as exc:
            raise BacktestError("NATIVE_IDENTITY_MISMATCH", "requested observation checkpoint differs") from exc


def make_state(wire,cursor,kernel,orders,accounts,history,latest,clock,last_request,*,risk_stops=None,
               _owned_output=False):
    from .native import MAX_BYTES,digest
    from .native_checkpoint import pack,detached_json,checkpoint_digest
    value=dict(contract=CONTRACT,input_hash=digest(wire),
        host_runtime_identity=wire["host_runtime_identity"],cursor=cursor,
        kernel=kernel.snapshot(),orders=orders.snapshot(),
        **({"pine_risk_stops":risk_stops.snapshot()} if risk_stops is not None and risk_stops.state is not None else {}))
    output=dict(accounts=accounts,history=history,latest=latest,clock=clock,last_request=last_request)
    if _owned_output:
        # Only an exclusive Pine replay job transfers its finished observations
        # and feedback. The clock freezes the live stream header/journal; the
        # last SDK output and source bars still belong to live owners, so keep
        # those boundaries detached along with ledger snapshots and identity.
        value=detached_json({**value,"latest":latest})
        output.update(latest=value["latest"],clock={**clock,"latest":value["latest"]},
            last_request={**last_request,"bars":detached_json(last_request["bars"])})
        value.update(output)
    else:
        value.update(output)
        value=detached_json(value)
    value["checksum"]=checkpoint_digest(value)
    if len(pack(value).encode("utf-8"))>MAX_BYTES:
        raise BacktestError("BUDGET_EXCEEDED","external account checkpoint exceeds 64 MiB")
    validate_state(wire,value)
    return value
