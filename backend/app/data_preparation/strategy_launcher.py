"""Durable chart strategy launch using the existing validation and worker queue."""
from __future__ import annotations

import json

from .models import PreparationError


def revision(runtime, revision_id):
    row = runtime.service.repository.get_strategy_revision(revision_id)
    if row is None or row["archived_at_ms"] is not None:
        raise PreparationError("STRATEGY_REVISION_UNAVAILABLE", "Select an active compiled strategy revision")
    capabilities = json.loads(row["capabilities_json"])
    return capabilities


def launch(runtime, intent, resolution, job_id):
    from app.backtest.request_contracts import RunCreateRequest
    from app.backtest.snapshot_validation import require_declared_snapshot, require_contract_snapshot
    from app.backtest.errors import BacktestError

    key = f"preparation:{job_id}"
    existing = runtime.service.repository.get_run_by_idempotency(key)
    if existing is not None:
        return existing
    capabilities = revision(runtime, intent["strategy_revision_id"])
    cost = resolution["cost_preset"]
    account = resolution["account_execution_preset"]
    context = resolution["request"]
    override = intent.get("execution_overrides") or {}
    output_modes = capabilities["output_modes"]
    body = {
        "strategy_revision_id": intent["strategy_revision_id"],
        "dataset_id": resolution["dataset_id"], "data_epoch": resolution["data_epoch"],
        "snapshot_hash": resolution["snapshot_hash"], "fidelity_mode": resolution["fidelity"]["mode"],
        "source_event_kind": "BAR" if resolution["fidelity"]["mode"] == "BAR_APPROX" else "AGG_TRADE",
        "start_time_ms": resolution["coverage"]["requested_start_ms"],
        "end_time_ms": resolution["coverage"]["requested_end_ms"],
        "exchange": context["exchange"], "market_type": context["market_type"],
        "symbol": context["symbol"], "interval": context["interval"],
        "parameters": intent["parameters"], "warmup_bars": intent.get("warmup_bars", 0),
        "output_mode": "TARGET_POSITION" if "TARGET_POSITION" in output_modes else output_modes[0],
        "signal_trace_mode": "PAGED_V1", "account_model": account["account_model"],
        "contract_data_mode": account["contract_data_mode"],
        "initial_balance": override.get("initialBalance", account["initial_cash"]),
        "slippage_bps": override.get("slippageBps", cost["slippage_bps"]),
        "taker_fee_bps": override.get("feeBps", cost["fee_bps"]),
        "maker_fee_bps": override.get("feeBps", cost["fee_bps"]),
        "fee_source": "user-defined" if override else cost["fee_source"],
        "funding_rate": "0", "funding_interval_hours": 8, "funding_mode": account["funding_mode"],
        "leverage": override.get("leverage", account["leverage"]),
        "sizing_policy": account["sizing_policy"],
        "equity_percent": override.get("equityPercent", account["equity_percent"]),
        "execution_model_revision": account["execution_model_revision"], "participation_rate": "0.1",
        "latency_ms": 0, "latency_events": 0, "order_end_policy": "CANCEL_AT_END", "gap_policy": "REJECT",
        "quick_preset_id": resolution["quick_preset_id"], "quick_preset_revision": cost["preset_revision"],
        "chart_range_mode": context["range_mode"], "chart_cell_scope": intent.get("chart_cell_scope"),
        "strategy_draft_id": intent.get("strategy_draft_id"),
        "python_runtime_mode": intent.get("python_runtime_mode"),
        "python_trusted_confirmed": intent.get("python_trusted_confirmed", False),
    }
    try:
        payload = RunCreateRequest.model_validate(body)
        normalized = payload.model_dump()
        runtime.service.smoke_strategy_revision(payload.strategy_revision_id, {
            "dataset_id": payload.dataset_id, "snapshot_hash": payload.snapshot_hash,
            "start_time_ms": payload.start_time_ms,
            "end_time_ms": min(payload.end_time_ms, payload.start_time_ms + 7 * 86_400_000),
            "parameters": payload.parameters, "python_runtime_mode": payload.python_runtime_mode,
            "python_trusted_confirmed": payload.python_trusted_confirmed,
        })
        runtime.service.validate_run(normalized)
        preview = runtime.preview_snapshot(**{name: normalized[name] for name in (
            "dataset_id", "data_epoch", "start_time_ms", "end_time_ms", "interval", "fidelity_mode",
            "exchange", "market_type", "contract_data_mode", "account_model", "funding_mode")})
        require_contract_snapshot(preview, payload.contract_data_mode)
        require_declared_snapshot(preview, payload)
        return runtime.service.create_run(normalized, idempotency_key=key)
    except BacktestError as exc:
        raise PreparationError(exc.code, str(exc)) from exc
