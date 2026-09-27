"""Curve records operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from heapq import heapify, heappop, heappush

from app.replay.canonical import canonical_json

from ..errors import TrainingRunError
from ..models import (
    validate_v2_counter,
)
from . import public_time as public_time_ops

CURVE_BODY_LOADS = 0


_EQUITY_RESOLUTIONS: tuple[tuple[str, int, int], ...] = (
    ("EVENT", 0, 2_048),
    ("1M", 60_000, 4_096),
    ("15M", 900_000, 2_048),
    ("1H", 3_600_000, 2_048),
)


_EQUITY_BUCKET_MS = {name: bucket_ms for name, bucket_ms, _ in _EQUITY_RESOLUTIONS}


def upsert_equity_samples(
    connection: sqlite3.Connection | None,
    *,
    run_id: str,
    session_id: str,
    policy: str,
    revealed: bool,
    state: Mapping[str, object],
    component_state: Mapping[str, object],
    now_ms: int,
    retain: bool = True,
    pending_samples: dict | None = None,
    resolutions: Sequence[str] | None = None,
    origin: Mapping[str, object] | None = None,
) -> None:
    cursor = state.get("cursor")
    account = component_state.get("account")
    ledger = component_state.get("ledger")
    if (
        not isinstance(cursor, Mapping)
        or not isinstance(account, Mapping)
        or not isinstance(ledger, Mapping)
    ):
        return
    required_account = ("equity", "cash_balance", "unrealized_pnl")
    if any(not isinstance(account.get(key), str) for key in required_account):
        return
    ledger_hash = ledger.get("tail_hash")
    if not isinstance(ledger_hash, str):
        return
    public_ms = int(cursor["virtual_time_ms"])
    source_sequence = validate_v2_counter(
        state["source_sequence"], field_name="source_sequence"
    )
    if origin is not None:
        actual_origin = int(origin["actual_replay_start_ms"])
        public_origin = (
            actual_origin
            if policy == "NONE"
            else public_time_ops.required_synthetic_origin(
                origin["synthetic_origin_ms"]
            )
        )
        public_time = public_time_ops.project_public_time(
            actual_origin_ms=actual_origin,
            public_origin_ms=public_origin,
            policy=policy,
            revealed=revealed,
            public_time_ms=public_ms,
            sequence=source_sequence,
        )
    else:
        public_time = public_time_ops.public_time(
            connection,
            session_id=session_id,
            policy=policy,
            revealed=revealed,
            public_time_ms=public_ms,
            sequence=source_sequence,
        )
    public_time_json = canonical_json(public_time)
    revision = validate_v2_counter(state["revision"], field_name="revision")
    items = _EQUITY_RESOLUTIONS
    if resolutions is not None:
        wanted = set(resolutions)
        items = tuple(item for item in _EQUITY_RESOLUTIONS if item[0] in wanted)
    for resolution, bucket_ms, limit in items:
        bucket_id = source_sequence if bucket_ms == 0 else public_ms // bucket_ms
        values = (
            run_id,
            resolution,
            bucket_id,
            source_sequence,
            revision,
            public_time_json,
            account["equity"],
            account["cash_balance"],
            account["unrealized_pnl"],
            ledger_hash,
            state["state_hash"],
            now_ms,
            now_ms,
        )
        if pending_samples is None:
            write_equity_samples(connection, (values,))
        else:
            key = (run_id, resolution, bucket_id)
            previous = pending_samples.get(key)
            if previous is not None:
                # An upsert keeps the first insertion timestamp.
                values = (*values[:11], previous[11], values[12])
            pending_samples[key] = values
        if retain:
            prune_equity_resolution(
                connection, run_id=run_id, resolution=resolution, limit=limit
            )


def write_equity_samples(connection, rows, *, historical=False):
    condition = (
        " WHERE (excluded.source_sequence, excluded.revision) >= "
        "(replay_equity_sample.source_sequence, replay_equity_sample.revision)"
        if historical
        else ""
    )
    connection.executemany(
        """
        INSERT INTO replay_equity_sample(
            run_id, resolution, bucket_id, source_sequence, revision,
            public_time_json, equity, cash_balance, unrealized_pnl,
            ledger_tail_hash, state_hash, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, resolution, bucket_id) DO UPDATE SET
            source_sequence = excluded.source_sequence,
            revision = excluded.revision,
            public_time_json = excluded.public_time_json,
            equity = excluded.equity,
            cash_balance = excluded.cash_balance,
            unrealized_pnl = excluded.unrealized_pnl,
            ledger_tail_hash = excluded.ledger_tail_hash,
            state_hash = excluded.state_hash,
            updated_at_ms = excluded.updated_at_ms
        """
        + condition,
        rows,
    )


def load_pending_interval_curves(connection, *, run_id, resolution=None, cutoff=None):
    pending = []
    predicate = ""
    parameters = [run_id]
    if cutoff is not None:
        if resolution == "EVENT":
            predicate = " AND (end_sequence >= ? OR start_sequence IS NULL)"
            parameters.append(cutoff)
        elif resolution in _EQUITY_BUCKET_MS:
            predicate = " AND (end_time_ms >= ? OR end_time_ms IS NULL)"
            parameters.append(cutoff * _EQUITY_BUCKET_MS[resolution])
    for row in connection.execute(
        """
        SELECT command_id, samples_json, end_sequence,
               start_sequence, start_time_ms, end_time_ms
        FROM replay_interval_curve
        WHERE run_id=? AND materialized=0
        """
        + predicate
        + " ORDER BY end_sequence, command_id",
        parameters,
    ).fetchall():
        pending.append(
            {
                "command_id": str(row["command_id"]),
                "samples_json": str(row["samples_json"]),
                "curve_json": None,
                "end_sequence": int(row["end_sequence"]),
                "start_sequence": (
                    None
                    if row["start_sequence"] is None
                    else int(row["start_sequence"])
                ),
                "start_time_ms": (
                    None if row["start_time_ms"] is None else int(row["start_time_ms"])
                ),
                "end_time_ms": (
                    None if row["end_time_ms"] is None else int(row["end_time_ms"])
                ),
            }
        )
    return pending


def interval_bound_window(interval, payload, *, bucket_ms):
    start_seq = interval.get("start_sequence")
    end_seq = interval.get("end_sequence")
    start_time = interval.get("start_time_ms")
    end_time = interval.get("end_time_ms")
    start = int(payload["start"])
    end = int(payload["end"])
    revision_base = int(payload.get("revision_base", 0))
    last_version = (
        int(end_seq) if end_seq is not None else 0,
        revision_base + max(0, end - start),
    )
    if bucket_ms == 0:
        if start_seq is None or end_seq is None:
            return None, None, last_version
        return int(end_seq), int(start_seq), last_version
    if start_time is None or end_time is None:
        return None, None, last_version
    return (
        int(end_time) // bucket_ms,
        int(start_time) // bucket_ms,
        last_version,
    )


def attach_needed_curve_bodies(
    connection, pending, *, run_id, cached, resolution, limit, bases=None
):
    global CURVE_BODY_LOADS
    chosen = {
        bucket: (version, None)
        for (name, bucket), version in cached.items()
        if name == resolution
    }
    chosen = dict(sorted(chosen.items(), reverse=True)[:limit])
    bases = {} if bases is None else bases
    bodies = {}
    for interval in reversed(pending):
        payload = json.loads(interval["samples_json"])
        if isinstance(payload, dict) and payload.get("schema") == "indexed-curve.v1":
            last, _, _ = interval_bound_window(
                interval, payload, bucket_ms=_EQUITY_BUCKET_MS[resolution]
            )
            if last is not None and len(chosen) >= limit and last < min(chosen):
                # Do not assume an older interval with unknown bounds is
                # outside the window. Inspect its metadata independently.
                continue
            curve_id = str(payload["curve_id"])
            if interval.get("curve_json") is None:
                if curve_id not in bodies:
                    row = connection.execute(
                        "SELECT data_json FROM replay_prepared_curve WHERE run_id=? AND curve_id=?",
                        (run_id, curve_id),
                    ).fetchone()
                    if row is None:
                        raise ValueError("indexed curve basis is missing")
                    bodies[curve_id] = str(row[0])
                    CURVE_BODY_LOADS += 1
                interval["curve_json"] = bodies[curve_id]
        versions = {(resolution, bucket): value[0] for bucket, value in chosen.items()}
        chosen = plan_interval_curve_samples(
            [interval], versions, resolution=resolution, limit=limit, bases=bases
        )

    return len(chosen)


def interval_curve_origins(connection, pending):
    sessions = set()
    for item in pending:
        payload = json.loads(item["samples_json"])
        if isinstance(payload, dict) and payload.get("schema") == "indexed-curve.v1":
            sessions.add(str(payload["session_id"]))
    origins = {}
    for session_id in sessions:
        dataset = connection.execute(
            """
            SELECT actual_replay_start_ms, synthetic_origin_ms
            FROM replay_dataset_ref WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if dataset is None:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "training dataset time binding is missing",
                status_code=503,
            )
        origins[session_id] = {
            "actual_replay_start_ms": int(dataset["actual_replay_start_ms"]),
            "synthetic_origin_ms": dataset["synthetic_origin_ms"],
        }
    return origins


def curve_sample_offsets(times, start, end, *, bucket_ms, limit):
    if start >= end or limit <= 0:
        return []
    if bucket_ms == 0:
        return list(range(max(start, end - limit), end))
    selected = []
    index = end - 1
    while index >= start and len(selected) < limit:
        bucket = int(times[index]) // bucket_ms
        selected.append(index)
        low, high = start, index
        while low < high:
            mid = (low + high) // 2
            if int(times[mid]) // bucket_ms < bucket:
                low = mid + 1
            else:
                high = mid
        index = low - 1
    selected.reverse()
    return selected


def plan_interval_curve_samples(pending, cached, *, resolution, limit, bases):
    # Plan bucket endpoints before evaluating account values. Cached and
    # deferred samples compete in the same global window, including shared
    # buckets at interval boundaries. Keep the newest sequence/revision.
    chosen = {
        bucket: (version, None)
        for (name, bucket), version in cached.items()
        if name == resolution
    }
    chosen = dict(sorted(chosen.items(), reverse=True)[:limit])
    buckets = list(chosen)
    heapify(buckets)
    bucket_ms = _EQUITY_BUCKET_MS[resolution]

    def offer(bucket, version, sample):
        old = chosen.get(bucket)
        if old is not None and old[0] >= version:
            return
        if len(chosen) >= limit and bucket < buckets[0]:
            return
        if old is None:
            heappush(buckets, bucket)
        chosen[bucket] = (version, sample)
        if len(chosen) > limit:
            del chosen[heappop(buckets)]

    for interval in reversed(pending):
        payload = json.loads(interval["samples_json"])
        if isinstance(payload, dict) and payload.get("schema") == "indexed-curve.v1":
            start, end = int(payload["start"]), int(payload["end"])
            if start >= end:
                continue
            last_bucket, _first_bucket, _version = interval_bound_window(
                interval, payload, bucket_ms=bucket_ms
            )
            stored = interval.get("curve_json")
            if (
                last_bucket is not None
                and len(chosen) >= limit
                and last_bucket < buckets[0]
            ):
                continue
            if stored is None:
                raise ValueError("indexed curve basis is missing")
            key = payload.get("curve_id", stored)
            basis = bases.get(key)
            if basis is None:
                basis = json.loads(stored)
                if basis.get("schema") == "shared-curve.v1":
                    from ...broker.shared_prepared import restore_curve

                    basis = restore_curve(basis)
                elif basis.get("schema") == "prepared-curve.v2":
                    from ...broker.shared_prepared import restore_legacy_curve

                    basis = restore_legacy_curve(basis)
                elif basis.get("schema") == "tape-curve.v1":
                    from ..tape_interval import restore_curve

                    basis = restore_curve(basis)
                elif basis.get("schema") != "prepared-curve.v1":
                    raise ValueError("indexed curve basis version is unsupported")
                bases[key] = basis
            if basis.get("schema") == "tape-curve.v1" and (
                basis["times"][0] < interval["start_time_ms"]
                or basis["times"][-1] > interval["end_time_ms"]
                or basis["sequences"][0] < interval["start_sequence"]
                or basis["sequences"][-1] != interval["end_sequence"]
            ):
                raise ValueError("tape curve escaped its committed interval")
            if last_bucket is None:
                last_bucket = (
                    basis["start"] + end
                    if bucket_ms == 0
                    else int(basis["times"][end - 1]) // bucket_ms
                )
            if len(chosen) >= limit and last_bucket < buckets[0]:
                continue
            offsets = curve_sample_offsets(
                basis["sequences"]
                if bucket_ms == 0 and "sequences" in basis
                else basis["times"],
                start,
                end,
                bucket_ms=1 if bucket_ms == 0 and "sequences" in basis else bucket_ms,
                limit=limit,
            )
            for offset in offsets:
                sequence = (
                    basis["sequences"][offset]
                    if "sequences" in basis
                    else basis["start"] + offset + 1
                )
                bucket = (
                    sequence
                    if bucket_ms == 0
                    else int(basis["times"][offset]) // bucket_ms
                )
                version = (
                    sequence,
                    payload.get(
                        "fixed_revision", payload["revision_base"] + offset - start + 1
                    ),
                )
                offer(bucket, version, (payload, basis, offset))
        else:
            if not isinstance(payload, list) or any(
                not isinstance(row, list) or len(row) != 13 for row in payload
            ):
                raise ValueError("interval curve record is malformed")
            for row in payload:
                if row[1] == resolution:
                    offer(int(row[2]), (int(row[3]), int(row[4])), row)
    return chosen


def expand_pending_interval_curves(
    pending, origins, *, run_id, resolution, limit, cached=None, bases=None
):
    cached = {} if cached is None else cached
    bases = {} if bases is None else bases
    plan = plan_interval_curve_samples(
        pending, cached, resolution=resolution, limit=limit, bases=bases
    )
    grouped = {}
    for _version, sample in plan.values():
        if sample is None or isinstance(sample, list):
            continue
        _payload, basis, offset = sample
        grouped.setdefault(id(basis), (basis, []))[1].append(offset)
    if grouped:
        from ...broker.shared_prepared import prefetch_account_samples

        for basis, offsets in grouped.values():
            prefetch_account_samples(basis, offsets)
    expanded = {}
    for bucket, (version, sample) in plan.items():
        if sample is None:
            continue
        if isinstance(sample, list):
            if sample[0] != run_id:
                raise ValueError("interval curve record is malformed")
            expanded[(run_id, resolution, bucket)] = sample
            continue
        payload, basis, offset = sample
        equity, cash, pnl = basis["samples"][offset]
        upsert_equity_samples(
            None,
            run_id=run_id,
            session_id=payload["session_id"],
            policy=payload["policy"],
            revealed=payload["revealed"],
            state={
                "cursor": {"virtual_time_ms": basis["times"][offset]},
                "source_sequence": version[0],
                "revision": version[1],
                "state_hash": (
                    "tape-interval-state:"
                    if basis.get("schema") == "tape-curve.v1"
                    else "interval-state:"
                )
                + basis["chains"][offset + 1],
            },
            component_state={
                "account": {
                    "equity": equity,
                    "cash_balance": cash,
                    "unrealized_pnl": pnl,
                },
                "ledger": {"tail_hash": basis["ledger_hash"]},
            },
            now_ms=payload["created_at_ms"],
            retain=False,
            pending_samples=expanded,
            resolutions=(resolution,),
            origin=origins[str(payload["session_id"])],
        )
    # Fully covered legacy records can retire. Indexed records remain the
    # reconstructible authority for other resolutions and larger windows;
    # persisted sample versions prevent repeated account evaluation.
    completed = []
    available = dict(cached)
    for row in expanded.values():
        available[(row[1], row[2])] = (row[3], row[4])
    for interval in pending:
        payload = json.loads(interval["samples_json"])
        if isinstance(payload, list) and all(
            row[0] == run_id
            and available.get((row[1], row[2]), (-1, -1)) >= (row[3], row[4])
            for row in payload
        ):
            completed.append(interval["command_id"])
    return list(expanded.values()), completed


def persist_interval_curve_samples(
    connection, *, run_id, rows, materialized_ids, resolution
):
    if rows:
        write_equity_samples(connection, rows, historical=True)
    for command_id in materialized_ids:
        connection.execute(
            "UPDATE replay_interval_curve SET materialized=1 WHERE run_id=? AND command_id=?",
            (run_id, command_id),
        )
    if rows:
        if materialized_ids:
            for name, _bucket_ms, keep in _EQUITY_RESOLUTIONS:
                prune_equity_resolution(
                    connection, run_id=run_id, resolution=name, limit=keep
                )
        else:
            keep = next(
                item[2] for item in _EQUITY_RESOLUTIONS if item[0] == resolution
            )
            prune_equity_resolution(
                connection, run_id=run_id, resolution=resolution, limit=keep
            )


def write_interval_curve(
    connection,
    *,
    run_id,
    command_id,
    end_sequence,
    rows,
    start_sequence=None,
    start_time_ms=None,
    end_time_ms=None,
):
    connection.execute(
        """
        INSERT INTO replay_interval_curve(
            run_id, command_id, end_sequence, samples_json,
            start_sequence, start_time_ms, end_time_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            command_id,
            end_sequence,
            canonical_json(list(rows)),
            start_sequence,
            start_time_ms,
            end_time_ms,
        ),
    )


def prune_equity_resolution(connection, *, run_id, resolution, limit):
    connection.execute(
        """DELETE FROM replay_equity_sample WHERE rowid IN (
               SELECT rowid FROM replay_equity_sample
               WHERE run_id = ? AND resolution = ?
               ORDER BY bucket_id DESC LIMIT -1 OFFSET ?
           )""",
        (run_id, resolution, limit),
    )
