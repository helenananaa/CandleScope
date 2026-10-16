"""Journal rules: phases, revision coalescing, locked risk and hindsight flags.

A trade note is one template document with append-only revisions. Its stage is
not chosen by the user; it follows from when each revision was saved relative
to the linked trade (before the first fill, while open, after flat). That gives
the "written after entry" label without a separate workflow and lets the risk
plan be locked at the first fill.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .models import dec_str
from .trades import Trade

# Autosave updates the latest revision in place inside this window, but never
# across a phase boundary, so what existed before entry stays provable.
COALESCE_WINDOW_MS = 120_000
RISK_FIELDS = ("entryPrice", "stopPrice", "targetPrice", "riskUsdt")


def phase_at(ts_ms: int, trade: Trade | None) -> str:
    if trade is None or ts_ms <= trade.opened_at_ms:
        return "pre"
    if trade.closed_at_ms is None or ts_ms <= trade.closed_at_ms:
        return "open"
    return "post"


def should_coalesce(latest: dict[str, Any] | None, now: int, trade: Trade | None) -> bool:
    if latest is None:
        return False
    saved = int(latest["saved_at_ms"])
    return now - saved <= COALESCE_WINDOW_MS and phase_at(saved, trade) == phase_at(now, trade)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def locked_plan(revisions: list[dict[str, Any]], trade: Trade | None) -> dict[str, Any] | None:
    """Risk fields as they stood at the first fill; None if nothing was planned."""
    if trade is None:
        return None
    before = [rev for rev in revisions if int(rev["saved_at_ms"]) <= trade.opened_at_ms]
    if not before:
        return None
    fields = before[-1]["fields"]
    plan = {key: _decimal(fields.get(key)) for key in RISK_FIELDS}
    if all(value is None for value in plan.values()):
        return None
    return {
        "lockedAtMs": int(before[-1]["saved_at_ms"]),
        **{key: dec_str(value) for key, value in plan.items()},
    }


def field_timing(revisions: list[dict[str, Any]], trade: Trade | None) -> dict[str, dict[str, Any]]:
    timing: dict[str, dict[str, Any]] = {}
    previous: dict[str, str] = {}
    for rev in revisions:
        saved = int(rev["saved_at_ms"])
        for key, value in rev["fields"].items():
            if key not in timing:
                timing[key] = {
                    "firstWrittenMs": saved,
                    "lastChangedMs": saved,
                    "phase": phase_at(saved, trade),
                }
            elif previous.get(key) != value:
                timing[key]["lastChangedMs"] = saved
        previous = dict(rev["fields"])
    return timing


def trade_metrics(trade: Trade, plan: dict[str, Any] | None) -> dict[str, Any]:
    risk = _decimal(plan.get("riskUsdt")) if plan else None
    entry = _decimal(plan.get("entryPrice")) if plan else None
    stop = _decimal(plan.get("stopPrice")) if plan else None
    target = _decimal(plan.get("targetPrice")) if plan else None
    metrics: dict[str, Any] = {
        "riskUsdt": dec_str(risk),
        "netR": None,
        "plannedRewardRisk": None,
        "entrySlippage": None,
    }
    if risk is not None and risk > 0 and trade.status == "closed":
        metrics["netR"] = dec_str((trade.net_pnl / risk).quantize(Decimal("0.01")))
    if entry is not None and stop is not None and target is not None and entry != stop:
        metrics["plannedRewardRisk"] = dec_str(
            (abs(target - entry) / abs(entry - stop)).quantize(Decimal("0.01"))
        )
    avg = trade.avg_entry_price
    if entry is not None and avg is not None:
        # Positive = paid more than planned (long) or received less (short).
        metrics["entrySlippage"] = dec_str((avg - entry) * trade.sign)
    return metrics
