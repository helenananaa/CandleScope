"""Transactional persistence for a shared multi-market BAR interval."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext

from ..canonical import canonical_json, canonical_sha256
from .account import InstrumentRule, isolated_margin_key
from .multi_interval import IntervalLeg, ordered_equity_summary
from .multitrack import StableMarketEvent, stable_market_event_order


def record_portfolio_point(
    store, connection, *, run_id, session_id, actual_time_ms, sequence
):
    """Keep exact fallback/financial boundary observations between intervals."""
    if run_id in getattr(store, "_tape_interval_active", ()):
        return
    if any(
        plan["run_id"] == run_id
        for plan in getattr(store, "_multi_interval_plans", {}).values()
    ):
        return
    cache = getattr(store, "_portfolio_summary_runs", None)
    if cache is None:
        cache = store._portfolio_summary_runs = {}
    if run_id not in cache:
        cache[run_id] = (
            connection.execute(
                "SELECT 1 FROM replay_multi_bar_interval WHERE run_id=? LIMIT 1",
                (run_id,),
            ).fetchone()
            is not None
        )
    if not cache[run_id]:
        return
    row = connection.execute(
        "SELECT current_equity FROM replay_training_run WHERE run_id=?", (run_id,)
    ).fetchone()
    previous = connection.execute(
        "SELECT summary_json FROM replay_multi_bar_interval WHERE run_id=? ORDER BY end_time_ms DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    equity = str(row[0])
    if previous is not None and Decimal(json.loads(previous[0])["last"]) == Decimal(
        equity
    ):
        return
    dataset = connection.execute(
        "SELECT actual_replay_start_ms,synthetic_origin_ms FROM replay_dataset_ref WHERE session_id=?",
        (session_id,),
    ).fetchone()
    at = (
        actual_time_ms
        if dataset[1] is None
        else actual_time_ms - dataset[0] + dataset[1]
    )
    summary = {
        "schema": "portfolio-interval-summary.v1",
        "first": equity,
        "last": equity,
        "peak": equity,
        "trough": equity,
        "max_drawdown": "0",
        "trough_time_ms": at,
        "events": 0,
        "integer_path": True,
    }
    basis = {
        "schema": "portfolio-point.v1",
        "time_ms": at,
        "start_time_ms": at,
        "end_time_ms": at,
        "equity": equity,
    }
    connection.execute(
        "INSERT INTO replay_multi_bar_interval VALUES (?,?,?,?,?,?)",
        (
            run_id,
            "point:" + str(sequence),
            at,
            at,
            canonical_json(summary),
            canonical_json(basis),
        ),
    )


def portfolio_price_rows(path, checksum, first, last):
    import sqlite3
    import zlib
    from .hedge_inputs import _read_verified_public_events
    from .public_price_blocks import read_price_blocks, prepare_price_blocks

    try:
        return read_price_blocks(path, checksum, first, last)
    except (sqlite3.Error, OSError, ValueError, TypeError, zlib.error):
        descriptor, archived = _read_verified_public_events(path)
        if descriptor.checksum_sha256 != checksum:
            raise ValueError("portfolio input revision changed")
        if not 0 <= first <= last <= len(archived):
            raise ValueError("portfolio input range changed")
        try:
            prepare_price_blocks(path, checksum, archived, force=True)
        except (sqlite3.Error, OSError):
            pass  # A read-only owner can still use the verified legacy input.
        return [
            (
                e.event_time_ms,
                e.event_phase,
                e.event_kind,
                e.event_sequence,
                e.payload.get("mark_price"),
            )
            for e in archived[first:last]
        ]


def reconstruct_portfolio_interval(basis, *, input_root, limit=5000, bucket_ms=60000):
    """Reconstruct requested committed portfolio points from pinned inputs.

    This runs only in the caller's history/export worker, outside the writer.
    It never stores or prepares future per-minute account snapshots.
    """
    from pathlib import Path

    if (
        type(limit) is not int
        or not 1 <= limit <= 5000
        or type(bucket_ms) is not int
        or bucket_ms < 0
    ):
        raise ValueError("invalid portfolio interval query")
    if basis.get("schema") == "multi-tape-interval.v1":
        from .tape_interval import reconstruct
        return reconstruct(basis, limit=limit, bucket_ms=bucket_ms)
    if basis.get("schema") == "portfolio-point.v1":
        equity, at = basis["equity"], basis["time_ms"]
        return {
            "schema": "portfolio-interval-summary.v1",
            "first": equity,
            "last": equity,
            "peak": equity,
            "trough": equity,
            "max_drawdown": "0",
            "trough_time_ms": at,
            "events": 0,
            "integer_path": True,
            "points": [(at, equity)],
        }

    if (
        basis.get("schema") != "multi-bar-interval.v1"
        or not 1 <= limit <= 5000
        or bucket_ms < 0
    ):
        raise ValueError("invalid portfolio interval query")
    root = Path(input_root).resolve()
    events, prices = [], {}
    for track in basis["tracks"]:
        path = (root / track["public_path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("portfolio input reference escaped its owner")
        first, last = track["mark_start"], track["mark_end"]
        source = portfolio_price_rows(path, track["public_checksum"], first, last)
        prices[track["track_id"]] = Decimal(track["initial_mark"])
        for event_time, phase, kind, sequence, price in source:
            timestamp = event_time - basis["actual_delta"]
            if (
                kind != "MARK_INDEX"
                or phase != 30
                or not basis["start_time_ms"] < timestamp <= basis["end_time_ms"]
            ):
                raise ValueError(
                    "portfolio interval contains an interaction or unrevealed event"
                )
            events.append(
                (
                    timestamp,
                    phase,
                    track["track_id"],
                    sequence,
                    Decimal(price),
                )
            )
    legs = [
        IntervalLeg(
            leg["track_id"],
            leg["side"],
            Decimal(leg["quantity"]),
            Decimal(leg["entry"]),
            InstrumentRule.from_mapping(leg["rule"]),
        )
        for leg in basis["legs"]
    ]
    timestamps = sorted({event[0] for event in events})
    buckets = {}
    for timestamp in timestamps:
        buckets[timestamp if bucket_ms == 0 else timestamp // bucket_ms] = timestamp
    selected = set(list(buckets.values())[-limit:])
    return ordered_equity_summary(
        cash=Decimal(basis["cash"]),
        legs=legs,
        initial_prices=prices,
        events=events,
        sample_times=selected,
    )


async def risk_context(store, run_id, tracks, *, all_tracks=None):
    def read(connection):
        account = connection.execute(
            "SELECT * FROM replay_training_contract_account WHERE run_id=?", (run_id,)
        ).fetchone()
        run = connection.execute(
            "SELECT initial_equity FROM replay_training_run WHERE run_id=?", (run_id,)
        ).fetchone()
        if account is None or account["status"] != "ACTIVE":
            return None
        if connection.execute(
            "SELECT 1 FROM replay_training_liquidation_case WHERE run_id=? AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1",
            (run_id,),
        ).fetchone():
            return None
        fingerprint = store._hedge_risk_fingerprint(connection, run_id=run_id)
        if store._hedge_risk_fingerprints.get(run_id) != fingerprint:
            return None
        legs, prices, archives = [], {}, {}
        isolated = json.loads(account["isolated_margin_json"])
        for track in tracks:
            tid = track["track_id"]
            row = connection.execute(
                "SELECT rule_json FROM replay_training_instrument_rule WHERE run_id=? AND track_id=? ORDER BY revision DESC LIMIT 1",
                (run_id, tid),
            ).fetchone()
            if row is None:
                return None
            rule = InstrumentRule.from_mapping(json.loads(row[0]))
            binding = connection.execute(
                "SELECT b.*, a.local_path FROM replay_hedge_track_public_binding b JOIN replay_hedge_public_archive a ON a.archive_id=b.public_archive_id WHERE b.run_id=? AND b.track_id=?",
                (run_id, tid),
            ).fetchone()
            if binding is None or binding["status"] != "ACTIVE":
                return None
            archives[tid] = dict(binding)
            # Controller/recovery snapshots may leave the display quote empty
            # for a nested HEDGE position. Risk uses the pinned public mark,
            # not that optional quote or the broker's BAR-close proxy.
            projection = connection.execute(
                "SELECT * FROM replay_hedge_track_public_projection WHERE run_id=? AND track_id=?",
                (run_id, tid),
            ).fetchone()
            if projection is None:
                return None
            public_state = json.loads(projection["state_json"])
            material = {
                "schema_version": "replay.hedge-track-public-projection.v1",
                "run_id": run_id,
                "track_id": tid,
                "last_event_sequence": projection["last_event_sequence"],
                "as_of_actual_time_ms": projection["as_of_actual_time_ms"],
                "as_of_virtual_time_ms": projection["as_of_virtual_time_ms"],
                "state": public_state,
                "input_chain_hash": projection["input_chain_hash"],
            }
            if canonical_sha256(material) != projection["component_hash"]:
                return None
            mark = public_state.get("mark_index", {}).get("mark_price")
            if not isinstance(mark, str):
                return None
            prices[tid] = Decimal(mark)
            for key, side in (("long", "LONG"), ("short", "SHORT")):
                leg = track["position"][key]
                quantity = Decimal(leg["quantity"]).copy_abs()
                if quantity:
                    legs.append(
                        IntervalLeg(
                            tid,
                            side,
                            quantity,
                            Decimal(leg["entry_price"]),
                            rule,
                            Decimal(isolated.get(isolated_margin_key(tid, side), "0")),
                        )
                    )
        portfolio = store._portfolio_projection(
            initial_equity=run["initial_equity"],
            tracks=list(tracks if all_tracks is None else all_tracks),
        )
        with localcontext() as context:
            context.prec = 60
            cash = Decimal(portfolio["cash_balance"]) + Decimal(account["overlay_cash"])
        return dict(
            fingerprint=fingerprint,
            legs=tuple(legs),
            prices=prices,
            cash=cash,
            reserved=Decimal(portfolio["reserved_margin"]),
            margin_mode=account["margin_mode"],
            archives=archives,
        )

    return await store.base_store.run_extension_read(read)


def prepare_group(group, mutations):
    """Encode immutable candidate records before acquiring the SQLite writer."""
    for plan in group["tracks"]:
        indexed = mutations[plan["session_id"]].history_frames[0]["indexed"]
        plan.update(index=indexed["index"], start=indexed["start"], end=indexed["end"])
        plan["price_bounds"] = plan["index"].closes.range_bounds(start=plan["start"], end=plan["end"])
    group["summary_json"] = canonical_json(group["summary"])
    group["basis_json"] = canonical_json(group["basis"])
    selected = next(p for p in group["tracks"] if p["session_id"] == group["selected_session_id"])
    basis = selected["index"].curve_basis()
    group["curve_record"] = (canonical_sha256({"run": group["run_id"], "basis": basis}), canonical_json(basis))


def stage_track(
    store, connection, session_id, command, frames, state, components, previous, now
):
    plan = store._multi_interval_plans[session_id]
    if command["command_id"] != plan["command_id"]:
        raise ValueError("multi interval candidate identity mismatch")
    # A second unpublished phase may rebase its market view after the prefix.
    # Persist the exact index used by that actor, including its curve seed.
    frame_index = frames[0]["indexed"]
    plan.update(index=frame_index["index"], start=frame_index["start"], end=frame_index["end"])
    for key in ("orders", "fills", "ledger", "closed_trades", "warnings"):
        if components.get(key) != previous.get(key):
            raise ValueError("multi interval contained a trading interaction")
    index = plan["index"]
    bounds = (
        plan["price_bounds"]
        if "price_bounds" in plan
        else index.closes.range_bounds(start=plan["start"], end=plan["end"])
    )
    store._sync_session_summary(
        connection,
        session_id,
        state,
        components,
        previous,
        now,
        recorded_history=True,
        equity_samples={},
        phase_summary=plan["projection_summary"],
        revealed_price_bounds=bounds,
    )
    plan["state"], plan["frame"] = state, frames[0]


def finish_group(store, connection, group):
    now = store.base_store._validated_now_ms()
    run_id = group["run_id"]
    stable = []
    for plan in group["tracks"]:
        first, last = plan["first_mark"], plan["last_mark"]
        if first is not None:
            projection = connection.execute(
                "SELECT last_event_sequence,input_chain_hash FROM replay_hedge_track_public_projection WHERE run_id=? AND track_id=?",
                (run_id, plan["track_id"]),
            ).fetchone()
            if (
                projection["last_event_sequence"] + 1 != first.event_sequence
                or projection["input_chain_hash"] != first.previous_hash
            ):
                raise ValueError("multi interval mark prefix changed")
            connection.execute(
                "INSERT INTO replay_hedge_mark_span VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    plan["track_id"],
                    first.event_sequence,
                    last.event_sequence,
                    first.previous_hash,
                    last.event_hash,
                    first.source_id,
                ),
            )
            connection.execute(
                "UPDATE replay_hedge_track_public_projection SET last_event_sequence=?,input_chain_hash=? WHERE run_id=? AND track_id=?",
                (last.event_sequence - 1, last.previous_hash, run_id, plan["track_id"]),
            )
            stable.extend(
                store._apply_hedge_public_mark_batch(
                    connection,
                    run_id=run_id,
                    events=(last,),
                    virtual_times_ms=(last.event_time_ms - group["actual_delta"],),
                    track_id=plan["track_id"],
                    now_ms=now,
                )
            )
        state = plan["state"]
        stable.append(
            StableMarketEvent(
                actual_event_time_ms=group["target"] + group["actual_delta"],
                event_phase=20,
                market_track_stable_id=plan["track_id"],
                source_sequence=state["source_sequence"],
            )
        )
    store._apply_hedge_mark_projection(connection, run_id=run_id, now_ms=now)
    store._detect_contract_liquidations(
        connection,
        run_id=run_id,
        now_ms=now,
        trigger_virtual_time_ms=group["target"],
        refresh_current_equity=True,
        record_valuation_history=False,
    )
    if connection.execute(
        "SELECT 1 FROM replay_training_liquidation_case WHERE run_id=? AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1",
        (run_id,),
    ).fetchone():
        raise ValueError("multi interval violated the portfolio envelope")
    # Risk projection above has refreshed equity from the aligned pinned marks.
    # Retain the legacy last-staged actor's summary revision without valuing
    # eight partially updated portfolios on the way to this phase boundary.
    connection.execute(
        "UPDATE replay_training_run SET summary_revision=? WHERE run_id=?",
        (group["projection_summary"].last_revision, run_id),
    )
    # Stable events and their review anchors become visible with every actor.
    ordered = stable_market_event_order(stable)
    store._record_global_events_in_transaction(
        connection, run_id=run_id, ordered=ordered, materialize_portfolio=False
    )
    connection.execute(
        "INSERT INTO replay_multi_bar_interval(run_id,command_id,start_time_ms,end_time_ms,summary_json,basis_json) VALUES (?,?,?,?,?,?)",
        (
            run_id,
            group["command_id"],
            group["start_time"],
            group["target"],
            group["summary_json"],
            group["basis_json"],
        ),
    )
    # Preserve the existing selected-adapter equity API independently from the
    # portfolio summary. The latter must never be substituted for this series.
    plan = next(
        plan
        for plan in group["tracks"]
        if plan["session_id"] == group["selected_session_id"]
    )
    index, state = plan["index"], plan["state"]
    curve_id, curve_json = group["curve_record"]
    connection.execute(
        "INSERT OR IGNORE INTO replay_prepared_curve VALUES (?,?,?)",
        (curve_id, run_id, curve_json),
    )
    curve = dict(
        schema="indexed-curve.v1",
        curve_id=curve_id,
        start=plan["start"],
        end=plan["end"],
        session_id=plan["session_id"],
        revision_base=state["revision"] - (plan["end"] - plan["start"]),
        policy=group["policy"],
        revealed=state["revealed"],
        created_at_ms=now,
    )
    connection.execute(
        "INSERT INTO replay_interval_curve(run_id,command_id,end_sequence,samples_json,start_sequence,start_time_ms,end_time_ms) VALUES (?,?,?,?,?,?,?)",
        (
            run_id,
            group["command_id"],
            state["source_sequence"],
            canonical_json(curve),
            index.start + plan["start"] + 1,
            index.times[plan["start"]],
            index.times[plan["end"] - 1],
        ),
    )
    group["stable"] = tuple(ordered)
    group["fingerprint_after"] = store._hedge_risk_fingerprint(
        connection, run_id=run_id
    )
    latest = next(
        p for p in group["tracks"] if p["session_id"] == group["selected_session_id"]
    )["state"]
    intent_plan = {
        "schema": "multi-bar-advance-intent.v1",
        "risk_fingerprint": group["fingerprint_after"],
        "latest_tracks": [
            {
                "session_id": p["session_id"],
                "state_hash": p["state"]["state_hash"],
                "source_sequence": p["state"]["source_sequence"],
                "virtual_time_ms": p["state"]["cursor"]["virtual_time_ms"],
            }
            for p in group["tracks"]
        ],
    }
    connection.execute(
        "UPDATE replay_training_advance_intent SET plan_json=?,latest_cursor_json=?,updated_at_ms=? WHERE run_id=? AND command_id=? AND status='RUNNING'",
        (
            canonical_json(intent_plan),
            canonical_json(
                {
                    "source_sequence": latest["source_sequence"],
                    "virtual_time_ms": latest["cursor"]["virtual_time_ms"],
                    "revision": latest["revision"],
                }
            ),
            now,
            run_id,
            group["parent_command"].command_id,
        ),
    )
