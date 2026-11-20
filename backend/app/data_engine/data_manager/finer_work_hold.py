"""Hold a mixed chunk's targets while another chart still fetches finer history there.

The B conflicts of docs/architecture/MIXED_ROUTE_PLANNING_zh.md (§1, §10). A
cold 10007m chunk plans its newest targets from 1h and its target edges from
1m, while the short charts open beside it (89m, 97m, 101m) are fetching every
1m row of the same days. Their writes land in the windows the chunk captured,
so the chunk's write is rejected. Their 1m also refines the 1h spans it
planned, so the retry needs more rows than one chunk may plan and is split.
Either way those targets can only be composed once the finer rows are stored.

So, before a qualified mixed chunk is dispatched, the scheduler asks which of
its targets another chart's unfinished foreground chunk may write into. Those
targets are split off, one per chunk, and wait until that work has finished
(at most MAX_HOLD_SECONDS); the chunk's other targets run at once. The newest
chunk of a mixed chart's initial history first waits SETTLE_SECONDS for the
charts opened with it. A held target then plans over the stored finer rows
like any later chunk, under every fence unchanged. Mixed chunks never hold
another chunk, so holds cannot wait on each other.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.data_engine.backfill.source_router import MAX_USDM_ARCHIVE_OBJECT_ROWS
from app.data_engine.interval_policy import parse_interval_ms
from app.data_engine.series_identity import identity_from_metadata

ENABLED = True
# A held target runs as it would today once it has waited this long.
MAX_HOLD_SECONDS = 60.0
# Charts opened together reach the scheduler tens of milliseconds apart (30-77
# ms on the four-chart bench). A mixed chart's newest initial-history chunk
# waits this long after its request first comes up for dispatch, so the finer
# charts beside it are queued before it decides what to hold; arriving first,
# it would otherwise run before any overlap is known.
SETTLE_SECONDS = 0.25
SETTLE_REASONS = frozenset({"initial_history"})
DAY = 86_400_000
_UTC = timezone.utc


def family(request) -> tuple[str, str, str] | None:
    """The symbol a chunk's rows belong to; None for a non-default series identity (never held or holding)."""
    identity = identity_from_metadata(request.exchange, request.metadata)
    if identity is not None and not identity.is_legacy_default_for(request.exchange):
        return None
    return request.exchange, request.market_type, request.symbol


def holdable_width(request) -> int | None:
    """The target width of a qualified mixed chunk, or None when this rule never holds it."""
    if not request.metadata.get("required_history_composition"):
        return None
    width = parse_interval_ms(request.interval)
    return width if width and request.end_ms >= request.start_ms and family(request) is not None else None


def reach(request) -> tuple[int, int, int] | None:
    """(width, lo, hi): where another chart's chunk may write, [lo, hi); None when it never holds a mixed chunk.

    Its target range, widened to the archive objects its base interval may
    import: whole UTC months where a month of the base fits one object, else
    whole UTC days. It holds only mixed chunks wider than ``width``. A chunk's
    request does not change, so the scheduler computes this once per chunk.
    """
    if request.metadata.get("required_history_composition") or family(request) is None:
        return None
    width = parse_interval_ms(request.interval)
    plan = request.metadata.get("interval_work_plan")
    base_interval = plan.get("base_interval") if isinstance(plan, dict) else None
    base = parse_interval_ms(base_interval or request.interval)
    if not width or not base or request.end_ms < request.start_ms:
        return None
    lo, hi = request.start_ms, request.end_ms + width
    if 31 * DAY // base <= MAX_USDM_ARCHIVE_OBJECT_ROWS:
        return width, _month_start(lo), _next_month(hi - 1)
    return width, lo // DAY * DAY, (hi - 1) // DAY * DAY + DAY


def partition(request, reaches) -> list[tuple[int, int, bool]] | None:
    """The chunk's targets as (first, last, held) ranges, or None when none is held.

    Each held target is a range of its own (finer rows make one target as
    large as a whole cold chunk); consecutive free targets stay together.
    """
    width = holdable_width(request)
    if width is None or not reaches:
        return None
    ranges: list[tuple[int, int, bool]] = []
    for at in range(request.start_ms, request.end_ms + 1, width):
        held = any(lo < at + width and at < hi for lo, hi in reaches)
        if not held and ranges and not ranges[-1][2]:
            ranges[-1] = (ranges[-1][0], at, False)
        else:
            ranges.append((at, at, held))
    return ranges if any(held for _, _, held in ranges) else None


def _month_start(ms: int) -> int:
    day = datetime.fromtimestamp(ms / 1000, tz=_UTC)
    return int(datetime(day.year, day.month, 1, tzinfo=_UTC).timestamp() * 1000)


def _next_month(ms: int) -> int:
    day = datetime.fromtimestamp(ms / 1000, tz=_UTC)
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return int(datetime(year, month, 1, tzinfo=_UTC).timestamp() * 1000)
