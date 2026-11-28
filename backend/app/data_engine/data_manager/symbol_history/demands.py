"""History demand for the per-symbol planner (ADR-DATA-001 §3.1, §6).

A demand says which target range a chart, study or stream needs, how urgent
it is and who owns it. The planner turns demands into source slots; the
owner decides when a demand ends. Registering the same demand again (a chart
polling ``/klines/latest`` or ``/klines/range``) changes nothing (§3.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DemandKind(str, Enum):
    """Why a range is wanted, from most to least urgent (§3.1)."""

    FORMING = "forming"            # closed components of an open target's current bucket
    FIRST_SCREEN = "first_screen"  # the newest count_back bars of a visible chart
    PAGE_BACK = "page_back"        # the page being scrolled into on the left
    VIEWPORT = "viewport"          # the rest of a visible range
    GAP_REPAIR = "gap_repair"      # a hole found inside stored history
    TAIL = "tail"                  # catching up to now after a pause
    PREFETCH = "prefetch"          # one page beyond the visible left edge


# Lower is more urgent. A viewport and a gap repair are equally urgent.
URGENCY: dict[DemandKind, int] = {
    DemandKind.FORMING: 0,
    DemandKind.FIRST_SCREEN: 1,
    DemandKind.PAGE_BACK: 2,
    DemandKind.VIEWPORT: 3,
    DemandKind.GAP_REPAIR: 3,
    DemandKind.TAIL: 4,
    DemandKind.PREFETCH: 5,
}

# How a piece of each kind enters the existing backfill path: the reason and
# scheduler priority (lower first). The router's urgent-demand rules
# (backfill/route_health.py: priority 25 or less) see the same urgency.
REQUEST_FIELDS: dict[DemandKind, tuple[str, int]] = {
    DemandKind.FORMING: ("visible_seed_gap", 5),
    DemandKind.FIRST_SCREEN: ("initial_history", 10),
    DemandKind.PAGE_BACK: ("visible_load_more", 20),
    DemandKind.VIEWPORT: ("visible_range_gap", 20),
    DemandKind.GAP_REPAIR: ("visible_range_gap", 20),
    DemandKind.TAIL: ("tail_gap", 25),
    DemandKind.PREFETCH: ("active_history_hydration", 90),
}

# Existing request reasons, for producers that still speak them.
_KIND_FOR_REASON: dict[str, DemandKind] = {
    "visible_seed_gap": DemandKind.FORMING,
    "initial_history": DemandKind.FIRST_SCREEN,
    "visible_load_more": DemandKind.PAGE_BACK,
    "visible_range_gap": DemandKind.VIEWPORT,
    "tail_gap": DemandKind.TAIL,
    "latest_refresh": DemandKind.TAIL,
    "active_history_hydration": DemandKind.PREFETCH,
    "full_subscription_warmup": DemandKind.PREFETCH,
}


def kind_for_reason(reason: str | None) -> DemandKind:
    """The most urgent kind among a (possibly ``+``-merged) request reason."""
    kinds = [_KIND_FOR_REASON[part] for part in str(reason or "").replace(" ", "").split("+")
             if part in _KIND_FOR_REASON]
    return min(kinds, key=URGENCY.__getitem__) if kinds else DemandKind.GAP_REPAIR


@dataclass(frozen=True, slots=True)
class DemandOwner:
    """Who holds a demand: a request's demand owner, a stream consumer or a target lifetime.

    ``scope`` and ``generation`` follow the coordinator's demand scopes: a
    newer generation of the same scope replaces the older one's demands (§6).
    """

    owner_id: str
    scope: str | None = None
    generation: int | None = None


@dataclass(frozen=True, slots=True)
class Demand:
    """A target range ``[start_ms, end_ms)`` one owner needs, by kind."""

    owner: DemandOwner
    target_interval: str
    start_ms: int
    end_ms: int
    kind: DemandKind

    def __post_init__(self) -> None:
        if type(self.start_ms) is not int or type(self.end_ms) is not int or self.start_ms >= self.end_ms:
            raise ValueError("demand needs an integer half-open range with start < end")
        if not isinstance(self.kind, DemandKind):
            raise ValueError("demand kind required")

    @property
    def key(self) -> tuple[DemandOwner, str, DemandKind]:
        """One owner holds at most one range per target interval and kind; a new one replaces it."""
        return self.owner, self.target_interval, self.kind

    @property
    def urgency(self) -> int:
        return URGENCY[self.kind]
