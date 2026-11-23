"""P0 financial oracles for ADR-BACKTEST-015 (unified strategy run model).

Every current execution path runs one fixed market scenario and one SMA-cross
strategy, and its signals, orders, fills and equity are pinned as digests in
``tests/fixtures/backtest/strategy_run_oracles/<path>.json``. Later migration
steps (P1-P6) must leave these digests unchanged unless the ADR records an
intended semantic change.

Regenerate deliberately, then review the JSON diff:

    CANDLESCOPE_UPDATE_STRATEGY_ORACLES=1 pytest tests/test_strategy_run_oracles*.py

The goldens only compare a path with itself. Paths report fills differently
(native Pine stamps the fill bar's open time in seconds; host kernels stamp the
bar's close event in milliseconds; costs differ per path), so cross-path
comparison belongs to the P1 run-result projection, not to these digests.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.backtest.identity import canonical_json, sha256_hex
from app.market_dataset.snapshot import MarketEvent
from app.simulation.trade_bar_builder import derive_complete_trade_bars

SCHEMA = "candlescope.strategy-run-oracle/1"
SCENARIO_ID = "swing-48m-aggtrade-v1"
UPDATE_ENV = "CANDLESCOPE_UPDATE_STRATEGY_ORACLES"
GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "backtest" / "strategy_run_oracles"

# One golden per execution path that exists on main@aae80d98 (ADR-BACKTEST-015 §6 P0).
# The continuous (FORWARD) path has no golden of its own: it must reproduce the
# fixed-history golden of the same provider exactly.
PATHS = {
    "host-bar-builtin": "Host BAR_APPROX kernel, builtin SMA cross provider",
    "host-bar-python": "Host BAR_APPROX kernel, SDK Python sma_cross template (TRUSTED_LOCAL)",
    "host-aggtrade-dual-clock": "Host AGG_TRADE_EXECUTION dual clock, builtin SMA cross provider",
    "host-pine-engine": "Host BAR_APPROX kernel, Pine engine provider (pine-engine-chart-v1)",
    "external-pine-feedback": "Pine engine decisions, CandleScope matching with account feedback (/backtests/external)",
    "native-pine": "Native Pine engine with its own account authority (/backtests/native)",
    # ADR-BACKTEST-015 P6e3: the practice account model, shared by forward runs and practice accounts.
    "host-practice-builtin": "Host PRACTICE clock (practice account model, 10x), builtin SMA cross provider",
    "host-practice-python": "Host PRACTICE clock (practice account model, 10x), SDK Python sma_cross template (TRUSTED_LOCAL)",
}

SMA_PARAMETERS = {"fast": 3, "slow": 5}
PINE_SMA_SOURCE = """//@version=6
strategy("Oracle SMA", initial_capital=10000)
fast = ta.sma(close, 3)
slow = ta.sma(close, 5)
if ta.crossover(fast, slow)
    strategy.entry("L", strategy.long, qty=1)
if ta.crossunder(fast, slow)
    strategy.close("L")
plot(fast)
plot(slow)
"""

_SWING = (100, 104, 108, 112, 110, 106, 102, 98, 96, 99, 103, 107, 110, 108, 104, 100)
MINUTES = 48
TRADES_PER_MINUTE = 4


def trades() -> tuple[MarketEvent, ...]:
    """Deterministic aggTrade tape: three swings of a 16-minute up/down cycle."""
    events: list[MarketEvent] = []
    sequence = 0
    for minute in range(MINUTES):
        start, end = _SWING[minute % len(_SWING)], _SWING[(minute + 1) % len(_SWING)]
        for step in range(TRADES_PER_MINUTE):
            sequence += 1
            price = start + (end - start) * step / TRADES_PER_MINUTE
            events.append(MarketEvent(
                sequence,
                minute * 60_000 + 5_000 + step * 12_000,
                "TRADES",
                {
                    "source_event_kind": "AGG_TRADE",
                    "source_sequence": 10_000 + sequence,
                    "tie_break": f"AGG_TRADE:{10_000 + sequence}",
                    "price": f"{price:.2f}",
                    "qty": "3",
                },
            ))
    return tuple(events)


def bars() -> tuple[MarketEvent, ...]:
    """Complete 1m bars derived from the tape (the last, unclosed minute is dropped)."""
    return derive_complete_trade_bars(trades(), "1m")


def _event_rows(events: tuple[MarketEvent, ...]) -> list[dict[str, Any]]:
    return [{"sequence": e.sequence, "event_time_ms": e.event_time_ms, "role": e.role,
             "payload": dict(e.payload)} for e in events]


def scenario() -> dict[str, Any]:
    tape, derived = trades(), bars()
    return {
        "id": SCENARIO_ID,
        "trades": len(tape),
        "bars": len(derived),
        "trades_digest": sha256_hex(_event_rows(tape)),
        "bars_digest": sha256_hex(_event_rows(derived)),
    }


def bars_csv() -> str:
    rows = [",".join(str(bar.payload[key]) for key in ("open_time_ms", "open", "high", "low", "close", "volume"))
            for bar in bars()]
    return "time,open,high,low,close,volume\n" + "\n".join(rows) + "\n"


def _digest(value: object) -> str:
    return "sha256:" + sha256_hex(value)


def _fill_row(fill: Mapping[str, Any]) -> str:
    """One readable line per fill so golden diffs stay reviewable."""
    return f"{fill['event_time_ms']} {fill['side']} {fill['qty']} @ {fill['price']} fee {fill['fee']}"


def _oracle(path: str, summary: Mapping[str, Any], digests: Mapping[str, Any]) -> dict[str, Any]:
    if path not in PATHS:
        raise KeyError(f"unknown oracle path {path!r}")
    return {
        "schema": SCHEMA,
        "path": path,
        "description": PATHS[path],
        "scenario": scenario(),
        "summary": dict(summary),
        "digests": dict(digests),
    }


def host_oracle(path: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Host-kernel result (service run or continuous kernel): HOST account authority."""
    fills = list(result["fills"])
    equity = list(result["equity_curve"])
    return _oracle(path, {
        "orders": len(result["orders"]),
        "fills": len(fills),
        "rejected": len(result.get("rejected") or ()),
        "final_equity": str(equity[-1]["equity"]) if equity else None,
        "final_position": str(equity[-1].get("position_qty")) if equity else None,
        "fill_rows": [_fill_row(f) for f in fills],
    }, {
        "decision_hash": result["decision_hash"],
        "fill_hash": result["fill_hash"],
        "ledger_hash": result["ledger_hash"],
        "orders": _digest(result["orders"]),
        "equity_curve": _digest(equity),
    })


def native_oracle(report: Mapping[str, Any]) -> dict[str, Any]:
    """Native Pine report: SCRIPT account authority, engine-owned orders and equity."""
    equity = list(report["equity"])
    trades_ = list(report["trades"])
    return _oracle("native-pine", {
        "account_authority": report["account_authority"],
        "orders": len(report["orders"]),
        "trades": len(trades_),
        "final_equity": equity[-1]["value"] if equity else None,
        "trade_rows": [f"{t['entryTime']}s -> {t['exitTime']}s qty {t['qty']} {t['entryPrice']} -> {t['exitPrice']}"
                       f" profit {t['profit']}" for t in trades_],
    }, {
        "orders": _digest(report["orders"]),
        "trades": _digest(trades_),
        "position": _digest(report["position"]),
        "equity": _digest(equity),
        "plots": _digest(report["graphics"]),
    })


ACCOUNT_FIELDS = ("position_qty", "quote_balance", "equity", "fees_paid", "entry_price")


def external_oracle(report: Mapping[str, Any]) -> dict[str, Any]:
    """Pine decisions matched by CandleScope: HOST account authority, Pine feedback."""
    equity = list(report["equity"])
    fills = list(report["trades"])
    account = {key: report["position"].get(key) for key in ACCOUNT_FIELDS}
    return _oracle("external-pine-feedback", {
        "account_authority": report["account_authority"],
        "orders": len(report["orders"]),
        "fills": len(fills),
        "closed_trades": len(report["closed_trades"]),
        "final_equity": equity[-1]["value"] if equity else None,
        "fill_rows": [_fill_row(f) for f in fills],
    }, {
        "orders": _digest(report["orders"]),
        "fills": _digest(fills),
        "closed_trades": _digest(report["closed_trades"]),
        "account": _digest(account),
        "equity": _digest(equity),
        "plots": _digest(report["graphics"]),
    })


def golden_path(path: str) -> Path:
    return GOLDEN_DIR / f"{path}.json"


def load_golden(path: str) -> dict[str, Any]:
    target = golden_path(path)
    if not target.is_file():
        pytest.fail(f"missing oracle golden {target.name}; generate it with {UPDATE_ENV}=1 and review the diff",
                    pytrace=False)
    return json.loads(target.read_text(encoding="utf-8"))


def assert_oracle(oracle: Mapping[str, Any]) -> None:
    """Compare with the committed golden, or rewrite it when explicitly requested."""
    path = str(oracle["path"])
    if os.environ.get(UPDATE_ENV) == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path(path).write_text(
            json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    golden = load_golden(path)
    if golden.get("scenario") != oracle["scenario"]:
        pytest.fail(f"{path}: the oracle scenario changed; regenerate every golden on purpose", pytrace=False)
    changed = sorted(key for key in set(golden["digests"]) | set(oracle["digests"])
                     if golden["digests"].get(key) != oracle["digests"].get(key))
    assert canonical_json(golden) == canonical_json(dict(oracle)), (
        f"{path}: financial oracle changed ({', '.join(changed) or 'summary only'}). "
        "If ADR-BACKTEST-015 records this change, regenerate with "
        f"{UPDATE_ENV}=1 and commit the reviewed diff.\n"
        f"golden summary:  {json.dumps(golden.get('summary'), sort_keys=True)}\n"
        f"current summary: {json.dumps(oracle['summary'], sort_keys=True)}"
    )


# Frontend contract fixtures: the backend's run-result/1 projection of an oracle run,
# parsed by the frontend runResult and StrategyDataManager tests. Kept equal to the live projection.
FRONTEND_FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures" / "run-result"


def assert_frontend_fixture(name: str, projected: Mapping[str, Any], *, kind: str = "run-result") -> None:
    """Keep a frontend contract fixture equal to what the backend serves (``kind`` names its directory)."""
    directory = FRONTEND_FIXTURES.parent / kind
    target = directory / f"{name}.{kind}.json"
    text = json.dumps(projected, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get(UPDATE_ENV) == "1":
        directory.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return
    if not target.is_file():
        pytest.fail(f"missing frontend fixture {target.name}; generate it with {UPDATE_ENV}=1", pytrace=False)
    assert json.loads(target.read_text(encoding="utf-8")) == json.loads(text), (
        f"{target.name} no longer matches the backend projection; regenerate with {UPDATE_ENV}=1")
