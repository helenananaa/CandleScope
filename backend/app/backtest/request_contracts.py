"""Validated backtest inputs shared by HTTP and durable preparation."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_revision_id: str = Field(min_length=1, max_length=128)
    dataset_id: str = Field(min_length=1, max_length=80)
    data_epoch: str = Field(min_length=8, max_length=80)
    snapshot_hash: str = Field(min_length=8, max_length=80)
    fidelity_mode: str
    source_event_kind: str | None = None
    start_time_ms: int
    end_time_ms: int
    warmup_bars: int = 0
    cost_sensitivity_mode: Literal["FULL", "SKIP"] | None = None
    checkpoint_policy: Literal["INTERVAL", "FINAL_ONLY", "NONE"] | None = None
    checkpoint_interval: int | None = Field(default=None, ge=1, strict=True)
    symbol: str | None = Field(default=None, max_length=80)
    interval: str | None = Field(default=None, max_length=16)
    signal_clock: str | None = Field(default=None, max_length=40)
    signal_interval: str | None = Field(default=None, max_length=16)
    execution_clock: str | None = Field(default=None, max_length=40)
    bar_builder: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    strategy_source: str | None = Field(default=None, max_length=2_000)
    signal_trace_mode: str = Field(default="LEGACY_INLINE_V1", max_length=32)
    output_mode: str = Field(default="TARGET_POSITION", max_length=32)
    initial_balance: str = Field(default="10000", max_length=64)
    slippage_bps: str = Field(default="1", max_length=64)
    taker_fee_bps: str = Field(default="0", max_length=64)
    maker_fee_bps: str = Field(default="0", max_length=64)
    fee_source: str | None = Field(default=None, max_length=80)
    quick_preset_id: str | None = Field(default=None, max_length=80)
    quick_preset_revision: str | None = Field(default=None, max_length=40)
    chart_range_mode: Literal["ALL_AVAILABLE", "VISIBLE", "CUSTOM"] | None = None
    chart_cell_scope: str | None = Field(default=None, min_length=1, max_length=320)
    strategy_draft_id: str | None = Field(
        default=None, pattern=r"^draft-[A-Za-z0-9_-]{8,152}$"
    )
    funding_rate: str = Field(default="0", max_length=64)
    funding_interval_hours: int = Field(default=8, ge=1, le=168)
    funding_mode: str = Field(default="OFF", max_length=32)
    leverage: str = Field(default="1", max_length=64)
    sizing_policy: str | None = Field(default=None, max_length=40)
    fixed_qty: str | None = Field(default=None, max_length=64)
    fixed_notional: str | None = Field(default=None, max_length=64)
    equity_percent: str | None = Field(default=None, max_length=64)
    risk_per_stop_percent: str | None = Field(default=None, max_length=64)
    stop_distance: str | None = Field(default=None, max_length=64)
    max_abs_position_qty: str | None = Field(default=None, max_length=64)
    max_notional: str | None = Field(default=None, max_length=64)
    max_leverage: str | None = Field(default=None, max_length=64)
    max_order_risk: str | None = Field(default=None, max_length=64)
    max_active_orders: int | None = Field(default=None, ge=1, le=10_000)
    max_cumulative_fees: str | None = Field(default=None, max_length=64)
    max_drawdown_percent: str | None = Field(default=None, max_length=64)
    daily_loss_limit: str | None = Field(default=None, max_length=64)
    cooldown_events: int = Field(default=0, ge=0, le=1_000_000)
    execution_model_revision: str | None = Field(default=None, max_length=48)
    participation_rate: str | None = Field(default=None, max_length=64)
    latency_ms: int = Field(default=0, ge=0, le=60_000)
    latency_events: int = Field(default=0, ge=0, le=100_000)
    order_end_policy: str = Field(default="CANCEL_AT_END", max_length=32)
    bar_path_scenario: str | None = Field(default=None, max_length=64)
    metrics_version: str | None = Field(default=None, max_length=48)
    risk_free_rate_annual: str = Field(default="0", max_length=64)
    sample_role: str = Field(default="IN_SAMPLE", max_length=32)
    exchange: str = Field(default="binance", min_length=1, max_length=40)
    market_type: str = Field(default="usdm", min_length=1, max_length=40)
    price_tick: str | None = Field(default=None, max_length=64)
    qty_step: str | None = Field(default=None, max_length=64)
    min_notional: str | None = Field(default=None, max_length=64)
    gap_policy: str = "REJECT"
    account_model: str = "LINEAR_PERP_ONE_WAY_V1"
    contract_data_mode: str = Field(default="LEGACY_FIXED_V1", max_length=40)
    study_id: str | None = None
    python_runtime_mode: str | None = Field(default=None, max_length=32)
    python_execution_protocol: str | None = Field(default=None, max_length=32)
    python_trusted_confirmed: bool = False

    @model_validator(mode="after")
    def require_explicit_quick_fee_identity(self) -> "RunCreateRequest":
        if not self.quick_preset_id:
            return self
        required_fee_fields = {"taker_fee_bps", "maker_fee_bps", "slippage_bps"}
        missing = sorted(required_fee_fields - self.model_fields_set)
        if not self.quick_preset_revision or not self.fee_source or missing:
            suffix = (
                f"; missing explicit fields: {', '.join(missing)}" if missing else ""
            )
            raise ValueError(
                f"quick backtests require a versioned, confirmed fee preset{suffix}"
            )
        return self


class StudyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    hypothesis: str = ""
    strategy_revision_id: str = Field(min_length=1, max_length=128)
    dataset_id: str | None = Field(default=None, max_length=80)
    data_epoch: str | None = Field(default=None, max_length=80)
    dataset_snapshot_hash: str | None = Field(default=None, max_length=80)
    interval: str | None = Field(default=None, max_length=16)
    start_ms: int
    end_ms: int
    train_ms: int
    test_ms: int
    step_ms: int | None = None
    purge_ms: int = 0
    embargo_ms: int = 0
    holdout_ms: int = 0
    parameter_space: dict[str, list[Any]] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    sampler: str = "grid"
    max_trials: int | None = None
    random_count: int | None = None
    seed: int | None = None
    candidate_budget: int | None = None
    total_run_budget: int | None = None
    objective: str = "SHARPE"
    constraints: dict[str, Any] = Field(default_factory=dict)
    tie_break: str | None = None
    study_protocol_revision: str | None = None
    selection_protocol_revision: str | None = None
    dataset_basket: dict[str, Any] | None = None
    warmup_bars: int = 0
    initial_balance: str = Field(default="10000", max_length=64)
    slippage_bps: str = Field(default="1", max_length=64)
    taker_fee_bps: str = Field(default="0", max_length=64)
    maker_fee_bps: str = Field(default="0", max_length=64)
    gap_policy: str = "REJECT"
    account_model: str | None = None
    contract_data_mode: str | None = None
    funding_mode: str = "OFF"
    leverage: str = Field(default="1", max_length=64)
    execution_model_revision: str | None = None
    participation_rate: str = Field(default="0.1", max_length=64)
    metrics_version: str | None = None
    risk_free_rate_annual: str = Field(default="0", max_length=64)
    sizing_policy: str = "FIXED_QTY_V1"
    fixed_qty: str = Field(default="1", max_length=64)


class SnapshotPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=80)
    data_epoch: str = Field(min_length=8, max_length=80)
    start_time_ms: int
    end_time_ms: int
    interval: str | None = Field(default=None, max_length=16)
    fidelity_mode: str = "BAR_APPROX"
    exchange: str = Field(default="binance", min_length=1, max_length=40)
    market_type: str = Field(default="usdm", min_length=1, max_length=40)
    contract_data_mode: str = Field(default="LEGACY_FIXED_V1", max_length=40)
    account_model: str = Field(default="LINEAR_PERP_ONE_WAY_V1", max_length=40)
    funding_mode: str = Field(default="OFF", max_length=32)


class ChartContextResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange: str = Field(min_length=1, max_length=40)
    market_type: str = Field(min_length=1, max_length=40)
    symbol: str = Field(min_length=1, max_length=80)
    interval: str = Field(min_length=2, max_length=32)
    range_mode: Literal["ALL_AVAILABLE", "VISIBLE", "CUSTOM"]
    start_time_ms: int | None = None
    end_time_ms: int | None = None
    fidelity_preference: Literal["FAST", "PRECISE"]

    @model_validator(mode="after")
    def validate_range(self) -> ChartContextResolveRequest:
        if self.range_mode != "ALL_AVAILABLE":
            if self.start_time_ms is None or self.end_time_ms is None:
                raise ValueError("VISIBLE and CUSTOM ranges require start/end times")
        if (
            self.start_time_ms is not None
            and self.end_time_ms is not None
            and self.start_time_ms >= self.end_time_ms
        ):
            raise ValueError("start_time_ms must be less than end_time_ms")
        return self


class ChartContextMaterializeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution_token: str = Field(min_length=16, max_length=256)
    user_confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=200)
    expected_dataset_id: str | None = Field(default=None, max_length=80)
    expected_data_epoch: str | None = Field(default=None, max_length=80)


class StrategyRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    language: str
    base_revision_id: str | None = None
    source_text: str = Field(default="", max_length=100_000)
    parameter_schema: list[dict[str, Any]] = Field(default_factory=list)


class StrategyCopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class StrategySmokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=80)
    snapshot_hash: str = Field(min_length=8, max_length=80)
    start_time_ms: int
    end_time_ms: int
    parameters: dict[str, Any] = Field(default_factory=dict)
    python_runtime_mode: str | None = Field(default=None, max_length=32)
    python_trusted_confirmed: bool = False


class RunCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameter: str = Field(min_length=1, max_length=128)
    value: Any


class ReviewBridgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time_ms: int
    end_time_ms: int


class ResearchChartSessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange: str = Field(min_length=1, max_length=40)
    market_type: str = Field(min_length=1, max_length=40)
    symbol: str = Field(min_length=1, max_length=80)
    interval: str = Field(min_length=1, max_length=32)


class ResearchRangePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["ALL_AVAILABLE", "VISIBLE", "CUSTOM"]
    start_time_ms: int | None = None
    end_time_ms: int | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "ResearchRangePayload":
        if self.mode != "ALL_AVAILABLE" and (
            self.start_time_ms is None or self.end_time_ms is None
        ):
            raise ValueError("VISIBLE and CUSTOM ranges require start/end times")
        if (
            self.start_time_ms is not None
            and self.end_time_ms is not None
            and self.start_time_ms >= self.end_time_ms
        ):
            raise ValueError("start_time_ms must be less than end_time_ms")
        return self


class ResearchDatasetIdentityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=80)
    data_epoch: str = Field(min_length=8, max_length=80)
    snapshot_hash: str = Field(min_length=8, max_length=80)


class ResearchExecutionOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initialBalance: str = Field(pattern=r"^\d+(?:\.\d+)?$")
    equityPercent: str = Field(pattern=r"^\d+(?:\.\d+)?$")
    leverage: str = Field(pattern=r"^\d+(?:\.\d+)?$")
    feeBps: str = Field(pattern=r"^\d+(?:\.\d+)?$")
    slippageBps: str = Field(pattern=r"^\d+(?:\.\d+)?$")

    @model_validator(mode="after")
    def validate_ranges(self) -> "ResearchExecutionOverrides":
        if Decimal(self.initialBalance) <= 0 or not 0 < Decimal(self.equityPercent) <= 100 or not 1 <= Decimal(self.leverage) <= 125:
            raise ValueError("Invalid backtest account conditions")
        return self


class ResearchLaunchContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_workspace_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_cell_id: str | None = Field(default=None, min_length=1, max_length=160)
    strategy_draft_id: str = Field(pattern=r"^draft-[A-Za-z0-9_-]{8,152}$")
    strategy_revision_id: str | None = Field(default=None, min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    quick_preset_id: str = Field(min_length=1, max_length=80)
    execution_overrides: ResearchExecutionOverrides | None = None
    chart_session: ResearchChartSessionPayload
    range: ResearchRangePayload
    dataset_identity: ResearchDatasetIdentityPayload | None = None
    latest_run_id: str | None = Field(
        default=None, pattern=r"^bt_[A-Za-z0-9_-]{8,128}$"
    )
    baseline_run_id: str | None = Field(
        default=None, pattern=r"^bt_[A-Za-z0-9_-]{8,128}$"
    )
    entry_task: Literal[
        "PRECISE_EXECUTION",
        "PARAMETER_ROBUSTNESS",
        "PYTHON_MODEL",
        "MULTI_MARKET",
        "REPLAY_REVIEW",
    ] | None = None


class PythonBundleZipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zip_base64: str = Field(min_length=8, max_length=2_000_000)


class PythonRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle_id: str = Field(min_length=1, max_length=80)
