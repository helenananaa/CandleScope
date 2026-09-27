"""Fail-closed HTTP control plane for BacktestRun / BacktestStudy."""

from __future__ import annotations

from app.backtest.request_contracts import (
    RunCreateRequest,
    StudyCreateRequest,
    SnapshotPreviewRequest,
    ChartContextResolveRequest,
    ChartContextMaterializeRequest,
    StrategyRevisionRequest,
    StrategyCopyRequest,
    StrategySmokeRequest,
    RunCloneRequest,
    ReviewBridgeRequest,
    ResearchLaunchContextRequest,
    PythonBundleZipRequest,
    PythonRevisionRequest,
)

from app.core.config import getenv as app_getenv

import base64
from typing import Any

from fastapi import APIRouter, Header, Request, Query
from fastapi.responses import JSONResponse

from app.core.operator_origin import (
    effective_python_runtime_mode,
    is_trusted_operator_origin,
    origin_from,
)
from app.backtest.snapshot_validation import require_contract_snapshot, require_declared_snapshot
from app.backtest.errors import BacktestError
from app.backtest.reports import export_bundle
from app.backtest.runtime import BacktestRuntime
from app.backtest.service import BacktestService
from .native_backtests import router as native_router, external_router


router = APIRouter(prefix="/backtests", tags=["backtests"])
router.include_router(native_router)
router.include_router(external_router)


def _service(request: Request) -> BacktestService:
    service = getattr(request.app.state, "backtest_service", None)
    if service is None:
        raise BacktestError("FLAG_DISABLED", "backtest control plane is not started")
    return service


def _runtime(request: Request) -> BacktestRuntime:
    runtime = getattr(request.app.state, "backtest_runtime", None)
    if runtime is None:
        raise BacktestError("FLAG_DISABLED", "backtest worker runtime is not started")
    return runtime


def _optional_runtime(request: Request) -> BacktestRuntime | None:
    runtime = getattr(request.app.state, "backtest_runtime", None)
    return runtime if isinstance(runtime, BacktestRuntime) else None


def _python_strategy_enabled() -> bool:
    return app_getenv("BACKTEST_PYTHON_STRATEGY_ENABLED", "0").strip() == "1"


def _require_python_strategy() -> None:
    if not _python_strategy_enabled():
        raise BacktestError("FLAG_DISABLED", "Python strategy path is default-off")


def _operator_python_payload(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    trusted = is_trusted_operator_origin(origin_from(request.headers))
    mode, confirmed = effective_python_runtime_mode(
        payload.get("python_runtime_mode"),
        bool(payload.get("python_trusted_confirmed")),
        trusted=trusted,
    )
    patched = dict(payload)
    patched["python_runtime_mode"] = mode
    patched["python_trusted_confirmed"] = confirmed
    return patched


def _error(exc: BacktestError) -> JSONResponse:
    retryable_capacity = exc.code == "RUN_CAPACITY_EXCEEDED"
    return JSONResponse(
        status_code=429 if retryable_capacity else 400,
        headers={"Retry-After": "1"} if retryable_capacity else None,
        content={
            "error": {"code": exc.code, "message": exc.message, "details": exc.details}
        },
    )


@router.get("/capabilities")
def capabilities(request: Request) -> dict[str, Any]:
    try:
        payload = _service(request).capabilities()
        flags = dict(payload.get("flags") or {})
        replay_service = getattr(request.app.state, "replay_service", None)
        flags["BACKTEST_REPLAY_TRAINING_AVAILABLE"] = (
            getattr(replay_service, "training", None) is not None
        )
        return {
            **payload,
            "flags": flags,
            "runtime_mode": getattr(request.app.state, "runtime_mode", "LIVE"),
        }
    except BacktestError as exc:
        return _error(exc)


@router.post("/chart-context/resolve", response_model=None)
def resolve_chart_context(payload: ChartContextResolveRequest, request: Request) -> Any:
    try:
        runtime = _runtime(request)
        if not runtime.settings.chart_context_effective:
            raise BacktestError("FLAG_DISABLED", "BACKTEST_CHART_CONTEXT_ENABLED is 0")
        automatic = bool(getattr(getattr(request.app.state, "data_preparation_service", None), "enabled", False))
        result = runtime.chart_context.resolve(
            payload.model_dump(),
            host_data_manager=getattr(request.app.state, "data_manager", None),
            automatic_preparation=automatic,
        )
        return {**result, "automatic_preparation_available": automatic}
    except BacktestError as exc:
        return _error(exc)
    except Exception:
        return _error(
            BacktestError(
                "CHART_CONTEXT_FAILED", "chart context resolution failed safely"
            )
        )


@router.post("/chart-context/materialize", response_model=None)
async def materialize_chart_context(
    payload: ChartContextMaterializeRequest, request: Request
) -> Any:
    try:
        runtime = _runtime(request)
        if not runtime.settings.chart_context_effective:
            raise BacktestError("FLAG_DISABLED", "BACKTEST_CHART_CONTEXT_ENABLED is 0")
        data_engine_runtime = getattr(request.app.state, "data_engine_runtime", None)
        return await runtime.chart_context.materialize(
            **payload.model_dump(),
            host_data_manager=getattr(request.app.state, "data_manager", None),
            backfill_coordinator=getattr(
                data_engine_runtime, "backfill_coordinator", None
            ),
        )
    except BacktestError as exc:
        return _error(exc)
    except Exception:
        return _error(
            BacktestError(
                "CHART_CONTEXT_FAILED", "chart context materialization failed safely"
            )
        )


@router.get("/strategy-revisions")
def list_strategy_revisions(
    request: Request, include_archived: bool = False
) -> dict[str, Any]:
    service = _service(request)
    return {
        "items": [
            service._revision_wire(item)
            for item in service.repository.list_strategy_revisions(
                include_archived=include_archived
            )
        ]
    }


@router.post("/strategy-revisions")
def create_strategy_revision(
    request: Request, payload: StrategyRevisionRequest
) -> dict[str, Any]:
    try:
        return _service(request).create_strategy_revision(payload.model_dump())
    except BacktestError as exc:
        return _error(exc)


@router.post("/strategy-revisions/{revision_id}/copy")
def copy_strategy_revision(
    request: Request, revision_id: str, payload: StrategyCopyRequest
) -> dict[str, Any]:
    try:
        return _service(request).copy_strategy_revision(revision_id, name=payload.name)
    except BacktestError as exc:
        return _error(exc)


@router.post("/strategy-revisions/{revision_id}/archive")
def archive_strategy_revision(request: Request, revision_id: str) -> dict[str, Any]:
    try:
        return _service(request).archive_strategy_revision(revision_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/strategy-bundles/inspect")
def inspect_python_strategy_bundle(
    request: Request, payload: PythonBundleZipRequest
) -> dict[str, Any]:
    try:
        _require_python_strategy()
        zip_bytes = base64.b64decode(payload.zip_base64)
        return _service(request).inspect_python_strategy_bundle(zip_bytes=zip_bytes)
    except BacktestError as exc:
        return _error(exc)


@router.post("/strategy-bundles")
def create_python_strategy_bundle(
    request: Request, payload: PythonBundleZipRequest
) -> dict[str, Any]:
    try:
        _require_python_strategy()
        zip_bytes = base64.b64decode(payload.zip_base64)
        return _service(request).create_python_strategy_bundle(zip_bytes=zip_bytes)
    except BacktestError as exc:
        return _error(exc)


@router.get("/strategy-bundles/{bundle_id}")
def get_python_strategy_bundle(request: Request, bundle_id: str) -> dict[str, Any]:
    try:
        _require_python_strategy()
        return _service(request).get_python_strategy_bundle(bundle_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/strategy-revisions/python")
def create_python_strategy_revision(
    request: Request, payload: PythonRevisionRequest
) -> dict[str, Any]:
    try:
        _require_python_strategy()
        return _service(request).create_python_strategy_revision(payload.bundle_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/strategy-revisions/{revision_id}/runtime-receipt")
def get_python_runtime_receipt(request: Request, revision_id: str) -> dict[str, Any]:
    try:
        _require_python_strategy()
        return _service(request).get_python_runtime_receipt(revision_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/strategy-revisions/{revision_id}/smoke")
def smoke_strategy_revision(
    request: Request, revision_id: str, payload: StrategySmokeRequest
) -> dict[str, Any]:
    try:
        return _service(request).smoke_strategy_revision(
            revision_id, _operator_python_payload(request, payload.model_dump())
        )
    except BacktestError as exc:
        return _error(exc)


@router.get("/datasets")
def list_datasets(request: Request) -> dict[str, Any]:
    try:
        return {"datasets": _runtime(request).list_datasets()}
    except BacktestError as exc:
        return _error(exc)


@router.post("/datasets/snapshot")
def preview_snapshot(
    request: Request,
    payload: SnapshotPreviewRequest,
) -> dict[str, Any]:
    try:
        return _runtime(request).preview_snapshot(**payload.model_dump())
    except BacktestError as exc:
        return _error(exc)


@router.post("/runs/validate")
def validate_run(request: Request, payload: RunCreateRequest) -> dict[str, Any]:
    try:
        validated = _service(request).validate_run(
            _operator_python_payload(request, payload.model_dump())
        )
        runtime = _optional_runtime(request)
        if runtime is not None:
            preview = runtime.preview_snapshot(
                dataset_id=payload.dataset_id,
                data_epoch=payload.data_epoch,
                start_time_ms=payload.start_time_ms,
                end_time_ms=payload.end_time_ms,
                interval=payload.interval,
                fidelity_mode=payload.fidelity_mode,
                exchange=payload.exchange,
                market_type=payload.market_type,
                contract_data_mode=payload.contract_data_mode,
                account_model=payload.account_model,
                funding_mode=payload.funding_mode,
            )
            require_contract_snapshot(preview, payload.contract_data_mode)
            require_declared_snapshot(preview, payload)
            validated["snapshot"] = preview
        return validated
    except BacktestError as exc:
        return _error(exc)


@router.post("/runs")
def create_run(
    request: Request,
    payload: RunCreateRequest,
    x_idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, Any]:
    try:
        runtime = _optional_runtime(request)
        if runtime is not None:
            preview = runtime.preview_snapshot(
                dataset_id=payload.dataset_id,
                data_epoch=payload.data_epoch,
                start_time_ms=payload.start_time_ms,
                end_time_ms=payload.end_time_ms,
                interval=payload.interval,
                fidelity_mode=payload.fidelity_mode,
                exchange=payload.exchange,
                market_type=payload.market_type,
                contract_data_mode=payload.contract_data_mode,
                account_model=payload.account_model,
                funding_mode=payload.funding_mode,
            )
            require_contract_snapshot(preview, payload.contract_data_mode)
            require_declared_snapshot(preview, payload)
        return _service(request).create_run(
            _operator_python_payload(request, payload.model_dump()),
            idempotency_key=x_idempotency_key,
        )
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs")
def list_runs(request: Request) -> dict[str, Any]:
    try:
        return {"runs": _service(request).list_runs()}
    except BacktestError as exc:
        return _error(exc)


@router.post("/research/contexts")
def create_research_launch_context(
    request: Request, payload: ResearchLaunchContextRequest
) -> dict[str, Any]:
    try:
        body = payload.model_dump()
        if payload.execution_overrides is None:
            body.pop("execution_overrides", None)
        return _service(request).create_research_launch_context(body)
    except BacktestError as exc:
        return _error(exc)


@router.get("/research/contexts/{context_id}")
def get_research_launch_context(request: Request, context_id: str) -> dict[str, Any]:
    try:
        if not context_id.startswith("brc_") or len(context_id) > 132:
            raise BacktestError("SCHEMA_UNKNOWN_FIELD", "invalid research context id")
        return _service(request).get_research_launch_context(context_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs/compare/pair")
def compare_run_pair(
    request: Request, left_run_id: str, right_run_id: str
) -> dict[str, Any]:
    try:
        return _service(request).compare_run_pair(left_run_id, right_run_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return _service(request).get_run(run_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/runs/{run_id}/cancel")
def cancel_run(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return _service(request).cancel_run(run_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/runs/{run_id}/resume")
def resume_run(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return _service(request).resume_failed_run(run_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs/{run_id}/report")
def get_report(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return _service(request).get_report(run_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs/{run_id}/report/summary")
def get_report_summary(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return _service(request).get_report_view(run_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs/{run_id}/report/details")
def get_report_details(request: Request, run_id: str, section: str = "fills",
                       offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    try:
        return _service(request).get_report_view(run_id, section=section, offset=offset, limit=limit)
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs/{run_id}/chart")
def get_chart(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return _runtime(request).chart_data(run_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs/{run_id}/comparison")
def compare_recent_compatible_run(request: Request, run_id: str) -> dict[str, Any]:
    try:
        return _service(request).compare_recent_compatible_run(run_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/runs/{run_id}/signal-trace")
def get_signal_trace(
    request: Request, run_id: str, after: int = 0, limit: int = 200
) -> dict[str, Any]:
    try:
        return _service(request).get_signal_trace(run_id, after=after, limit=limit)
    except BacktestError as exc:
        return _error(exc)


@router.post("/runs/{run_id}/clone")
def clone_run(
    request: Request,
    run_id: str,
    payload: RunCloneRequest,
    x_idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, Any]:
    try:
        return _service(request).clone_run_parameter(
            run_id,
            parameter=payload.parameter,
            value=payload.value,
            idempotency_key=x_idempotency_key,
            trusted=is_trusted_operator_origin(origin_from(request.headers)),
        )
    except BacktestError as exc:
        return _error(exc)


@router.post("/runs/{run_id}/review-bridge")
async def create_review_bridge(
    request: Request, run_id: str, payload: ReviewBridgeRequest
) -> dict[str, Any]:
    try:
        bridge = _service(request).create_review_bridge(run_id, payload.model_dump())
        replay_service = getattr(request.app.state, "replay_service", None)
        training = getattr(replay_service, "training", None)
        if training is None:
            _service(request).repository.delete_review_bridge(str(bridge["bridgeId"]))
            raise BacktestError(
                "REPLAY_TRAINING_UNAVAILABLE",
                "Replay TrainingRun runtime is unavailable; start replay before creating the bridge",
            )
        try:
            from app.replay.training.models import TrainingRunSetupRequest

            window_ms = payload.end_time_ms - payload.start_time_ms
            setup = TrainingRunSetupRequest.from_dict(
                {
                    "protocol": "replay.v3",
                    "name": f"Backtest blind review {run_id[-8:]}",
                    "source_kind": "BAR",
                    "start_mode": "MANUAL",
                    "settlement_asset": "USDT",
                    "requested_start_ms": payload.start_time_ms,
                    "indicator_warmup_bars": 24,
                    "visible_history_lookback": {
                        "mode": "DURATION",
                        "duration_ms": min(window_ms, 86_400_000),
                    },
                    "forward_cache_ms": window_ms,
                    "random_seed": None,
                    "initial_equity": "10000",
                    "max_leverage": "3",
                    "maker_fee_bps": "0",
                    "taker_fee_bps": "0",
                    "market_slippage_bps": "0",
                    "integrity_mode": "CHALLENGE",
                    "time_disclosure_policy": "HIDE_ALL",
                    "book_mode": "OFF",
                    "margin_mode": "CROSS",
                    "position_mode": "ONE_WAY",
                    "funding_mode": "OFF",
                    "account_data_mode": "APPROX_PROXY",
                    "fixed_funding_rate": None,
                    "funding_interval_ms": None,
                    "allow_rule_changes": False,
                    "allowed_mutations": [],
                    "market_selection_hint": None,
                }
            )
            training_run = await training.create_empty_run(setup)
            training_run_id = str(training_run["run_id"])
            bound = _service(request).bind_review_bridge_training_run(
                str(bridge["bridgeId"]), training_run_id
            )
        except Exception as exc:
            _service(request).repository.delete_review_bridge(str(bridge["bridgeId"]))
            raise BacktestError(
                "REPLAY_TRAINING_UNAVAILABLE",
                f"TrainingRun creation failed: {type(exc).__name__}",
            ) from exc
        return {**bound, "trainingRun": training_run}
    except BacktestError as exc:
        return _error(exc)


@router.get("/review-bridges/{bridge_id}")
def get_review_bridge(request: Request, bridge_id: str) -> dict[str, Any]:
    try:
        return _service(request).get_review_bridge(bridge_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/review-bridges/{bridge_id}/reveal")
async def reveal_review_bridge(request: Request, bridge_id: str) -> dict[str, Any]:
    try:
        service = _service(request)
        bridge = service.get_review_bridge(bridge_id)
        if bridge["state"] == "REVEALED":
            return bridge
        training_run_id = str(bridge.get("trainingRunId") or "")
        replay_service = getattr(request.app.state, "replay_service", None)
        training = getattr(replay_service, "training", None)
        if training is None or not training_run_id:
            raise BacktestError(
                "REPLAY_TRAINING_UNAVAILABLE",
                "bound Replay TrainingRun runtime is unavailable",
            )
        training_run = await training.get_run(training_run_id)
        if str(training_run.get("state")) != "ENDED":
            raise BacktestError(
                "IDENTITY_MUTATION",
                "complete the blind TrainingRun before revealing strategy orders",
            )
        human_results = await training.training_results(training_run_id, limit=2_000)
        if human_results.get("truncated"):
            raise BacktestError(
                "BUDGET_EXCEEDED",
                "blind review has more than 2000 trades; narrow the immutable review window",
            )
        return service.reveal_review_bridge(
            bridge_id,
            training_run_id=training_run_id,
            training_state=str(training_run["state"]),
            human_results=human_results,
        )
    except BacktestError as exc:
        return _error(exc)
    except Exception as exc:
        return _error(
            BacktestError(
                "REPLAY_TRAINING_UNAVAILABLE",
                f"TrainingRun reveal failed: {type(exc).__name__}",
            )
        )


@router.get("/runs/{run_id}/export")
def export_run(request: Request, run_id: str) -> dict[str, Any]:
    try:
        service = _service(request)
        return export_bundle(service.get_run(run_id), service.get_report(run_id))
    except BacktestError as exc:
        return _error(exc)
    except ValueError as exc:
        return _error(BacktestError("HASH_MISMATCH", str(exc)))


@router.post("/studies")
def create_study(request: Request, payload: StudyCreateRequest) -> dict[str, Any]:
    try:
        return _service(request).create_study(payload.model_dump())
    except BacktestError as exc:
        return _error(exc)


@router.get("/studies/{study_id}")
def get_study(request: Request, study_id: str) -> dict[str, Any]:
    try:
        return _service(request).get_study(study_id)
    except BacktestError as exc:
        return _error(exc)


@router.get("/studies")
def list_studies(request: Request) -> dict[str, Any]:
    try:
        return {"studies": _service(request).list_studies()}
    except BacktestError as exc:
        return _error(exc)


@router.get("/studies/{study_id}/compare")
def compare_study(request: Request, study_id: str) -> dict[str, Any]:
    try:
        return _service(request).compare_study(study_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/studies/{study_id}/start")
def start_study(request: Request, study_id: str) -> dict[str, Any]:
    try:
        return _service(request).start_study(study_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/studies/{study_id}/cancel")
def cancel_study(request: Request, study_id: str) -> dict[str, Any]:
    try:
        return _service(request).cancel_study(study_id)
    except BacktestError as exc:
        return _error(exc)


@router.post("/studies/{study_id}/reveal-holdout")
def reveal_study_holdout(request: Request, study_id: str) -> dict[str, Any]:
    try:
        return _service(request).reveal_study_holdout(study_id)
    except BacktestError as exc:
        return _error(exc)
