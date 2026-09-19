"""Plan and atomically advance a conservatively safe shared BAR interval."""

from __future__ import annotations

import asyncio
from bisect import bisect_left, bisect_right
from decimal import Decimal
from time import perf_counter

from ..constants import REPLAY_PROTOCOL
from ..internal_commands import InternalCommandType
from ..models import ReplayCommand
from ..multi_commit import commit_actor_commands
from ..timing import record_timing
from .hedge_timeline import IndexedHedgeSnapshot
from .multi_interval import safe_envelope
from .multi_interval_store import finish_group, risk_context, prepare_group
from .errors import TrainingRunError
from .phase_projection import PhaseSummary


async def resume_advance(owner, *, command, binding, intent):
    """Resume the portfolio coordinator, never the legacy single-actor scanner."""
    service, store = owner.replay_service, owner.store
    tracks = tuple(
        t
        for t in await store.get_market_track_heads(command.run_id)
        if t["subscription_tier"] == "FULL"
    )
    expected = {t["session_id"]: t for t in intent["plan"]["latest_tracks"]}
    fingerprint = await store.base_store.run_extension_read(
        lambda connection: store._hedge_risk_fingerprint(
            connection, run_id=command.run_id
        )
    )
    if fingerprint != intent["plan"].get("risk_fingerprint"):
        raise TrainingRunError(
            "ADVANCE_INTENT_CURSOR_CONFLICT",
            "account state changed after the committed interval",
            status_code=409,
        )
    if {owner._track_session_id(t) for t in tracks} != set(expected) or binding[
        "adapter_session_id"
    ] != intent["session_id"]:
        raise TrainingRunError(
            "ADVANCE_INTENT_CURSOR_CONFLICT",
            "portfolio membership changed after the committed interval",
            status_code=409,
        )
    for track in tracks:
        sid = owner._track_session_id(track)
        snapshot = owner._snapshot(await service.get_session(sid))
        prior = expected[sid]
        if (
            snapshot["cursor"]["source_sequence"] != prior["source_sequence"]
            or snapshot["cursor"]["virtual_time_ms"] != prior["virtual_time_ms"]
            or snapshot["state_hash"] != prior["state_hash"]
        ):
            raise TrainingRunError(
                "ADVANCE_INTENT_CURSOR_CONFLICT",
                "portfolio state changed after the committed interval",
                status_code=409,
            )
    for track in tracks:
        await service.ensure_advance_recovery_controller(
            owner._track_session_id(track),
            client_instance_id=command.client_instance_id,
        )
    target = int(intent["target_virtual_time_ms"])
    snapshot = owner._snapshot(await service.get_session(intent["session_id"]))
    decision = owner._plan_fast_forward(
        binding=binding, snapshot=snapshot, tracks=tracks, target_virtual_time_ms=target
    )
    job = dict(
        cancel=asyncio.Event(),
        client_instance_id=command.client_instance_id,
        status="RUNNING",
        initial_virtual_time_ms=snapshot["cursor"]["virtual_time_ms"],
        target_virtual_time_ms=target,
        current_virtual_time_ms=snapshot["cursor"]["virtual_time_ms"],
        consumed=0,
        chunks=0,
        cancelable=True,
        plan=decision.to_dict(),
        chunk_event_limit=1,
        queue_high_water=0,
        stable_order_truncated=False,
    )
    key = (command.run_id, command.command_id)
    owner._advance_jobs[key] = job
    event_stop = {} if owner._stop_on_event(command) else None
    try:
        if snapshot["cursor"]["virtual_time_ms"] < target:
            await owner._advance_full_tracks_to(
                command=command,
                binding=binding,
                tracks=tracks,
                target_virtual_time_ms=target,
                job=job,
                allow_final_state_batch=True,
                audit_account_at_barrier=False,
                event_stop=event_stop,
            )
        final = owner._snapshot(await service.get_session(intent["session_id"]))
        cancelled = job["status"] == "CANCELLED"
        if not cancelled:
            job["status"] = "COMPLETED"
        job["cancelable"] = False
        viewer = await store.get_viewer_state(command.run_id)
        result = owner._result_payload(
            command=command,
            session_id=intent["session_id"],
            snapshot=final,
            viewer=viewer.to_dict(),
            data={
                "recovered": True,
                "cancelled": cancelled,
                "consumed": final["cursor"]["source_sequence"]
                - intent["initial_cursor"]["source_sequence"],
                "full_track_count": len(tracks),
                "progress": owner._public_progress(job),
                **({"event_stop": event_stop} if event_stop else {}),
            },
        )
        await store.finish_advance_intent(
            run_id=command.run_id,
            command_id=command.command_id,
            result=result,
            cancelled=cancelled,
        )
        return result
    finally:
        job["cancelable"] = False
        owner._advance_jobs.pop(key, None)
        getattr(store, "_multi_interval_commands", set()).discard(key)


async def try_advance(
    owner,
    *,
    command,
    binding,
    tracks,
    snapshots,
    target,
    runtime_snapshot,
    cancel_event=None,
    command_target=None,
    completion=None,
):
    service, store = owner.replay_service, owner.store
    planning_started = perf_counter()
    command_target = target if command_target is None else command_target
    if (
        not service.settings.replay_multi_bar_interval_enabled
        or not 2 <= len(tracks) <= 8
        or binding.get("source_kind") != "BAR"
        or binding.get("position_mode") != "HEDGE"
        or binding.get("book_mode", "OFF") != "OFF"
        or binding.get("account_data_mode") == "HISTORICAL_EXACT"
        or binding.get("funding_mode") not in {"OFF", "HISTORICAL_EXACT"}
        or not isinstance(runtime_snapshot, IndexedHedgeSnapshot)
    ):
        return None
    if not hasattr(store, "_portfolio_summary_runs"):
        store._portfolio_summary_runs = {}
    store._portfolio_summary_runs[command.run_id] = True
    starts = {owner._cursor_time(snapshot) for _, snapshot in snapshots}
    if len(starts) != 1 or any(
        snapshot.get("state") != "PAUSED" for _, snapshot in snapshots
    ):
        return None
    start_time = next(iter(starts))
    if target <= start_time:
        return None
    # The browser owns the selected adapter only. The ordinary event path
    # acquires the other tracks on demand; a shared interval must do the same
    # before capturing candidate revisions (including after idle expiry).
    controlled = []
    for track, snapshot in snapshots:
        session_id = owner._track_session_id(track)
        controlled_snapshot = await owner._ensure_track_controller(
            session_id=session_id,
            client_instance_id=command.client_instance_id,
            command_id=command.command_id,
            known_snapshot=snapshot,
        )
        # Heartbeat preserves the revision; acquisition returns its committed
        # revision/cursor. Neither requires reserializing the complete snapshot.
        controlled.append((track, controlled_snapshot))
    snapshots = controlled
    all_current_tracks = await store.get_market_track_heads(command.run_id)
    full_ids = {track["track_id"] for track in tracks}
    current_tracks = [
        track for track in all_current_tracks if track["track_id"] in full_ids
    ]
    context = await risk_context(
        store, command.run_id, current_tracks, all_tracks=all_current_tracks
    )
    if context is None:
        return None
    public, simulation = await owner.hedge_inputs._projection_cursors(command.run_id)
    delta = owner._actual_event_time_ms(binding, target) - target
    actual_target = target + delta
    lanes = {}
    for lane in runtime_snapshot.lanes:
        a = bisect_right(lane.sequences, lane.cursor(public, simulation))
        if a < len(lane.times) and lane.times[a] <= start_time + delta:
            return None
        barrier_at = bisect_left(lane.barrier_indices, a)
        if barrier_at < len(lane.barrier_indices):
            actual_target = min(
                actual_target, lane.times[lane.barrier_indices[barrier_at]] - 1
            )
        if lane.source_kind == "PUBLIC":
            lanes[lane.track_id] = (lane, a)
    for archive in context["archives"].values():
        actual_target = min(actual_target, archive["bound_range_end_ms"])
    target = actual_target - delta
    if target <= start_time or any(t["track_id"] not in lanes for t in tracks):
        return None
    plans = []
    sources = await asyncio.gather(
        *(
            service.plan_source_chunk(
                owner._track_session_id(track),
                target_time_ms=target,
                max_events=100000,
                indexed=True,
            )
            for track, _ in snapshots
        ),
        return_exceptions=True,
    )
    for source in sources:
        if isinstance(source, BaseException):
            raise source
    for (track, snapshot), source in zip(snapshots, sources, strict=True):
        session = owner._track_session_id(track)
        if (
            not source
            or not getattr(source["index"], "shared", False)
            or source["end"] <= source["start"]
        ):
            return None
        # Stop before the first possible order interaction on any market.
        index = source["index"]
        if (
            source["end"] < len(index.bars)
            and int(index.times[source["end"]]) <= target
        ):
            target = min(target, int(index.times[source["end"]]) - 1)
        plans.append(
            dict(
                source,
                run_id=command.run_id,
                session_id=session,
                track_id=track["track_id"],
                snapshot=snapshot,
            )
        )

    def bounds_at(at):
        bounds = {}
        for tid, (lane, a) in lanes.items():
            b = bisect_right(lane.times, at + delta)
            value = lane.price_index.range_bounds(start=a, end=b) if b > a else None
            mark = context["prices"][tid]
            bounds[tid] = (
                (mark, mark)
                if value is None
                else (min(mark, value[0]), max(mark, value[1]))
            )
        return bounds

    def safe(at):
        return safe_envelope(
            cash=context["cash"],
            legs=context["legs"],
            bounds=bounds_at(at),
            margin_mode=context["margin_mode"],
            reserved_margin=context["reserved"],
        )

    if not safe(target):
        low, high = start_time, target
        while high - low > 1:
            middle = (low + high) // 2
            if safe(middle):
                low = middle
            else:
                high = middle
        target = low
    if target <= start_time:
        return None
    record_timing("multi_plan", planning_started)
    summary_started = perf_counter()

    def summarize():
        return runtime_snapshot.portfolio_prices.summary(
            cash=context["cash"],
            legs=context["legs"],
            initial_prices=context["prices"],
            start=start_time + delta,
            end=target + delta,
            delta=delta,
        )

    summary = await asyncio.to_thread(summarize)
    record_timing("multi_portfolio_summary", summary_started)
    if cancel_event is not None and cancel_event.is_set():
        return (), start_time
    split_time = None
    minimum_time = summary["trough_time_ms"]
    if minimum_time is not None and start_time < minimum_time < target:
        prior = await store.base_store.run_extension_read(
            lambda connection: store._review._minimum_prior_equity(connection, run_id=command.run_id)
        )
        if prior is None or Decimal(summary["trough"]) < prior:
            split_time = minimum_time
    # Each phase remains a real command/checkpoint. Their publication shares
    # one commit; no reader can observe only the prefix.
    original_plans = plans

    def make_phase(phase_start, phase_end):
        initial_prices = {}
        phase_lanes = {}
        phase_plans = []
        for plan in original_plans:
            lane, original_a = lanes[plan["track_id"]]
            a = bisect_right(lane.times, phase_start + delta)
            initial_prices[plan["track_id"]] = (
                context["prices"][plan["track_id"]] if a <= original_a
                else Decimal(lane.events[a-1].payload["mark_price"])
            )
            phase_lanes[plan["track_id"]] = (lane, a)
            phase_plan = dict(plan)
            phase_plan["start"] = plan["index"].end_for_time(phase_start)
            phase_plan["snapshot"] = dict(plan["snapshot"], revision=(
                int(plan["snapshot"]["revision"]) + phase_plan["start"] - plan["start"]
            ))
            phase_plans.append(phase_plan)
        phase_summary = runtime_snapshot.portfolio_prices.summary(
            cash=context["cash"], legs=context["legs"], initial_prices=initial_prices,
            start=phase_start + delta, end=phase_end + delta, delta=delta,
        )
        return build_group(phase_start, phase_end, phase_summary, phase_plans, phase_lanes, initial_prices)

    def build_group(start_time, target, summary, plans, lanes, initial_prices):
        commands, basis_tracks = [], []
        for plan in plans:
            index = plan["index"]
            plan["end"] = index.end_for_time(target)
            if plan["end"] - plan["start"] < 1:
                return None
            lane, a = lanes[plan["track_id"]]
            b = bisect_right(lane.times, target + delta)
            plan["first_mark"] = lane.events[a] if b > a else None
            plan["last_mark"] = lane.events[b - 1] if b > a else None
            part = owner._multi_command_id(
                command.command_id,
                plan["track_id"],
                "multi-indexed",
                int(plan["snapshot"]["revision"]),
            )
            plan["command_id"] = part
            commands.append(
                (
                    plan["session_id"],
                    ReplayCommand(
                        protocol=REPLAY_PROTOCOL,
                        command_id=part,
                        client_instance_id=command.client_instance_id,
                        expected_revision=int(plan["snapshot"]["revision"]),
                        type=InternalCommandType.MULTI_SHARED_INDEXED_INTERVAL,
                        payload={
                            "target_virtual_time_ms": target,
                            "max_events": plan["end"] - plan["start"],
                            "require_empty_account": False,
                            "snapshot_only": False,
                            "transport_tail_bars": 16,
                        },
                    ),
                )
            )
            archive = context["archives"][plan["track_id"]]
            basis_tracks.append(
                dict(
                    track_id=plan["track_id"],
                    market=index.market.descriptor(),
                    start=plan["start"],
                    end=plan["end"],
                    public_path=archive["local_path"],
                    public_checksum=archive["public_checksum_sha256"],
                    mark_start=a,
                    mark_end=b,
                    initial_mark=str(initial_prices[plan["track_id"]]),
                )
            )
        group = dict(
            run_id=command.run_id,
            command_id=command.command_id + ":multi:" + str(start_time),
            start_time=start_time,
            target=target,
            actual_delta=delta,
            tracks=plans,
            summary=summary,
            selected_session_id=binding["adapter_session_id"],
            policy=binding["time_disclosure_policy"],
            parent_command=command,
            requested_target=command_target,
            basis=dict(
                schema="multi-bar-interval.v1",
                start_time_ms=start_time,
                end_time_ms=target,
                cash=str(context["cash"]),
                actual_delta=delta,
                tracks=basis_tracks,
                legs=[
                    dict(
                        track_id=leg.track_id,
                        side=leg.side,
                        quantity=str(leg.quantity),
                        entry=str(leg.entry),
                        rule=leg.rule.to_dict(),
                    )
                    for leg in context["legs"]
                ],
            ),
        )
        group["commands"] = commands
        return group

    if split_time is not None and all(
        p["start"] < p["index"].end_for_time(split_time) < p["index"].end_for_time(target)
        for p in plans
    ):
        groups = await asyncio.to_thread(lambda: [make_phase(start_time, split_time), make_phase(split_time, target)])
    else:
        # Unequal grids may not contain a BAR on both sides of the minimum.
        # Retain the original single-prefix fallback in that case.
        if split_time is not None:
            target = split_time
            summary = await asyncio.to_thread(summarize)
        groups = [build_group(start_time, target, summary, plans, lanes, context["prices"])]
    if any(part is None for part in groups):
        return None
    group = groups[-1]
    plans = groups[0]["tracks"]
    if cancel_event is not None and cancel_event.is_set():
        return (), start_time
    registry = getattr(store, "_multi_interval_plans", None)
    if registry is None:
        registry = store._multi_interval_plans = {}
    if any(plan["session_id"] in registry for plan in plans):
        raise RuntimeError("overlapping multi interval plan")
    registry.update({plan["session_id"]: plan for plan in plans})

    def before(connection):
        if (
            store._hedge_risk_fingerprint(connection, run_id=command.run_id)
            != context["fingerprint"]
        ):
            raise ValueError(
                "portfolio state changed during multi interval preparation"
            )
        for plan in plans:
            row = connection.execute(
                "SELECT revision FROM replay_session WHERE session_id=?",
                (plan["session_id"],),
            ).fetchone()
            if row is None or row[0] != plan["snapshot"]["revision"]:
                raise ValueError(
                    "actor revision changed during multi interval preparation"
                )

        intent = store._advance_intent_writer(
            run_id=command.run_id,
            command_id=command.command_id,
            command=command.to_dict(),
            session_id=group["selected_session_id"],
            initial_cursor=command.expected_cursor.to_dict(),
            target_virtual_time_ms=command_target,
            plan={"schema": "multi-bar-advance-intent.v1"},
            summary=None,
        )(connection)
        if intent["status"] != "RUNNING":
            raise ValueError("multi interval intent is no longer running")

    def phase_callbacks(phase, ordinal):
        def prepare(connection):
            if ordinal == 0:
                before(connection)
            phase["projection_summary"] = PhaseSummary.load(connection, command.run_id)
            for plan in phase["tracks"]:
                plan["projection_summary"] = phase["projection_summary"]
            registry.update({p["session_id"]: p for p in phase["tracks"]})

        def finish(connection):
            finish_group(store, connection, phase)
            if ordinal == len(groups)-1:
                phase["stable"] = tuple(e for part in groups for e in part["stable"])
                if completion is not None and target >= command_target:
                    result = completion(phase)
                    store._finish_advance_intent_in_transaction(
                        connection, run_id=command.run_id, command_id=command.command_id,
                        result=result, cancelled=bool(result["data"]["cancelled"]),
                    )
                    phase["completed_result"] = result
        return dict(commands=phase["commands"], before=prepare, after=finish,
                    prepare_candidates=lambda mutations: prepare_group(phase, mutations))

    phases = [phase_callbacks(phase, i) for i, phase in enumerate(groups)]
    try:
        commit_started = perf_counter()
        if len(phases) == 1:
            await commit_actor_commands(service, **phases[0])
        else:
            from ..multi_phase_commit import commit_actor_phases
            await commit_actor_phases(service, phases)
        record_timing("multi_commit", commit_started)
        store._cache_committed_hedge_fingerprint(
            command.run_id, group["fingerprint_after"]
        )
        if "completed_result" in group:
            completed = getattr(store, "_multi_completed_results", None)
            if completed is None:
                completed = store._multi_completed_results = {}
            completed[(command.run_id, command.command_id)] = group["completed_result"]
        if not hasattr(store, "_multi_interval_commands"):
            store._multi_interval_commands = set()
        store._multi_interval_commands.add((command.run_id, command.command_id))
        return group["stable"], target
    finally:
        for plan in plans:
            registry.pop(plan["session_id"], None)
