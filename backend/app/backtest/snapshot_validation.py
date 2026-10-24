"""Snapshot identity and fidelity checks for all backtest launch paths."""
from __future__ import annotations

from typing import Any
from .errors import BacktestError
from .request_contracts import RunCreateRequest


def bind_external_snapshot_symbol(values: dict[str, Any], preview: dict[str, Any]) -> dict[str, Any]:
    """Freeze an external Run's instrument before it becomes visible in the queue."""
    if values.get("external_connection_id") is None:
        return values
    identity = preview.get("identity")
    symbol = identity.get("symbol") if isinstance(identity, dict) else None
    if not isinstance(symbol, str) or not symbol or symbol != symbol.strip():
        raise BacktestError("DATA_QUALITY_FAILED", "verified external snapshot lacks an instrument identity")
    return {**values, "symbol": symbol}


def require_contract_snapshot(
    preview: dict[str, Any], contract_data_mode: str
) -> None:
    if contract_data_mode != "HISTORICAL_CONTRACT_V1":
        return
    contract = preview.get("quality", {}).get("contract_data", {})
    if contract.get("status") != "complete":
        raise BacktestError(
            "DATA_ROLE_COVERAGE_MISSING",
            "historical contract roles must be complete before Run",
            details={"contract_data": contract},
        )


def require_declared_snapshot(preview: dict[str, Any], payload: RunCreateRequest) -> None:
    if (
        preview["snapshot_hash"] != payload.snapshot_hash
        or preview.get("data_epoch") != payload.data_epoch
    ):
        raise BacktestError(
            "DATA_SNAPSHOT_MISMATCH",
            "declared snapshot identity does not match the selected window",
        )
    if payload.fidelity_mode == "BAR_APPROX":
        return
    capabilities = preview.get("fidelity_capabilities") or []
    from .chart_book import BOOK_MODES
    if payload.fidelity_mode not in capabilities and (payload.fidelity_mode in BOOK_MODES or "AGG_TRADE_TAPE" not in capabilities):
        raise BacktestError(
            "FIDELITY_UNSUPPORTED",
            "this data only supports bar estimate",
        )
