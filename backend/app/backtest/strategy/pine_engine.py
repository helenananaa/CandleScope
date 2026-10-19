"""Real Pine decisions, with market orders and one net entry owner.

The existing Host planner/account remains authoritative. Rich order profiles
continue to use the separate native/host-matching workbench.
"""

from __future__ import annotations

import json
import re
import threading
from decimal import Decimal

from .protocol import (
    ProviderCapabilities,
    StrategyOutput,
    StrategyProviderError,
    canonical_hash,
)

REVISION = "pine-engine-chart-v1"
SOURCE_SCHEMA = "candlescope.chart-pine/1"


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
        or feature.startswith("strategy.risk")
        or feature
        in {"strategy.exit", "strategy.order", "strategy.cancel", "strategy.cancel_all"}
    }
    execution = requirements.get("execution", {})
    if (
        info.get("scriptMode") != "strategy"
        or not info.get("executable")
        or blocked
        or result.get("profileError")
        or result.get("pyramiding") != 1
        or any(item.get("function") not in {"security", "request.security", "request.security_lower_tf"}
               for item in requirements.get("requests", []))
        or (requirements.get("account") or {}).get("declaredCurrency")
        or any(
            execution.get(key)
            for key in ("calcOnEveryTick", "calcOnOrderFills", "processOrdersOnClose")
        )
        or execution.get("clock") not in {"notUsed", "explicitTimestampWhenEvaluated"}
        or (execution.get("clock") == "explicitTimestampWhenEvaluated"
            and not result["identity"].get("external_execution_times"))
    ):
        raise StrategyProviderError(
            "FIDELITY_UNSUPPORTED",
            "Chart Pine supports closed-bar market entry/close with one entry ID; "
            "use pinned requested datasets; use the native strategy workbench for price orders, pyramiding or intrabar callbacks. "
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
            output_modes=("TARGET_POSITION",),
            signal_clock="BAR_CLOSE",
        )

    def prepare(self, context):
        from app.backtest.native import PROTOCOL, invoke
        from app.backtest.native_session import SessionWorker

        self.close()
        self.cancelled = threading.Event()
        self.context = dict(context)
        try:
            frozen = json.loads(context["source"])
            if frozen.get("schema") != SOURCE_SCHEMA:
                raise ValueError("unknown source envelope")
            self.source = frozen["source"]
            self.libraries = validate_libraries(frozen.get("libraries", {}))
            self.runtime_identity = frozen["identity"]
            self.needs_clock = frozen.get("executionClock") == "explicitTimestampWhenEvaluated"
        except (KeyError, ValueError, TypeError) as exc:
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION", "compiled Pine source envelope required"
            ) from exc
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
        self.state_hash = canonical_hash([])

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
        self.bars.append(bar)
        account = dict(frame.account_view)
        account["time"] = bar["time"]
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
            min(frame.watermark_ms, int(row.get("close_time_ms", frame.event_time_ms))))
        result = self.worker.request(
            {
                **self.wire,
                "bars": self.bars,
                "accounts": self.accounts,
                **({"contexts": contexts} if contexts else {}),
                **({"execution_times": self.execution_times} if self.needs_clock else {}),
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
        previous = [item for item in result["intents"] if item["bar_index"] < index]
        if previous != self.history:
            raise StrategyProviderError(
                "LOOKAHEAD_VIOLATION", "Pine changed an earlier decision"
            )
        intents = [item for item in result["intents"] if item["bar_index"] == index]
        if len(intents) > 64 or len(previous) + len(intents) != len(result["intents"]):
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
                **({"executionTimeMs": frame.event_time_ms} if self.needs_clock else {}),
            }
        )
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
                    "FIDELITY_UNSUPPORTED", "use the native workbench for price orders"
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
            **({"execution_times": self.execution_times} if self.needs_clock else {}),
        }

    def restore(self, payload):
        self.prepare(payload["context"])
        self.bars, self.accounts = list(payload["bars"]), list(payload["accounts"])
        self.history, self.entry_id = list(payload["history"]), payload["entry_id"]
        self.state_hash = payload["state_hash"]
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

    def abort(self):
        self.cancelled.set()
        self.close()

    def close(self):
        if self.worker is not None:
            self.worker.close()
            self.worker = None
        return canonical_hash(self.history)
