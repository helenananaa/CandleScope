"""HTTP contract for immutable user-provided data in LOCAL_OFFLINE mode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.config import LOCAL_DATA_MAX_UPLOAD_BYTES, RUNTIME_MODE
from app.local_data import LocalDatasetError, LocalDatasetService, LocalImportOptions


router = APIRouter(prefix="/local", tags=["local-data"])


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
        if exc.code == "dataset_corrupt"
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
        "timestamp_units": ["auto", "s", "ms", "iso"],
        "realtime": False,
        "backfill": False,
        "gaps_are_terminal": True,
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
