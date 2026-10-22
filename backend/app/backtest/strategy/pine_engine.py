"""Pine decisions over the authoritative Host account and causal chart clock.

ORDER_INTENT preserves script orders for Host allocation and matching. The
legacy target-position mode retains its one-entry market-order profile.
"""

from __future__ import annotations

import json
import re
import threading
from decimal import Decimal

from app.backtest.pine_entry_risk import CONTRACT as RISK_CONTRACT, FUNCTIONS as RISK_FUNCTIONS
from app.backtest.pine_risk_stops import CONTRACT as STOP_CONTRACT
from app.backtest.pine_risk_state import STOP_FUNCTIONS
from .pine_schedule import CONTRACT as SCHEDULE_CONTRACT, frame_context, encode as encode_schedule, decode as decode_schedule

from .protocol import (
    ProviderCapabilities,
    StrategyOutput,
    StrategyProviderError,
    canonical_hash,
)

REVISION = "pine-engine-chart-v1"
SOURCE_SCHEMA = "candlescope.chart-pine/1"
ORDER_CONTRACT = "candlescope.pine-orders/1"
CALLBACK_CONTRACT = "candlescope.pine-fill-callbacks/1"
CLOSING_CONTRACT = "candlescope.pine-closing-tick/1"
STREAM_CONTRACT = "candlescope.pine-external-stream/1"


def plugin():
    from app.backtest.native import resolve_plugin

    result = resolve_plugin("pine")
    result["command"][-1] = "candlescope_plugin_pine_compat.chart_strategy"
    return result


def validate_libraries(libraries):
    if not isinstance(libraries, dict) or len(libraries) > 64:
        raise StrategyProviderError("PINE_HOST_LIBRARIES_INVALID", "at most 64 versioned libraries are allowed")
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][\w.-]*/[A-Za-z_][\w.-]*/[1-9][0-9]*", key)
           or not isinstance(value, str) or not value.strip() for key, value in libraries.items()):
        raise StrategyProviderError("PINE_HOST_LIBRARIES_INVALID", "use owner/name/version keys and nonempty source text")
    if sum(len(value.encode("utf-8")) for value in libraries.values()) > 2_000_000:
        raise StrategyProviderError("PINE_HOST_LIBRARIES_INVALID", "library sources exceed 2 MB")
    return dict(libraries)


def analyze(source, libraries=None):
    from app.backtest.errors import BacktestError
    from app.backtest.native import PROTOCOL, invoke

    libraries = validate_libraries(libraries if libraries is not None else {})
    runtime = plugin()
    try:
        identity = invoke(runtime, {"operation": "describe"}, timeout=15)["identity"]
        result = invoke(
            runtime,
            {
                "protocol": PROTOCOL,
                "identity": identity,
                "operation": "analyze",
                "source": source,
                "libraries": libraries,
            },
            timeout=15,
        )
    except BacktestError as exc:
        if exc.code == "NATIVE_EXECUTION_FAILED":
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION",
                json.dumps(exc.details.get("diagnostics", [])),
            ) from exc
        raise StrategyProviderError(
            "PINE_RUNTIME_UNAVAILABLE",
            f"Install the chart Pine adapter and retry: {exc}",
        ) from exc
    info, requirements = result["analysis"], result["requirements"]
    features = {
        item["feature"] for item in info.get("compatibility", {}).get("supported", [])
    }
    from app.backtest.pine_sizing import supported as sizing_supported, declaration as sizing_declaration
    quantity = (requirements.get("account") or {}).get("defaultQuantity") or {}
    if sizing_supported(result["identity"]) and info.get("scriptMode") == "strategy":
        try:
            quantity = sizing_declaration(quantity)
        except ValueError as exc:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", str(exc)) from exc
    if (quantity.get("kind") in {"cash", "percent_of_equity"}
        or "strategy.default_entry_qty" in features) and not sizing_supported(result["identity"]):
        raise StrategyProviderError("FIDELITY_UNSUPPORTED", "Install a Pine worker with external sizing schema 1 for default quantity execution")
    blocked = {
        feature
        for feature in features
        if (feature.startswith("request.") and feature not in {"request.security", "request.security_lower_tf"})
        or (feature.startswith("strategy.risk") and not (
            (feature in RISK_FUNCTIONS and result["identity"].get("entry_risk_contract") == RISK_CONTRACT)
            or (feature in STOP_FUNCTIONS and result["identity"].get("risk_stop_contract") == STOP_CONTRACT)))
    }
    execution = requirements.get("execution", {})
    if (
        info.get("scriptMode") != "strategy"
        or not info.get("executable")
        or blocked
        or result.get("profileError")
        or type(result.get("pyramiding")) is not int
        or not 1 <= result["pyramiding"] <= 64
        or any(item.get("function") not in {"security", "request.security", "request.security_lower_tf"}
               for item in requirements.get("requests", []))
        or (requirements.get("account") or {}).get("declaredCurrency")
        or (execution.get("calcOnEveryTick") and result["identity"].get("external_stream_contract")!=STREAM_CONTRACT)
        or (execution.get("calcOnEveryHistoryTick") and result["identity"].get("external_stream_contract")!=STREAM_CONTRACT)
        or (execution.get("calcOnOrderFills") and result["identity"].get("fill_callbacks") != CALLBACK_CONTRACT)
        or (execution.get("processOrdersOnClose") and result["identity"].get("closing_tick_contract") != CLOSING_CONTRACT)
        or (any(feature == "strategy.order" or feature.startswith("strategy.oca.") for feature in features)
            and result["identity"].get("external_orders", 1) < 2)
        or execution.get("clock") not in {"notUsed", "explicitTimestampWhenEvaluated"}
        or (execution.get("clock") == "explicitTimestampWhenEvaluated"
            and not result["identity"].get("external_execution_times"))
    ):
        raise StrategyProviderError(
            "FIDELITY_UNSUPPORTED",
            "Chart Pine supports closed-bar entry, exit and cancellation with pinned requested datasets; "
            "fill callbacks require the aggregate-trade execution clock; closing ticks require explicit Host support. "
            + ", ".join(sorted(blocked)),
        )
    return result


class PineEngineProvider:
    def __init__(self):
        self.worker = None
        self.stream = None
        self._closed_stream_checkpoint = None
        self.streaming = False
        self.realtime_streaming = False
        self.cancelled = threading.Event()
        self.bars, self.accounts, self.history = [], [], []
        self.entry_id = None
        self.context = {}
        self.runtime_identity = None
        self.default_quantity = None
        self.request_feed = None
        self.request_groups = []
        self.state_hash = canonical_hash([])

    def describe(self):
        return ProviderCapabilities(
            input_modes=("BAR_CLOSE",),
            output_modes=("TARGET_POSITION", "ORDER_INTENT"),
            signal_clock="BAR_CLOSE",
        )

    def prepare(self, context):
        from app.backtest.native import PROTOCOL, invoke
        from app.backtest.native_session import SessionWorker

        self.close()
        self._closed_stream_checkpoint=None
        self.cancelled = threading.Event()
        from copy import deepcopy
        self.context = deepcopy(context)
        self.order_mode = context.get("outputMode") == "ORDER_INTENT"
        try:
            frozen = json.loads(context["source"])
            if frozen.get("schema") != SOURCE_SCHEMA:
                raise ValueError("unknown source envelope")
            if self.order_mode and frozen.get("orderContract") != ORDER_CONTRACT:
                raise ValueError("recompile Pine for the Host order contract")
            self.source = frozen["source"]
            self.libraries = validate_libraries(frozen.get("libraries", {}))
            self.runtime_identity = frozen["identity"]
            self.default_quantity = None
            if frozen.get("defaultQuantity") is not None:
                from app.backtest.pine_sizing import declaration
                self.default_quantity = declaration(frozen["defaultQuantity"])
            self.needs_clock = frozen.get("executionClock") == "explicitTimestampWhenEvaluated"
            self.fill_callbacks = frozen.get("fillCallbacks") is True
            self.process_on_close = frozen.get("processOnClose") is True
            self.entry_risk = frozen.get("entryRisk") is True
            self.stop_functions = frozen.get("riskStopFunctions") or []
        except (KeyError, ValueError, TypeError) as exc:
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION", "compiled Pine source envelope required"
            ) from exc
        schedule_contract = context.get("pineExecutionScheduleContract")
        self.scheduled = schedule_contract is not None
        self.streaming = context.get("pineStreamContract") is not None
        self.realtime_streaming = context.get("pineRealtimeTicks") is True
        if self.streaming and (context["pineStreamContract"]!=STREAM_CONTRACT or not self.scheduled
                or self.runtime_identity.get("external_stream_contract")!=STREAM_CONTRACT
                or (frozen.get("realtimeTicks") is not True if self.realtime_streaming else
                    frozen.get("historyTicks") is not True or not isinstance(context.get("pineHistoricalBars"),list))):
            raise StrategyProviderError("FIDELITY_UNSUPPORTED","chart ticks require a negotiated stream and compatible clock")
        if self.realtime_streaming and not self.streaming:
            raise StrategyProviderError("FIDELITY_UNSUPPORTED","realtime ticks require the explicit stream")
        if self.streaming:
            self.context.pop("inputPlan",None)
        self.pass_mode = self.fill_callbacks or self.scheduled
        if self.scheduled and (schedule_contract != SCHEDULE_CONTRACT or not self.order_mode
                or frozen.get("executionScheduleContract") != SCHEDULE_CONTRACT
                or self.runtime_identity.get("execution_schedule_contract") != SCHEDULE_CONTRACT):
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "explicit Pine schedule requires a compiled contract and ORDER_INTENT")
        if self.fill_callbacks and not self.order_mode:
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "fill callbacks require ORDER_INTENT mode")
        if self.entry_risk and (not self.order_mode or self.runtime_identity.get("entry_risk_contract") != RISK_CONTRACT):
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "Pine risk rules require the Host order risk contract")
        if self.stop_functions and self.runtime_identity.get("risk_stop_contract") != STOP_CONTRACT:
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "Pine stop rules require the Host event risk contract")
        if frozen.get("requiresOrderMode") and not self.order_mode:
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "generic and OCA orders require ORDER_INTENT mode")
        runtime = plugin()
        self.runtime_launch=runtime
        current = invoke(runtime, {"operation": "describe"}, timeout=15)["identity"]
        if current != self.runtime_identity:
            raise StrategyProviderError(
                "IDENTITY_MUTATION",
                "Pine installation changed; compile the source again",
            )
        self.wire = {
            "protocol": PROTOCOL,
            "identity": current,
            "source": self.source,
            "libraries": self.libraries,
            "parameters": dict(context.get("parameters") or {}),
            **({"execution_schedule_contract": SCHEDULE_CONTRACT} if self.scheduled else {}),
            **({"closing_ticks": True} if self.process_on_close else {}),
            **({"order_metadata_contract": self.runtime_identity["order_metadata_contract"]}
               if self.order_mode and self.runtime_identity.get("order_metadata_contract") else {}),
            **({"risk_contract": STOP_CONTRACT if self.stop_functions else RISK_CONTRACT} if self.entry_risk else {}),
        }
        from app.backtest.errors import BacktestError
        from app.backtest.pine_requested_data import load_contexts
        try:
            self.requested_streams = load_contexts(context.get("pineLocalDataRoot"), context.get("pineRequestedContexts", []))
        except BacktestError as exc:
            raise StrategyProviderError(exc.code, str(exc)) from exc
        from app.backtest.pine_request_updates import CONTRACT as REQUEST_UPDATE_CONTRACT, RequestedObservationFeed
        self.request_feed = None
        self.request_groups = []
        if self.requested_streams and frozen.get("requestUpdateContract") == REQUEST_UPDATE_CONTRACT:
            if current.get("request_update_contract") != REQUEST_UPDATE_CONTRACT:
                raise StrategyProviderError("FIDELITY_UNSUPPORTED", "Pine requested-update capability differs")
            self.request_feed = RequestedObservationFeed(self.requested_streams)
            self.wire["request_update_contract"] = REQUEST_UPDATE_CONTRACT
        self.worker = None if self.streaming else SessionWorker(runtime, self.wire, self.cancelled, evaluator=True)
        self.bars, self.accounts, self.history, self.entry_id = [], [], [], None
        self.execution_times = []
        self.execution_passes = []
        self.execution_contexts = []
        self.state_hash = canonical_hash([])
        self.risk_configuration = None

    def _evaluate(self, frame, *, warmup=False):
        if (self.worker is None and not self.streaming) or not frame.account_view:
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION",
                "Pine requires the authoritative Host account",
            )
        row = frame.bar or {}
        schedule_context = frame_context(frame, self.scheduled)
        bar = {
            name: float(row[name])
            for name in ("open", "high", "low", "close", "volume")
        }
        bar["time"] = int(row.get("open_time_ms", frame.event_time_ms)) // 1000
        account = dict(frame.account_view)
        actual_metadata = account.pop("_contract_metadata", None)
        if actual_metadata is not None:
            from app.backtest.pine_contract_metadata import bind_observed_metadata
            from app.backtest.errors import BacktestError
            try:
                self.context["pineChartMetadata"] = bind_observed_metadata(actual_metadata, self.context.get("pineChartMetadata") or {})
            except BacktestError as exc:
                raise StrategyProviderError(exc.code, str(exc)) from exc
        account["time"] = bar["time"]
        confirmed, pass_index = True, None
        if self.pass_mode:
            observation = frame.features.get("pineExecutionPass") or {}
            index, confirmed = observation.get("barIndex"), observation.get("confirmed")
            if (type(index) is not int or type(confirmed) is not bool or index < 0
                    or index not in {len(self.bars), len(self.bars) - 1}):
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "an ordered Pine execution pass is required")
            if index == len(self.bars):
                if self.execution_passes and not self.execution_passes[-1][-1]["confirmed"]:
                    raise StrategyProviderError("LOOKAHEAD_VIOLATION", "confirm the previous Pine bar before advancing")
                self.bars.append(bar)
                self.accounts.append(account)
                self.execution_passes.append([])
                self.execution_contexts.append([])
                if self.needs_clock:
                    self.execution_times.append(frame.event_time_ms)
            else:
                previous_pass = self.execution_passes[index][-1]
                if (self.bars[index]["time"] != bar["time"] or (previous_pass["confirmed"] and
                    (not self.process_on_close or not confirmed or previous_pass["bar"] != bar or previous_pass["event_time_ms"] != frame.event_time_ms))):
                    raise StrategyProviderError("LOOKAHEAD_VIOLATION", "a committed Pine bar cannot be replaced")
                self.bars[index], self.accounts[index] = bar, account
                if self.needs_clock:
                    self.execution_times[index] = frame.event_time_ms
            pass_index = len(self.execution_passes[index])
            if pass_index >= (100_000 if self.streaming else 65):
                raise StrategyProviderError("BUDGET_EXCEEDED", "at most 64 fill callbacks and one close per bar")
        else:
            self.bars.append(bar)
            self.accounts.append(account)
            if self.needs_clock:
                self.execution_times.append(frame.event_time_ms)
        market = frame.market
        venue = str(market.get("venue") or "local").upper()
        symbol = str(market.get("symbol") or "LOCAL")
        chart_symbol = symbol if ":" in symbol else f"{venue}:{symbol}"
        if (chart_symbol.startswith("BINANCE:")
                and str(self.context.get("pineChartMarketType") or "").lower() in {"usdm", "futures", "swap"}
                and not chart_symbol.endswith(".P")):
            chart_symbol += ".P"
        timeframe = str(
            max(
                1,
                (
                    int(row.get("close_time_ms", frame.event_time_ms))
                    + 1
                    - bar["time"] * 1000
                )
                // 60_000,
            )
        )
        if self.context.get("pineChartInterval"):
            from app.backtest.native import timeframe as pine_timeframe

            timeframe = pine_timeframe(self.context["pineChartInterval"])
        from app.backtest.pine_requested_data import visible_contexts
        cutoff = int(row.get("close_time_ms", frame.event_time_ms))
        if self.streaming and (not schedule_context or schedule_context["bar_state"] != "historical"):
            cutoff=min(frame.event_time_ms,cutoff)
        elif not schedule_context or schedule_context["bar_state"] != "historical":
            cutoff = min(frame.watermark_ms - (0 if confirmed else 1), cutoff)
        contexts = (self.request_feed.empty_contexts() if self.request_feed is not None
                    else visible_contexts(self.requested_streams, cutoff))
        requested = (dict(request_observed_at_ms=cutoff, request_updates=self.request_feed.advance(cutoff))
                     if self.request_feed is not None else None)
        if self.pass_mode:
            self.execution_passes[index].append({"bar": dict(bar), "account": dict(account), "confirmed": confirmed,
                "event_time_ms": frame.event_time_ms, **(requested if requested is not None else {"request_data": [
                    {key: value for key, value in context.items() if key in {"symbol", "timeframe", "bars"}}
                    for context in contexts]})})
            if self.scheduled:
                self.execution_contexts[index].append(schedule_context)
            contexts = [{**context, "bars": []} for context in contexts]
        elif requested is not None:
            self.request_groups.append(dict(observed_at_ms=cutoff, updates=requested["request_updates"]))
        if self.streaming:
            from .pine_streaming import observe
            result=observe(self,self.runtime_launch,chart_symbol,timeframe,contexts,index,pass_index)
        else:
            result = self.worker.request(
                {
                    **self.wire,
                    "bars": self.bars,
                    "accounts": self.accounts,
                    **({"contexts": contexts} if contexts else {}),
                    **({"request_updates": self.request_groups} if self.request_feed is not None and not self.pass_mode else {}),
                    **({"execution_times": self.execution_times} if self.needs_clock else {}),
                    **({"execution_schedule": encode_schedule(self.execution_passes, self.execution_contexts)} if self.scheduled
                       else {"execution_passes": self.execution_passes} if self.pass_mode else {}),
                    "context": {
                        "symbol": chart_symbol,
                        "timeframe": timeframe,
                        **(
                            {"metadata": self.context["pineChartMetadata"]}
                            if self.context.get("pineChartMetadata")
                            else {}
                        ),
                    },
                },
                self.cancelled,
                timeout=5,
            )
        if (
            result.get("contract") != "external-broker/1"
            or result.get("account_authority") != "candlescope"
            or (self.scheduled and result.get("execution_schedule_contract") != SCHEDULE_CONTRACT)
            or (self.request_feed is not None and result.get("request_update_contract") != self.wire["request_update_contract"])
        ):
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION",
                "Pine returned the wrong account contract",
            )
        index = len(self.bars) - 1
        if self.entry_risk:
            configuration = result.get("risk_rules")
            if not isinstance(configuration, dict) or not configuration.get("rules"):
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "Pine risk configuration missing")
            if self.risk_configuration is not None and configuration != self.risk_configuration:
                raise StrategyProviderError("LOOKAHEAD_VIOLATION", "Pine risk configuration changed")
            self.risk_configuration = configuration
        def ordinal(item):
            return (item["bar_index"], item.get("pass_index", -1)) if self.pass_mode else (item["bar_index"], -1)
        cursor = (index, pass_index) if self.pass_mode else (index, -1)
        previous = self.history if self.streaming else [item for item in result["intents"] if ordinal(item) < cursor]
        if previous != self.history:
            raise StrategyProviderError(
                "LOOKAHEAD_VIOLATION", "Pine changed an earlier decision"
            )
        intents = result["intents"] if self.streaming else [item for item in result["intents"] if ordinal(item) == cursor]
        if (len(intents)>64 or (self.streaming and (result["intent_base"]!=len(self.history)
                or any(ordinal(item)!=(index-self.stream.input_skip,pass_index) for item in intents)))
                or (not self.streaming and (len(previous)+len(intents)!=len(result["intents"])
                    or sum(item["bar_index"]==index for item in result["intents"])>64))):
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION", "invalid Pine intent prefix"
            )
        self.history.extend(intents)
        self.state_hash = canonical_hash(
            {
                "previous": self.state_hash,
                "bar": bar,
                "account": account,
                "intents": intents,
                **({"risk_rules": self.risk_configuration} if self.entry_risk else {}),
                **({"executionTimeMs": frame.event_time_ms} if self.needs_clock else {}),
                **({"executionPass": {"barIndex": index, "passIndex": pass_index, "confirmed": confirmed,
                    "eventTimeMs": frame.event_time_ms}} if self.pass_mode else {}),
                **({"executionContext": schedule_context} if self.scheduled else {}),
            }
        )
        if self.order_mode:
            if warmup or (not intents and not self.entry_risk):
                return None
            payload = {"contract": ORDER_CONTRACT, "intents": intents, "pyramiding": result.get("pyramiding", 1)}
            if self.wire.get("order_metadata_contract"):
                payload["order_metadata_contract"] = self.wire["order_metadata_contract"]
            if self.entry_risk:
                payload["risk_rules"] = self.risk_configuration
            return StrategyOutput(frame.sequence, "ORDER_INTENT", payload, self.state_hash, canonical_hash(payload))
        if result.get("pyramiding", 1) != 1:
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "Pyramiding requires ORDER_INTENT mode")
        actual = Decimal(str(account["position_size"]))
        target = actual
        for intent in intents:
            if any(
                intent.get(key) is not None
                for key in (
                    "limit",
                    "stop",
                    "trail_price",
                    "trail_points",
                    "trail_offset",
                )
            ):
                raise StrategyProviderError(
                    "FIDELITY_UNSUPPORTED", "select ORDER_INTENT mode for price orders"
                )
            action = intent["action"]
            if action == "entry":
                owner = str(intent["id"])
                if self.entry_id is not None and self.entry_id != owner:
                    raise StrategyProviderError(
                        "FIDELITY_UNSUPPORTED", "chart Pine supports one entry ID"
                    )
                self.entry_id = owner
                quantity = Decimal(
                    str(intent["qty"] if intent.get("qty") is not None else 1)
                )
                if not quantity.is_finite() or quantity <= 0:
                    raise StrategyProviderError(
                        "PROVIDER_PROTOCOL_VIOLATION", "invalid Pine entry quantity"
                    )
                if intent.get("direction") not in {"long", "short"}:
                    raise StrategyProviderError(
                        "PROVIDER_PROTOCOL_VIOLATION", "invalid Pine entry direction"
                    )
                direction = 1 if intent["direction"] == "long" else -1
                if target * direction <= 0:
                    target = quantity * direction
            elif action in {"close", "close_all"}:
                if action == "close_all" or intent.get("id") == self.entry_id:
                    if intent.get("qty_percent") is not None:
                        percent = Decimal(str(intent["qty_percent"]))
                        if not percent.is_finite() or not 0 < percent <= 100:
                            raise StrategyProviderError(
                                "PROVIDER_PROTOCOL_VIOLATION", "invalid Pine close percentage"
                            )
                        quantity = abs(target) * percent / 100
                    else:
                        quantity = (
                            abs(target)
                            if intent.get("qty") is None
                            else Decimal(str(intent["qty"]))
                        )
                    # Closing an already flat authoritative account is a no-op.
                    if target == 0:
                        continue
                    if not quantity.is_finite() or quantity <= 0:
                        raise StrategyProviderError(
                            "PROVIDER_PROTOCOL_VIOLATION", "invalid Pine close quantity"
                        )
                    target = max(Decimal(0), abs(target) - quantity) * (
                        1 if target >= 0 else -1
                    )
            else:
                raise StrategyProviderError(
                    "FIDELITY_UNSUPPORTED",
                    f"unsupported chart Pine order action: {action}",
                )
        if warmup or not intents or target == actual:
            return None
        payload = {"targetExposure": str(target), "reasonCode": "pine_engine_market"}
        return StrategyOutput(
            frame.sequence,
            "TARGET_POSITION",
            payload,
            self.state_hash,
            canonical_hash(payload),
        )

    def warmup(self, frame):
        self._evaluate(frame, warmup=True)

    def step(self, frame):
        return self._evaluate(frame)

    def on_execution_report(self, report):
        # Every subsequent observation carries the actual ledger state.
        if "accepted" not in report:
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION", "execution report missing accepted"
            )

    def snapshot(self):
        from copy import deepcopy
        if self.streaming:
            from .pine_streaming import snapshot
            stream_checkpoint=snapshot(self)
        return deepcopy({
            "context": self.context,
            "bars": self.bars,
            "accounts": self.accounts,
            "history": self.history,
            "entry_id": self.entry_id,
            "state_hash": self.state_hash,
            **({"stream_checkpoint":stream_checkpoint} if self.streaming else {}),
            **({"request_feed": self.request_feed.snapshot(), "request_updates": self.request_groups}
               if self.request_feed is not None else {}),
            **({"risk_rules": self.risk_configuration} if self.entry_risk else {}),
            **({"execution_times": self.execution_times} if self.needs_clock else {}),
            **({"execution_schedule": encode_schedule(self.execution_passes, self.execution_contexts)} if self.scheduled
               else {"execution_passes": self.execution_passes} if self.pass_mode else {}),
        })

    def restore(self, payload):
        from copy import deepcopy
        payload = deepcopy(payload)
        self.prepare(payload["context"])
        if ("execution_schedule" in payload) != self.scheduled or (self.scheduled and "execution_passes" in payload):
            self.close()
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "restored Pine schedule mode differs")
        self.bars, self.accounts = list(payload["bars"]), list(payload["accounts"])
        self.history, self.entry_id = list(payload["history"]), payload["entry_id"]
        self.state_hash = payload["state_hash"]
        if self.entry_risk:
            self.risk_configuration = payload.get("risk_rules")
            if self.bars and not isinstance(self.risk_configuration, dict):
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "restored Pine risk configuration missing")
        if self.scheduled:
            self.execution_passes, self.execution_contexts = decode_schedule(payload.get("execution_schedule"), len(self.bars),streaming=self.streaming)
        elif self.fill_callbacks:
            from copy import deepcopy
            passes = payload.get("execution_passes")
            if not isinstance(passes, list) or len(passes) != len(self.bars):
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "restored Pine execution passes are missing")
            self.execution_passes = deepcopy(passes)
        if self.needs_clock:
            clocks = payload.get("execution_times")
            if not isinstance(clocks, list) or len(clocks) != len(self.bars):
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "restored Pine execution clocks are missing")
            self.execution_times = list(clocks)
        if self.request_feed is not None:
            try:
                self.request_groups = payload.get("request_updates", [])
                if self.pass_mode:
                    if self.request_groups:
                        raise ValueError("mixed requested transcript modes")
                    observations = [dict(observed_at_ms=item["request_observed_at_ms"], updates=item["request_updates"])
                                    for group in self.execution_passes for item in group]
                else:
                    if len(self.request_groups) != len(self.bars):
                        raise ValueError("requested transcript count differs")
                    observations = self.request_groups
                self.request_feed.replay(observations)
                if self.request_feed.snapshot() != payload.get("request_feed"):
                    raise ValueError("requested observation cursor differs")
            except (KeyError, ValueError, TypeError) as exc:
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "restored Pine requested transcript differs") from exc
        elif "request_feed" in payload or "request_updates" in payload:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "restored Pine requested mode differs")
        if self.streaming:
            from .pine_streaming import restore
            restore(self,payload,self.runtime_launch)

    def identity(self):
        return {
            "matrixVersion": REVISION,
            "runtime": self.runtime_identity,
            "tradingViewEquivalent": False,
        }

    def report_metadata(self):
        close_callbacks = sum(max(0, sum(item["confirmed"] for item in group) - 1) for group in self.execution_passes)
        if self.scheduled:
            close_callbacks = sum(item["trigger"] == "closing_fill" for group in self.execution_contexts for item in group)
        skip=(self.stream.input_skip if self.stream is not None else (self._closed_stream_checkpoint or {}).get("input_skip",0)) if self.streaming else 0
        return {"pineExecution": {
            "profile": "OBSERVED_AGG_TRADE_TICK_STREAM" if self.realtime_streaming else "HISTORICAL_OHLC_TICK_STREAM" if self.streaming else "EXPLICIT_HOST_EXECUTION_SCHEDULE" if self.scheduled else "CAUSAL_AGG_TRADE_FILL_PASSES" if self.fill_callbacks else "CONFIRMED_BAR_CLOSE",
            **({"executionScheduleContract": SCHEDULE_CONTRACT} if self.scheduled else {}),
            **({"externalStreamContract":STREAM_CONTRACT,
                **({"realtimeTickCount":sum(item["trigger"]=="realtime_tick" for group in self.execution_contexts for item in group),
                    "confirmationCount":sum(item["trigger"]=="bar_close" for group in self.execution_contexts for item in group)} if self.realtime_streaming else
                   {"historicalTickCount":sum(len(group) for group in self.execution_passes[skip:]),
                    "historicalObservationCount":sum(len(group) for group in self.execution_passes)}),"inputSkip":skip} if self.streaming else {}),
            "accountAuthority": "candlescope", "tradingViewEquivalent": False,
            **({"defaultQuantity": dict(self.default_quantity)} if self.default_quantity is not None else {}),
            "barCount": len(self.bars),
            "fillCallbackCount": (sum(item["trigger"] in {"order_fill", "closing_fill"} for group in self.execution_contexts for item in group)
                                  if self.scheduled else sum(not item["confirmed"] for group in self.execution_passes for item in group) + close_callbacks),
            **({"closingTickContract": CLOSING_CONTRACT, "closingFillCallbackCount": close_callbacks} if self.process_on_close else {}),
        }}

    def abort(self):
        self.cancelled.set()
        self.close()

    def close(self):
        if self.stream is not None:
            self._closed_stream_checkpoint=self.stream.checkpoint()
            self.stream.close()
            self.stream=None
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.close()
        return canonical_hash(self.history)
