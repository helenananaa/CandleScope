"""Aggregate statistics over the closed trades of one account.

Pure: the input is closed trades plus what the journal knows about each one
(locked risk, tags, when the plan was written). Stats never mix accounts, so
practice and real results stay apart.

Definitions:
- A win is net P&L (after fees) > 0, a loss < 0; win rate counts break-even
  trades in the denominator.
- Profit factor = gross profit / |gross loss|; ``None`` when there is no loss
  (the client shows ∞ if there was profit).
- Max drawdown is the largest fall from a running peak of cumulative net P&L
  in close order, starting from 0 before the first trade.
- R uses only trades with a locked risk (> 0 at the first fill). ``coverage``
  says what share that is, so R figures are never silently a subset.
  Expectancy is the mean net R (= win rate × avg win R + loss rate × avg
  loss R).
- R buckets are inclusive on the side away from zero: exactly −1R is a full
  1R loss (``-2 … -1``), exactly +2R reached 2R (``2 … 3``).
- Groups or metrics with fewer than ``LOW_SAMPLE_TRADES`` trades are flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Iterable

from .journal import PLAN_TIMINGS
from .models import dec_str
from .trades import Trade

ZERO = Decimal("0")
LOW_SAMPLE_TRADES = 20
# Edges between R buckets; the outer buckets are open-ended.
R_EDGES = (Decimal(-2), Decimal(-1), ZERO, Decimal(1), Decimal(2), Decimal(3))
DIRECTIONS = ("long", "short")

_MONEY = Decimal("0.00000001")
_RATIO = Decimal("0.0001")
_R = Decimal("0.01")
_TAG_SEPARATORS = re.compile(r"[,;，；、]")
MAX_TAG_LENGTH = 40


def journal_tags(entries: Iterable[dict[str, Any]], note_fields: dict[str, Any]) -> tuple[str, ...]:
    """A trade's tags: tags on its linked entries plus the note's strategy tag.

    The template's ``strategyTag`` text may hold several tags separated by
    commas; each counts on its own.
    """
    candidates = [tag for entry in entries for tag in entry.get("tags") or ()]
    candidates += _TAG_SEPARATORS.split(str(note_fields.get("strategyTag") or ""))
    tags: list[str] = []
    for candidate in candidates:
        tag = str(candidate).strip()[:MAX_TAG_LENGTH]
        if tag and tag not in tags:
            tags.append(tag)
    return tuple(tags)


@dataclass(frozen=True, slots=True)
class TradeFacts:
    trade: Trade
    risk: Decimal | None = None
    tags: tuple[str, ...] = ()
    plan_timing: str = "none"

    @property
    def net_r(self) -> Decimal | None:
        return None if self.risk is None else self.trade.net_pnl / self.risk


def _money(value: Decimal | None) -> str | None:
    return None if value is None else dec_str(value.quantize(_MONEY))


def _ratio(part: int, whole: int) -> str | None:
    return None if whole == 0 else dec_str((Decimal(part) / Decimal(whole)).quantize(_RATIO))


def _mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, ZERO) / len(values) if values else None


def _r(value: Decimal | None) -> str | None:
    return None if value is None else dec_str(value.quantize(_R))


def _r_block(rows: list[TradeFacts]) -> dict[str, Any]:
    values = [r for r in (row.net_r for row in rows) if r is not None]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    return {
        "count": len(values),
        "missing": len(rows) - len(values),
        "coverage": _ratio(len(values), len(rows)),
        "winRate": _ratio(len(wins), len(values)),
        "expectancyR": _r(_mean(values)),
        "avgWinR": _r(_mean(wins)),
        "avgLossR": _r(_mean(losses)),
        "totalR": _r(sum(values, ZERO)) if values else None,
        "lowSample": len(values) < LOW_SAMPLE_TRADES,
    }


def _core(rows: list[TradeFacts]) -> dict[str, Any]:
    nets = [row.trade.net_pnl for row in rows]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value < 0]
    gross_profit = sum(wins, ZERO)
    gross_loss = sum(losses, ZERO)
    return {
        "tradeCount": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(rows) - len(wins) - len(losses),
        "winRate": _ratio(len(wins), len(rows)),
        "avgWin": _money(_mean(wins)),
        "avgLoss": _money(_mean(losses)),
        "avgPnl": _money(_mean(nets)),
        "grossProfit": _money(gross_profit),
        "grossLoss": _money(gross_loss),
        "profitFactor": dec_str((gross_profit / -gross_loss).quantize(_R)) if gross_loss < 0 else None,
        "realizedPnl": _money(sum((row.trade.realized_pnl for row in rows), ZERO)),
        "fees": _money(sum((row.trade.fees for row in rows), ZERO)),
        "netPnl": _money(sum(nets, ZERO)),
        "lowSample": len(rows) < LOW_SAMPLE_TRADES,
        "r": _r_block(rows),
    }


def _max_drawdown(rows: list[TradeFacts]) -> dict[str, Any]:
    equity = peak = worst = ZERO
    peak_at: int | None = None
    start: int | None = None
    end: int | None = None
    for row in rows:
        equity += row.trade.net_pnl
        if equity > peak:
            peak, peak_at = equity, row.trade.closed_at_ms
        if peak - equity > worst:
            worst, start, end = peak - equity, peak_at, row.trade.closed_at_ms
    return {"amount": _money(worst), "peakAtMs": start, "troughAtMs": end}


def _bucket(value: Decimal) -> int:
    for index, edge in enumerate(R_EDGES):
        if value < edge or (value == edge and edge < 0):
            return index
    return len(R_EDGES)


def _distribution(rows: list[TradeFacts]) -> list[dict[str, Any]]:
    counts = [0] * (len(R_EDGES) + 1)
    for row in rows:
        value = row.net_r
        if value is not None:
            counts[_bucket(value)] += 1
    bounds = [None, *R_EDGES, None]
    return [
        {"fromR": dec_str(bounds[index]), "toR": dec_str(bounds[index + 1]), "count": count}
        for index, count in enumerate(counts)
    ]


def _groups(
    rows: list[TradeFacts],
    keys: Callable[[TradeFacts], Iterable[str | None]],
    order: Iterable[str | None] = (),
) -> list[dict[str, Any]]:
    grouped: dict[str | None, list[TradeFacts]] = {key: [] for key in order}
    for row in rows:
        for key in keys(row):
            grouped.setdefault(key, []).append(row)
    return [{"key": key, **_core(items)} for key, items in grouped.items()]


def _tag_groups(rows: list[TradeFacts]) -> list[dict[str, Any]]:
    groups = _groups(rows, lambda row: row.tags or (None,))
    # Most used first; untagged trades last.
    groups.sort(key=lambda group: (group["key"] is None, -group["tradeCount"], group["key"] or ""))
    return groups


def compute_stats(facts: Iterable[TradeFacts]) -> dict[str, Any]:
    rows = sorted(
        (row for row in facts if row.trade.closed_at_ms is not None),
        key=lambda row: (row.trade.closed_at_ms or 0, row.trade.id),
    )
    return {
        "lowSampleThreshold": LOW_SAMPLE_TRADES,
        **_core(rows),
        "maxDrawdown": _max_drawdown(rows),
        "rDistribution": _distribution(rows),
        "breakdowns": {
            "planTiming": _groups(rows, lambda row: (row.plan_timing,), PLAN_TIMINGS),
            "direction": _groups(rows, lambda row: (row.trade.direction,), DIRECTIONS),
            "tag": _tag_groups(rows),
        },
    }
