"""HTTP contract for immutable user-provided data in LOCAL_OFFLINE mode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.config import LOCAL_DATA_MAX_UPLOAD_BYTES, RUNTIME_MODE
from app.local_data import LocalDatasetError, LocalDatasetService, LocalImportOptions
from app.local_data.indicator_compute import (
    LOCAL_INDICATOR_NAMES,
    MAX_LOCAL_INDICATOR_BARS,
    compute_local_indicator_batch,
)


router = APIRouter(prefix="/local", tags=["local-data"])


class ResolveEventTimesRequest(BaseModel):
    data_epoch: str = Field(min_length=8, max_length=80)
    times_ms: list[int] = Field(min_length=1, max_length=5_000)
    mode: Literal["exact", "containing"]


class LocalIndicatorComputeItem(BaseModel):
    jobKey: str = Field(min_length=1, max_length=256)
    clientId: str = Field(min_length=1, max_length=256)
    name: Literal["MA", "EMA", "RSI", "MACD", "BOLL"]
    params: dict[str, Any] = Field(default_factory=dict)


class LocalIndicatorComputeBatchRequest(BaseModel):
    schemaVersion: Literal[1] = 1
    data_epoch: str = Field(min_length=8, max_length=80)
    requests: list[LocalIndicatorComputeItem] = Field(min_length=1, max_length=32)


def _service(request: Request) -> LocalDatasetService:
    service = getattr(request.app.state, "local_data_service", None)
    if RUNTIME_MODE != "LOCAL_OFFLINE" or service is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "local_profile_not_active",
                "message": "Restart CandleScope with CANDLESCOPE_RUNTIME_MODE=LOCAL_OFFLINE",
            },
        )
    return service


def _translate_error(exc: LocalDatasetError) -> HTTPException:
    status = (
        404
        if exc.code == "dataset_not_found"
        else 409
        if exc.code in {"dataset_corrupt", "dataset_revision_changed"}
        else 422
    )
    return HTTPException(
        status_code=status, detail={"code": exc.code, "message": str(exc)}
    )


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, Any]:
    service = _service(request)
    return {
        "runtime_mode": "LOCAL_OFFLINE",
        "network_policy": "loopback_only",
        "import_formats": ["csv"],
        "ohlc_only": True,
        "missing_volume_semantics": "unavailable_never_zero",
        "timestamp_units": ["auto", "s", "ms", "iso"],
        "realtime": False,
        "backfill": False,
        "gaps_are_terminal": True,
        "static_indicators": sorted(LOCAL_INDICATOR_NAMES),
        "static_indicator_max_bars": MAX_LOCAL_INDICATOR_BARS,
        "max_upload_bytes": LOCAL_DATA_MAX_UPLOAD_BYTES,
        "datasets": len(await asyncio.to_thread(service.list_datasets)),
    }


@router.get("/datasets")
async def list_datasets(request: Request) -> dict[str, Any]:
    service = _service(request)
    datasets = await asyncio.to_thread(service.list_datasets)
    return {"datasets": datasets, "count": len(datasets)}


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str, request: Request) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_service(request).get_manifest, dataset_id)
    except LocalDatasetError as exc:
        raise _translate_error(exc) from exc


@router.post("/datasets/{dataset_id}/events/resolve-times")
async def resolve_event_times(
    dataset_id: str,
    body: ResolveEventTimesRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _service(request).resolve_event_times,
            dataset_id,
            data_epoch=body.data_epoch,
            times_ms=body.times_ms,
            mode=body.mode,
        )
    except LocalDatasetError as exc:
        raise _translate_error(exc) from exc


@router.post("/datasets/{dataset_id}/indicators/compute/batch")
async def compute_local_indicators(
    dataset_id: str,
    body: LocalIndicatorComputeBatchRequest,
    request: Request,
) -> dict[str, Any]:
    job_keys = [item.jobKey for item in body.requests]
    client_ids = [item.clientId for item in body.requests]
    if any(value != value.strip() for value in [*job_keys, *client_ids]):
        raise HTTPException(status_code=422, detail="Indicator identities must be trimmed")
    if len(set(job_keys)) != len(job_keys) or len(set(client_ids)) != len(client_ids):
        raise HTTPException(status_code=422, detail="Indicator identities must be unique")
    service = _service(request)

    def _compute() -> dict[str, Any]:
        manifest, rows = service.load_revision_bars(
            dataset_id,
            data_epoch=body.data_epoch,
            max_rows=MAX_LOCAL_INDICATOR_BARS,
        )
        return compute_local_indicator_batch(
            dataset_id=dataset_id,
            data_epoch=body.data_epoch,
            symbol=manifest["symbol"],
            interval=manifest["interval"],
            rows=rows,
            requests=[item.model_dump() for item in body.requests],
        )

    try:
        return await asyncio.to_thread(_compute)
    except LocalDatasetError as exc:
        raise _translate_error(exc) from exc


@router.post("/imports/csv", status_code=201)
async def import_csv(
    request: Request,
    name: Annotated[str, Query(min_length=1, max_length=160)],
    symbol: Annotated[str, Query(min_length=1, max_length=80)],
    interval: Annotated[str, Query(min_length=2, max_length=16)],
    timezone_name: Annotated[
        str, Query(alias="timezone", min_length=1, max_length=80)
    ] = "UTC",
    timestamp_unit: Annotated[str, Query(pattern="^(auto|s|ms|iso)$")] = "auto",
    time_column: Annotated[str, Query(min_length=1)] = "time",
    open_column: Annotated[str, Query(min_length=1)] = "open",
    high_column: Annotated[str, Query(min_length=1)] = "high",
    low_column: Annotated[str, Query(min_length=1)] = "low",
    close_column: Annotated[str, Query(min_length=1)] = "close",
    volume_column: Annotated[str, Query(min_length=1)] = "volume",
    volume_required: bool = False,
    quote_volume_column: str | None = None,
    trades_column: str | None = None,
    taker_buy_base_column: str | None = None,
    taker_buy_quote_column: str | None = None,
    last_bar_closed: bool = True,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    service = _service(request)
    upload_path = service.new_upload_path()
    size = 0
    try:
        with Path(upload_path).open("xb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > LOCAL_DATA_MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "code": "upload_too_large",
                            "message": f"CSV exceeds {LOCAL_DATA_MAX_UPLOAD_BYTES} bytes",
                        },
                    )
                handle.write(chunk)
        if size == 0:
            raise HTTPException(
                status_code=422,
                detail={"code": "empty_upload", "message": "CSV body is empty"},
            )
        options = LocalImportOptions(
            name=name,
            symbol=symbol,
            interval=interval,
            timezone_name=timezone_name,
            timestamp_unit=timestamp_unit,
            time_column=time_column,
            open_column=open_column,
            high_column=high_column,
            low_column=low_column,
            close_column=close_column,
            volume_column=volume_column,
            volume_required=volume_required,
            quote_volume_column=quote_volume_column,
            trades_column=trades_column,
            taker_buy_base_column=taker_buy_base_column,
            taker_buy_quote_column=taker_buy_quote_column,
            last_bar_closed=last_bar_closed,
            dataset_id=dataset_id,
        )
        return await asyncio.to_thread(service.import_csv, upload_path, options)
    except LocalDatasetError as exc:
        raise _translate_error(exc) from exc
    finally:
        upload_path.unlink(missing_ok=True)


def _query(
    request: Request,
    dataset_id: str,
    *,
    interval: str,
    limit: int,
    before_ms: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> dict[str, Any]:
    try:
        return _service(request).query(
            dataset_id,
            interval=interval,
            limit=limit,
            before_ms=before_ms,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except LocalDatasetError as exc:
        raise _translate_error(exc) from exc


@router.get("/datasets/{dataset_id}/klines/history")
async def history(
    dataset_id: str,
    request: Request,
    interval: str,
    days: int | None = None,
    count_back: Annotated[int, Query(ge=1, le=5_000)] = 1_000,
) -> dict[str, Any]:
    del days
    return await asyncio.to_thread(
        _query, request, dataset_id, interval=interval, limit=count_back
    )


@router.get("/datasets/{dataset_id}/klines/history/before")
async def before(
    dataset_id: str,
    request: Request,
    interval: str,
    before: Annotated[int, Query(ge=0)],
    bars: Annotated[int, Query(ge=1, le=5_000)] = 1_000,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _query,
        request,
        dataset_id,
        interval=interval,
        limit=bars,
        before_ms=before * 1_000,
    )


@router.get("/datasets/{dataset_id}/klines/range")
async def range_query(
    dataset_id: str,
    request: Request,
    interval: str,
    start: Annotated[int, Query(ge=0)],
    end: Annotated[int, Query(ge=0)],
    limit: Annotated[int, Query(ge=1, le=5_000)] = 5_000,
) -> dict[str, Any]:
    if end < start:
        raise HTTPException(
            status_code=422, detail="end must be greater than or equal to start"
        )
    return await asyncio.to_thread(
        _query,
        request,
        dataset_id,
        interval=interval,
        limit=limit,
        start_ms=start * 1_000,
        end_ms=end * 1_000,
    )


@router.get("/datasets/{dataset_id}/klines/latest")
async def latest(
    dataset_id: str,
    request: Request,
    interval: str,
    limit: Annotated[int, Query(ge=1, le=5_000)] = 1_000,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _query, request, dataset_id, interval=interval, limit=limit
    )
