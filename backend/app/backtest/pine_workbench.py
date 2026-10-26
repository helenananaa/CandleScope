"""Freeze Workbench Pine controls before any Host account execution."""
from copy import deepcopy

from .errors import BacktestError
from .pine_risk_stops import CONTRACT as RISK_CONTRACT, PineRiskStops, window_contract

CONTRACT = "candlescope.pine-workbench-control/1"


def freeze_control(native, plugin, wire, payload):
    identity = wire["identity"]
    from .pine_order_metadata import CONTRACT as METADATA_CONTRACT
    if identity.get("order_metadata_contract") == METADATA_CONTRACT:
        wire["order_metadata_contract"] = METADATA_CONTRACT
    if identity.get("workbench_control") != CONTRACT:
        return  # Older adapters keep their existing explicit unsupported diagnostics.
    probe = {key: value for key, value in wire.items()
        if key not in {"bars", "contexts", "execution_events", "execution_times"}}
    probe.update(bars=[], contexts=[{**row, "bars": []} for row in wire.get("contexts", [])])
    response = native.runner(plugin, {**probe, "operation": "host_control",
        **({"risk_contract": RISK_CONTRACT} if identity.get("risk_stop_contract") == RISK_CONTRACT else {})}, timeout=30)
    if response.get("identity") != identity or response.get("contract") != CONTRACT:
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Workbench control identity differs")
    from .pine_request_updates import CONTRACT as REQUEST_UPDATE_CONTRACT
    from .pine_event_requests import CONTRACT as EVENT_CONTRACT
    if response.get("event_request_contract") is not None:
        if response["event_request_contract"]!=EVENT_CONTRACT or identity.get("event_request_contract")!=EVENT_CONTRACT:
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR","Workbench event request capability differs")
        wire["event_request_contract"]=EVENT_CONTRACT
    if wire.get("contexts") and response.get("request_update_contract") == REQUEST_UPDATE_CONTRACT:
        if identity.get("request_update_contract") != REQUEST_UPDATE_CONTRACT:
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Workbench requested update capability differs")
        wire["request_update_contract"] = REQUEST_UPDATE_CONTRACT
    if response.get("fixed_history_required"):
        if identity.get("fixed_history_contract") != "candlescope.pine-fixed-history/1":
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "fixed-history capability differs")
        wire["fixed_history_contract"] = "candlescope.pine-fixed-history/1"
    execution = response.get("execution")
    if not isinstance(execution, dict):
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine execution requirements missing")
    if any(type(execution.get(name)) is not bool for name in ("calcOnOrderFills", "processOrdersOnClose")):
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine execution requirements")
    from .pine_sizing import supported, declaration
    quantity = None
    if supported(identity):
        try:
            quantity = declaration(response.get("default_quantity"))
        except ValueError as exc:
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", str(exc)) from exc
    if execution.get("calcOnOrderFills") and not wire.get("fill_recalculation"):
        raise BacktestError("EXTERNAL_UNSUPPORTED", "Pine calc_on_order_fills requires explicit fill_recalculation")
    if execution.get("processOrdersOnClose"):
        if identity.get("closing_tick_contract") != "candlescope.pine-closing-tick/1":
            raise BacktestError("EXTERNAL_UNSUPPORTED", "Workbench closing-tick capability missing")
        wire["closing_ticks"] = True
    configuration = response.get("risk_rules")
    if configuration is not None:
        if (identity.get("risk_stop_contract") != RISK_CONTRACT or not isinstance(configuration, dict)
                or type(configuration.get("schemaVersion")) is not int or configuration["schemaVersion"] != 1
                or configuration.get("unresolvedCallSiteIds") != []
                or not isinstance(configuration.get("rules"), list)):
            raise BacktestError("EXTERNAL_UNSUPPORTED", "resolved Workbench Pine risk configuration required")
        wire["risk_contract"] = RISK_CONTRACT
        context = {"exchange": payload.get("exchange", "binance"), "market_type": payload.get("market_type", "usdm"),
            "interval": wire["interval"], "fidelity_mode": wire["execution_fidelity"]}
        context["pine_risk_windows"] = window_contract(context, {rule["function"] for rule in configuration["rules"]})
        wire["pine_risk_context"] = context
    wire["pine_host_control"] = {"contract": CONTRACT, "execution": deepcopy(execution),
        "risk_rules": deepcopy(configuration)}
    if quantity is not None:
        wire["pine_host_control"]["default_quantity"] = quantity
    if execution.get("calcOnEveryTick") and wire["execution_fidelity"]!="BAR_APPROX":
        from .native_session import STREAM_CONTRACT,SCHEDULE_CONTRACT,TICK_CONTRACT
        from .pine_print_tick_execution import CONTRACT as PRINT_CONTRACT
        from .pine_print_account import FIDELITIES
        if (wire["execution_fidelity"] not in FIDELITIES or identity.get("external_stream_contract")!=STREAM_CONTRACT
                or identity.get("execution_schedule_contract")!=SCHEDULE_CONTRACT
                or identity.get("execution_tick_contract")!=TICK_CONTRACT):
            raise BacktestError("EXTERNAL_UNSUPPORTED","physical Pine ticks require the negotiated print stream")
        wire.update(pine_print_tick_contract=PRINT_CONTRACT,execution_schedule_contract=SCHEDULE_CONTRACT,
                    execution_tick_contract=TICK_CONTRACT)
    if execution.get("calcOnEveryHistoryTick") and not wire.get("pine_print_tick_contract"):
        from .native_session import STREAM_CONTRACT, SCHEDULE_CONTRACT, TICK_CONTRACT
        from .pine_history_tick_execution import CONTRACT as HISTORY_CONTRACT
        from app.simulation.pine_bar_kernel import CONTRACT as PATH_CONTRACT
        if (wire["execution_fidelity"]!="BAR_APPROX" or identity.get("external_stream_contract")!=STREAM_CONTRACT
                or identity.get("execution_schedule_contract")!=SCHEDULE_CONTRACT
                or identity.get("execution_tick_contract")!=TICK_CONTRACT):
            raise BacktestError("EXTERNAL_UNSUPPORTED","historical Pine ticks require the negotiated OHLC stream")
        wire.update(pine_history_tick_contract=HISTORY_CONTRACT,pine_bar_path_contract=PATH_CONTRACT,
                    execution_schedule_contract=SCHEDULE_CONTRACT,execution_tick_contract=TICK_CONTRACT)
    if wire["execution_fidelity"] == "BAR_APPROX" and wire.get("fill_recalculation"):
        from .strategy.pine_schedule import CONTRACT as SCHEDULE_CONTRACT
        from app.simulation.pine_bar_kernel import CONTRACT as PATH_CONTRACT
        if identity.get("execution_schedule_contract") != SCHEDULE_CONTRACT or not execution.get("calcOnOrderFills"):
            raise BacktestError("EXTERNAL_UNSUPPORTED", "Pine BAR callbacks require explicit schedule support and calc_on_order_fills")
        wire.update(pine_bar_path_contract=PATH_CONTRACT, execution_schedule_contract=SCHEDULE_CONTRACT)


def configure_risk(orders, wire, *, resume=None):
    control = wire.get("pine_host_control")
    if control is None:
        return None
    if control.get("contract") != CONTRACT:
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Workbench control contract differs")
    configuration = control.get("risk_rules")
    if configuration is None:
        if resume and resume.get("pine_risk_stops") is not None:
            raise BacktestError("CHECKPOINT_CORRUPT", "unexpected Workbench stop checkpoint")
        return None
    controller = PineRiskStops(orders, wire.get("pine_risk_context"))
    state = resume.get("pine_risk_stops") if resume else None
    if state is not None:
        controller.restore(state)
        if controller.configuration != configuration:
            raise BacktestError("NATIVE_IDENTITY_MISMATCH", "Workbench risk checkpoint configuration differs")
    else:
        controller.configure(configuration, observe=False)
        if resume and controller.state is not None:
            raise BacktestError("CHECKPOINT_CORRUPT", "Workbench risk stop checkpoint missing")
    return controller


def check_risk_response(orders, wire, response):
    control = wire.get("pine_host_control")
    if control is None:
        return
    expected = control.get("risk_rules")
    if response.get("risk_rules") != expected:
        raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "Workbench Pine risk configuration changed")
    if expected is not None:
        orders.risk_stops.configure(expected)


def bar_event(wire, index, sequence):
    from app.data_engine.interval_policy import parse_interval_spec
    from app.market_dataset.snapshot import MarketEvent
    bar = wire["bars"][index]
    end = parse_interval_spec(wire["interval"]).next_ms(bar["time"] * 1000) - 1
    return MarketEvent(sequence, end, "BARS", {"open_time_ms": bar["time"] * 1000,
        "close_time_ms": end, **{name: str(bar[name]) for name in ("open", "high", "low", "close", "volume")}})
