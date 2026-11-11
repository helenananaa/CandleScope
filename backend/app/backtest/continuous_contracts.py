"""Wire contracts for current-code continuous strategies; no user revisions."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.series_identity import KlineSeriesIdentity

MAX_COUNTER=9_007_199_254_740_991


class StrictInput(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)


class EditorParameters(StrictInput):
    source_text: str = Field(max_length=262144)


class SeriesIdentity(StrictInput):
    provider_id:str=Field(min_length=1,max_length=64,pattern=r"^\S+$")
    venue:str=Field(min_length=1,max_length=64,pattern=r"^\S+$")
    asset_class:str=Field(min_length=1,max_length=64,pattern=r"^\S+$")
    series_variant:str=Field(min_length=1,max_length=64,pattern=r"^\S+$")
    price_adjustment:str=Field(min_length=1,max_length=64,pattern=r"^\S+$")
    session_variant:str=Field(min_length=1,max_length=64,pattern=r"^\S+$")
    volume_semantics:str=Field(min_length=1,max_length=64,pattern=r"^\S+$")


class MarketSeries(StrictInput):
    exchange:str=Field(min_length=1,max_length=40,pattern=r"^\S+$")
    market_type:str=Field(min_length=1,max_length=40,pattern=r"^\S+$")
    symbol:str=Field(min_length=1,max_length=128,pattern=r"^\S+$")
    interval:str=Field(min_length=1,max_length=64,pattern=r"^\S+$")
    identity:SeriesIdentity

    def key(self):
        return SeriesKey.create(self.symbol,self.interval,exchange=self.exchange,market_type=self.market_type,
            identity=KlineSeriesIdentity(**self.identity.model_dump()))


class CurrentProvider(StrictInput):
    language:str=Field(min_length=1,max_length=24)
    schema_version:str|None=Field(default=None,max_length=80,alias="schema")
    builtin_id:str|None=Field(default=None,min_length=1,max_length=128,pattern=r"^\S+$")
    source_text:str=Field(default="",max_length=262144)
    parameters:dict[str,Any]=Field(default_factory=dict)
    output_mode:Literal["SIGNAL","TARGET_POSITION","ORDER_INTENT"]="TARGET_POSITION"
    runtime_mode:Literal["SANDBOXED_LOCAL","TRUSTED_LOCAL"]|None=None
    trusted_confirmed:bool=False


class ContinuousCreate(StrictInput):
    mode:Literal["HISTORY_LIVE","LIVE_ONLY"]
    series:MarketSeries
    provider:CurrentProvider
    execution:dict[str,Any]
    from_ms:int|None=Field(default=None,ge=0,le=MAX_COUNTER)
    warmup_bars:int=Field(default=0,ge=0,le=200000)

    @model_validator(mode="after")
    def window(self):
        if (self.mode=="HISTORY_LIVE")!=(self.from_ms is not None):
            raise ValueError("Only history+live requires its initial history start")
        return self


class CommittedIdentity(StrictInput):
    id:str=Field(min_length=1,max_length=128,pattern=r"^\S+$")
    generation:int=Field(ge=1,le=MAX_COUNTER)
    revision:int=Field(ge=1,le=MAX_COUNTER)
    checkpoint_revision:int=Field(ge=1,le=MAX_COUNTER)
    sequence:int=Field(ge=0,le=MAX_COUNTER)
    event_time_ms:int=Field(ge=0,le=MAX_COUNTER)
    data_revision:str=Field(min_length=1,max_length=256)


class ContinuousControl(StrictInput):
    action:Literal["pause","resume","retry","cancel"]
    revision:int=Field(ge=1,le=MAX_COUNTER)
    expected:CommittedIdentity|None=None
    refresh_input:bool=False


class ResultQuery(StrictInput):
    kind:str|None=Field(default=None,max_length=32)
    after:int=Field(default=-1,ge=-1,le=MAX_COUNTER)
    limit:int=Field(default=100,ge=1,le=200)
    expected:CommittedIdentity|None=None
    since_revision:int|None=Field(default=None,ge=0,le=MAX_COUNTER)
    change_cursor:list[Any]|None=Field(default=None,min_length=3,max_length=3)


class RepairPreview(StrictInput):
    expected:CommittedIdentity
    resume_after:bool


class RepairConfirm(RepairPreview):
    plan_id:str=Field(min_length=64,max_length=64,pattern=r"^[0-9a-f]{64}$")
    confirmed:bool

    @model_validator(mode="after")
    def consent(self):
        if self.confirmed is not True:raise ValueError("Repair requires explicit consent")
        return self


class RepairCancel(StrictInput):
    expected:CommittedIdentity


class AutomaticRepairSetting(StrictInput):
    enabled: bool
    expected_version: int = Field(ge=0, le=MAX_COUNTER)
