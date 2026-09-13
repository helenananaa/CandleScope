"""Deterministic execution-cost sensitivity from frozen Host decisions."""

from __future__ import annotations

from decimal import Decimal
from dataclasses import dataclass
from typing import Any, Mapping

from app.market_dataset.snapshot import MarketEvent, MarketDatasetError, sha256_hex
from app.core.config import getenv

from .dual_clock_kernel import DualClockSimulationKernel
from .execution_realism import EXECUTION_REALISM_V2
from .kernel import SimulationKernel, SimulationResult, _bar_decimal
from .linear_perp_account_v2 import LinearPerpetualAccountV2
from .trade_kernel import TradeSimulationKernel


def build_cost_sensitivity_matrix(
    kernel: SimulationKernel | TradeSimulationKernel | DualClockSimulationKernel,
    events: tuple[MarketEvent, ...],
    primary: SimulationResult,
    *, fast_bar: bool = True,
) -> dict[str, object]:
    """Replay immutable accepted decision intents without invoking the Provider."""

    if getattr(kernel, "execution_model_revision", None) != EXECUTION_REALISM_V2:
        return {}
    frozen = list(getattr(kernel, "frozen_intents", []))
    by_sequence = {
        int(item["sequence"]): [dict(intent) for intent in item.get("intents") or []]
        for item in frozen
    }

    def strategy(_visible: tuple[MarketEvent, ...], event: MarketEvent) -> list[dict]:
        return [dict(intent) for intent in by_sequence.get(event.sequence, [])]

    base_rate = Decimal(str(getattr(kernel, "participation_rate")))
    fused = None
    if (fast_bar and type(kernel) is SimulationKernel
            and getenv("BACKTEST_FUSED_BAR_SENSITIVITY_ENABLED", "1").strip() == "1"):
        replays = [
            _clone_kernel(kernel, _bar_sensitivity=True,
                          taker_fee_bps=kernel.taker_fee_bps * multiplier,
                          maker_fee_bps=kernel.maker_fee_bps * multiplier,
                          slippage_bps=kernel.slippage_bps * multiplier)
            for multiplier in (Decimal("1.25"), Decimal("1.5"))
        ]
        replays.append(_clone_kernel(kernel, _bar_sensitivity=True, participation_rate=base_rate / Decimal("2")))
        fused = iter(_run_bar_scenarios(replays, events, by_sequence))
    scenarios: list[dict[str, object]] = [
        _scenario_wire(
            "BASELINE",
            {
                "fee_multiplier": "1",
                "slippage_multiplier": "1",
                "latency_ms_delta": 0,
                "latency_events_delta": 0,
                "participation_rate": str(base_rate),
            },
            primary,
        )
    ]
    for name, multiplier in (
        ("COSTS_PLUS_25_PERCENT", Decimal("1.25")),
        ("COSTS_PLUS_50_PERCENT", Decimal("1.5")),
    ):
        replay = _clone_kernel(
            kernel, _bar_sensitivity=fast_bar,
            taker_fee_bps=getattr(kernel, "taker_fee_bps") * multiplier,
            maker_fee_bps=getattr(kernel, "maker_fee_bps") * multiplier,
            slippage_bps=getattr(kernel, "slippage_bps") * multiplier,
        )
        result = next(fused) if fused is not None else _run_scenario(replay, events, strategy)
        scenarios.append(
            _scenario_wire(
                name,
                {
                    "fee_multiplier": str(multiplier),
                    "slippage_multiplier": str(multiplier),
                    "latency_ms_delta": 0,
                    "latency_events_delta": 0,
                    "participation_rate": str(base_rate),
                },
                result,
            )
        )
    if isinstance(kernel, SimulationKernel):
        scenarios.append(
            {
                **_scenario_wire(
                    "LATENCY_PLUS_ONE_TIER",
                    {
                        "fee_multiplier": "1",
                        "slippage_multiplier": "1",
                        "latency_ms_delta": 0,
                        "latency_events_delta": 0,
                        "participation_rate": str(base_rate),
                    },
                    primary,
                ),
                "status": "NOT_APPLICABLE_BAR_CLOCK",
            }
        )
    else:
        replay = _clone_kernel(
            kernel, _bar_sensitivity=fast_bar,
            latency_ms=getattr(kernel, "latency_ms") + 100,
            latency_events=getattr(kernel, "latency_events") + 1,
        )
        result = _run_scenario(replay, events, strategy)
        scenarios.append(
            _scenario_wire(
                "LATENCY_PLUS_ONE_TIER",
                {
                    "fee_multiplier": "1",
                    "slippage_multiplier": "1",
                    "latency_ms_delta": 100,
                    "latency_events_delta": 1,
                    "participation_rate": str(base_rate),
                },
                result,
            )
        )
    lower_rate = base_rate / Decimal("2")
    replay = _clone_kernel(kernel, _bar_sensitivity=fast_bar, participation_rate=lower_rate)
    result = next(fused) if fused is not None else _run_scenario(replay, events, strategy)
    scenarios.append(
        _scenario_wire(
            "PARTICIPATION_DOWN_ONE_TIER",
            {
                "fee_multiplier": "1",
                "slippage_multiplier": "1",
                "latency_ms_delta": 0,
                "latency_events_delta": 0,
                "participation_rate": str(lower_rate),
            },
            result,
        )
    )
    payload = {
        "schemaVersion": "candlescope.cost-sensitivity/1",
        "purpose": "ROBUSTNESS_CHECK_NOT_PARAMETER_TUNING",
        "decision_source": "FROZEN_PRIMARY_HOST_INTENTS",
        "included_in_primary_config_hash": False,
        "scenarios": scenarios,
    }
    return {**payload, "matrix_hash": "sha256:" + sha256_hex(payload)}


def _scenario_wire(
    name: str, assumptions: Mapping[str, object], result: SimulationResult | _SensitivityResult
) -> dict[str, object]:
    account = dict(result.ledger.get("account") or {})
    wire = {
        "name": name,
        "status": "COMPLETED",
        "assumptions": dict(assumptions),
        "metrics": {
            "fill_count": len(result.fills),
            "fee_total": str(result.ledger.get("fee_total") or "0"),
            "ending_equity": str(account.get("equity") or "0"),
            "open_order_count": int(result.ledger.get("open_order_count") or 0),
        },
        "hashes": {
            "fill": result.fill_hash,
            "ledger": result.ledger_hash,
        },
    }
    return {**wire, "scenario_hash": "sha256:" + sha256_hex(wire)}


def _clone_kernel(kernel: Any, *, _bar_sensitivity=False, **overrides: object) -> Any:
    common = {
        "account_model": kernel.account_model,
        "funding_mode": kernel.funding_mode,
        "leverage": kernel.leverage,
        "host_policy_revision": kernel.host_policy_revision,
        "slippage_bps": kernel.slippage_bps,
        "taker_fee_bps": kernel.taker_fee_bps,
        "maker_fee_bps": kernel.maker_fee_bps,
        "funding_rate": kernel.funding_rate,
        "funding_interval_ms": kernel.funding_interval_ms,
        "initial_balance": kernel.initial_balance,
        "execution_model_revision": kernel.execution_model_revision,
        "participation_rate": kernel.participation_rate,
        "latency_ms": kernel.latency_ms,
        "latency_events": kernel.latency_events,
        "order_end_policy": kernel.order_end_policy,
        "equity_curve_event_interval": kernel.equity_curve_event_interval,
    }
    common.update(overrides)
    if isinstance(kernel, DualClockSimulationKernel):
        return DualClockSimulationKernel(
            signal_interval=kernel.signal_interval,
            gap_policy=kernel.gap_policy,
            max_events=kernel.max_events,
            checkpoint_event_interval=0,
            **common,
        )
    if isinstance(kernel, TradeSimulationKernel):
        return TradeSimulationKernel(
            max_events=kernel.max_events,
            checkpoint_event_interval=0,
            **common,
        )
    kind = _BarSensitivityKernel if _bar_sensitivity and type(kernel) is SimulationKernel else SimulationKernel
    return kind(
        price_tick=kernel.price_tick,
        qty_step=kernel.qty_step,
        min_notional=kernel.min_notional,
        gap_policy=kernel.gap_policy,
        fill_policy=kernel.fill_policy,
        bar_path_scenario=kernel.bar_path_scenario,
        **common,
    )


@dataclass(frozen=True)
class _SensitivityResult:
    fills: list
    ledger: dict
    fill_hash: str
    ledger_hash: str


class _BarSensitivityKernel(SimulationKernel):
    """Same execution/account engine, only the evidence consumed by the matrix."""
    def run(self, *args, **kwargs):
        raise TypeError("use run_sensitivity; this kernel does not produce a full run report")

    def snapshot(self):
        raise TypeError("sensitivity-only execution has no resumable checkpoint")

    def _record_decision(self, intents, market_event):
        self._decision_count += 1

    def _record_equity(self, market_event):
        pass

    def _append_terminal_curve_point(self):
        pass

    def run_sensitivity(self, events, strategy):
        self._run_events(events, strategy, finalize=True)
        return self.sensitivity_result()

    def sensitivity_result(self):
        fills, ledger = self._financial_result()
        return _SensitivityResult(fills, ledger, sha256_hex(fills), sha256_hex(ledger))


class _SharedBarPrices:
    """Lazy immutable Decimal inputs; capacity and accounting stay per scenario."""
    def __init__(self, event):
        self.payload = event.payload
        self.values = {}

    def __call__(self, name):
        if name not in self.values:
            raw = self.payload.get(name) or "0" if name == "volume" else self.payload[name]
            self.values[name] = Decimal(str(raw))
        return self.values[name]


def _run_bar_scenarios(replays, events, by_sequence):
    """Advance owned independent accounts on one shared source clock.

    These clones have identical gap/account policies, no provider or external
    callbacks, and only consume frozen intents. Financial operations continue
    to use the reference funding, matching, enqueue and finalization methods.
    """
    clock = replays[0]
    account_v2 = isinstance(clock.account, LinearPerpetualAccountV2)
    funding = clock.funding_rate != 0 and clock.funding_interval_ms > 0
    if account_v2:
        funding = funding and clock.funding_mode == "FIXED_SCENARIO"
    for event in events:
        if clock.paused:
            break
        ambiguity_before = clock.ambiguity_count
        accepted = clock._accept_event(event)
        gap_ambiguity = clock.ambiguity_count - ambiguity_before
        for replay in replays[1:]:
            replay._last_event = clock._last_event
            replay.paused = clock.paused
            replay.ambiguity_count += gap_ambiguity
        if not accepted:
            continue
        if event.role in {"INSTRUMENT_RULES", "MARK_INDEX", "FUNDING"}:
            for replay in replays:
                replay.account.apply(event)
            continue
        if event.role != "BARS":
            raise MarketDatasetError("BAR kernel received unsupported role", code="FIDELITY_MISLABEL")
        count = clock._market_event_count + 1
        market_event = (MarketEvent(count, event.event_time_ms, event.role, event.payload)
                        if account_v2 else event)
        close = None if account_v2 else _bar_decimal(event, "close")
        intents = by_sequence.get(market_event.sequence)
        prices = None
        for replay in replays:
            replay._market_event_count = count
            if account_v2:
                replay.account.validate_ready()
            else:
                replay.account.mark = close
            if funding:
                replay._apply_funding(market_event)
            # No code outside these owned clones can mutate the order index.
            if replay._active_orders:
                if prices is None:
                    prices = _SharedBarPrices(market_event)
                replay._match(market_event, _prices=prices)
            replay._decision_count += 1
            if intents:
                replay._enqueue_many(intents, current_sequence=market_event.sequence)
    for replay in replays:
        replay.finalize_orders()
    return [replay.sensitivity_result() for replay in replays]


def _run_scenario(kernel, events, strategy):
    if isinstance(kernel, _BarSensitivityKernel):
        return kernel.run_sensitivity(events, strategy)
    return kernel.run(events, strategy, warmup_events=0, finalize=True)
