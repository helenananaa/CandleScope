"""Prepare selected review inputs outside connection-local persistence work."""

from __future__ import annotations

from app.replay.canonical import canonical_json, canonical_sha256

from .errors import TrainingRunError
from .persistence.hedge_review_fork import input_snapshot, selected_inputs


async def _prepare_selected_inputs(manager, run_binding, event_id):
    """Rebuild legacy prefixes outside the writer, using committed receipts only."""
    from .control_rules import actual_event_time_ms, virtual_event_time_ms
    from .hedge_inputs import _projection

    run_id = run_binding["run_id"]

    def read(connection):
        frozen = selected_inputs(connection, run_id, event_id)
        if frozen is not None:
            return frozen, None
        event = connection.execute(
            "SELECT * FROM replay_review_timeline_event WHERE run_id=? AND event_id=?",
            (run_id, event_id),
        ).fetchone()
        from .review import ReviewRecorder
        historical = ReviewRecorder.decode_event_projection(connection, event=event)
        rows = {name: [dict(r) for r in connection.execute(
            f"SELECT * FROM {name} WHERE run_id=?", (run_id,),
        )] for name in (
            "replay_hedge_input_applied_event", "replay_hedge_track_public_applied_event",
            "replay_hedge_mark_span", "replay_hedge_track_input_admission",
        )}
        return input_snapshot(connection, run_id), (historical, rows)

    frozen, legacy = await manager.store.run_extension_read(read)
    if legacy is None:
        return frozen
    historical, rows = legacy
    virtual = historical["cursor"]["virtual_time_ms"]
    actual = actual_event_time_ms(run_binding, virtual)
    public, simulation = await manager.runtime_snapshot(run_id)
    def rebuild():
        selected_ids = {t["track_id"] for t in historical["tracks"] if t["state_hash"] is not None}
        frozen["track_bindings"] = [b for b in frozen["track_bindings"] if b["track_id"] in selected_ids]

        def reconstruct(old, events, initial, applied, track_id=None):
            events = tuple(events)
            spans = [s for s in rows["replay_hedge_mark_span"]
                     if old.get("source_kind") != "SIMULATION" and s["track_id"] == (track_id or "track-1")]
            later_admissions = [a for a in rows["replay_hedge_track_input_admission"]
                                if a["track_id"] == (track_id or "track-1") and a["admitted_virtual_time_ms"] > virtual]
            committed = {r["event_sequence"] for r in applied if r["applied_virtual_time_ms"] <= virtual}
            for e in events:
                if (e.event_time_ms <= actual and e.event_sequence <= old["last_event_sequence"]
                        and any(s["first_sequence"] <= e.event_sequence <= s["last_sequence"] for s in spans)
                        and not any(a["first_sequence"] <= e.event_sequence <= a["last_sequence"] for a in later_admissions)):
                    committed.add(e.event_sequence)
            last = max(committed, default=initial)
            last = max(initial, last)
            prefix = [e for e in events if e.event_sequence <= last]
            if not prefix or prefix[-1].event_time_ms > actual:
                raise TrainingRunError("REVIEW_HEDGE_INPUT_SNAPSHOT_UNAVAILABLE",
                                       "legacy review input prefix is unavailable", status_code=409)
            as_of = max(frozen["binding"]["bound_range_start_ms"], prefix[-1].event_time_ms)
            rebuilt = _projection(prefix, source_kind=old.get("source_kind", "PUBLIC"),
                                  actual_time_ms=as_of, virtual_time_ms=virtual_event_time_ms(run_binding, as_of))
            payload = {"schema_version": "replay.hedge-input-projection.v1" if track_id is None else "replay.hedge-track-public-projection.v1",
                       "last_event_sequence": rebuilt.last_event_sequence,
                       "as_of_actual_time_ms": rebuilt.as_of_actual_time_ms,
                       "as_of_virtual_time_ms": rebuilt.as_of_virtual_time_ms,
                       "state": dict(rebuilt.state), "input_chain_hash": rebuilt.input_chain_hash}
            if track_id is None:
                payload["source_kind"] = old["source_kind"]
            else:
                payload.update(run_id=run_id, track_id=track_id)
            return {**old, **{k: v for k, v in payload.items() if k not in {"schema_version", "state"}},
                    "state_json": canonical_json(payload["state"]), "component_hash": canonical_sha256(payload)}

        for index, old in enumerate(frozen["projections"]):
            kind = old["source_kind"]
            events = [e for e in public if e.track_id == "track-1"] if kind == "PUBLIC" else simulation
            initial = max((e.event_sequence for e in events if e.event_time_ms <= frozen["binding"]["bound_range_start_ms"]), default=0)
            applied = [r for r in rows["replay_hedge_input_applied_event"] if r["source_kind"] == kind]
            frozen["projections"][index] = reconstruct(old, events, initial, applied)
        projections = {p["track_id"]: p for p in frozen["track_projections"]}
        frozen["track_projections"] = [reconstruct(
            projections[b["track_id"]], [e for e in public if e.track_id == b["track_id"]],
            b["initial_event_sequence"] if b["initial_event_sequence"] is not None else max(
                (e.event_sequence for e in public if e.track_id == b["track_id"]
                 and e.event_time_ms <= b["bound_range_start_ms"]), default=0,
            ),
            [r for r in rows["replay_hedge_track_public_applied_event"] if r["track_id"] == b["track_id"]], b["track_id"],
        ) for b in frozen["track_bindings"]]
        return frozen

    return await manager.store.run_worker("review_fork_inputs", rebuild)


async def prepare_selected_inputs(manager, run_binding, event_id):
    from .persistence.review_insurance import rebuild_funds
    from .review import ReviewRecorder

    frozen = await _prepare_selected_inputs(manager, run_binding, event_id)
    if frozen is None:
        return None
    run_id = run_binding["run_id"]

    def read(connection):
        event = connection.execute(
            "SELECT * FROM replay_review_timeline_event WHERE run_id=? AND event_id=?", (run_id, event_id),
        ).fetchone()
        historical = ReviewRecorder.decode_event_projection(connection, event=event)
        definitions = [dict(row) for row in connection.execute(
            "SELECT * FROM replay_training_insurance_fund WHERE run_id=? ORDER BY asset", (run_id,),
        )]
        if not definitions:
            # Old flat review forks omitted the untouched insurance wallet.
            # Its initial definition remains pinned by the simulation input.
            definitions = [dict(row) for row in connection.execute(
                "SELECT model_version,settlement_asset AS asset FROM replay_hedge_simulation_manifest "
                "WHERE manifest_id=?", (frozen["binding"]["simulation_manifest_id"],),
            )]
        postings = [dict(row) for row in connection.execute(
            "SELECT p.*,c.trigger_virtual_time_ms FROM replay_training_insurance_posting p "
            "JOIN replay_training_liquidation_case c USING(run_id,case_id) "
            "WHERE p.run_id=? ORDER BY p.asset,p.posting_sequence", (run_id,),
        )]
        return historical, definitions, postings

    historical, definitions, postings = await manager.store.run_extension_read(read)
    _, simulation = await manager.runtime_snapshot(run_id)
    frozen["insurance_funds"] = await manager.store.run_worker("review_fork_insurance", lambda: rebuild_funds(
        run_binding=run_binding, frozen=frozen, projection=historical,
        definitions=definitions, postings=postings, simulation=simulation,
    ))
    return frozen
