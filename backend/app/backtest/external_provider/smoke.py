"""Actual bounded external lifecycle smoke on a verified Host snapshot."""

from __future__ import annotations

import time
import uuid
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json, sha256_hex
from app.backtest.strategy.host_adapter import StrategyHostAdapter
from app.backtest.strategy.protocol import (
    StrategyProviderError,
    StrategyProviderSession,
)
from app.market_dataset.snapshot import MarketDatasetError
from app.simulation.trade_bar_builder import derive_complete_trade_bars

if TYPE_CHECKING:
    from app.backtest.runtime import BacktestRuntime

PREVIEW_KEYS = ("dataset_id", "data_epoch", "start_time_ms", "end_time_ms", "interval", "fidelity_mode",
                "exchange", "market_type", "contract_data_mode", "account_model", "funding_mode")


def verify_snapshot(runtime: BacktestRuntime, values: dict[str, Any]) -> dict[str, Any]:
    runtime.service.external.require_enabled()
    if values["fidelity_mode"] not in {"BAR_APPROX", "AGG_TRADE_EXECUTION"}:
        raise BacktestError("FIDELITY_UNSUPPORTED", "external models require a closed BAR signal clock")
    if (values["end_time_ms"] <= values["start_time_ms"] or
            values["end_time_ms"] - values["start_time_ms"] > runtime.settings.max_horizon_days * 86_400_000):
        raise BacktestError("BUDGET_EXCEEDED", "external snapshot window exceeds the Host horizon budget")
    preview = runtime.preview_snapshot(**{key: values[key] for key in PREVIEW_KEYS})
    if preview["snapshot_hash"] != values["snapshot_hash"] or preview["data_epoch"] != values["data_epoch"]:
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", "external connection snapshot changed")
    from app.backtest.snapshot_validation import require_contract_snapshot
    require_contract_snapshot(preview, values["contract_data_mode"])
    return preview


def run_smoke(runtime: BacktestRuntime, values: dict[str, Any]) -> dict[str, Any]:
    with runtime.service.external.smoke_slot():
        return _run_smoke(runtime, values)


def _run_smoke(runtime: BacktestRuntime, values: dict[str, Any]) -> dict[str, Any]:
    """Probe inference, not a fabricated financial or deterministic-model result."""
    control = runtime.service.external
    parsed = control.manifest(values["strategy_revision_id"])
    preview = verify_snapshot(runtime, values)
    binding = control.validate_binding(values)
    output_mode = values["output_mode"]
    if output_mode not in parsed.output_modes:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external smoke output mode was not declared")
    snapshot = None
    try:
        if values["fidelity_mode"] == "BAR_APPROX":
            snapshot = runtime.snapshots.open(runtime._dataset_ref(**values))
            events = (event for event in snapshot.events if event.role == "BARS")
        else:
            manifest = runtime._manifest(values["dataset_id"])
            dataset = runtime._freeze_trade_dataset(exchange=values["exchange"], market_type=values["market_type"],
                                                    symbol=str(manifest["symbol"]), start_time_ms=values["start_time_ms"],
                                                    end_time_ms=values["end_time_ms"])
            if dataset.to_dict() != preview["identity"]:
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", "external smoke trade archive changed after preview")
            # The preview verified the full binding; the same immutable archive
            # is used for causal derived BARs, never replaced with imported OHLC.
            events = iter(derive_complete_trade_bars(runtime.worker._load_trade_events(dataset), values["interval"]))
        selected = []
        for event in events:
            if selected and event.event_time_ms - selected[0].event_time_ms > 7 * 86_400_000:
                break
            selected.append(event)
            if len(selected) >= parsed.warmup_bars + 3:
                break
        if len(selected) <= parsed.warmup_bars:
            raise BacktestError("DATA_QUALITY_FAILED", "bounded smoke needs the declared warmup and at least one evaluation BAR")
        run_id = "smoke_" + uuid.uuid4().hex
        deadline = time.monotonic() + runtime.settings.max_run_seconds

        def check_control():
            if time.monotonic() > deadline:
                raise StrategyProviderError("BUDGET_EXCEEDED", "external smoke exceeded the Host run budget")
            if runtime._shutdown:
                raise StrategyProviderError("PROVIDER_CRASH_UNRECOVERABLE", "Host is shutting down")

        from .provider import ExternalDecisionProvider
        provider = ExternalDecisionProvider(control.journal(binding["external_connection_id"]),
                                            connection_id=binding["external_connection_id"], host_generation=1,
                                            step_timeout_s=runtime.settings.provider_step_timeout_ms / 1000,
                                            check_control=check_control)
        session = StrategyProviderSession(provider, run_id=run_id)
        adapter = StrategyHostAdapter(session, step_timeout_s=runtime.settings.provider_step_timeout_ms / 1000)
        try:
            adapter.start({"roles": ["BARS"], "parameters": values["parameters"], "outputMode": output_mode,
                           "externalScopeHash": binding["external_scope_hash"]})
            market = runtime._manifest(values["dataset_id"])
            for ordinal, event in enumerate(selected):
                adapter.observe(sequence=event.sequence, event_time_ms=event.event_time_ms, watermark_ms=event.event_time_ms,
                                phase="WARMUP" if ordinal < parsed.warmup_bars else "EVALUATION",
                                market={"venue": values["exchange"], "symbol": str(market["symbol"])}, bar=dict(event.payload),
                                features={name: event.payload[name] for name in parsed.required_features})
            audit = provider.report_metadata()["external_provider"]
            session.close()
        finally:
            if not session.closed:
                # Preserve the primary failure without logging model content.
                with suppress(Exception):
                    provider.abort()
            adapter.close()
        stamp = int(time.time() * 1000)
        details = {"schema": "STRATEGY_SMOKE_V1", "revisionId": values["strategy_revision_id"],
                   "datasetId": values["dataset_id"], "snapshotHash": values["snapshot_hash"],
                   "startTimeMs": selected[0].event_time_ms, "endTimeMs": selected[-1].event_time_ms,
                   "status": "PASSED", "runtimeMode": None,
                   "externalSmokeConfigHash": control.smoke_config_hash(values),
                   "externalProvider": audit, "warmupBars": parsed.warmup_bars,
                   "evaluationBars": len(selected) - parsed.warmup_bars,
                   "qualification": "EXTERNAL_LIFECYCLE_ONLY"}
        receipt_hash = "sha256:" + sha256_hex(canonical_json(details))
        runtime.service.repository.insert_strategy_smoke({
            "receipt_hash": receipt_hash, "revision_id": values["strategy_revision_id"], "dataset_id": values["dataset_id"],
            "snapshot_hash": values["snapshot_hash"], "start_time_ms": details["startTimeMs"], "end_time_ms": details["endTimeMs"],
            "status": "PASSED", "details_json": canonical_json(details), "created_at_ms": stamp,
        })
        return {**details, "receiptHash": receipt_hash}
    except MarketDatasetError as exc:
        raise BacktestError(exc.code, exc.message) from exc
    finally:
        if snapshot is not None:
            snapshot.close()
