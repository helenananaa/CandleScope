"""Host configuration of a compiled Pine strategy, shared by fixed-history and forward runs.

A fixed-history run admits each Pine execution feature on the fidelity that supports it
(``pine_execution_config``). A forward run (B-333b) admits only the close-bar
ORDER_INTENT subset (``forward_pine_refusals``): the forward host has no bar path,
tick stream, fill-callback pass, closing tick, stop window or requested dataset.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from .chart_book import DUAL_MODES
from .errors import BacktestError

EXTERNAL_STREAM_CONTRACT = "candlescope.pine-external-stream/1"
BAR_PATH_CONTRACT = "candlescope.pine-bar-path/1"
V2_BAR_CONTRACT = "candlescope.pine-v2-bar/1"
SCHEDULE_CONTRACT = "candlescope.pine-execution-schedule/1"


def pine_execution_config(compiled: Mapping[str, object], *, payload: Mapping[str, object], fidelity: str,
                          output_mode: str, account_model: str, realism_enabled: bool) -> dict[str, object]:
    """The run configuration a fixed-history Pine run adds for its compiled envelope."""
    config: dict[str, object] = {"pine_runtime_identity": compiled["dependencyHash"]}
    envelope = json.loads(str(compiled["executionSource"]))
    fill_callbacks = envelope.get("fillCallbacks") is True
    history_ticks = envelope.get("historyTicks") is True
    realtime_ticks = envelope.get("realtimeTicks") is True
    if realtime_ticks and fidelity not in DUAL_MODES and not (history_ticks and fidelity == "BAR_APPROX"):
        raise BacktestError("FIDELITY_UNSUPPORTED", "realtime Pine ticks require aggregate-trade execution; historical BAR ticks require calc_on_every_history_tick")
    if realtime_ticks and fidelity in DUAL_MODES:
        if output_mode != "ORDER_INTENT" or envelope["identity"].get("external_stream_contract") != EXTERNAL_STREAM_CONTRACT:
            raise BacktestError("FIDELITY_UNSUPPORTED", "realtime Pine ticks require the negotiated aggregate-trade stream and ORDER_INTENT")
        config["pine_realtime_ticks"] = True
    if history_ticks and not config.get("pine_realtime_ticks"):
        if (fidelity != "BAR_APPROX" or output_mode != "ORDER_INTENT"
                or envelope["identity"].get("external_stream_contract") != EXTERNAL_STREAM_CONTRACT):
            raise BacktestError("FIDELITY_UNSUPPORTED", "chart historical ticks require the negotiated BAR stream and ORDER_INTENT")
        config.update(pine_history_ticks=True, pine_bar_path_contract=BAR_PATH_CONTRACT)
        if account_model == "LINEAR_PERP_ONE_WAY_V2" or realism_enabled:
            config["pine_v2_bar_contract"] = V2_BAR_CONTRACT
    process_close = envelope.get("processOnClose") is True
    stop_functions = envelope.get("riskStopFunctions") or []
    if stop_functions:
        from .pine_risk_stops import window_contract
        if output_mode != "ORDER_INTENT":
            raise BacktestError("FIDELITY_UNSUPPORTED", "Pine stop rules require ORDER_INTENT")
        config["pine_risk_windows"] = window_contract({**payload, "fidelity_mode": fidelity}, stop_functions)
    if process_close:
        config["pine_process_on_close"] = True
    if fill_callbacks:
        if fidelity not in {"BAR_APPROX", *DUAL_MODES} or output_mode != "ORDER_INTENT":
            raise BacktestError("FIDELITY_UNSUPPORTED", "Pine fill callbacks require ORDER_INTENT and BAR or aggregate-trade execution")
        if fidelity == "BAR_APPROX":
            if envelope.get("executionScheduleContract") != SCHEDULE_CONTRACT:
                raise BacktestError("FIDELITY_UNSUPPORTED", "historical BAR callbacks require explicit execution schedules")
            if account_model == "LINEAR_PERP_ONE_WAY_V2" or realism_enabled:
                config["pine_v2_bar_contract"] = V2_BAR_CONTRACT
            config["pine_bar_path_contract"] = BAR_PATH_CONTRACT
        config["pine_fill_callbacks"] = True
    if output_mode == "ORDER_INTENT" or process_close:
        from .strategy.pine_planner import host_identity
        config["pine_order_runtime_identity"] = host_identity()
    if fidelity not in {"BAR_APPROX", *DUAL_MODES}:
        raise BacktestError("FIDELITY_UNSUPPORTED", "chart Pine requires closed-bar observations")
    return config


def pine_chart_metadata(supplied: object, *, payload: Mapping[str, object], account_model: str) -> dict[str, object]:
    """Validate explicit chart contract metadata against the run's own tick and step."""
    from fractions import Fraction
    from .native_contracts import PineChartMetadata
    try:
        metadata = PineChartMetadata.model_validate(supplied).model_dump(exclude_none=True)
    except ValueError as exc:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "invalid Pine contract metadata") from exc
    for field, config_field in (("priceTickSize", "price_tick"), ("quantityStep", "qty_step")):
        if metadata.get(field) is not None and payload.get(config_field) is not None and Fraction(metadata[field]) != Fraction(str(payload[config_field])):
            raise BacktestError("DATA_SNAPSHOT_MISMATCH", f"Pine {field} differs from Host {config_field}")
    if account_model == "SPOT_CASH_V1" and metadata.get("pointValue", 1) != 1:
        raise BacktestError("FIDELITY_UNSUPPORTED", "spot cash accounting requires unit pointValue")
    return metadata


# What a forward run cannot run yet, named as the script declares it.
FORWARD_EXCLUDED = (
    ("fillCallbacks", "calc_on_order_fills"),
    ("historyTicks", "calc_on_every_history_tick"),
    ("realtimeTicks", "calc_on_every_tick"),
    ("processOnClose", "process_orders_on_close"),
)


def forward_pine_refusals(envelope: Mapping[str, object], requests: object = ()) -> list[str]:
    """Pine features outside the forward subset: close-bar ORDER_INTENT without them (B-333b)."""
    refused = [label for key, label in FORWARD_EXCLUDED if envelope.get(key) is True]
    if envelope.get("riskStopFunctions"):
        refused.append("strategy.risk stop rules")
    # The runtime negotiates request contracts for every script; only declared requests need datasets.
    if requests:
        refused.append("request.* datasets")
    return refused
