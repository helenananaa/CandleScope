"""P6a kernel baselines for ADR-BACKTEST-015 (matching kernel convergence).

P6 folds the three Pine-specific bar kernels (``PineBarKernel``, ``PineChartBarKernel``,
``PineV2BarKernel``) into the one Host bar kernel. Its gate is that every account
model x fill clock keeps its P0 digests. The path oracles (``strategy_run_oracles``)
cover one account model per run path; these baselines cover the kernels themselves:
every bar-family fill clock with every account model it accepts, one scripted order
flow (market entries, OCO brackets, stop-limit breakouts, resting limits, shorts on
perpetuals), and the checkpoint payloads that stored runs restore from.

Regenerate deliberately, then review the JSON diff:

    CANDLESCOPE_UPDATE_STRATEGY_ORACLES=1 pytest tests/test_kernel_baselines.py
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

from app.backtest.identity import canonical_json, sha256_hex
from app.market_dataset.snapshot import MarketEvent
from app.simulation.execution_realism import BAR_PATH_SCENARIO, EXECUTION_REALISM_V2, PINE_BAR_PATH_SCENARIO
from app.simulation.kernel import SimulationKernel
from app.simulation.pine_bar_kernel import PineBarKernel
from app.simulation.pine_chart_kernel import PineChartBarKernel
from app.simulation.pine_v2_bar_kernel import PineV2BarKernel
from tests.strategy_run_oracles import UPDATE_ENV, bars, scenario

SCHEMA = "candlescope.kernel-baseline/1"
GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "backtest" / "kernel_baselines"
CHECKPOINT_BAR = 20

PERP = "LINEAR_PERP_ONE_WAY_V1"
PERP_V2 = "LINEAR_PERP_ONE_WAY_V2"
SPOT = "SPOT_CASH_V1"
# Settings the Host passes for execution realism V2 (service._execution_kernel_kwargs).
# A 5% participation rate leaves under one unit per scenario bar (volume 12), so every order fills in parts.
REALISM = {"execution_model_revision": EXECUTION_REALISM_V2, "participation_rate": Decimal("0.05"),
           "equity_curve_event_interval": 100}

# clock -> (kernel class, extra settings, driver); each clock runs with every account model it accepts.
CLOCKS: dict[str, tuple[type, dict[str, Any], str]] = {
    "bar-worst-case": (SimulationKernel, {}, "bar"),
    "bar-worst-case-realism": (SimulationKernel, {**REALISM, "bar_path_scenario": BAR_PATH_SCENARIO}, "bar"),
    "pine-ohlc-path": (PineBarKernel, {}, "path"),
    "pine-chart-bar": (PineChartBarKernel, {}, "chart"),
    "pine-chart-bar-on-close": (PineChartBarKernel, {"process_orders_on_close": True}, "chart"),
    "pine-v2-path": (PineV2BarKernel, {}, "chart"),
    "pine-v2-path-realism": (PineV2BarKernel, {**REALISM, "bar_path_scenario": PINE_BAR_PATH_SCENARIO}, "chart"),
}
ACCOUNT_MODELS = (PERP, SPOT, PERP_V2)


def _order(kind: str, side: str, **fields: Any) -> dict[str, Any]:
    return {"type": kind, "side": side, "qty": "1",
            **{key: str(value) if isinstance(value, Decimal) else value for key, value in fields.items()}}


def scripted_strategy(*, shorts: bool) -> Callable[[tuple[MarketEvent, ...], MarketEvent], list[dict]]:
    """SMA(3)/SMA(5) crosses with brackets one bar after entry, tight brackets, stop-limit and limit entries.

    The script keeps its own intended position: orders are inputs, so a rejected or
    unfilled order only changes what the kernels report, never what is asked next.
    """
    closes: list[Decimal] = []
    state = {"long": False, "short": False, "bracket": None}

    def plan(_history: tuple[MarketEvent, ...], event: MarketEvent) -> list[dict]:
        payload = event.payload
        close, high, low = (Decimal(str(payload[key])) for key in ("close", "high", "low"))
        closes.append(close)
        index = len(closes)
        intents: list[dict] = []
        if state["bracket"] == "long":
            intents += [_order("LIMIT", "SELL", limit_price=close + 4, reduce_only=True, oco_group=f"long-{index}"),
                        _order("STOP", "SELL", stop_price=close - 3, reduce_only=True, oco_group=f"long-{index}")]
        elif state["bracket"] == "short":
            intents += [_order("LIMIT", "BUY", limit_price=close - 4, reduce_only=True, oco_group=f"short-{index}"),
                        _order("STOP", "BUY", stop_price=close + 3, reduce_only=True, oco_group=f"short-{index}")]
        state["bracket"] = None
        if index >= 6:
            fast, slow = sum(closes[-3:]) / 3, sum(closes[-5:]) / 5
            fast_before, slow_before = sum(closes[-4:-1]) / 3, sum(closes[-6:-1]) / 5
            if fast_before <= slow_before and fast > slow:
                if state["short"]:
                    intents.append(_order("MARKET", "BUY", reduce_only=True))
                intents.append(_order("MARKET", "BUY"))
                state.update(long=True, short=False, bracket="long")
            elif fast_before >= slow_before and fast < slow:
                if state["long"]:
                    intents.append(_order("MARKET", "SELL", reduce_only=True))
                state["long"] = False
                if shorts:
                    intents.append(_order("MARKET", "SELL"))
                    state.update(short=True, bracket="short")
        if index % 9 == 4 and (state["long"] or state["short"]):
            # A bracket tighter than one bar's range: both legs trade in the next bar, where the worst
            # case (stop first) and the Pine path (nearest extreme first) part ways.
            exit_side = "SELL" if state["long"] else "BUY"
            sign = 1 if state["long"] else -1
            intents += [_order("LIMIT", exit_side, limit_price=close + sign * Decimal("0.5"), reduce_only=True,
                               oco_group=f"tight-{index}"),
                        _order("STOP", exit_side, stop_price=close - sign * Decimal("0.5"), reduce_only=True,
                               oco_group=f"tight-{index}")]
        if index % 11 == 5:
            intents.append(_order("STOP_LIMIT", "BUY", stop_price=high + Decimal("0.5"), limit_price=high + 1))
        if index % 13 == 7:
            intents.append(_order("LIMIT", "BUY", limit_price=low - 1))
        return intents

    return plan


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _digest(value: Any) -> str:
    return "sha256:" + sha256_hex(_plain(value))


# The V2 perpetual account trades only with instrument rules and a mark price: one rule set,
# then a mark at every bar's open (inside that bar, as the Pine V2 path requires).
RULES = {"rule_version": "kernel-baseline", "contract_multiplier": "1", "price_tick": "0.01", "quantity_step": "0.001",
         "min_notional": "5", "maintenance_tiers": [
             {"notional_floor": "0", "notional_cap": "1000000", "maintenance_rate": "0.005", "maintenance_deduction": "0"}]}


def stream(account_model: str) -> tuple[MarketEvent, ...]:
    """The scenario bars, with the account events a V2 perpetual needs; sequences stay contiguous."""
    source = bars()
    if account_model != PERP_V2:
        return source
    rows: list[MarketEvent] = [MarketEvent(0, 0, "INSTRUMENT_RULES", dict(RULES))]
    for bar in source:
        open_ = str(bar.payload["open"])
        rows += [MarketEvent(0, int(bar.payload["open_time_ms"]), "MARK_INDEX", {"mark_price": open_, "index_price": open_}), bar]
    return tuple(replace(row, sequence=index) for index, row in enumerate(rows, 1))


def _drive(kernel: Any, driver: str, strategy: Callable, snapshots: list[Any]) -> Any:
    source = stream(kernel.account_model)
    checkpoint_sequence = [event for event in source if event.role == "BARS"][CHECKPOINT_BAR - 1].sequence

    def checkpoint(event: MarketEvent) -> None:
        if event.sequence == checkpoint_sequence:
            snapshots.append(_plain(kernel.snapshot()))

    if driver == "bar":
        return kernel.run(source, strategy, finalize=True, checkpoint_callback=checkpoint,
                          **({"close_callback": lambda *_: None} if kernel.process_orders_on_close else {}))
    if driver == "chart":
        return kernel.run(source, strategy, finalize=True, checkpoint_callback=checkpoint, fill_callback=lambda *_: [])
    # The external Pine clock (pine_bar_clock.run_bar_clock) walks each bar and enqueues at its close.
    for bar in source:
        kernel.walk_bar(bar, lambda point, bar=bar: kernel._enqueue_many(strategy((bar,), bar), current_sequence=point.sequence))
        checkpoint(bar)
    kernel.finalize_orders()
    return kernel.result()


def baseline(clock: str, account_model: str) -> dict[str, Any] | None:
    """One kernel run, or None when the clock refuses the account model (refusals are pinned separately)."""
    kernel_type, settings, driver = CLOCKS[clock]
    try:
        kernel = kernel_type(account_model=account_model, **settings)
    except Exception as exc:  # noqa: BLE001 - which combinations a clock refuses is itself baseline data
        return {"refused": f"{type(exc).__name__}: {getattr(exc, 'code', '')}".rstrip(": ")}
    snapshots: list[Any] = []
    result = _drive(kernel, driver, scripted_strategy(shorts=account_model != SPOT), snapshots)
    equity = list(result.equity_curve)
    fills = [_plain(fill) for fill in result.fills]
    return {
        "summary": {
            "kernel": kernel_type.__name__,
            "fill_policy": kernel.fill_policy,
            "orders": len(result.orders),
            "fills": len(fills),
            "rejected": len(result.rejected),
            "ambiguity": result.ambiguity_count,
            "final_equity": str(equity[-1].get("equity")) if equity else None,
            "fill_rows": [f"{fill['event_time_ms']} {fill['side']} {fill['qty']} @ {fill['price']} {fill['reason']}"
                          for fill in fills],
        },
        "digests": {
            "decision_hash": result.decision_hash,
            "fill_hash": result.fill_hash,
            "ledger_hash": result.ledger_hash,
            "report_hash": result.report_hash,
            "orders": _digest(result.orders),
            "rejected": _digest(result.rejected),
            "equity_curve": _digest(equity),
            "checkpoint": _digest(snapshots),
            "final_snapshot": _digest(kernel.snapshot()),
        },
    }


def case_name(clock: str, account_model: str) -> str:
    return f"{clock}.{account_model.lower().replace('_', '-')}"


def build(clock: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "clock": clock,
        "scenario": scenario(),
        "checkpoint_bar": CHECKPOINT_BAR,
        "accounts": {case_name(clock, model): baseline(clock, model) for model in ACCOUNT_MODELS},
    }


def golden_path(clock: str) -> Path:
    return GOLDEN_DIR / f"{clock}.json"


def assert_baseline(current: Mapping[str, Any]) -> None:
    """Compare with the committed golden, or rewrite it when explicitly requested."""
    clock = str(current["clock"])
    target = golden_path(clock)
    if os.environ.get(UPDATE_ENV) == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    if not target.is_file():
        pytest.fail(f"missing kernel baseline {target.name}; generate it with {UPDATE_ENV}=1 and review the diff",
                    pytrace=False)
    golden = json.loads(target.read_text(encoding="utf-8"))
    if golden.get("scenario") != current["scenario"]:
        pytest.fail(f"{clock}: the baseline scenario changed; regenerate every golden on purpose", pytrace=False)
    changed = sorted(
        f"{name}.{key}"
        for name in set(golden["accounts"]) | set(current["accounts"])
        for key in set((golden["accounts"].get(name) or {}).get("digests") or {})
        | set((current["accounts"].get(name) or {}).get("digests") or {})
        if ((golden["accounts"].get(name) or {}).get("digests") or {}).get(key)
        != ((current["accounts"].get(name) or {}).get("digests") or {}).get(key))
    assert canonical_json(golden) == canonical_json(dict(current)), (
        f"{clock}: kernel baseline changed ({', '.join(changed) or 'summary or refusals only'}). "
        "If ADR-BACKTEST-015 records this change, regenerate with "
        f"{UPDATE_ENV}=1 and commit the reviewed diff.")
