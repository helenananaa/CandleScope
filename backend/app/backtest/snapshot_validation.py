"""Snapshot identity and fidelity checks for all backtest launch paths."""
from __future__ import annotations

from typing import Any
from .errors import BacktestError
from .request_contracts import RunCreateRequest


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
    if payload.fidelity_mode not in capabilities and "AGG_TRADE_TAPE" not in capabilities:
        raise BacktestError(
            "FIDELITY_UNSUPPORTED",
            "this data only supports bar estimate",
        )
