
"""Bounded tape intervals sharing a durable publication barrier.

ONE_WAY ranges prove a trade-price risk envelope. HEDGE ranges stop before the
next pinned input and prove both legs at their unchanged public marks. Both
retain exact source order, deferred curves and two complete-cohort review anchors;
an account interaction aborts the unpublished batch for the scalar coordinator.
"""

import json
from bisect import bisect_right
from decimal import Decimal

from app.replay.training.persistence import account_marks as account_marks_ops
from app.replay.training.persistence import portfolio as portfolio_ops

from ..canonical import canonical_json
from ..constants import CommandType, REPLAY_PROTOCOL
from ..models import ReplayCommand
from ..multi_phase_commit import commit_actor_phases
from . import control_rules as control_rules_ops
from . import service_validation as service_validation_ops
from .account import InstrumentRule, isolated_margin_key
from .multi_interval import IntervalLeg, safe_envelope
from .multitrack import StableMarketEvent, stable_market_event_order, PreparedGlobalEventHashes

MAX_COHORTS = 16
MAX_EVENTS_PER_TRACK = 8192


class TapeRiskBoundary(Exception):
    """The speculative batch must be replayed through the interaction path."""


def require_safe_prices(store, connection, run_id, planned_prices):
    """Prove no liquidation anywhere in the bounded trade-price envelope.

    Read the financial basis under the writer lock. This is only permission to
    batch; exact cohort account/review writes still run afterwards.
    """
    account = connection.execute(
        "SELECT a.*,r.initial_equity FROM replay_training_contract_account a "
        "JOIN replay_training_run r USING(run_id) WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if account is None or account["status"] != "ACTIVE":
        raise TapeRiskBoundary()
    rows = connection.execute(
        "SELECT * FROM replay_training_market_track WHERE run_id=? ORDER BY stable_ordinal,track_id",
        (run_id,),
    ).fetchall()
    tracks = [portfolio_ops.market_track_from_row(row) for row in rows]
    portfolio = portfolio_ops.portfolio_projection(
        initial_equity=account["initial_equity"], tracks=tracks
    )
    isolated = json.loads(account["isolated_margin_json"])
    legs, bounds, initial_prices = [], {}, {}
    for track in tracks:
        position = track["position"]
        quantity = Decimal(position.get("quantity", "0"))
        initial_prices[track["track_id"]] = Decimal(position.get("mark_price") or "0")
        if not quantity:
            continue
        tid = track["track_id"]
        rule = connection.execute(
            "SELECT rule_json FROM replay_training_instrument_rule WHERE run_id=? AND track_id=? ORDER BY revision DESC LIMIT 1",
            (run_id, tid),
        ).fetchone()
        if rule is None:
            raise TapeRiskBoundary()
        values = [
            Decimal(position["mark_price"]),
            *map(Decimal, planned_prices.get(tid, ())),
        ]
        bounds[tid] = min(values), max(values)
        legs.append(
            IntervalLeg(
                tid,
                "LONG" if quantity > 0 else "SHORT",
                abs(quantity),
                Decimal(position["entry_price"]),
                InstrumentRule.from_mapping(json.loads(rule[0])),
                Decimal(isolated.get(isolated_margin_key(tid, None), "0")),
            )
        )
    if not safe_envelope(
        cash=Decimal(portfolio["cash_balance"]) + Decimal(account["overlay_cash"]),
        legs=legs,
        bounds=bounds,
        margin_mode=account["margin_mode"],
        reserved_margin=Decimal(portfolio["reserved_margin"]),
    ):
        raise TapeRiskBoundary("price envelope")
    if any(Decimal(leg.rule.contract_size) != 1 for leg in legs):
        raise TapeRiskBoundary()
    return dict(
        cash=Decimal(portfolio["cash_balance"]) + Decimal(account["overlay_cash"]),
        legs=legs,
        initial_prices=initial_prices,
        fingerprint=account_marks_ops.hedge_risk_fingerprint(connection, run_id=run_id),
    )


def coordinator_waves(store, command, binding, job, budget):
    """Renew a bounded scan window only for a progressing durable tape job."""
    while True:
        before = (
            None if job is None else (job["current_virtual_time_ms"], job["consumed"])
        )
        yield from range(budget)
        if (
            job is None
            or binding.get("source_kind") != "AGG_TRADE"
            or (command.run_id, command.command_id)
            not in getattr(store, "_multi_interval_commands", ())
            or job["status"] != "RUNNING"
            or (job["current_virtual_time_ms"], job["consumed"]) <= before
        ):
            return


def update_intent(store, connection, run_id):
    """Bookmark every committed cohort, including exact fallback interactions."""
    intents = connection.execute(
        "SELECT command_id,session_id,plan_json FROM replay_training_advance_intent WHERE run_id=? AND status='RUNNING'",
        (run_id,),
    ).fetchall()
    for intent in intents:
        plan = json.loads(intent["plan_json"])
        if plan.get("schema") != "tape-cohort-advance.v1":
            continue
        rows = connection.execute(
            "SELECT s.session_id,s.state_hash,s.source_sequence,s.revision,t.virtual_time_ms FROM replay_session s JOIN replay_training_market_track t ON t.adapter_session_id=s.session_id WHERE t.run_id=? AND t.subscription_tier='FULL' ORDER BY t.stable_ordinal",
            (run_id,),
        ).fetchall()
        if len({r["virtual_time_ms"] for r in rows}) != 1:
            raise ValueError("tape intent requires a complete global cohort")
        plan.update(
            latest_tracks=[dict(r) for r in rows],
            risk_fingerprint=account_marks_ops.hedge_risk_fingerprint(connection, run_id=run_id),
        )
        selected = next(r for r in rows if r["session_id"] == intent["session_id"])
        cursor = {
            k: selected[k] for k in ("source_sequence", "virtual_time_ms", "revision")
        }
        connection.execute(
            "UPDATE replay_training_advance_intent SET plan_json=?,latest_cursor_json=? WHERE run_id=? AND command_id=?",
            (
                canonical_json(plan),
                canonical_json(cursor),
                run_id,
                intent["command_id"],
            ),
        )


async def try_advance(owner, *, command, binding, tracks, snapshots, target, runtime_snapshot=None, source_goal=None):
    service, store = owner.replay_service, owner.store
    hedge = binding.get("position_mode") == "HEDGE"
    if (
        not service.settings.replay_fast_forward_optimization_enabled
        or binding.get("source_kind") != "AGG_TRADE"
        or binding.get("position_mode") not in {"ONE_WAY", "HEDGE"}
        or (source_goal is not None and (not hedge or len(tracks) != 1))
        or (not hedge and binding.get("funding_mode") != "OFF")
        or binding.get("book_mode", "OFF") != "OFF"
        or binding.get("account_data_mode") == "HISTORICAL_EXACT"
        or not 1 <= len(tracks) <= 8
        or any(
            s["state"] != "PAUSED" or s["cursor"].get("at_end") for _, s in snapshots
        )
    ):
        return None
    clocks = {s["cursor"]["virtual_time_ms"] for _, s in snapshots}
    if len(clocks) != 1:
        return None
    current = clocks.pop()
    for _, snapshot in snapshots:
        if any(
            o["status"] in {"OPEN", "PARTIALLY_FILLED"}
            for o in snapshot["components"]["orders"]
        ):
            return None
    context = None
    if hedge:
        from .hedge_tape_interval import prepare_context
        context = await prepare_context(
            owner, run_id=command.run_id, binding=binding, tracks=tracks,
            current=current, target=target, runtime_snapshot=runtime_snapshot,
        )
        if context is None:
            return None
    parent_target = target
    if hedge:
        target = context["target"]
    if source_goal is not None:
        # Keep the entire final timestamp on the exact-count path: the user's
        # requested event may be in the middle of a same-time trade cohort.
        target = min(target, source_goal.target_virtual_time_ms - 1)
    plans = {}
    blocks = {}
    prices = {}
    cap = target
    for track, snapshot in snapshots:
        sid = service_validation_ops.track_session_id(track)
        controlled = await owner._ensure_track_controller(
            session_id=sid,
            client_instance_id=command.client_instance_id,
            command_id=command.command_id,
            known_snapshot=snapshot,
        )
        if controlled["revision"] != snapshot["revision"]:
            return None
        plan = await service.plan_source_chunk(
            sid,
            target_time_ms=target,
            max_events=min(MAX_EVENTS_PER_TRACK, service.settings.event_buffer_size),
            prepare_tape=True,
        )
        blocks[sid] = plan.get("prepared_tape")
        times = tuple(plan["event_times_ms"])
        if not times or times[0] <= current:
            return None
        # Exclude the final planned timestamp, which may be split by a page or
        # be a source terminal. Both retain the established exact fallback.
        cap = min(cap, times[-1] - 1)
        plans[sid] = times
        prices[sid] = tuple(plan["event_prices"])
    times = sorted(
        {t for values in plans.values() for t in values if current < t <= cap}
    )
    if len(times) < 2:
        return None
    while True:
        planned_prices = {
            track["track_id"]: prices[service_validation_ops.track_session_id(track)][
                : bisect_right(plans[service_validation_ops.track_session_id(track)], times[-1])
            ]
            for track, _ in snapshots
        }
        try:
            if not hedge:
                context = await store.base_store.run_extension_read(
                    lambda c: require_safe_prices(store, c, command.run_id, planned_prices)
                )
            break
        except TapeRiskBoundary as error:
            if str(error) != "price envelope":
                return None
            times = times[: len(times) // 2]
            if len(times) < 2:
                return None
    from .tape_interval import prepare_intervals, persist_interval, PreparedIntervalRecord
    from ..timing import timed_to_thread

    intervals, times = await timed_to_thread(
        "tape_interval_prepare",
        lambda: prepare_intervals(
            context, snapshots, plans, prices, times, current=current, binding=binding
        ),
    )
    phases, stable = [], []
    previous = current
    for ordinal, at in enumerate(times):
        commands, expected, events, bounds = [], {}, [], {}
        prepared_tape = {}
        for track, snapshot in snapshots:
            sid, tid = service_validation_ops.track_session_id(track), track["track_id"]
            first = bisect_right(plans[sid], previous)
            last = bisect_right(plans[sid], at)
            if first < last:
                values = list(map(Decimal, prices[sid][first:last]))
                bounds[sid] = min(values), max(values)
            if blocks[sid] is not None:
                prepared_tape[sid] = blocks[sid].slice(first, last, snapshot["revision"] + ordinal, at)
            sequence = snapshot["cursor"]["source_sequence"]
            expected[sid] = (
                snapshot["revision"] + ordinal,
                sequence + first,
                sequence + last,
            )
            commands.append(
                (
                    sid,
                    ReplayCommand(
                        protocol=REPLAY_PROTOCOL,
                        command_id=control_rules_ops.multi_command_id(
                            command.command_id,
                            tid,
                            "tape_batch",
                            snapshot["revision"] + ordinal,
                        ),
                        client_instance_id=command.client_instance_id,
                        expected_revision=snapshot["revision"] + ordinal,
                        type=CommandType.ADVANCE_BY,
                        payload={"ms": at - previous},
                    ),
                )
            )
            events.extend(
                StableMarketEvent(
                    actual_event_time_ms=control_rules_ops.actual_event_time_ms(
                        binding, plans[sid][i]
                    ),
                    event_phase=20,
                    market_track_stable_id=tid,
                    source_sequence=sequence + i + 1,
                )
                for i in range(first, last)
            )
        ordered = stable_market_event_order(events)
        encoded = {}
        interval_command_id = command.command_id + ":tape:" + str(ordinal) + ":" + str(at)

        def prepare_candidates(_mutations, encoded=encoded, ordered=ordered,
                               interval=intervals[ordinal], cid=interval_command_id):
            encoded["hashes"] = PreparedGlobalEventHashes.prepare(ordered)
            encoded["interval"] = PreparedIntervalRecord.prepare(interval, command.run_id, cid)

        def before(connection, expected=expected, ordinal=ordinal, bounds=bounds):
            active_bounds = getattr(store, "_tape_interval_bounds", None)
            if active_bounds is None:
                active_bounds = store._tape_interval_bounds = {}
            for sid in expected:
                active_bounds.pop(sid, None)
            active_bounds.update(bounds)
            for sid, (revision, first, _) in expected.items():
                row = connection.execute(
                    "SELECT revision,source_sequence FROM replay_session WHERE session_id=?",
                    (sid,),
                ).fetchone()
                if row is None or tuple(row) != (revision, first):
                    raise ValueError("tape phase lost its committed source basis")
            if ordinal == 0:
                if context["fingerprint"] != account_marks_ops.hedge_risk_fingerprint(
                    connection, run_id=command.run_id
                ):
                    raise TapeRiskBoundary()
                if hedge:
                    from .hedge_tape_interval import validate_input_cursors
                    if not validate_input_cursors(connection, command.run_id, context["input_cursors"]):
                        raise TapeRiskBoundary()
                else:
                    require_safe_prices(store, connection, command.run_id, planned_prices)
                intent = store._advance_intent_writer(
                    run_id=command.run_id,
                    command_id=command.command_id,
                    command=command.to_dict(),
                    session_id=binding["adapter_session_id"],
                    initial_cursor=command.expected_cursor.to_dict(),
                    target_virtual_time_ms=parent_target,
                    plan={"schema": "tape-cohort-advance.v1", **(
                        {"target_source_sequence": source_goal.target_source_sequence}
                        if source_goal is not None else {}
                    )},
                    summary=None,
                )(connection)
                if intent["status"] != "RUNNING":
                    raise ValueError("tape parent intent is already terminal")

        def after(
            connection, expected=expected, at=at, ordered=ordered, ordinal=ordinal,
            encoded=encoded, cid=interval_command_id
        ):
            for sid, (_, _, last) in expected.items():
                row = connection.execute(
                    "SELECT s.source_sequence,t.virtual_time_ms FROM replay_session s JOIN replay_training_market_track t ON t.adapter_session_id=s.session_id WHERE s.session_id=?",
                    (sid,),
                ).fetchone()
                if row is None or tuple(row) != (last, at):
                    raise ValueError("tape phase missed its complete cohort")
            if connection.execute(
                "SELECT 1 FROM replay_training_liquidation_case WHERE run_id=? AND state NOT IN ('COMPLETED','BANKRUPT','FAILED_CLOSED','RECOVERED_AFTER_CANCEL') LIMIT 1",
                (command.run_id,),
            ).fetchone():
                raise TapeRiskBoundary()
            if hedge:
                fingerprint = store._finalize_hedge_inputs_in_transaction(
                    connection, run_id=command.run_id, risk_virtual_time_ms=at,
                    cached_fingerprint=context["fingerprint"],
                )
                if fingerprint != context["fingerprint"]:
                    raise TapeRiskBoundary("fixed-mark account basis changed")
            store._record_global_events_in_transaction(
                connection,
                run_id=command.run_id,
                ordered=ordered,
                materialize_portfolio=False,
                prepared_hashes=encoded["hashes"],
            )
            persist_interval(
                store,
                connection,
                run_id=command.run_id,
                command_id=cid,
                prepared=encoded["interval"],
                interval=intervals[ordinal],
            )
            if hedge:
                # An unchanged public mark has no financial SOURCE_EVENT
                # descriptor. Still retain each committed phase as a usable
                # historical review/fork anchor, not only an invisible curve.
                store._append_review_timeline_event(
                    connection, run_id=command.run_id,
                    session_id=binding["adapter_session_id"],
                    context={"kind": "DIRECT", "category": "SYSTEM", "event_type": "HEDGE_TAPE_INTERVAL"},
                    state=None, checkpoint=None, now_ms=store.base_store._validated_now_ms(),
                )

        phases.append(
            dict(commands=commands, before=before, after=after, tape_summary=True, prepared_tape=prepared_tape,
                 prepare_candidates=prepare_candidates)
        )
        stable.extend(ordered)
        previous = at
    try:
        intent_runs = getattr(store, "_tape_intent_runs", None)
        if intent_runs is None:
            intent_runs = store._tape_intent_runs = set()
        intent_runs.add(command.run_id)
        active = getattr(store, "_tape_interval_active", None)
        if active is None:
            active = store._tape_interval_active = set()
        active.add(command.run_id)
        await commit_actor_phases(service, phases, tape=True)
    except TapeRiskBoundary:
        return None
    finally:
        getattr(store, "_tape_interval_active", set()).discard(command.run_id)
        getattr(store, "_portfolio_summary_runs", {}).pop(command.run_id, None)
        for sid in plans:
            getattr(store, "_tape_interval_bounds", {}).pop(sid, None)
    used = getattr(store, "_multi_interval_commands", None)
    if used is None:
        used = store._multi_interval_commands = set()
    used.add((command.run_id, command.command_id))
    if hedge:
        fingerprint = await store.base_store.run_extension_read(
            lambda c: account_marks_ops.hedge_risk_fingerprint(c, run_id=command.run_id)
        )
        store._cache_committed_hedge_fingerprint(command.run_id, fingerprint)
    return tuple(stable), times[-1]
