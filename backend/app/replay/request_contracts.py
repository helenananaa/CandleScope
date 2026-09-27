"""Validated replay inputs shared by transports and preparation services."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.core.config import REPLAY_SETTINGS
from app.replay.constants import REPLAY_PROTOCOL, CommandType
from app.replay.models import MAX_COUNTER, MAX_RANDOM_SEED, MAX_TIMESTAMP_MS
from app.replay.training.models import (
    AccountDataMode, BookMode, FundingMode, IntegrityMode, MarginMode,
    PositionMode, ReplaySource, StartMode, TimeDisclosurePolicy,
)

_MAX_HORIZON_MS = REPLAY_SETTINGS.max_horizon_days * 86_400_000


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReplayCommandPayload(_StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "protocol": REPLAY_PROTOCOL,
                    "command_id": "cmd-01J00000000000000000000000",
                    "client_instance_id": "browser-tab-01",
                    "expected_revision": 2,
                    "type": "step",
                    "payload": {"count": 1},
                }
            ]
        },
    )

    protocol: Literal["replay.v1"]
    command_id: str = Field(min_length=1, max_length=128)
    client_instance_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0, le=MAX_COUNTER)
    type: CommandType
    payload: dict[str, object]


class ReplayLaunchWatchlistItemPayload(_StrictModel):
    exchange: str = Field(min_length=1, max_length=128)
    market_type: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=128)


class ReplayLaunchWatchlistGroupPayload(_StrictModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(min_length=1, max_length=32)
    items: list[ReplayLaunchWatchlistItemPayload] = Field(max_length=100)


class ReplayWatchlistSnapshotPayload(_StrictModel):
    schema_version: Literal["replay.watchlist-snapshot.v1"]
    groups: list[ReplayLaunchWatchlistGroupPayload] = Field(max_length=32)


class ReplayLaunchContextPayload(_StrictModel):
    schema_version: Literal["replay.launch-context.v1"]
    source: Literal["LIVE_PAGE", "DIRECT_HUB"]
    exchange: str = Field(min_length=1, max_length=128)
    market_type: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=128)
    display_interval: str = Field(min_length=1, max_length=128)
    watchlist_snapshot: ReplayWatchlistSnapshotPayload


class VisibleHistoryLookbackPayload(_StrictModel):
    mode: Literal["DURATION", "ALL_AVAILABLE"]
    duration_ms: int | None = Field(default=None, ge=1, le=MAX_TIMESTAMP_MS)


class AccountHistoryRefPayload(_StrictModel):
    schema_version: Literal["replay.account-history-ref.v1"]
    archive_id: str = Field(min_length=1, max_length=128)
    dataset_epoch: str = Field(min_length=71, max_length=71)
    checksum_sha256: str = Field(min_length=71, max_length=71)


class HedgePublicHistoryRefPayload(_StrictModel):
    schema_version: Literal["replay.hedge-public-history-ref.v1"]
    archive_id: str = Field(min_length=1, max_length=128)
    dataset_epoch: str = Field(min_length=71, max_length=71)
    checksum_sha256: str = Field(min_length=71, max_length=71)


class HedgeSimulationManifestRefPayload(_StrictModel):
    schema_version: Literal["replay.hedge-simulation-manifest-ref.v1"]
    manifest_id: str = Field(min_length=1, max_length=128)
    dataset_epoch: str = Field(min_length=71, max_length=71)
    checksum_sha256: str = Field(min_length=71, max_length=71)
    contract_hash: str = Field(min_length=71, max_length=71)
    model_version: str = Field(min_length=1, max_length=128)


class TrainingRunPreparationPayload(_StrictModel):
    protocol: Literal["replay.v3"]
    catalog_epoch: str = Field(min_length=71, max_length=71)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    source_kind: ReplaySource
    start_mode: StartMode
    exchange: str = Field(min_length=1, max_length=128)
    market_type: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=128)
    settlement_asset: str = Field(min_length=1, max_length=128)
    base_interval: str = Field(min_length=1, max_length=128)
    display_interval: str = Field(min_length=1, max_length=128)
    requested_start_ms: int | None = Field(default=None, ge=0, le=MAX_TIMESTAMP_MS)
    warmup_bars: int | None = Field(
        default=None,
        ge=1,
        le=REPLAY_SETTINGS.max_warmup_bars,
    )
    indicator_warmup_bars: int | None = Field(
        default=None,
        ge=1,
        le=REPLAY_SETTINGS.max_warmup_bars,
    )
    visible_history_lookback: VisibleHistoryLookbackPayload | None = None
    forward_cache_ms: int = Field(ge=1, le=_MAX_HORIZON_MS)
    random_seed: int | None = Field(default=None, ge=0, le=MAX_RANDOM_SEED)
    initial_equity: str = Field(min_length=1, max_length=128)
    max_leverage: str = Field(min_length=1, max_length=128)
    maker_fee_bps: str = Field(min_length=1, max_length=128)
    taker_fee_bps: str = Field(min_length=1, max_length=128)
    market_slippage_bps: str = Field(min_length=1, max_length=128)
    integrity_mode: IntegrityMode
    time_disclosure_policy: TimeDisclosurePolicy
    book_mode: BookMode
    margin_mode: MarginMode
    position_mode: PositionMode = PositionMode.ONE_WAY
    funding_mode: FundingMode
    account_data_mode: AccountDataMode = AccountDataMode.APPROX_PROXY
    account_history_ref: AccountHistoryRefPayload | None = None
    hedge_public_history_ref: HedgePublicHistoryRefPayload | None = None
    simulation_manifest_ref: HedgeSimulationManifestRefPayload | None = None
    account_fidelity: str | None = Field(
        default=None,
        max_length=128,
    )
    insurance_adl_fidelity: str | None = Field(
        default=None,
        max_length=128,
    )
    fixed_funding_rate: str | None = Field(default=None, min_length=1, max_length=128)
    funding_interval_ms: int | None = Field(default=None, ge=60_000, le=2_592_000_000)
    allow_rule_changes: bool
    allowed_mutations: list[str] = Field(default_factory=list, max_length=6)
    launch_context: ReplayLaunchContextPayload | None = None


class TrainingRunSetupPayload(_StrictModel):
    protocol: Literal["replay.v3"]
    name: str | None = Field(default=None, min_length=1, max_length=80)
    source_kind: ReplaySource
    start_mode: StartMode
    settlement_asset: str = Field(min_length=1, max_length=128)
    requested_start_ms: int | None = Field(default=None, ge=0, le=MAX_TIMESTAMP_MS)
    random_range_start_ms: int | None = Field(default=None, ge=0, le=MAX_TIMESTAMP_MS)
    random_range_end_ms: int | None = Field(default=None, ge=0, le=MAX_TIMESTAMP_MS)
    indicator_warmup_bars: int = Field(
        ge=1,
        le=REPLAY_SETTINGS.max_warmup_bars,
    )
    visible_history_lookback: VisibleHistoryLookbackPayload
    forward_cache_ms: int = Field(ge=1, le=_MAX_HORIZON_MS)
    random_seed: int | None = Field(default=None, ge=0, le=MAX_RANDOM_SEED)
    initial_equity: str = Field(min_length=1, max_length=128)
    max_leverage: str = Field(min_length=1, max_length=128)
    maker_fee_bps: str = Field(min_length=1, max_length=128)
    taker_fee_bps: str = Field(min_length=1, max_length=128)
    market_slippage_bps: str = Field(min_length=1, max_length=128)
    integrity_mode: IntegrityMode
    time_disclosure_policy: TimeDisclosurePolicy
    book_mode: BookMode
    margin_mode: MarginMode
    position_mode: PositionMode = PositionMode.ONE_WAY
    funding_mode: FundingMode
    account_data_mode: AccountDataMode = AccountDataMode.APPROX_PROXY
    account_fidelity: str | None = Field(default=None, max_length=128)
    insurance_adl_fidelity: str | None = Field(default=None, max_length=128)
    fixed_funding_rate: str | None = Field(default=None, min_length=1, max_length=128)
    funding_interval_ms: int | None = Field(default=None, ge=60_000, le=2_592_000_000)
    allow_rule_changes: bool
    allowed_mutations: list[str] = Field(default_factory=list, max_length=6)
    market_selection_hint: ReplayLaunchContextPayload | None = None


class TrainingRunMarketSelectionPayload(_StrictModel):
    catalog_epoch: str = Field(min_length=71, max_length=71)
    exchange: str = Field(min_length=1, max_length=128)
    market_type: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=128)
    base_interval: str = Field(min_length=1, max_length=128)
    display_interval: str = Field(min_length=1, max_length=128)
    account_history_ref: AccountHistoryRefPayload | None = None
    hedge_public_history_ref: HedgePublicHistoryRefPayload | None = None
    simulation_manifest_ref: HedgeSimulationManifestRefPayload | None = None


class TrainingRunMarketTrackPlanPayload(_StrictModel):
    exchange: str = Field(min_length=1, max_length=128)
    market_type: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=128)
    subscription_tier: Literal["NONE", "WARM", "FULL"] = "NONE"


class TrainingCursorPayload(_StrictModel):
    virtual_time_ms: int = Field(ge=0, le=MAX_TIMESTAMP_MS)
    source_sequence: int = Field(ge=0, le=MAX_COUNTER)
    revision: int = Field(ge=0, le=MAX_COUNTER)


class ReplayV2CommandPayload(_StrictModel):
    protocol: Literal["replay.v3"]
    run_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    client_instance_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0, le=MAX_COUNTER)
    expected_cursor: TrainingCursorPayload
    type: str = Field(min_length=1, max_length=64)
    payload: dict[str, object]


class ReplayOrderRequestPayload(_StrictModel):
    client_order_id: str = Field(min_length=1, max_length=128)
    side: Literal["BUY", "SELL"]
    order_type: Literal[
        "MARKET",
        "LIMIT",
        "STOP_MARKET",
        "TAKE_PROFIT_MARKET",
    ]
    quantity: str = Field(min_length=1, max_length=128)
    reduce_only: bool
    limit_price: str | None = Field(default=None, min_length=1, max_length=128)
    stop_price: str | None = Field(default=None, min_length=1, max_length=128)
    leverage: str | None = Field(default=None, min_length=1, max_length=128)
    position_side: Literal["LONG", "SHORT"] | None = None


class ReplayTradePlanDraftPayload(_StrictModel):
    sizing_mode: Literal["RISK_AMOUNT", "ACCOUNT_RISK_PERCENT"]
    risk_amount: str | None = Field(default=None, min_length=1, max_length=128)
    risk_percent: str | None = Field(default=None, min_length=1, max_length=128)
    invalidation_price: str = Field(min_length=1, max_length=128)
    target_price: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class ReplayOrderPreviewPayload(_StrictModel):
    protocol: Literal["replay.v3"]
    expected_revision: int = Field(ge=0, le=MAX_COUNTER)
    expected_cursor: TrainingCursorPayload
    position_intent: Literal["NET", "OPEN"]
    order: ReplayOrderRequestPayload
    trade_plan: ReplayTradePlanDraftPayload | None = None


class ReplayOrderCapacityContextPayload(_StrictModel):
    side: Literal["BUY", "SELL"]
    order_type: Literal[
        "MARKET",
        "LIMIT",
        "STOP_MARKET",
        "TAKE_PROFIT_MARKET",
    ]
    reduce_only: bool
    limit_price: str | None = Field(default=None, min_length=1, max_length=128)
    stop_price: str | None = Field(default=None, min_length=1, max_length=128)
    leverage: str | None = Field(default=None, min_length=1, max_length=128)
    position_side: Literal["LONG", "SHORT"] | None = None


class ReplayOrderCapacityPayload(_StrictModel):
    protocol: Literal["replay.v3"]
    expected_revision: int = Field(ge=0, le=MAX_COUNTER)
    expected_cursor: TrainingCursorPayload
    position_intent: Literal["NET", "OPEN"]
    context: ReplayOrderCapacityContextPayload


class ReplayReviewPayload(_StrictModel):
    event_id: str | None = Field(default=None, min_length=1, max_length=128)


class ReplayDrawingDocumentPayload(_StrictModel):
    protocol: Literal["replay.review.drawing-document.v1"]
    command_id: str = Field(min_length=1, max_length=128)
    document_hash: str = Field(min_length=71, max_length=71)
    document: dict[str, object]
    entity_count: int = Field(ge=0, le=512)


class ReplayReviewMarkerPayload(_StrictModel):
    protocol: Literal["replay.review.marker.v1"]
    command_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=500)


class ReplayReviewControlPayload(_StrictModel):
    action: Literal["JUMP", "NEXT", "PREVIOUS", "PLAY", "PAUSE"]
    event_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_cursor_revision: int = Field(ge=1, le=MAX_COUNTER)
    playback_rate: str | None = Field(default=None, min_length=1, max_length=8)


class ReplayPublicTimeBatchPayload(_StrictModel):
    timeline_ms: list[int] = Field(min_length=1, max_length=2_000)


class ReplayForkPayload(_StrictModel):
    event_id: str = Field(min_length=1, max_length=128)


class ReplaySegmentGcPlanPayload(_StrictModel):
    protocol: Literal["replay.data.gc.v1"]
    target_reclaim_bytes: int = Field(ge=1, le=1_000_000_000_000)
    max_segments: int = Field(default=100, ge=1, le=10_000)


class ReplaySegmentGcRunPayload(ReplaySegmentGcPlanPayload):
    plan_hash: str = Field(min_length=71, max_length=71)
    confirm: Literal[True]


class ReplayHistoricalBookGcPlanPayload(_StrictModel):
    protocol: Literal["replay.historical-book.gc.v1"]
    target_reclaim_bytes: int = Field(ge=1, le=1_000_000_000_000)
    max_archives: int = Field(default=100, ge=1, le=10_000)


class ReplayHistoricalBookGcRunPayload(ReplayHistoricalBookGcPlanPayload):
    plan_hash: str = Field(min_length=71, max_length=71)
    confirm: Literal[True]


class ReplayAccountHistoryGcPlanPayload(_StrictModel):
    protocol: Literal["replay.account-history.gc.v1"]
    target_reclaim_bytes: int = Field(ge=1, le=1_000_000_000_000)
    max_archives: int = Field(default=100, ge=1, le=10_000)


class ReplayAccountHistoryGcRunPayload(ReplayAccountHistoryGcPlanPayload):
    plan_hash: str = Field(min_length=71, max_length=71)
    confirm: Literal[True]
