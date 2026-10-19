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
    blocked = {
        feature
        for feature in features
        if (feature.startswith("request.") and feature not in {"request.security", "request.security_lower_tf"})
        or (feature.startswith("strategy.risk") and (feature not in RISK_FUNCTIONS
            or result["identity"].get("entry_risk_contract") != RISK_CONTRACT))
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
        or any(
            execution.get(key)
            for key in ("calcOnEveryTick",)
        )
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
        self.cancelled = threading.Event()
        self.bars, self.accounts, self.history = [], [], []
        self.entry_id = None
        self.context = {}
        self.runtime_identity = None
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
        self.cancelled = threading.Event()
        self.context = dict(context)
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
            self.needs_clock = frozen.get("executionClock") == "explicitTimestampWhenEvaluated"
            self.fill_callbacks = frozen.get("fillCallbacks") is True
            self.process_on_close = frozen.get("processOnClose") is True
            self.entry_risk = frozen.get("entryRisk") is True
        except (KeyError, ValueError, TypeError) as exc:
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION", "compiled Pine source envelope required"
            ) from exc
        if self.fill_callbacks and not self.order_mode:
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "fill callbacks require ORDER_INTENT mode")
        if self.entry_risk and (not self.order_mode or self.runtime_identity.get("entry_risk_contract") != RISK_CONTRACT):
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "Pine risk rules require the Host order risk contract")
        if frozen.get("requiresOrderMode") and not self.order_mode:
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "generic and OCA orders require ORDER_INTENT mode")
        runtime = plugin()
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
            **({"closing_ticks": True} if self.process_on_close else {}),
            **({"risk_contract": RISK_CONTRACT} if self.entry_risk else {}),
        }
        from app.backtest.errors import BacktestError
        from app.backtest.pine_requested_data import load_contexts
        try:
            self.requested_streams = load_contexts(context.get("pineLocalDataRoot"), context.get("pineRequestedContexts", []))
        except BacktestError as exc:
            raise StrategyProviderError(exc.code, str(exc)) from exc
        self.worker = SessionWorker(runtime, self.wire, self.cancelled, evaluator=True)
        self.bars, self.accounts, self.history, self.entry_id = [], [], [], None
        self.execution_times = []
        self.execution_passes = []
        self.state_hash = canonical_hash([])
        self.risk_configuration = None

    def _evaluate(self, frame, *, warmup=False):
        if self.worker is None or not frame.account_view:
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION",
                "Pine requires the authoritative Host account",
            )
        row = frame.bar or {}
        bar = {
            name: float(row[name])
            for name in ("open", "high", "low", "close", "volume")
        }
        bar["time"] = int(row.get("open_time_ms", frame.event_time_ms)) // 1000
        account = dict(frame.account_view)
        account["time"] = bar["time"]
        confirmed, pass_index = True, None
        if self.fill_callbacks:
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
            if pass_index >= 65:
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
        contexts = visible_contexts(self.requested_streams,
            min(frame.watermark_ms - (0 if confirmed else 1), int(row.get("close_time_ms", frame.event_time_ms))))
        if self.fill_callbacks:
            self.execution_passes[index].append({"bar": dict(bar), "account": dict(account), "confirmed": confirmed,
                "event_time_ms": frame.event_time_ms, "request_data": [
                    {key: value for key, value in context.items() if key in {"symbol", "timeframe", "bars"}}
                    for context in contexts]})
            contexts = [{**context, "bars": []} for context in contexts]
        result = self.worker.request(
            {
                **self.wire,
                "bars": self.bars,
                "accounts": self.accounts,
                **({"contexts": contexts} if contexts else {}),
                **({"execution_times": self.execution_times} if self.needs_clock else {}),
                **({"execution_passes": self.execution_passes} if self.fill_callbacks else {}),
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
            return (item["bar_index"], item.get("pass_index", -1)) if self.fill_callbacks else (item["bar_index"], -1)
        cursor = (index, pass_index) if self.fill_callbacks else (index, -1)
        previous = [item for item in result["intents"] if ordinal(item) < cursor]
        if previous != self.history:
            raise StrategyProviderError(
                "LOOKAHEAD_VIOLATION", "Pine changed an earlier decision"
            )
        intents = [item for item in result["intents"] if ordinal(item) == cursor]
        if (len(intents) > 64 or len(previous) + len(intents) != len(result["intents"])
                or sum(item["bar_index"] == index for item in result["intents"]) > 64):
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
                    "eventTimeMs": frame.event_time_ms}} if self.fill_callbacks else {}),
            }
        )
        if self.order_mode:
            if warmup or not intents:
                return None
            payload = {"contract": ORDER_CONTRACT, "intents": intents, "pyramiding": result.get("pyramiding", 1)}
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
        return {
            "context": self.context,
            "bars": self.bars,
            "accounts": self.accounts,
            "history": self.history,
            "entry_id": self.entry_id,
            "state_hash": self.state_hash,
            **({"risk_rules": self.risk_configuration} if self.entry_risk else {}),
            **({"execution_times": self.execution_times} if self.needs_clock else {}),
            **({"execution_passes": self.execution_passes} if self.fill_callbacks else {}),
        }

    def restore(self, payload):
        self.prepare(payload["context"])
        self.bars, self.accounts = list(payload["bars"]), list(payload["accounts"])
        self.history, self.entry_id = list(payload["history"]), payload["entry_id"]
        self.state_hash = payload["state_hash"]
        if self.entry_risk:
            self.risk_configuration = payload.get("risk_rules")
            if self.bars and not isinstance(self.risk_configuration, dict):
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "restored Pine risk configuration missing")
        if self.fill_callbacks:
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

    def identity(self):
        return {
            "matrixVersion": REVISION,
            "runtime": self.runtime_identity,
            "tradingViewEquivalent": False,
        }

    def report_metadata(self):
        close_callbacks = sum(max(0, sum(item["confirmed"] for item in group) - 1) for group in self.execution_passes)
        return {"pineExecution": {
            "profile": "CAUSAL_AGG_TRADE_FILL_PASSES" if self.fill_callbacks else "CONFIRMED_BAR_CLOSE",
            "accountAuthority": "candlescope", "tradingViewEquivalent": False,
            "barCount": len(self.bars),
            "fillCallbackCount": sum(not item["confirmed"] for group in self.execution_passes for item in group) + close_callbacks,
            **({"closingTickContract": CLOSING_CONTRACT, "closingFillCallbackCount": close_callbacks} if self.process_on_close else {}),
        }}

    def abort(self):
        self.cancelled.set()
        self.close()

    def close(self):
        if self.worker is not None:
            self.worker.close()
            self.worker = None
        return canonical_hash(self.history)
