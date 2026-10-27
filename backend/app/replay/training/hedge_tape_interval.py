"""Order-free tape ranges bounded by the next pinned HEDGE input.

Trade prices build candles and broker excursions. Portfolio valuation retains
the already committed public mark, independently for both position legs. Every
public/simulation input (including unchanged marks) remains an exact boundary.
"""

from . import control_rules
from .hedge_timeline import IndexedHedgeSnapshot
from .multi_interval import safe_envelope
from .multi_interval_store import risk_context
from .tape_phases import refuse


async def prepare_context(
    owner, *, run_id, binding, tracks, current, target, runtime_snapshot
):
    if not isinstance(runtime_snapshot, IndexedHedgeSnapshot) or binding.get(
        "funding_mode"
    ) not in {"OFF", "HISTORICAL_EXACT"}:
        return refuse(owner.store, "hedge_input_mode")
    public, simulation = await owner.hedge_inputs._projection_cursors(run_id)
    delta = control_rules.actual_event_time_ms(binding, target) - target
    next_input = runtime_snapshot.next_time(public, simulation, target + delta)
    if next_input is not None:
        target = min(target, next_input - delta - 1)
    if target <= current:
        return refuse(owner.store, "hedge_next_input")
    all_tracks = await owner.store.get_market_track_heads(run_id)
    full_ids = {t["track_id"] for t in tracks}
    if {
        t["track_id"] for t in all_tracks if t["subscription_tier"] == "FULL"
    } != full_ids:
        return refuse(owner.store, "hedge_full_tier")
    context = await risk_context(
        owner.store,
        run_id,
        [t for t in all_tracks if t["track_id"] in full_ids],
        all_tracks=all_tracks,
    )
    if context is None:
        return refuse(owner.store, "hedge_risk_context")
    if not safe_envelope(
        cash=context["cash"],
        legs=context["legs"],
        bounds={tid: (p, p) for tid, p in context["prices"].items()},
        margin_mode=context["margin_mode"],
        reserved_margin=context["reserved"],
    ):
        return refuse(owner.store, "hedge_unsafe_envelope")
    for archive in context["archives"].values():
        # A bound at or behind the cursor no longer limits the range. As on
        # the exact path, that leg keeps its committed public mark, and
        # next_time above still stops before any later event in its lane.
        end = archive["bound_range_end_ms"] - delta
        if end > current:
            target = min(target, end)
    return {
        **context,
        "initial_prices": context["prices"],
        "target": target,
        "valuation": "PINNED_HEDGE_MARK",
        "input_cursors": (public, simulation),
    }


def validate_input_cursors(connection, run_id, expected):
    public = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT track_id,last_event_sequence FROM replay_hedge_track_public_projection WHERE run_id=?",
            (run_id,),
        )
    }
    simulation = connection.execute(
        "SELECT last_event_sequence FROM replay_hedge_input_projection WHERE run_id=? AND source_kind='SIMULATION'",
        (run_id,),
    ).fetchone()
    return simulation is not None and (public, int(simulation[0])) == expected
