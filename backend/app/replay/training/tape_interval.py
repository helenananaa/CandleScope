"""Versioned, committed tape intervals with deferred adapter/portfolio curves.

Only revealed price/time ranges are stored. No per-trade account snapshots are
prepared. Review anchors are complete global cohorts at the trough and endpoint.
"""

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal

from ..canonical import canonical_json, canonical_sha256
from ..broker.shared_prepared import LazySequence, account_sample
from .multi_interval import ordered_equity_summary, IntervalLeg
from .account import InstrumentRule


def prepare_intervals(context, snapshots, plans, prices, times, *, current, binding):
    events = []
    for track, snapshot in snapshots:
        sid, tid = track["adapter_session_id"], track["track_id"]
        sequence = snapshot["cursor"]["source_sequence"]
        events.extend(
            (at, 20, tid, sequence + i + 1, Decimal(prices[sid][i]))
            for i, at in enumerate(plans[sid])
            if at <= times[-1]
        )
    arguments = {k: context[k] for k in ("cash", "legs", "initial_prices")}
    full = ordered_equity_summary(
        **arguments, events=events,
        _partition_after=(current, times[len(times) // 2 - 1]),
    )
    pivot = full["partition_time_ms"]
    events = full.pop("ordered_events")
    endpoints = [pivot, times[-1]]
    marks = dict(context["initial_prices"])
    intervals, previous = [], current
    for ordinal, end in enumerate(endpoints):
        selected_events = [e for e in events if previous < e[0] <= end]
        summary = full["partitions"][ordinal]
        basis = dict(
            schema="multi-tape-interval.v1",
            start_time_ms=previous,
            end_time_ms=end,
            cash=str(context["cash"]),
            initial_prices={t: str(p) for t, p in marks.items()},
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
            events=[[*e[:4], str(e[4])] for e in selected_events],
        )
        curves = []
        for track, snapshot in snapshots:
            sid = track["adapter_session_id"]
            if sid != binding["adapter_session_id"]:
                continue
            sample_times = sorted({e[0] for e in selected_events})
            if not sample_times:
                continue
            components = snapshot["components"]
            position = components["position"]
            offsets = [bisect_right(plans[sid], at) for at in sample_times]
            sequences = [snapshot["cursor"]["source_sequence"] + i for i in offsets]
            curve = dict(
                schema="tape-curve.v1",
                start=sequences[0],
                times=sample_times,
                sequences=sequences,
                prices=[
                    prices[sid][i - 1] if i else position.get("mark_price") or "0"
                    for i in offsets
                ],
                account=dict(
                    cash=components["account"]["cash_balance"],
                    legs=[[position["quantity"], position["entry_price"] or "0"]],
                ),
                ledger_hash=components["ledger"]["tail_hash"],
            )
            curves.append(
                dict(
                    basis=curve,
                    session_id=sid,
                    revision=snapshot["revision"] + ordinal + 1,
                    revealed=snapshot.get("revealed", False),
                    policy=binding["time_disclosure_policy"],
                )
            )
        intervals.append(dict(summary=summary, basis=basis, curves=curves))
        for e in selected_events:
            marks[e[2]] = e[4]
        previous = end
    return intervals, endpoints


@dataclass(frozen=True)
class PreparedIntervalRecord:
    interval: dict
    run_id: str
    command_id: str
    summary_json: str
    basis_json: str
    curves: tuple

    @classmethod
    def prepare(cls, interval, run_id, command_id):
        return cls(
            interval, run_id, command_id,
            canonical_json(interval["summary"]), canonical_json(interval["basis"]),
            tuple((canonical_sha256(dict(run_id=run_id, command_id=command_id,
                                         data=curve["basis"])),
                   canonical_json(curve["basis"])) for curve in interval["curves"]),
        )

    def validate(self, interval, run_id, command_id):
        if (self.interval is not interval or self.run_id != run_id
                or self.command_id != command_id
                or len(self.curves) != len(interval["curves"])):
            raise ValueError("prepared interval record lost its basis")


def persist_interval(store, connection, *, run_id, command_id, interval, prepared=None):
    if prepared is None:
        prepared = PreparedIntervalRecord.prepare(interval, run_id, command_id)
    prepared.validate(interval, run_id, command_id)
    basis, summary = interval["basis"], interval["summary"]
    equity = connection.execute(
        "SELECT current_equity FROM replay_training_run WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    if Decimal(equity) != Decimal(summary["last"]):
        raise ValueError("tape interval portfolio basis changed")
    connection.execute(
        "INSERT INTO replay_multi_bar_interval VALUES (?,?,?,?,?,?)",
        (
            run_id,
            command_id,
            basis["start_time_ms"],
            basis["end_time_ms"],
            prepared.summary_json,
            prepared.basis_json,
        ),
    )
    for curve, (curve_id, curve_json) in zip(interval["curves"], prepared.curves, strict=True):
        data = curve["basis"]
        connection.execute(
            "INSERT INTO replay_prepared_curve VALUES (?,?,?)",
            (curve_id, run_id, curve_json),
        )
        payload = dict(
            schema="indexed-curve.v1",
            curve_id=curve_id,
            start=0,
            end=len(data["times"]),
            session_id=curve["session_id"],
            revision_base=0,
            fixed_revision=curve["revision"],
            policy=curve["policy"],
            revealed=curve["revealed"],
            created_at_ms=store.base_store._validated_now_ms(),
        )
        connection.execute(
            "INSERT INTO replay_interval_curve(run_id,command_id,end_sequence,samples_json,start_sequence,start_time_ms,end_time_ms) VALUES (?,?,?,?,?,?,?)",
            (
                run_id,
                command_id,
                data["sequences"][-1],
                canonical_json(payload),
                data["sequences"][0],
                data["times"][0],
                data["times"][-1],
            ),
        )


def restore_curve(basis):
    times, prices = basis["times"], basis["prices"]
    if (
        not 1 <= len(times) == len(prices) == len(basis["sequences"]) <= 65536
        or times != sorted(times)
        or basis["sequences"] != sorted(basis["sequences"])
    ):
        raise ValueError("invalid tape curve range")
    anchor = canonical_sha256(basis)
    return {
        **basis,
        "samples": LazySequence(
            len(times), lambda i: account_sample(basis["account"], prices[i])
        ),
        "chains": LazySequence(len(times) + 1, lambda i: anchor + ":" + str(i)),
    }


def sample_reference(value):
    if value.startswith("tape-interval-state:"):
        anchor, offset = value[len("tape-interval-state:") :].rsplit(":", 1)
        return dict(
            state_hash=None,
            interval_reference=dict(basis_hash=anchor, offset=int(offset)),
        )
    if value.startswith("interval-state:"):
        return dict(state_hash=None, source_event_hash=value[len("interval-state:") :])
    return dict(state_hash=value)


def reconstruct(basis, *, limit, bucket_ms):
    events = basis["events"]
    if len(events) > 65536 or any(
        not basis["start_time_ms"] < e[0] <= basis["end_time_ms"] for e in events
    ):
        raise ValueError("tape interval crossed its committed range")
    buckets = {}
    for at in sorted({e[0] for e in events}):
        buckets[at if bucket_ms == 0 else at // bucket_ms] = at
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
    return ordered_equity_summary(
        cash=Decimal(basis["cash"]),
        legs=legs,
        initial_prices={t: Decimal(p) for t, p in basis["initial_prices"].items()},
        events=[(*e[:4], Decimal(e[4])) for e in events],
        sample_times=set(list(buckets.values())[-limit:]),
    )
