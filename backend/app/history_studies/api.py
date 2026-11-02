"""Trusted-local adapters; all study and annotation IO has one manager owner."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    ValidationError,
)

from app.core.config import DATA_DIR
from app.core.executors import run_storage
from app.research_data.access import require_local_research_access

from .repository import StudyConflict

router = APIRouter(prefix="/history-studies", tags=["history-studies"],
                   dependencies=[Depends(require_local_research_access)])
Text = Annotated[str, StringConstraints(min_length=1, max_length=128, strip_whitespace=True)]
StudyId = Annotated[str, StringConstraints(pattern=r"^hs_[a-f0-9]{32}$")]
NoteId = Annotated[str, StringConstraints(pattern=r"^je_[a-f0-9]{20}$")]
Owner = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,2048}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Series(Model):
    exchange: Text
    marketType: Text
    symbol: Text
    interval: Text
    providerId: Text
    venue: Text
    assetClass: Text
    seriesVariant: Text
    priceAdjustment: Text
    sessionVariant: Text
    volumeSemantics: Text


class OrderFlow(Model):
    taker_sell_base: FiniteFloat = Field(ge=0)
    volume_delta_base: FiniteFloat
    taker_buy_ratio_base: FiniteFloat | None = None
    cvd_contribution_base: FiniteFloat


class Bar(Model):
    time: int = Field(ge=0, le=253402300799)
    open: FiniteFloat
    high: FiniteFloat
    low: FiniteFloat
    close: FiniteFloat
    volume: FiniteFloat = Field(ge=0)
    quote_volume: FiniteFloat | None = Field(default=None, ge=0)
    trades: int | None = Field(default=None, ge=0)
    taker_buy_base: FiniteFloat | None = Field(default=None, ge=0)
    taker_buy_quote: FiniteFloat | None = Field(default=None, ge=0)
    order_flow: OrderFlow | None = None


class Capture(Model):
    id: StudyId
    series: Series
    rows: list[Bar] = Field(min_length=1, max_length=5000)
    cursorMs: int = Field(ge=0)
    expectedRevision: int = Field(ge=0)


class Move(Model):
    studyId: StudyId
    cursorMs: int = Field(ge=0)
    expectedRevision: int = Field(ge=1)
    active: bool


class Note(Model):
    id: NoteId
    marketTimeMs: int = Field(ge=0)
    expectedRevision: int = Field(ge=0, le=100)
    fields: dict[str, str] = Field(max_length=80)


class SavedSelection(Model):
    studyId: StudyId
    expectedRevision: int = Field(ge=1)


async def body(request, model):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 2_000_000:
            raise HTTPException(413, detail={"code": "study_input_too_large"})
    try:
        return model.model_validate_json(data)
    except ValidationError:
        raise HTTPException(422, detail={"code": "study_request_invalid"}) from None


async def invoke(request, method, *args, **kwargs):
    core = getattr(request.app.state, "data_manager_core", None)
    if core is None:
        raise HTTPException(503, detail={"code": "study_unavailable"})
    try:
        owner = core.history_studies(DATA_DIR / "history-studies.sqlite3")
        return await run_storage(getattr(owner, method), *args, **kwargs)
    except StudyConflict as exc:
        raise HTTPException(409, detail={"code": "study_revision_conflict", "message": str(exc)}) from None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "study_input_invalid", "message": str(exc)}) from None


@router.get("/views/{owner}")
async def get_view(request: Request, owner: Owner):
    return await invoke(request, "view", owner)


@router.post("/views/{owner}")
async def capture(request: Request, owner: Owner):
    value = await body(request, Capture)
    return await invoke(request, "capture", owner, value.id, value.series.model_dump(),
                        [bar.model_dump(exclude_unset=True) for bar in value.rows], cursor_ms=value.cursorMs,
                        expected_revision=value.expectedRevision)


@router.patch("/views/{owner}")
async def move(request: Request, owner: Owner):
    value = await body(request, Move)
    return await invoke(request, "move", owner, value.studyId, cursor_ms=value.cursorMs,
                        expected_revision=value.expectedRevision, active=value.active)


@router.get("/saved/{owner}")
async def saved(request: Request, owner: Owner):
    return {"studies": await invoke(request, "saved", owner)}


@router.post("/saved/{owner}/activate")
async def activate(request: Request, owner: Owner):
    value = await body(request, SavedSelection)
    return await invoke(request, "activate", owner, value.studyId, expected_revision=value.expectedRevision)


@router.post("/saved/{owner}/remove")
async def remove(request: Request, owner: Owner):
    value = await body(request, SavedSelection)
    return await invoke(request, "remove", owner, value.studyId, expected_revision=value.expectedRevision)


@router.get("/{study_id}/notes")
async def notes(request: Request, study_id: StudyId, cursorMs: int):
    return {"notes": await invoke(request, "notes", study_id, cursorMs)}


@router.post("/{study_id}/notes")
async def save_note(request: Request, study_id: StudyId):
    value = await body(request, Note)
    return await invoke(request, "save_note", study_id, value.id, value.fields,
                        market_ms=value.marketTimeMs, expected_revision=value.expectedRevision)


@router.get("/{study_id}/notes/{note_id}/revisions")
async def note_history(request: Request, study_id: StudyId, note_id: NoteId,
                       beforeRevision: int = 101, limit: int = 20):
    return await invoke(request, "note_history", study_id, note_id,
                        before_revision=beforeRevision, limit=limit)
