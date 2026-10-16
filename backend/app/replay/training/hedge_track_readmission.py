"""Catch up dormant, financially empty public input lanes before admission.

This uses the existing immutable mark-span contract. It never replays account
events against today's positions. Legacy unpublished source prefixes can be
reconstructed only behind the same financial-emptiness guard.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from decimal import Decimal

from app.replay.canonical import canonical_json, canonical_sha256

from .control_rules import actual_event_time_ms, virtual_event_time_ms
from .errors import TrainingRunError
from .multitrack import StableMarketEvent, stable_market_event_order

CURSOR_BEHIND = "HEDGE_INPUT_CURSOR_BEHIND_MARKET"


def _unavailable(message):
    return TrainingRunError(
        "HEDGE_TRACK_READMISSION_REQUIRES_REVIEW", message, status_code=409,
        details={"fallback_applied": False},
    )


def _assert_empty_since(connection, run_id, track_id, first_virtual_time):
    legs = connection.execute(
        "SELECT absolute_quantity FROM replay_training_position_leg WHERE run_id=? AND track_id=?",
        (run_id, track_id),
    ).fetchall()
    if any(Decimal(row[0]) != 0 for row in legs):
        raise _unavailable("a held HEDGE track cannot skip historical mark/risk events")
    for row in connection.execute(
        "SELECT order_json FROM replay_training_contract_order WHERE run_id=? AND track_id=?",
        (run_id, track_id),
    ):
        order = json.loads(row[0])
        if (order["status"] in {"NEW", "OPEN", "PARTIALLY_FILLED"}
                or int(order["created_time_ms"]) >= first_virtual_time):
            raise _unavailable("HEDGE orders overlap the missing public-input interval")
    if connection.execute(
        "SELECT 1 FROM replay_training_contract_fill WHERE run_id=? AND track_id=? "
        "AND CAST(json_extract(fill_json,'$.event_time_ms') AS INTEGER)>=? LIMIT 1",
        (run_id, track_id, first_virtual_time),
    ).fetchone():
        raise _unavailable("HEDGE fills overlap the missing public-input interval")


async def catch_up_public_marks(*, manager, binding, track_ids, target_virtual_time_ms,
                                recover_paused=False, store=None, replay_service=None):
    """Called under the run actor; prepare outside the writer, then recheck atomically."""
    run_id = str(binding["run_id"])
    if binding.get("position_mode") != "HEDGE":
        return
    target_actual = actual_event_time_ms(binding, target_virtual_time_ms)
    market_actual = target_actual
    recovery_checkpoint = None
    recovery_boundary = None
    recovery_tracks = ()
    recovery_events = []
    if recover_paused:
        checkpoint = await manager.store.run_extension_read(lambda connection: connection.execute(
            "SELECT * FROM replay_training_global_checkpoint WHERE run_id=? ORDER BY checkpoint_sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone())
        boundary = (virtual_event_time_ms(binding, binding["actual_replay_start_ms"])
                    if checkpoint is None else checkpoint["global_virtual_time_ms"])
        if boundary < target_virtual_time_ms:
            # A legacy batch may have persisted a revealed source prefix but
            # failed before publishing its global-event boundary. Reconstruct
            # those exact consumed events, never merely advance the input cursor.
            if store is None or replay_service is None or binding.get("source_kind") != "AGG_TRADE":
                raise _unavailable("an unfinished market cohort requires source-prefix recovery")
            recovery_checkpoint = checkpoint
            recovery_boundary = boundary
            checkpoint_tracks = ({} if checkpoint is None else
                                 {t["track_id"]: t for t in json.loads(checkpoint["tracks_json"])["tracks"]})
            if checkpoint is None and await manager.store.run_extension_read(lambda connection: connection.execute(
                "SELECT 1 FROM replay_training_global_event WHERE run_id=? LIMIT 1", (run_id,),
            ).fetchone()):
                raise _unavailable("global events lack a recoverable checkpoint")
            recovery_tracks = tuple(t for t in await store.get_market_track_heads(run_id)
                                    if t["subscription_tier"] == "FULL")
            for track in recovery_tracks:
                prior = checkpoint_tracks.get(track["track_id"])
                if checkpoint is not None and (prior is None or prior["adapter_session_id"] != track["adapter_session_id"]):
                    raise _unavailable("unfinished market recovery changed track topology")
                cursor = 0 if prior is None else int(prior["cursor"]["source_sequence"])
                end = int(track["cursor"]["source_sequence"])
                if not 0 <= end - cursor <= 8192:
                    raise _unavailable("unfinished market prefix exceeds bounded recovery")
                while cursor < end:
                    page = await replay_service.source_events_page(
                        str(track["adapter_session_id"]), after_sequence=cursor, limit=min(500, end-cursor),
                    )
                    if not page["events"] or page["revealed_sequence"] != end:
                        raise _unavailable("revealed source changed during market recovery")
                    for event in page["events"]:
                        if event["source_sequence"] != cursor + 1 or cursor >= end:
                            raise _unavailable("unfinished market source prefix is discontinuous")
                        if not boundary <= event["trade_time_ms"] <= target_virtual_time_ms:
                            raise _unavailable("unfinished market event is outside its committed prefix")
                        cursor += 1
                        recovery_events.append(StableMarketEvent(
                            actual_event_time_ms(binding, event["trade_time_ms"]), 20,
                            str(track["track_id"]), cursor,
                        ))
            # A mark at the partial market timestamp belongs after the *whole*
            # same-time cohort. Leave it to the ordinary coordinator on retry.
            target_actual -= 1
    plans = []
    for track_id in track_ids:
        row = await manager.store.run_extension_read(lambda connection: connection.execute(
            "SELECT b.*, a.local_path, a.health, a.generation, a.checksum_sha256, "
            "a.event_chain_tail FROM replay_hedge_track_public_binding b "
            "JOIN replay_hedge_public_archive a ON a.archive_id=b.public_archive_id "
            "WHERE b.run_id=? AND b.track_id=?", (run_id, track_id),
        ).fetchone())
        if row is None:
            raise _unavailable("HEDGE track requires a pinned public input before admission")
        if (row["status"] != "ACTIVE" and not (
                recover_paused and row["status"] == "PAUSED" and row["degraded_reason"] == CURSOR_BEHIND)):
            raise _unavailable("HEDGE track input is paused for another reason")
        if (row["health"] != "READY" or row["generation"] != row["public_generation"]
                or row["checksum_sha256"] != row["public_checksum_sha256"]
                or row["event_chain_tail"] != row["public_event_chain_tail"]
                or not row["bound_range_start_ms"] <= target_actual <= row["bound_range_end_ms"]):
            raise _unavailable("HEDGE track public binding changed or lacks coverage")
        path = await manager._guard_catalog_row(row, source_kind="PUBLIC")
        events = await manager._cached_verified_events(
            source_kind="PUBLIC", path=path, checksum_sha256=str(row["checksum_sha256"]), track_id=track_id,
        )
        projection = await manager.store.run_extension_read(lambda connection: connection.execute(
            "SELECT * FROM replay_hedge_track_public_projection WHERE run_id=? AND track_id=?",
            (run_id, track_id),
        ).fetchone())
        if projection is None:
            raise _unavailable("HEDGE track public projection is missing")
        start = bisect_right(events, projection["last_event_sequence"], key=lambda e: e.event_sequence)
        end = bisect_right(events, target_actual, key=lambda e: e.event_time_ms)
        missing = tuple(events[start:end])
        if not missing:
            continue
        if any(e.event_kind not in {"MARK_INDEX", "FUNDING", "RULE", "FEE_POLICY"} for e in missing):
            raise _unavailable("unsupported public event in HEDGE readmission")
        if store is None and any(e.event_kind != "MARK_INDEX" for e in missing):
            raise _unavailable("HEDGE public-input admission requires the account store")
        sequence, previous_hash = projection["last_event_sequence"], projection["input_chain_hash"]
        for event in missing:
            if event.event_sequence != sequence + 1 or event.previous_hash != previous_hash:
                raise _unavailable("HEDGE readmission marks are not contiguous")
            sequence, previous_hash = event.event_sequence, event.event_hash
        if recovery_boundary is not None:
            if missing[0].event_time_ms < actual_event_time_ms(binding, recovery_boundary):
                raise _unavailable("missing inputs precede the recoverable global boundary")
            recovery_events.extend(StableMarketEvent(e.event_time_ms, e.event_phase, e.stable_track_id, e.event_sequence)
                                   for e in missing)
        plans.append((track_id, projection, missing))

    if recover_paused:
        audit = await manager.audit_run(run_id)
        if audit["status"] != "PASS":
            raise _unavailable("paused HEDGE inputs failed their pinned-source audit")
        _, _, simulation = await manager._binding_rows(run_id)
        path = await manager._guard_catalog_row(simulation, source_kind="SIMULATION")
        events = await manager._cached_verified_events(
            source_kind="SIMULATION", path=path, checksum_sha256=str(simulation["checksum_sha256"]),
        )
        _, cursor = await manager._projection_cursors(run_id)
        if any(e.event_sequence > cursor and e.event_time_ms < market_actual for e in events):
            raise _unavailable("account-level simulation inputs require ordered recovery")

    if not plans and not recover_paused:
        return

    def write(connection):
        now = manager.store._validated_now_ms()
        if recovery_boundary is not None:
            current_checkpoint = connection.execute(
                "SELECT * FROM replay_training_global_checkpoint WHERE run_id=? ORDER BY checkpoint_sequence DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if ((None if current_checkpoint is None else dict(current_checkpoint))
                    != (None if recovery_checkpoint is None else dict(recovery_checkpoint))):
                raise _unavailable("global checkpoint changed during market recovery")
            for track in recovery_tracks:
                head = connection.execute(
                    "SELECT source_sequence,virtual_time_ms,subscription_tier FROM replay_training_market_track WHERE run_id=? AND track_id=?",
                    (run_id, track["track_id"]),
                ).fetchone()
                if (head["source_sequence"] != track["cursor"]["source_sequence"]
                        or head["virtual_time_ms"] != target_virtual_time_ms or head["subscription_tier"] != "FULL"):
                    raise _unavailable("market cursor changed during source-prefix recovery")
                _assert_empty_since(connection, run_id, str(track["track_id"]),
                                    recovery_boundary)
        if recover_paused:
            rows = connection.execute(
                "SELECT status,degraded_reason FROM replay_hedge_input_binding WHERE run_id=? "
                "UNION ALL SELECT status,degraded_reason FROM replay_hedge_track_public_binding WHERE run_id=?",
                (run_id, run_id),
            ).fetchall()
            if not rows or any(r["status"] != "PAUSED" or r["degraded_reason"] != CURSOR_BEHIND for r in rows):
                raise _unavailable("HEDGE pause reason changed during recovery")
        ordered_inputs = []
        for track_id, original, missing in plans:
            first, last = missing[0], missing[-1]
            current = connection.execute(
                "SELECT * FROM replay_hedge_track_public_projection WHERE run_id=? AND track_id=?",
                (run_id, track_id),
            ).fetchone()
            if dict(current) != dict(original):
                raise _unavailable("HEDGE input cursor changed during admission")
            state = json.loads(current["state_json"])
            material = {
                "schema_version": "replay.hedge-track-public-projection.v1",
                "run_id": run_id, "track_id": track_id,
                "last_event_sequence": current["last_event_sequence"],
                "as_of_actual_time_ms": current["as_of_actual_time_ms"],
                "as_of_virtual_time_ms": current["as_of_virtual_time_ms"],
                "state": state, "input_chain_hash": current["input_chain_hash"],
            }
            if canonical_sha256(material) != current["component_hash"]:
                raise _unavailable("HEDGE input projection failed its digest check")
            _assert_empty_since(connection, run_id, track_id, virtual_event_time_ms(binding, first.event_time_ms))
            if any(e.event_kind != "MARK_INDEX" for e in missing):
                if track_id == "track-1":
                    fees = [e for e in missing if e.event_kind == "FEE_POLICY"]
                    if fees:
                        # The primary fee affects every market. Never rewrite
                        # fees underneath an order/fill from the missed period.
                        for other in connection.execute(
                            "SELECT track_id FROM replay_training_market_track WHERE run_id=?", (run_id,),
                        ):
                            _assert_empty_since(connection, run_id, str(other[0]),
                                                virtual_event_time_ms(binding, fees[0].event_time_ms))
                ordered_inputs.extend(missing)
                if recovery_boundary is None:
                    connection.execute("INSERT INTO replay_hedge_track_input_admission VALUES (?,?,?,?,?)", (
                        run_id, track_id, first.event_sequence, last.event_sequence, target_virtual_time_ms,
                    ))
                continue
            connection.execute("INSERT INTO replay_hedge_mark_span VALUES (?,?,?,?,?,?,?)", (
                run_id, track_id, first.event_sequence, last.event_sequence,
                first.previous_hash, last.event_hash, first.source_id,
            ))
            state["mark_index"] = dict(last.payload)
            material.update(last_event_sequence=last.event_sequence, as_of_actual_time_ms=last.event_time_ms,
                            as_of_virtual_time_ms=virtual_event_time_ms(binding, last.event_time_ms),
                            input_chain_hash=last.event_hash)
            values = (last.event_sequence, last.event_time_ms, material["as_of_virtual_time_ms"],
                      canonical_json(state), last.event_hash)
            connection.execute(
                "UPDATE replay_hedge_track_public_projection SET last_event_sequence=?,as_of_actual_time_ms=?,"
                "as_of_virtual_time_ms=?,state_json=?,input_chain_hash=?,component_hash=?,updated_at_ms=? "
                "WHERE run_id=? AND track_id=?", (*values, canonical_sha256(material), now, run_id, track_id),
            )
            if track_id == "track-1":
                compatibility = {k: v for k, v in material.items() if k not in {"run_id", "track_id"}}
                compatibility.update(schema_version="replay.hedge-input-projection.v1", source_kind="PUBLIC")
                connection.execute(
                    "UPDATE replay_hedge_input_projection SET last_event_sequence=?,as_of_actual_time_ms=?,"
                    "as_of_virtual_time_ms=?,state_json=?,input_chain_hash=?,component_hash=?,updated_at_ms=? "
                    "WHERE run_id=? AND source_kind='PUBLIC'", (*values, canonical_sha256(compatibility), now, run_id),
                )
        if recover_paused:
            for table in ("replay_hedge_input_binding", "replay_hedge_track_public_binding"):
                connection.execute(f"UPDATE {table} SET status='ACTIVE',degraded_reason=NULL,updated_at_ms=? WHERE run_id=?", (now, run_id))
            connection.execute("UPDATE replay_training_run SET compatibility='READY',updated_at_ms=? WHERE run_id=?", (now, run_id))
        if ordered_inputs:
            ordered_inputs.sort(key=lambda e: (e.event_time_ms, e.event_phase, e.stable_track_id, e.event_sequence))
            store._hedge_input_write_operation(
                run_id, events=ordered_inputs, virtual_time_ms=target_virtual_time_ms,
                event_virtual_times_ms=tuple(virtual_event_time_ms(binding, e.event_time_ms) for e in ordered_inputs),
            )(connection)
        if recovery_boundary is not None:
            # This is an exact revealed-prefix checkpoint, like SOURCE_EVENT,
            # not a claim that its last timestamp cohort has finished. The
            # next coordinator command drains the rest before post-market input.
            store._record_global_events_in_transaction(
                connection, run_id=run_id, ordered=stable_market_event_order(recovery_events),
                materialize_portfolio=False,
            )

    await manager.store.run_extension_write(write)
