"""Preparation tasks are durable; disconnecting an HTTP observer never cancels one."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.data_preparation.models import PreparationError, PreparationRequest, Requirement
from app.api.v1.replay import TrainingRunSetupPayload
from app.api.v1.backtests import ChartContextResolveRequest, ResearchExecutionOverrides, _operator_python_payload

router = APIRouter(prefix="/data-preparations", tags=["data-preparation"])


class ReplayPreparationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    setup: TrainingRunSetupPayload
    exchange: str
    market_type: str
    symbol: str
    display_interval: str = "1m"
    progressive: bool = False


class StrategyLaunchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_revision_id: str = Field(min_length=1, max_length=128)
    parameters: dict = Field(default_factory=dict)
    execution_overrides: ResearchExecutionOverrides | None = None
    chart_cell_scope: str | None = Field(default=None, min_length=1, max_length=320)
    strategy_draft_id: str | None = Field(default=None, pattern=r"^draft-[A-Za-z0-9_-]{8,152}$")


class StrategyPreparationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    context: ChartContextResolveRequest
    strategy: StrategyLaunchPayload | None = None


class NativeDependencyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange: str = Field(min_length=1, max_length=40)
    market_type: str = Field(min_length=1, max_length=40)
    symbol: str = Field(min_length=1, max_length=80)
    interval: str = Field(min_length=1, max_length=16)
    binding_symbol: str | None = Field(default=None, min_length=1, max_length=120)
    warmup_bars: int | None = Field(default=None, strict=True, ge=0, le=5000)


class NativePreparationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    context: ChartContextResolveRequest
    language: Literal["pine", "pyne"]
    source: str = Field(min_length=1, max_length=100_000)
    parameters: dict = Field(default_factory=dict)
    contexts: list[NativeDependencyPayload] = Field(default_factory=list, max_length=16)
    libraries: dict[str, str] = Field(default_factory=dict)


@router.post("/native-strategy", status_code=202)
async def prepare_native_strategy(request: Request, payload: NativePreparationPayload):
    import time
    from app.data_engine.interval_policy import parse_interval_spec
    from app.data_preparation.bar_adapter import storage_call
    from app.data_preparation.models import canonical
    from app.data_preparation.native_plan import requested_contexts, requested_lookbacks, chart_interval, plan_inputs
    from app.backtest.chart_context import ChartContextRequest
    submission = payload.model_dump(mode="json")
    prior = service(request).repository.by_idempotency(payload.idempotency_key)
    if prior is not None:
        if canonical(prior["request"]["intent"].get("submission")) != canonical(submission):
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Key belongs to a different native preparation"})
        return prior
    runtime = getattr(request.app.state, "backtest_runtime", None)
    if runtime is None or not runtime.settings.bar_effective or not runtime.settings.chart_context_effective:
        raise HTTPException(503, detail={"code": "NATIVE_PREPARATION_UNAVAILABLE", "message": "Native BAR preparation is unavailable"})
    if payload.context.fidelity_preference != "FAST":
        raise HTTPException(409, detail={"code": "NATIVE_INPUT_UNSUPPORTED", "message": "Native execution requires its own BAR input profile"})
    context = payload.context.model_dump()
    if context["range_mode"] == "ALL_AVAILABLE":
        resolved = await storage_call(runtime.chart_context.resolve, context)
        bounds = ((resolved["coverage"]["requested_start_ms"], resolved["coverage"]["requested_end_ms"])
                  if resolved["status"] == "READY" else runtime.chart_context._host_range(
                      ChartContextRequest.from_mapping(context), getattr(request.app.state, "data_manager", None), "1m"))
        if bounds is None:
            raise HTTPException(409, detail={"code": "RANGE_REQUIRED", "message": "Select the historical range to prepare"})
        context.update(start_time_ms=bounds[0], end_time_ms=bounds[1], range_mode="CUSTOM")
    spec = parse_interval_spec(context["interval"])
    if spec is None or spec.nominal_ms < 60_000:
        raise HTTPException(422, detail={"code": "INVALID_INTERVAL", "message": "Select a minute or coarser interval"})
    context["start_time_ms"] = spec.floor_ms(context["start_time_ms"])
    context["end_time_ms"] = min(spec.next_ms(spec.floor_ms(context["end_time_ms"])), spec.floor_ms(int(time.time() * 1000))) - 1
    dependencies = [item.model_dump(exclude_none=True) for item in payload.contexts]
    for dependency in dependencies:
        dependency_spec = parse_interval_spec(dependency["interval"])
        if dependency_spec is None or dependency_spec.nominal_ms < 60_000:
            raise HTTPException(422, detail={"code": "DEPENDENCY_INTERVAL_UNSUPPORTED", "message": "Select minute or coarser dependency intervals"})
        dependency["interval"] = dependency_spec.canonical
    source = "\n".join([payload.source, *payload.libraries.values()])
    discovered = invoke(lambda: requested_contexts(source,
        symbol=f"{context['exchange'].upper()}:{context['symbol']}", interval=context["interval"], explicit=bool(dependencies)))
    lookbacks = invoke(lambda: requested_lookbacks(source,
        symbol=f"{context['exchange'].upper()}:{context['symbol']}", interval=context["interval"], explicit=bool(dependencies)))
    required = {}
    for (binding_symbol, requested_timeframe), count in lookbacks.items():
        pair = (binding_symbol, invoke(lambda: chart_interval(requested_timeframe)))
        previous = required.get(pair, 0)
        required[pair] = None if previous is None or count is None else max(previous, count + 1)
    known = {(item.get("binding_symbol", f"{item['exchange'].upper()}:{item['symbol']}"), item["interval"]) for item in dependencies}
    for binding_symbol, requested_timeframe in discovered:
        interval = invoke(lambda: chart_interval(requested_timeframe))
        if (binding_symbol, interval) in known:
            continue
        exchange, symbol = (binding_symbol.split(":", 1) if ":" in binding_symbol else (context["exchange"], binding_symbol))
        dependencies.append({"exchange": exchange.lower(), "market_type": context["market_type"],
            "symbol": symbol, "interval": interval, "binding_symbol": binding_symbol})
        known.add((binding_symbol, interval))
    for dependency in dependencies:
        pair = (dependency.get("binding_symbol", f"{dependency['exchange'].upper()}:{dependency['symbol']}"), dependency["interval"])
        count = required.get(pair)
        declared = dependency.get("warmup_bars")
        if count is None and declared is None:
            raise HTTPException(409, detail={"code": "DEPENDENCY_WARMUP_REQUIRED",
                "message": f"Declare prior history bars for {pair[0]} {pair[1]}; this expression's history cannot be inferred"})
        dependency["warmup_bars"] = max(1, declared or 0, count or 0)
    if len(dependencies) > 16:
        raise HTTPException(409, detail={"code": "DEPENDENCY_LIMIT", "message": "Native execution supports at most 16 requested contexts"})
    requirements, bindings = invoke(lambda: plan_inputs(context, dependencies))
    prepared = PreparationRequest(idempotency_key=payload.idempotency_key, consumer="STRATEGY",
        requirements=requirements, intent={"submission": submission, "native_strategy": {
            "language": payload.language, "source": payload.source, "parameters": payload.parameters,
            "libraries": payload.libraries, "bindings": bindings, "dependency_requirements": dependencies}})
    return invoke(lambda: service(request).submit(prepared))


@router.post("/strategy", status_code=202)
async def prepare_strategy(request: Request, payload: StrategyPreparationPayload):
    import time
    from app.backtest.chart_context import ChartContextRequest
    from app.data_engine.interval_policy import parse_interval_spec
    from app.data_preparation.models import canonical
    from app.data_preparation.bar_adapter import storage_call
    submission = payload.model_dump(mode="json")
    prior = service(request).repository.by_idempotency(payload.idempotency_key)
    if prior is not None:
        if canonical(prior["request"]["intent"].get("submission")) != canonical(submission):
            raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Key belongs to a different strategy preparation"})
        return prior
    runtime = getattr(request.app.state, "backtest_runtime", None)
    if runtime is None or not runtime.settings.chart_context_effective:
        raise HTTPException(503, detail={"code": "STRATEGY_PREPARATION_UNAVAILABLE", "message": "Strategy runtime is unavailable"})
    context = ChartContextRequest.from_mapping(payload.context.model_dump())
    if context.fidelity_preference == "PRECISE" and not runtime.settings.trade_tape_effective:
        raise HTTPException(409, detail={"code": "TRADE_ENGINE_DISABLED", "message": "Precise strategy execution is disabled"})
    interval = parse_interval_spec(context.interval)
    if interval is None:
        raise HTTPException(422, detail={"code": "INVALID_INTERVAL", "message": "Select a supported interval"})
    host = getattr(request.app.state, "data_manager", None)
    bounds = runtime.chart_context._host_range(context, host, "1m") if host is not None else None
    if bounds is None and context.range_mode == "ALL_AVAILABLE":
        existing = await storage_call(runtime.chart_context.resolve, context.wire())
        if existing["status"] == "READY":
            bounds = (existing["coverage"]["requested_start_ms"], existing["coverage"]["requested_end_ms"])
    if bounds is None:
        if context.range_mode == "ALL_AVAILABLE":
            raise HTTPException(409, detail={"code": "RANGE_REQUIRED", "message": "No local history exists; select a time range to download"})
        bounds = (context.start_time_ms, context.end_time_ms)
    start = interval.floor_ms(bounds[0])
    end = interval.next_ms(interval.floor_ms(bounds[1]))
    if end > int(time.time() * 1000):
        end = interval.floor_ms(int(time.time() * 1000))
    if end <= start:
        raise HTTPException(422, detail={"code": "INVALID_RANGE", "message": "Select a range containing closed bars"})
    requested_start = start
    warmup_bars = 0
    if payload.strategy is not None:
        from app.data_preparation.dependency_plan import strategy_warmup, warmup_start
        warmup_bars = invoke(lambda: strategy_warmup(runtime, payload.strategy.strategy_revision_id, payload.strategy.parameters))
        if context.range_mode == "ALL_AVAILABLE":
            # The first available bars are the warmup; do not invent required
            # history before listing simply because the user chose ALL.
            for _ in range(warmup_bars):
                requested_start = interval.next_ms(requested_start)
            if requested_start >= end:
                raise HTTPException(409, detail={"code": "WARMUP_RANGE_INSUFFICIENT", "message": "Available history is shorter than the strategy warmup"})
        else:
            start = invoke(lambda: warmup_start(interval, start, warmup_bars))
    frozen_context = {**context.wire(), "range_mode": "CUSTOM", "start_time_ms": start, "end_time_ms": end - 1}
    base = Requirement(exchange=context.exchange, market_type=context.market_type,
                       symbol=context.symbol, start_ms=start, end_ms=end)
    requirements = [base]
    if context.fidelity_preference == "PRECISE":
        requirements.append(base.model_copy(update={"role": "TRADES"}))
    intent = {"chart_context": frozen_context, "submission": submission}
    if payload.strategy is not None:
        from app.data_preparation.strategy_launcher import revision
        invoke(lambda: revision(runtime, payload.strategy.strategy_revision_id))
        intent["strategy"] = _operator_python_payload(request, payload.strategy.model_dump())
        intent["strategy"]["warmup_bars"] = warmup_bars
        intent["preparation"] = {"warmup_bars": warmup_bars, "requested_start_ms": requested_start,
                                 "prepared_start_ms": start}
    existing = await storage_call(runtime.chart_context.resolve, frozen_context)
    if existing["status"] == "READY":
        intent["ready_resolution"] = existing
    prepared = PreparationRequest(idempotency_key=payload.idempotency_key, consumer="STRATEGY",
        requirements=requirements,
        intent=intent)
    return invoke(lambda: service(request).submit(prepared))


@router.post("/replay", status_code=202)
async def prepare_replay(request: Request, payload: ReplayPreparationPayload):
    setup = payload.setup.model_dump(mode="json")
    if setup["start_mode"] == "MANUAL":
        first = last = setup["requested_start_ms"]
    else:
        first, last = setup["random_range_start_ms"], setup["random_range_end_ms"]
    if first is None or last is None or first > last:
        raise HTTPException(422, detail={"code": "INVALID_RANGE", "message": "Select a valid training range"})
    lookback = setup["visible_history_lookback"]
    history_ms = max(setup["indicator_warmup_bars"] * 60_000,
                     lookback.get("duration_ms") or 0)
    start = max(0, first - history_ms) // 60_000 * 60_000
    end = ((last + setup["forward_cache_ms"] + 59_999) // 60_000) * 60_000
    base = Requirement(exchange=payload.exchange, market_type=payload.market_type,
                       symbol=payload.symbol, start_ms=start, end_ms=end)
    requirements = [base]
    if setup["source_kind"] == "AGG_TRADE":
        # Replay's existing catalog and warmup bind bars alongside the tape.
        requirements.append(base.model_copy(update={"role": "TRADES"}))
    prepared = PreparationRequest(
        idempotency_key=payload.idempotency_key, consumer="REPLAY",
        requirements=requirements,
        progressive=payload.progressive,
        intent={"replay_setup": setup, "display_interval": payload.display_interval},
    )
    return invoke(lambda: service(request).submit(prepared))


def service(request: Request):
    instance = getattr(request.app.state, "data_preparation_service", None)
    if instance is None:
        raise HTTPException(503, detail={"code": "PREPARATION_UNAVAILABLE", "message": "Automatic history preparation is unavailable"})
    return instance


def invoke(operation):
    try:
        return operation()
    except PreparationError as exc:
        raise HTTPException(404 if exc.code == "JOB_NOT_FOUND" else 409,
                            detail={"code": exc.code, "message": str(exc), "retryable": exc.retryable}) from exc


@router.get("")
def list_jobs(request: Request):
    return {"items": service(request).repository.list()}


@router.get("/capabilities")
def capabilities(request: Request):
    instance = service(request)
    from app.replay.manual_history_import import import_unavailable_reason
    adapter = instance.adapter
    replay = getattr(adapter, "replay_service", None)
    bar_reason = import_unavailable_reason(replay)
    archive = getattr(getattr(adapter, "trades", None), "archive", None)
    trade_ready = (archive is not None and getattr(archive, "enabled", False)
                   and hasattr(archive, "root") and not getattr(archive, "read_only", False))
    exact_account = getattr(getattr(getattr(replay, "training", None), "account_history", None), "enabled", False)
    return {"enabled": instance.enabled, "roles": ["BARS", *(["TRADES"] if trade_ready else [])],
            "replay_sources": {"BAR": instance.enabled and bar_reason is None,
                               "AGG_TRADE": instance.enabled and bar_reason is None and trade_ready},
            "trade_providers": [{"exchange": "binance", "market_type": "futures"}] if trade_ready else [],
            "base_intervals": ["1m"],
            "replay_account_modes": ["APPROX_PROXY", *(["HISTORICAL_EXACT"] if exact_account else [])],
            "progressive": instance.enabled and bar_reason is None,
            "max_requirements": 32, "max_active_jobs": 64,
            "default_job_budget_bytes": 512 * 1024**2}


@router.get("/cache")
def cache_inventory(request: Request):
    return service(request).repository.cache_inventory()


class CacheSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_budget_bytes: int = Field(ge=16 * 1024**2, le=1024**4, strict=True)
    prefetch_enabled: bool


@router.put("/cache/settings")
async def configure_cache(request: Request, payload: CacheSettingsPayload):
    instance = service(request)
    result = invoke(lambda: instance.repository.configure(**payload.model_dump()))
    if not payload.prefetch_enabled:
        for job in instance.repository.list(active=True):
            if job["request"]["consumer"] == "PREFETCH" and job["stage"] != "STARTING":
                instance.cancel(job["id"])
    return result


@router.post("/cache/cleanup")
def cleanup_cache(request: Request):
    instance = service(request)
    result = invoke(lambda: instance.repository.evict_unreferenced(instance.adapter.remove_cached_object))
    instance.repository.refresh_publications()
    return result


@router.post("", status_code=202)
async def create_job(request: Request, payload: PreparationRequest):
    if "strategy" in payload.intent or "native_strategy" in payload.intent:
        raise HTTPException(422, detail={"code": "STRATEGY_ENDPOINT_REQUIRED",
            "message": "Submit strategy execution through /data-preparations/strategy"})
    return invoke(lambda: service(request).submit(payload))


@router.get("/{job_id}")
def get_job(request: Request, job_id: str):
    return invoke(lambda: service(request).repository.get(job_id))


@router.post("/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str):
    return invoke(lambda: service(request).cancel(job_id))


@router.post("/{job_id}/retry")
async def retry_job(request: Request, job_id: str):
    return invoke(lambda: service(request).retry(job_id))


@router.post("/{job_id}/release-cache")
def release_cache(request: Request, job_id: str):
    instance = service(request)
    invoke(lambda: instance.repository.release_finished(job_id))
    job = instance.repository.get(job_id)
    # Failed tasks remain retryable, so their feed cannot lose its archive
    # references even when disposable acquisition chunks are released.
    if job["request"].get("progressive") and job["state"] in {"READY", "CANCELLED"}:
        replay = getattr(instance.adapter, "replay_service", None)
        if replay is not None:
            replay.progressive_history.release("preparation:preparation-" + job_id)
    return {"released": True, "job_id": job_id}
