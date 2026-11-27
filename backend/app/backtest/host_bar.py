"""Host BAR execution pieces shared by fixed-history and forward runs.

The kernel, Host order planner, observation features, planning context and the
Pine account view a strategy reads. ``service.execute_bar_run`` and the forward
host (``continuous_bar_host``) both build them here, so the two runs keep one
account and matching configuration (ADR-BACKTEST-015 §3.4).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from app.market_dataset.snapshot import MarketEvent
from app.simulation import SimulationKernel, TradeSimulationKernel
from app.simulation.execution_realism import EXECUTION_REALISM_V2

from .errors import BacktestError
from .execution_contract import _config_decimal, _config_optional_decimal
from .strategy.host_planner import HostOrderPlanner
from .strategy.host_policy import PlanningContext
from .strategy.protocol import StrategyProviderError


def _strategy_observation_features(
    provider: object,
    *,
    bar: Mapping[str, object] | None,
    trade: Mapping[str, object] | None,
    _names: tuple[str, ...] | None = None,
) -> dict[str, str]:
    source: dict[str, object] = {}
    if bar is not None:
        for name in ("open", "high", "low", "close", "volume"):
            if bar.get(name) is not None:
                source[name] = bar[name]
    if trade is not None:
        if trade.get("price") is not None:
            source.setdefault("close", trade["price"])
            source.setdefault("price", trade["price"])
        if trade.get("qty") is not None:
            source.setdefault("volume", trade["qty"])
    names = _declared_feature_names(provider) if _names is None else _names
    if names:
        missing = [name for name in names if name not in source]
        if missing:
            raise StrategyProviderError(
                "PROVIDER_PROTOCOL_VIOLATION",
                f"missing features {missing}",
            )
        return {name: str(source[name]) for name in names}
    if "close" in source:
        return {"close": str(source["close"])}
    return {key: str(value) for key, value in source.items()}


def _assert_strategy_frame_inputs(
    provider: object,
    *,
    bar: Mapping[str, object] | None,
    trade: Mapping[str, object] | None,
    _modes: tuple[str, ...] | None = None,
) -> None:
    modes = _modes
    if modes is None:
        describe = getattr(provider, "describe", None)
        if not callable(describe):
            return
        modes = tuple(getattr(describe(), "input_modes", ()) or ())
    if "BAR_CLOSE" in modes and bar is None:
        raise StrategyProviderError(
            "PROVIDER_PROTOCOL_VIOLATION", "BAR_CLOSE requires a bar"
        )
    if "TRADE_EVENT" in modes and trade is None:
        raise StrategyProviderError(
            "PROVIDER_PROTOCOL_VIOLATION", "TRADE_EVENT requires a trade"
        )
    if "BOOK_EVENT" in modes:
        raise StrategyProviderError(
            "FIDELITY_UNSUPPORTED",
            "BOOK_EVENT is not available on this execute path",
        )


def _declared_feature_names(provider: object) -> tuple[str, ...] | None:
    artifact = getattr(provider, "_artifact", None)
    schema = getattr(artifact, "feature_schema", None) if artifact is not None else None
    if schema is None:
        schema = getattr(provider, "feature_schema", None)
    names = getattr(schema, "names", None)
    if not names:
        describe = getattr(provider, "describe", None)
        capabilities = describe() if callable(describe) else None
        names = getattr(capabilities, "required_features", None)
    if not names:
        return None
    return tuple(str(name) for name in names)


def _execution_kernel_kwargs(config: Mapping[str, object]) -> dict[str, object]:
    if config.get("execution_model_revision") != EXECUTION_REALISM_V2:
        return {}
    return {
        "execution_model_revision": EXECUTION_REALISM_V2,
        "participation_rate": _config_decimal(config, "participation_rate", "0.1"),
        "latency_ms": int(config.get("latency_ms") or 0),
        "latency_events": int(config.get("latency_events") or 0),
        "order_end_policy": str(config.get("order_end_policy") or "CANCEL_AT_END"),
        "equity_curve_event_interval": int(
            config.get("equity_curve_event_interval") or 100
        ),
        "equity_curve_mode": (
            str(config["equity_curve_mode"])
            if config.get("equity_curve_mode") is not None
            else None
        ),
        **(
            {"bar_path_scenario": str(config["bar_path_scenario"])}
            if config.get("bar_path_scenario") is not None
            else {}
        ),
    }


def _planning_context(kernel: Any, event: MarketEvent) -> PlanningContext:
    account = kernel.account
    reference = getattr(account, "mark", None)
    if reference is None:
        reference = event.payload.get("close", event.payload.get("price"))
    if reference is None:
        raise BacktestError(
            "DATA_ROLE_COVERAGE_MISSING", "Host policy requires a visible price"
        )
    quantity_step = getattr(account, "step", None) or getattr(kernel, "qty_step", None)
    min_notional = getattr(account, "min_notional", None) or getattr(
        kernel, "min_notional", None
    )
    contract_multiplier = getattr(account, "multiplier", None) or Decimal("1")
    active_orders = (len(kernel._live_orders()) if isinstance(kernel, SimulationKernel)
                     else sum(order.status in {"OPEN", "PARTIAL"} for order in
                              (kernel._working_orders() if isinstance(kernel, TradeSimulationKernel) else kernel.orders)))
    cumulative_fees = getattr(account, "cumulative_fees", None)
    if cumulative_fees is None:
        cumulative_fees = getattr(kernel, "fee_total", Decimal("0"))
    return PlanningContext(
        sequence=event.sequence,
        event_time_ms=event.event_time_ms,
        actual_position=account.position_qty,
        projected_position=kernel.projected_position_qty,
        reference_price=Decimal(str(reference)),
        equity=account.equity(),
        initial_balance=kernel.initial_balance,
        cumulative_fees=Decimal(str(cumulative_fees)),
        leverage=Decimal(str(getattr(account, "leverage", kernel.leverage))),
        active_order_count=active_orders,
        quantity_step=quantity_step,
        min_notional=min_notional,
        contract_multiplier=Decimal(str(contract_multiplier)),
        rule_revision=str(getattr(account, "rule_version", None) or "LEGACY_CONFIG"),
        taker_fee_bps=kernel.taker_fee_bps,
        maker_fee_bps=kernel.maker_fee_bps,
    )


def _pine_account_view(kernel):
    account = kernel.account
    from .external import account_feedback_profit
    from .pine_contract_metadata import observed_contract_metadata
    metadata = observed_contract_metadata(kernel)
    return {**({"_contract_metadata": metadata} if metadata is not None else {}), "position_size": float(account.position_qty),
            "position_avg_price": None if account.entry_price is None else float(account.entry_price),
            "equity": float(account.equity()), "initial_capital": float(kernel.initial_balance),
            "netprofit": float(account_feedback_profit(account, kernel.initial_balance)),
            "openprofit": float(account.unrealized())}


def _strategy_execution_reporter(session):
    def report(event: dict) -> None:
        payload = dict(event)
        payload.setdefault("accepted", True)
        payload["generation"] = session.generation
        session.on_execution_report(payload)

    return report


def _build_bar_kernel(config, execution_reporter):
    """One BAR kernel configuration for fixed and continuing strategy execution.

    A Pine script with a frozen path contract runs on the Host bar kernel's chart clock, or
    its V2 path clock when the V2 contract is frozen too (ADR-BACKTEST-015 P6).
    """
    from app.simulation.ohlc_path import BAR_CLOCK, PINE_CHART, PINE_V2
    from app.simulation.practice_clock import PRACTICE, PRACTICE_ACCOUNT_RULES
    bar_clock = (PINE_V2 if config.get("pine_v2_bar_contract") else PINE_CHART) if config.get("pine_bar_path_contract") else BAR_CLOCK
    if config.get("account_rules") == PRACTICE_ACCOUNT_RULES:
        bar_clock = PRACTICE
    kernel = SimulationKernel(
        bar_clock=bar_clock,
        process_orders_on_close=bool(config.get("pine_process_on_close")),
        account_model=str(
            config.get("account_model") or "LINEAR_PERP_ONE_WAY_V1"
        ),
        funding_mode=str(config.get("funding_mode") or "OFF"),
        leverage=_config_decimal(config, "leverage", "1"),
        host_policy_revision=config.get("host_policy_revision"),
        slippage_bps=_config_decimal(config, "slippage_bps", "1"),
        taker_fee_bps=_config_decimal(config, "taker_fee_bps", "0"),
        maker_fee_bps=_config_decimal(config, "maker_fee_bps", "0"),
        funding_rate=_config_decimal(config, "funding_rate", "0"),
        funding_interval_ms=int(config.get("funding_interval_hours") or 8)
        * 3_600_000,
        initial_balance=_config_decimal(config, "initial_balance", "10000"),
        price_tick=_config_optional_decimal(config, "price_tick"),
        qty_step=_config_optional_decimal(config, "qty_step"),
        min_notional=_config_optional_decimal(config, "min_notional"),
        gap_policy=str(config.get("gap_policy") or "REJECT"),
        **_execution_kernel_kwargs(config),
        execution_reporter=execution_reporter,
    )
    return kernel


def _new_host_planner(config, **kwargs):
    if config.get("pine_process_on_close"):
        from .strategy.pine_planner import host_identity
        if config.get("pine_order_runtime_identity") != host_identity():
            raise BacktestError("IDENTITY_MUTATION", "Pine closing-tick implementation changed; create a fresh run")
    if config.get("pine_runtime_identity") and config.get("output_mode") == "ORDER_INTENT":
        from .strategy.pine_planner import PineHostPlanner, host_identity
        if config.get("pine_order_runtime_identity") != host_identity():
            raise BacktestError("IDENTITY_MUTATION", "Pine Host order implementation changed; create a fresh run")
        return PineHostPlanner(config, **kwargs)
    return HostOrderPlanner(config, **kwargs)
