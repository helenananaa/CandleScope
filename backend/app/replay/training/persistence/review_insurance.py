"""Rebuild a fork's insurance wallet from its frozen input and posting prefix."""

from ..control_rules import virtual_event_time_ms
from ..hedge_inputs import _projection


def rebuild_funds(*, run_binding, frozen, projection, definitions, postings, simulation):
    start = frozen["binding"]["bound_range_start_ms"]
    selected = next(p for p in frozen["projections"] if p["source_kind"] == "SIMULATION")
    events = tuple(e for e in simulation if e.event_sequence <= selected["last_event_sequence"])
    initial = _projection(
        tuple(e for e in events if e.event_time_ms <= start), source_kind="SIMULATION",
        actual_time_ms=start, virtual_time_ms=virtual_event_time_ms(run_binding, start),
    )
    updates = [e for e in events if e.event_time_ms > start and e.event_kind == "INSURANCE_INPUT"]
    latest = updates[-1] if updates else None
    base = dict(initial.state["insurance"])
    base_hash = initial.input_chain_hash
    base_time = virtual_event_time_ms(run_binding, start)
    if latest is not None:
        base = dict(latest.payload)
        base_hash = latest.event_hash
        base_time = virtual_event_time_ms(run_binding, latest.event_time_ms)
    # Timeline identities, not source counters from a different market, bind
    # exactly which postings existed at the selected command boundary.
    posting_ids = {p["posting_id"] for case in projection["liquidations"]
                   for step in case["steps"] for p in step["insurance_postings"]}
    result = []
    for definition in definitions:
        prefix = [p for p in postings if p["asset"] == definition["asset"] and p["posting_id"] in posting_ids]
        subsequent = [p for p in prefix if p["trigger_virtual_time_ms"] >= base_time]
        tail = subsequent[-1] if subsequent else None
        result.append({
            **definition,
            "opening_balance": definition.get("opening_balance", initial.state["insurance"]["balance_after"]),
            "current_balance": base["balance_after"] if tail is None else tail["balance_after"],
            "ledger_tail_hash": base_hash if tail is None else tail["posting_hash"],
            "revision": len(updates) + len(prefix),
        })
    return result
