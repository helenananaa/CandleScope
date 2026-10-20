"""Validated inputs for native and host-matched engine services."""
from __future__ import annotations

from typing import Any, Literal
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


class PineChartMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    priceTickSize: str = Field(min_length=1, max_length=80)
    quantityPrecision: int | None = Field(default=None, ge=0, le=9, strict=True)
    pointValue: float | None = Field(default=None, gt=0, strict=True)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{1,20}$")

    @model_validator(mode="after")
    def check_price_tick(self):
        from fractions import Fraction

        try:
            tick = Fraction(self.priceTickSize)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("priceTickSize must be a positive finite decimal") from exc
        if tick <= 0 or max(tick.numerator, tick.denominator) > 4_294_967_295:
            raise ValueError("priceTickSize exceeds the Pine runtime price grid")
        if self.pointValue is not None and self.pointValue != 1:
            raise ValueError("this Pine runtime only supports pointValue=1")
        return self


class NativeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=120)
    timeframe: str = Field(min_length=1, max_length=16)
    metadata: PineChartMetadata | None = None


class RequestedNativeData(FrozenNativeData):
    symbol: str = Field(min_length=1, max_length=120)
    timeframe: str = Field(min_length=1, max_length=16)
    metadata: PineChartMetadata | None = None


class NativeRunRequest(FrozenNativeData):
    language: Literal["pine", "pyne"]
    source: str = Field(min_length=1, max_length=500_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: NativeContext
    contexts: list[RequestedNativeData] = Field(default_factory=list, max_length=16)
    libraries: dict[str, str] = Field(default_factory=dict)
    currency_rates: dict[str, Any] | None = None
    magnifier: FrozenNativeData | None = None

    @model_validator(mode="after")
    def validate_pine_metadata(self):
        if self.language != "pine" and (self.context.metadata is not None or self.currency_rates is not None
                or any(item.metadata is not None for item in self.contexts)):
            raise ValueError("Pine chart metadata and currency rates require a Pine strategy")
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


class AccountEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_ms: int = Field(strict=True)
    role: Literal["INSTRUMENT_RULES", "MARK_INDEX", "FUNDING"]
    payload: dict[str, Any]


class AccountData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=120)
    events: list[AccountEvent] = Field(min_length=1, max_length=500_000)
    provenance: dict[str, Any] = Field(default_factory=dict)


class WorkbenchBarSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    account_model: Literal["LINEAR_PERP_ONE_WAY_V1", "LINEAR_PERP_ONE_WAY_V2", "SPOT_CASH_V1"] | None = None
    leverage: float = Field(default=1, gt=0, le=1000)
    funding_mode: Literal["OFF", "HISTORICAL_REQUIRED"] = "OFF"
    account_data: AccountData | None = None
    execution_model_revision: Literal["EXECUTION_REALISM_V2"] | None = None
    participation_rate: float | None = Field(default=None, gt=0, le=1)
    bar_path_scenario: Literal["OHLC_NEAREST_EXTREME_PATH_V2"] | None = None

    @model_validator(mode="after")
    def check_account_settings(self):
        if self.execution_model_revision is None and (self.participation_rate is not None or self.bar_path_scenario is not None):
            raise ValueError("participation settings require EXECUTION_REALISM_V2")
        if self.execution_model_revision is not None and self.participation_rate is None:
            raise ValueError("EXECUTION_REALISM_V2 requires participation_rate")
        if self.account_model == "LINEAR_PERP_ONE_WAY_V2":
            if self.account_data is None:
                raise ValueError("V2 account requires frozen account_data")
        elif self.account_data is not None or self.funding_mode != "OFF" or self.leverage != 1:
            raise ValueError("historical account settings require LINEAR_PERP_ONE_WAY_V2")
        return self


class ExternalRunRequest(NativeRunRequest, WorkbenchBarSettings):
    execution_mode: Literal["CANDLESCOPE"] = "CANDLESCOPE"
    execution_fidelity: Literal["BAR_APPROX", "TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"] = "BAR_APPROX"
    fill_recalculation: bool = False
    execution_data: ExecutionData | None = None
    host_settings: HostMatchingSettings = Field(default_factory=HostMatchingSettings)


class ReplayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=80)


class ReplayCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    action: Literal["play", "pause", "step", "seek", "snapshot", "restore"]
    target: int | None = Field(default=None, ge=0)
    snapshot_id: str | None = Field(default=None, max_length=80)
