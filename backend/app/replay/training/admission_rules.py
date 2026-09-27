"""Admission rules shared by training coordinators."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from app.data_engine.interval_policy import (
    parse_interval_ms,
)
from app.replay.canonical import canonical_sha256
from app.replay.constants import (
    REPLAY_PROTOCOL,
    ExecutionModel,
    QualityMode,
    SlippageKind,
    SourceKind,
    StartPolicy,
)
from app.replay.models import (
    FeeModel,
    ReplaySessionConfig,
    SlippageModel,
)

from . import control_rules as control_rules_ops
from .errors import TrainingRunError
from .models import (
    ReplaySource,
    StartMode,
    SubscriptionTier,
    TimeDisclosurePolicy,
    TrainingRunCreateRequest,
    VisibleHistoryMode,
)

_MARKET_TRACK_PLAN_CACHE_SIZE = 1_024


_MARKET_TRACK_PLAN_TTL_MS = 60_000


@dataclass(frozen=True, slots=True)
class _MarketTrackPlan:
    plan_id: str
    run_id: str
    exchange: str
    market_type: str
    symbol: str
    base_asset: str
    settlement_asset: str
    subscription_tier: SubscriptionTier
    target_virtual_time_ms: int
    expires_at_ms: int


@dataclass(frozen=True, slots=True)
class _MarketSetupAdmission:
    windows: tuple[tuple[int, int], ...]
    code: str
    message: str
    book_windows: tuple[tuple[int, int], ...] = ()
    account_windows: tuple[tuple[int, int], ...] = ()
    hedge_book_pairs: tuple[tuple[int, int, int, int], ...] = ()

    @staticmethod
    def _merged(
        windows: Sequence[tuple[int, int]],
    ) -> tuple[tuple[int, int], ...]:
        merged: list[list[int]] = []
        for first, last in sorted(windows):
            if not merged or first > merged[-1][1]:
                merged.append([first, last])
            else:
                merged[-1][1] = max(merged[-1][1], last)
        return tuple((first, last) for first, last in merged)

    @classmethod
    def _start_windows(
        cls,
        windows: Sequence[tuple[int, int]],
        *,
        required_span_ms: int,
    ) -> tuple[tuple[int, int], ...]:
        return tuple(
            (first, last - required_span_ms)
            for first, last in cls._merged(windows)
            if last - required_span_ms >= first
        )

    @classmethod
    def _intersection(
        cls,
        left: Sequence[tuple[int, int]],
        right: Sequence[tuple[int, int]],
    ) -> tuple[tuple[int, int], ...]:
        return cls._merged(
            tuple(
                (max(left_start, right_start), min(left_end, right_end))
                for left_start, left_end in left
                for right_start, right_end in right
                if max(left_start, right_start) <= min(left_end, right_end)
            )
        )

    def eligible_start_windows(
        self,
        required_span_ms: int,
        *,
        book_interval_ms: int = 0,
    ) -> tuple[tuple[int, int], ...]:
        account_starts = self._start_windows(
            self.account_windows,
            required_span_ms=required_span_ms,
        )
        if self.hedge_book_pairs:
            candidates: list[tuple[int, int]] = []
            for book_start, book_end, hedge_start, hedge_end in self.hedge_book_pairs:
                paired = self._intersection(
                    self._start_windows(
                        ((book_start, book_end),),
                        required_span_ms=required_span_ms + book_interval_ms,
                    ),
                    self._start_windows(
                        ((hedge_start, hedge_end),),
                        required_span_ms=required_span_ms,
                    ),
                )
                if self.account_windows:
                    paired = self._intersection(paired, account_starts)
                candidates.extend(paired)
            return self._merged(candidates)
        if self.book_windows:
            candidates = self._start_windows(
                self.book_windows,
                required_span_ms=required_span_ms + book_interval_ms,
            )
            if self.account_windows:
                candidates = self._intersection(candidates, account_starts)
            return candidates
        return self._start_windows(
            self.windows,
            required_span_ms=required_span_ms,
        )


def _sample_unique_source_time(
    candidate_ranges: Sequence[tuple[int, int, int]],
    *,
    random_seed: int,
) -> int:
    """Map a seed to a uniformly weighted T0 without materializing every minute.

    The input is a compact multiset of ``(first, interval, count)`` progressions
    contributed by source-compatible markets. A timestamp present in more than
    one progression still represents one Run T0, so deterministic rejection
    removes the otherwise accidental market-count weighting.
    """

    candidate_count = sum(count for _first, _step, count in candidate_ranges)
    if candidate_count < 1:
        raise ValueError("candidate_ranges must contain at least one timestamp")
    for attempt in range(10_000):
        if attempt == 0:
            candidate_index = random_seed % candidate_count
        else:
            draw = canonical_sha256(
                {
                    "schema_version": "replay.source-time-sample.v1",
                    "random_seed": random_seed,
                    "attempt": attempt,
                }
            )
            candidate_index = int(draw[7:], 16) % candidate_count
        mapped_index = candidate_index
        candidate_start_ms: int | None = None
        for first, interval_ms, count in candidate_ranges:
            if mapped_index < count:
                candidate_start_ms = first + mapped_index * interval_ms
                break
            mapped_index -= count
        if candidate_start_ms is None:
            raise RuntimeError("aggregate-trade random range mapping drifted")
        multiplicity = sum(
            1
            for first, interval_ms, count in candidate_ranges
            if first <= candidate_start_ms <= first + (count - 1) * interval_ms
            and (candidate_start_ms - first) % interval_ms == 0
        )
        if multiplicity < 1:
            raise RuntimeError("aggregate-trade random coverage multiplicity drifted")
        acceptance = canonical_sha256(
            {
                "schema_version": "replay.source-time-deduplication.v1",
                "random_seed": random_seed,
                "attempt": attempt,
                "candidate_start_ms": candidate_start_ms,
            }
        )
        if int(acceptance[7:], 16) % multiplicity == 0:
            return candidate_start_ms
    raise TrainingRunError(
        "TRAINING_RANDOM_SEED_UNAVAILABLE",
        "server could not map the random seed to a unique source time",
        status_code=503,
    )


def assert_same_market_scope(
    *,
    binding: Mapping[str, object],
    exchange: str,
    market_type: str,
    settlement_asset: str,
) -> None:
    actual = (exchange, market_type, settlement_asset)
    expected = (
        str(binding["exchange"]),
        str(binding["market_type"]),
        str(binding["settlement_asset"]),
    )
    if actual != expected:
        raise TrainingRunError(
            "MARKET_SCOPE_MISMATCH",
            "multi-market tracks must share exchange, market type, and settlement asset",
            status_code=409,
            details={"expected": list(expected), "actual": list(actual)},
        )


def selection_warmup_bars(request: TrainingRunCreateRequest) -> int:
    visible = request.visible_history_lookback
    if visible is None or visible.mode is VisibleHistoryMode.ALL_AVAILABLE:
        return request.indicator_warmup_bars
    assert visible.duration_ms is not None
    interval_ms = parse_interval_ms(request.base_interval)
    if interval_ms is None:
        raise TrainingRunError(
            "VISIBLE_HISTORY_INTERVAL_MISMATCH",
            "visible history requires a fixed base interval",
            status_code=422,
        )
    if visible.duration_ms % interval_ms:
        raise TrainingRunError(
            "VISIBLE_HISTORY_INTERVAL_MISMATCH",
            "visible history duration must be an exact base-interval multiple",
            status_code=422,
            details={"base_interval_ms": interval_ms},
        )
    return max(
        request.indicator_warmup_bars,
        visible.duration_ms // interval_ms,
    )


def adapter_config(
    request: TrainingRunCreateRequest,
    *,
    warmup_bars: int | None = None,
) -> ReplaySessionConfig:
    return ReplaySessionConfig(
        protocol=REPLAY_PROTOCOL,
        source_kind=(
            SourceKind.BAR
            if request.source_kind is ReplaySource.BAR
            else SourceKind.AGG_TRADE
        ),
        exchange=request.exchange,
        market_type=request.market_type,
        symbol=request.symbol,
        base_interval=request.base_interval,
        # Phase 3 keeps the adapter projection at the atomic base interval.
        # Mutable display projection lives in replay_training_viewer_state.
        display_interval=request.base_interval,
        start_policy=(
            StartPolicy.MANUAL
            if request.start_mode is StartMode.MANUAL
            else StartPolicy.RANDOM_ELIGIBLE
        ),
        requested_start_ms=request.requested_start_ms,
        warmup_bars=(
            request.indicator_warmup_bars if warmup_bars is None else warmup_bars
        ),
        horizon_ms=request.forward_cache_ms,
        random_seed=0 if request.random_seed is None else request.random_seed,
        quality_mode=QualityMode.EXACT,
        blind_mode=(request.time_disclosure_policy is not TimeDisclosurePolicy.NONE),
        initial_equity=request.initial_equity,
        quote_asset=request.settlement_asset,
        execution_model=ExecutionModel.PAPER_LINEAR_V1,
        fee_model=FeeModel(request.maker_fee_bps, request.taker_fee_bps),
        slippage_model=SlippageModel(
            SlippageKind.FIXED_BPS,
            request.market_slippage_bps,
        ),
        max_leverage=request.max_leverage,
        pause_on_controller_loss=True,
        position_mode=request.position_mode.value,
    )


def catalog_identity_key(entry: Mapping[str, object]) -> tuple[str, str, str]:
    identity = entry.get("identity")
    if not isinstance(identity, Mapping):
        return ("", "", "")
    return (
        str(identity.get("exchange", "")),
        str(identity.get("market_type", "")),
        str(identity.get("symbol", "")),
    )


def market_start_compatibility(
    entry: Mapping[str, object],
    committed_start_ms: int,
) -> dict[str, object]:
    interval = entry.get("selected_base_interval")
    if not isinstance(interval, str):
        return {
            "state": "UNSUPPORTED",
            "code": "MARKET_MODE_INCOMPATIBLE",
            "message": "当前训练参数没有可用的精确基础周期。",
        }
    interval_ms = parse_interval_ms(interval)
    if interval_ms is None:
        return {
            "state": "UNSUPPORTED",
            "code": "START_NOT_ALIGNED",
            "message": "本局固定开始时间无法对齐该商品的基础周期。",
        }
    raw_ranges = entry.get("eligible_ranges")
    within_range_but_unaligned = False
    if isinstance(raw_ranges, list):
        for raw_range in raw_ranges:
            if not isinstance(raw_range, Mapping):
                continue
            first = raw_range.get("first_start_ms")
            last = raw_range.get("last_start_ms")
            step = raw_range.get("interval_ms")
            if (
                isinstance(first, int)
                and not isinstance(first, bool)
                and isinstance(last, int)
                and not isinstance(last, bool)
                and isinstance(step, int)
                and not isinstance(step, bool)
                and step > 0
                and first <= committed_start_ms <= last
            ):
                if (committed_start_ms - first) % step == 0:
                    return {
                        "state": "READY",
                        "code": "TIME_COMPATIBLE",
                        "message": "该商品支持本局已冻结的开始时间。",
                    }
                within_range_but_unaligned = True
    if within_range_but_unaligned:
        return {
            "state": "UNSUPPORTED",
            "code": "START_NOT_ALIGNED",
            "message": "本局固定开始时间无法对齐该商品的基础周期。",
        }
    bounds = entry.get("bounds")
    earliest = bounds.get("earliest_open_ms") if isinstance(bounds, Mapping) else None
    if isinstance(earliest, int) and committed_start_ms < earliest:
        return {
            "state": "UNSUPPORTED",
            "code": "MARKET_NOT_LISTED_AT_START",
            "message": "本局开始时该商品尚未上市或尚无历史数据。",
        }
    return {
        "state": "UNSUPPORTED",
        "code": "MARKET_COVERAGE_INSUFFICIENT",
        "message": "该商品在本局固定开始时间缺少预热、连续历史或前向覆盖。",
    }


def progressive_admission_settings(setup, initial_horizon_ms):
    settings = setup.to_dict()
    if initial_horizon_ms is not None:
        if (
            type(initial_horizon_ms) is not int
            or initial_horizon_ms < 60_000
            or initial_horizon_ms % 60_000
            or initial_horizon_ms > settings["forward_cache_ms"]
            or settings["source_kind"] != "BAR"
            or settings["start_mode"] != "MANUAL"
        ):
            raise TrainingRunError(
                "PROGRESSIVE_PREPARATION_INVALID",
                "progressive admission requires a fixed BAR start and aligned initial range",
                status_code=422,
            )
        # Admission needs only the published prefix. Persist the original
        # setup and use its full range for account/dependency commitments.
        settings = {**settings, "forward_cache_ms": initial_horizon_ms}
    return settings


def setup_market_compatibility(
    settings: Mapping[str, object],
    entry: Mapping[str, object],
    *,
    capability_admission: Mapping[tuple[str, str, str], _MarketSetupAdmission],
    committed_start_ms: int | None,
) -> dict[str, object]:
    identity = entry.get("identity")
    exchange = (
        str(identity.get("exchange", "")) if isinstance(identity, Mapping) else ""
    )
    market_type = (
        str(identity.get("market_type", "")) if isinstance(identity, Mapping) else ""
    )
    if settings.get("position_mode") == "HEDGE" and (
        exchange != "binance" or market_type != "futures"
    ):
        return {
            "state": "UNSUPPORTED",
            "code": "HEDGE_BINANCE_USDM_REQUIRED",
            "message": "双向持仓当前只支持 Binance futures（USD-M 线性合约）。",
        }
    if settings.get("book_mode") == "BOOK_ASSISTED_REQUIRED" and (
        exchange != "binance" or market_type != "futures"
    ):
        return {
            "state": "UNSUPPORTED",
            "code": "BOOK_BINANCE_USDM_REQUIRED",
            "message": "历史盘口辅助当前只支持 Binance futures（USD-M）。",
        }
    identity_key = (exchange, market_type, str(identity.get("symbol", "")))
    admission = capability_admission.get(identity_key)
    requires_local_capability = (
        settings.get("book_mode") == "BOOK_ASSISTED_REQUIRED"
        or settings.get("account_data_mode") == "HISTORICAL_EXACT"
    )
    if requires_local_capability and admission is None:
        return {
            "state": "UNSUPPORTED",
            "code": "REQUIRED_HISTORY_UNAVAILABLE",
            "message": ("该商品缺少本局要求的完整精确账户历史或连续历史盘口。"),
        }
    interval_ms = parse_interval_ms(str(entry.get("selected_base_interval", "")))
    required_span_ms = int(settings.get("forward_cache_ms", 0))
    book_interval_ms = (
        interval_ms
        if settings.get("book_mode") == "BOOK_ASSISTED_REQUIRED"
        and interval_ms is not None
        else 0
    )
    if (
        admission is not None
        and committed_start_ms is not None
        and not any(
            first <= committed_start_ms <= last
            for first, last in admission.eligible_start_windows(
                required_span_ms,
                book_interval_ms=book_interval_ms,
            )
        )
    ):
        return {
            "state": "UNSUPPORTED",
            "code": admission.code,
            "message": admission.message,
        }
    return {
        "state": "READY",
        "code": "SETUP_COMPATIBLE",
        "message": "该商品支持本局已选择的账户与执行模式。",
    }


def setup_admission_cache_key(
    settings: Mapping[str, object],
) -> control_rules_ops._SetupAdmissionCacheKey:
    return (
        str(settings.get("book_mode", "")),
        str(settings.get("account_data_mode", "")),
        str(settings.get("position_mode", "")),
        str(settings.get("funding_mode", "")),
        str(settings.get("settlement_asset", "")),
    )


def eligible_source_ranges(
    entries: Sequence[Mapping[str, object]],
    *,
    range_start_ms: int,
    range_end_ms: int,
    settings: Mapping[str, object],
    capability_admission: Mapping[tuple[str, str, str], _MarketSetupAdmission],
) -> list[tuple[int, int, int]]:
    candidate_ranges: list[tuple[int, int, int]] = []
    for entry in entries:
        identity = entry.get("identity")
        identity_key = (
            (
                str(identity.get("exchange", "")),
                str(identity.get("market_type", "")),
                str(identity.get("symbol", "")),
            )
            if isinstance(identity, Mapping)
            else ("", "", "")
        )
        admission = capability_admission.get(identity_key)
        interval_ms = parse_interval_ms(str(entry.get("selected_base_interval", "")))
        required_span_ms = int(settings.get("forward_cache_ms", 0))
        book_interval_ms = (
            interval_ms
            if settings.get("book_mode") == "BOOK_ASSISTED_REQUIRED"
            and interval_ms is not None
            else 0
        )
        capability_windows = (
            ((range_start_ms, range_end_ms),)
            if admission is None
            else admission.eligible_start_windows(
                required_span_ms,
                book_interval_ms=book_interval_ms,
            )
        )
        for eligible_range in cast(
            list[Mapping[str, object]], entry.get("eligible_ranges", [])
        ):
            source_first = int(eligible_range["first_start_ms"])
            source_last = int(eligible_range["last_start_ms"])
            source_interval_ms = int(eligible_range["interval_ms"])
            origin = int(eligible_range["first_start_ms"])
            for capability_first, capability_last in capability_windows:
                first = max(range_start_ms, source_first, capability_first)
                last = min(range_end_ms, source_last, capability_last)
                first += (-((first - origin) % source_interval_ms)) % source_interval_ms
                if first <= last:
                    candidate_ranges.append(
                        (
                            first,
                            source_interval_ms,
                            ((last - first) // source_interval_ms) + 1,
                        )
                    )
    return candidate_ranges


def public_time_commitment(
    commitment: Mapping[str, object],
    *,
    disclose_start: bool,
) -> dict[str, object]:
    return {
        "schema_version": "replay.time-commitment.v1",
        "start_mode": commitment["start_mode"],
        "committed": True,
        "committed_start_ms": (
            commitment["committed_start_ms"] if disclose_start else None
        ),
        "random_range_start_ms": (
            commitment["random_range_start_ms"] if disclose_start else None
        ),
        "random_range_end_ms": (
            commitment["random_range_end_ms"] if disclose_start else None
        ),
        "commitment_hash": commitment["commitment_hash"],
    }
