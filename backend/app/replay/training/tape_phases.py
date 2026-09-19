"""Bounded exact tape cohorts sharing a durable publication barrier.

Account projections, risk detection and review execute in their original cohort
order. Dense same-time trades use candle and ordered-price summaries; a risk
interaction aborts the unpublished batch and uses the scalar coordinator.
"""

from bisect import bisect_right
import json
from decimal import Decimal

from ..canonical import canonical_json
from ..constants import CommandType, REPLAY_PROTOCOL
from ..models import ReplayCommand
from ..multi_phase_commit import commit_actor_phases
from .multitrack import StableMarketEvent, stable_market_event_order, PreparedGlobalEventHashes
from .account import InstrumentRule, isolated_margin_key
from .multi_interval import IntervalLeg, safe_envelope

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
    tracks = [store._market_track_from_row(row) for row in rows]
    portfolio = store._portfolio_projection(
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
        fingerprint=store._hedge_risk_fingerprint(connection, run_id=run_id),
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
            risk_fingerprint=store._hedge_risk_fingerprint(connection, run_id=run_id),
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


async def try_advance(owner, *, command, binding, tracks, snapshots, target):
    service, store = owner.replay_service, owner.store
    if (
        not service.settings.replay_fast_forward_optimization_enabled
        or binding.get("source_kind") != "AGG_TRADE"
        or binding.get("position_mode") != "ONE_WAY"
        or binding.get("funding_mode") != "OFF"
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
    plans = {}
    blocks = {}
    prices = {}
    cap = target
    for track, snapshot in snapshots:
        sid = owner._track_session_id(track)
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
            track["track_id"]: prices[owner._track_session_id(track)][
                : bisect_right(plans[owner._track_session_id(track)], times[-1])
            ]
            for track, _ in snapshots
        }
        try:
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
            sid, tid = owner._track_session_id(track), track["track_id"]
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
                        command_id=owner._multi_command_id(
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
                    actual_event_time_ms=owner._actual_event_time_ms(
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
                if context["fingerprint"] != store._hedge_risk_fingerprint(
                    connection, run_id=command.run_id
                ):
                    raise TapeRiskBoundary()
                require_safe_prices(store, connection, command.run_id, planned_prices)
                intent = store._advance_intent_writer(
                    run_id=command.run_id,
                    command_id=command.command_id,
                    command=command.to_dict(),
                    session_id=binding["adapter_session_id"],
                    initial_cursor=command.expected_cursor.to_dict(),
                    target_virtual_time_ms=target,
                    plan={"schema": "tape-cohort-advance.v1"},
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
    return tuple(stable), times[-1]
