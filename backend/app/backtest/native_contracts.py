"""Validated inputs for native and host-matched engine services."""
from __future__ import annotations

from typing import Any, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenNativeData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=80)
    data_epoch: str = Field(min_length=8, max_length=80)
    snapshot_hash: str = Field(min_length=8, max_length=80)
    start_time_ms: int
    end_time_ms: int
    interval: str = Field(min_length=1, max_length=16)
    exchange: str = Field(default="binance", max_length=40)
    market_type: str = Field(default="usdm", max_length=40)

    @model_validator(mode="after")
    def check_range(self):
        if self.end_time_ms <= self.start_time_ms:
            raise ValueError("end_time_ms must follow start_time_ms")
        return self


class NativeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=120)
    timeframe: str = Field(min_length=1, max_length=16)


class RequestedNativeData(FrozenNativeData):
    symbol: str = Field(min_length=1, max_length=120)
    timeframe: str = Field(min_length=1, max_length=16)


class PineInstrumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    minMove: int = Field(gt=0, le=4294967295, strict=True)
    priceScale: int = Field(gt=0, le=4294967295, strict=True)
    pointValue: float | None = Field(default=None, gt=0)
    quantityPrecision: int | None = Field(default=None, ge=0, le=9, strict=True)
    quantityStep: str | None = Field(default=None, max_length=64)
    minContract: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, pattern="^[A-Z]+$", max_length=16)


class PineHostEnvironment(BaseModel):
    """Frozen metadata and clocks; market bars continue to require dataset refs."""
    model_config = ConfigDict(extra="forbid")
    chartMetadata: PineInstrumentMetadata | None = None
    symbolMetadata: dict[str, PineInstrumentMetadata] = Field(default_factory=dict)
    executionTimes: list[Annotated[int, Field(ge=0, strict=True)]] | None = Field(default=None, max_length=100_000)
    currencyRates: dict[str, Any] | None = None
    barCalendars: dict[str, Any] | None = None
    sessionWindows: dict[str, Any] | None = None


class NativeRunRequest(FrozenNativeData):
    language: Literal["pine", "pyne"]
    source: str = Field(min_length=1, max_length=500_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: NativeContext
    contexts: list[RequestedNativeData] = Field(default_factory=list, max_length=16)
    libraries: dict[str, str] = Field(default_factory=dict)
    magnifier: FrozenNativeData | None = None
    host_inputs: PineHostEnvironment = Field(default_factory=PineHostEnvironment)

    @model_validator(mode="after")
    def host_language(self):
        if self.language != "pine" and any(value is not None and value != {} for value in self.host_inputs.model_dump().values()):
            raise ValueError("Pine host inputs require the Pine language")
        return self


class HostMatchingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    price_tick: float | None = Field(default=None, gt=0)
    initial_balance: float = Field(default=10000, gt=0)
    slippage_bps: float = Field(default=1, ge=0, le=1000)
    taker_fee_bps: float = Field(default=0, ge=0, le=1000)


class ExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_ms: int
    role: Literal["TRADES", "ORDER_BOOK"]
    payload: dict[str, Any]


class ExecutionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=120)
    events: list[ExecutionEvent] = Field(min_length=1, max_length=500_000)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ExternalRunRequest(NativeRunRequest):
    execution_mode: Literal["CANDLESCOPE"] = "CANDLESCOPE"
    execution_fidelity: Literal["BAR_APPROX", "TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"] = "BAR_APPROX"
    fill_recalculation: bool = False
    execution_data: ExecutionData | None = None
    host_settings: HostMatchingSettings = Field(default_factory=HostMatchingSettings)

    @model_validator(mode="after")
    def host_clock(self):
        if self.host_inputs.executionTimes is not None or self.host_inputs.sessionWindows is not None:
            raise ValueError("host matching owns the observation clock and account windows; omit executionTimes and sessionWindows")
        return self


class ReplayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=80)


class ReplayCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    action: Literal["play", "pause", "step", "seek", "snapshot", "restore"]
    target: int | None = Field(default=None, ge=0)
    snapshot_id: str | None = Field(default=None, max_length=80)
