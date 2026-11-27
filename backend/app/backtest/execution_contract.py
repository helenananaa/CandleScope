"""The shared financial preflight of a strategy run's account and fees.

No revision, input, provider or storage access: fixed-history runs and forward
runs both validate their execution configuration here.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping

from .errors import BacktestError
from .strategy.host_policy import HostPolicyConfig
from .strategy.protocol import StrategyProviderError


def _config_decimal(config: Mapping[str, object], name: str, default: str) -> Decimal:
    try:
        value = Decimal(str(config.get(name, default)))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", f"{name} must be Decimal") from exc
    if not value.is_finite() or value < 0:
        raise BacktestError(
            "SCHEMA_UNKNOWN_FIELD", f"{name} must be finite and non-negative"
        )
    return value


def _config_optional_decimal(config: Mapping[str, object], name: str) -> Decimal | None:
    if config.get(name) is None:
        return None
    value = _config_decimal(config, name, "0")
    if value <= 0:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", f"{name} must be positive")
    return value


def _base_execution_contract(payload):
    """Shared financial preflight; no revision, input, provider or storage access."""
    account_model = str(payload.get("account_model") or "LINEAR_PERP_ONE_WAY_V1")
    if account_model not in {"LINEAR_PERP_ONE_WAY_V1", "LINEAR_PERP_ONE_WAY_V2", "SPOT_CASH_V1"}:
        raise BacktestError("FIDELITY_UNSUPPORTED", "unsupported account model")
    if str(payload.get("gap_policy") or "REJECT") not in {
        "REJECT",
        "PAUSE",
        "SKIP_WITH_WARNING",
    }:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "unknown gap_policy")
    contract_data_mode = str(payload.get("contract_data_mode") or "LEGACY_FIXED_V1")
    if contract_data_mode not in {
        "LEGACY_FIXED_V1",
        "HISTORICAL_CONTRACT_V1",
    }:
        raise BacktestError("FIDELITY_UNSUPPORTED", "unknown contract_data_mode")
    funding_mode = str(payload.get("funding_mode") or "OFF")
    if funding_mode not in {"OFF", "FIXED_SCENARIO", "HISTORICAL_REQUIRED"}:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "unknown funding_mode")
    leverage = _config_decimal(payload, "leverage", "1")
    if leverage < 1 or leverage > 125:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "leverage must be 1..125")
    if (
        account_model == "LINEAR_PERP_ONE_WAY_V2"
        and contract_data_mode != "HISTORICAL_CONTRACT_V1"
    ):
        raise BacktestError(
            "DATA_ROLE_COVERAGE_MISSING",
            "LINEAR_PERP_ONE_WAY_V2 requires historical mark and instrument rules",
        )
    for name, default, strictly_positive in (
        ("initial_balance", "10000", True),
        ("slippage_bps", "1", False),
        ("taker_fee_bps", "0", False),
        ("maker_fee_bps", "0", False),
    ):
        value = _config_decimal(payload, name, default)
        if strictly_positive and value <= 0:
            raise BacktestError("SCHEMA_UNKNOWN_FIELD", f"{name} must be positive")
        if not strictly_positive and value < 0:
            raise BacktestError(
                "SCHEMA_UNKNOWN_FIELD", f"{name} cannot be negative"
            )
    funding_rate = _config_decimal(payload, "funding_rate", "0")
    if account_model == "SPOT_CASH_V1" and (
        str(payload.get("market_type") or "").lower() != "spot" or leverage != 1
        or funding_mode != "OFF" or funding_rate != 0 or contract_data_mode != "LEGACY_FIXED_V1"
    ):
        raise BacktestError("SPOT_ACCOUNT_CONFIG_INVALID", "Spot cash requires a spot market, leverage 1, funding OFF and no contract multiplier")
    if abs(funding_rate) > Decimal("1"):
        raise BacktestError(
            "SCHEMA_UNKNOWN_FIELD", "funding_rate must be between -1 and 1"
        )
    if account_model == "LINEAR_PERP_ONE_WAY_V2":
        if funding_mode in {"OFF", "HISTORICAL_REQUIRED"} and funding_rate != 0:
            raise BacktestError(
                "SCHEMA_UNKNOWN_FIELD",
                f"{funding_mode} requires funding_rate=0",
            )
    try:
        funding_interval_hours = int(payload.get("funding_interval_hours") or 8)
    except (TypeError, ValueError) as exc:
        raise BacktestError(
            "SCHEMA_UNKNOWN_FIELD", "invalid funding_interval_hours"
        ) from exc
    if funding_interval_hours < 1 or funding_interval_hours > 168:
        raise BacktestError(
            "SCHEMA_UNKNOWN_FIELD", "funding_interval_hours must be 1..168"
        )
    output_mode = str(payload.get("output_mode") or "TARGET_POSITION")
    if output_mode not in {"SIGNAL", "TARGET_POSITION", "ORDER_INTENT"}:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "unsupported output_mode")
    try:
        host_policy = HostPolicyConfig.from_mapping(payload)
    except StrategyProviderError as exc:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", str(exc)) from exc
    quick_preset_id = str(payload.get("quick_preset_id") or "").strip()
    quick_preset_revision = str(payload.get("quick_preset_revision") or "").strip()
    fee_source = str(payload.get("fee_source") or "").strip()
    quick_fee_fields = ("taker_fee_bps", "maker_fee_bps", "slippage_bps")
    missing_quick_fee_fields = [
        name
        for name in quick_fee_fields
        if name not in payload or not str(payload.get(name) or "").strip()
    ]
    if quick_preset_id and (
        not quick_preset_revision or not fee_source or missing_quick_fee_fields
    ):
        raise BacktestError(
            "FEE_PRESET_UNKNOWN",
            "quick backtests require a versioned, confirmed fee preset",
            details={
                "next_step": "select or confirm the market fee preset",
                "missing_fields": missing_quick_fee_fields,
            },
        )
    return (account_model, contract_data_mode, funding_mode, leverage, funding_rate, funding_interval_hours, output_mode, host_policy, quick_preset_id, quick_preset_revision, fee_source)
