"""Point-in-time portfolio review reads and lossless interval exports."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from .errors import TrainingRunError
from .multi_interval import combine_equity_summaries
from .multi_interval_store import reconstruct_portfolio_interval


async def capture(owner, run_id):
    run_id = owner._identifier(run_id, field_name="run_id")
    # Take a short consistent read; valuation/export run after releasing this
    # lock so a large review request cannot hold up account advancement.
    from .multitrack import TrainingRunActor

    actor = owner._run_actors.setdefault(run_id, TrainingRunActor(run_id))
    async with actor.serialized():

        def read(connection):
            run = connection.execute(
                "SELECT settlement_asset FROM replay_training_run WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            tracks = connection.execute(
                "SELECT track_id,revision,virtual_time_ms,subscription_tier,symbol,exchange,market_type FROM replay_training_market_track WHERE run_id=?",
                (run_id,),
            ).fetchall()
            times = [
                row[2] for row in tracks if row[3] == "FULL" and row[2] is not None
            ]
            end = min(times) if times else 0
            rows = connection.execute(
                "SELECT rowid,start_time_ms,end_time_ms,summary_json,basis_json FROM replay_multi_bar_interval WHERE run_id=? AND end_time_ms<=? ORDER BY end_time_ms,rowid",
                (run_id, end),
            ).fetchall()
            return dict(
                run_id=run_id,
                end=end,
                versions={row[0]: row[1] for row in tracks},
                settlement_asset=run[0],
                markets=[
                    dict(
                        track_id=row[0],
                        symbol=row[4],
                        exchange=row[5],
                        market_type=row[6],
                    )
                    for row in tracks
                ],
                rows=[tuple(row) for row in rows],
            )

        return await owner.store.base_store.run_extension_read(read)


def curve(snapshot, *, input_root, limit=1000, bucket_ms=3600000):
    if (
        type(limit) is not int
        or not 1 <= limit <= 5000
        or type(bucket_ms) is not int
        or bucket_ms < 1
    ):
        raise ValueError("invalid portfolio curve window")
    rows = snapshot["rows"]
    result = dict(
        protocol="replay.v3",
        run_id=snapshot["run_id"],
        scope="RECORDED_PORTFOLIO_INTERVALS",
        versions=snapshot["versions"],
        available=bool(rows),
        complete_training_history=False,
        bucket_ms=bucket_ms,
        samples=[],
        summary=None,
        span_ms=0,
        truncated=False,
    )
    if not rows:
        return result
    buckets, included = {}, []
    for row in reversed(rows):
        basis = json.loads(row[4])
        rebuilt = reconstruct_portfolio_interval(
            basis, input_root=input_root, limit=limit, bucket_ms=bucket_ms
        )
        included.append(row)
        observations = rebuilt["points"] or [(row[2], rebuilt["last"])]
        for at, equity in observations:
            bucket = at // bucket_ms
            # Descending commit order keeps the final financial observation
            # when multiple events share the same timestamp.
            if bucket not in buckets or at > buckets[bucket][0]:
                buckets[bucket] = (at, equity)
        if len(buckets) >= limit:
            break
    ordered = sorted(buckets.values())[-limit:]
    start = min(row[1] for row in included)
    result.update(
        samples=[
            dict(offset_ms=at - start, equity=format(Decimal(value), "f"))
            for at, value in ordered
        ],
        summary=combine_equity_summaries(
            [json.loads(row[3]) for row in reversed(included)]
        ),
        span_ms=max(row[2] for row in included) - start,
        truncated=len(included) < len(rows) or len(buckets) > limit,
    )
    # Absolute archive times and local file references never leave this API.
    result["summary"].pop("trough_time_ms", None)
    for key in ("first", "last", "peak", "trough", "max_drawdown"):
        result["summary"][key] = format(Decimal(result["summary"][key]), "f")
    return result


def export_intervals(snapshot, *, input_root):
    """Stream every recorded interval plus its exact inputs, without sampling.

    This is a complete export of the recorded portfolio-curve coverage, not a
    portable archive of an entire training run. The footer detects truncation.
    """
    root = Path(input_root).resolve()
    rows = snapshot["rows"]
    origin = min((row[1] for row in rows), default=snapshot["end"])
    digest = hashlib.sha256()
    count = 0

    def encode(value):
        nonlocal count
        raw = (
            json.dumps(value, separators=(",", ":"), ensure_ascii=True) + "\n"
        ).encode()
        digest.update(raw)
        count += 1
        return raw

    yield encode(
        dict(
            schema="replay.portfolio-curve-export.v1",
            run_id=snapshot["run_id"],
            scope="RECORDED_PORTFOLIO_INTERVALS",
            complete_training_history=False,
            versions=snapshot["versions"],
            settlement_asset=snapshot["settlement_asset"],
            markets=snapshot["markets"],
            span_ms=snapshot["end"] - origin,
            intervals=len(rows),
            order="offset_ms,event_phase,track_id,sequence",
        )
    )
    for index, row in enumerate(rows):
        basis = json.loads(row[4])
        summary = json.loads(row[3])
        summary.pop("trough_time_ms", None)
        if basis["schema"] == "portfolio-point.v1":
            yield encode(
                dict(
                    kind="point",
                    offset_ms=basis["time_ms"] - origin,
                    equity=basis["equity"],
                )
            )
            continue
        legs = [
            dict(
                track_id=leg["track_id"],
                side=leg["side"],
                quantity=leg["quantity"],
                entry=leg["entry"],
                contract_size=leg["rule"]["contract_size"],
            )
            for leg in basis["legs"]
        ]
        yield encode(
            dict(
                kind="interval",
                index=index,
                start_ms=row[1] - origin,
                end_ms=row[2] - origin,
                cash=basis["cash"],
                legs=legs,
                summary=summary,
                initial_prices={
                    t["track_id"]: t["initial_mark"] for t in basis["tracks"]
                },
            )
        )
        for track in basis["tracks"]:
            path = (root / track["public_path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("portfolio input escaped its owner")
            # Reuse the verified legacy reader on a missing derived index.
            from .multi_interval_store import portfolio_price_rows

            events = portfolio_price_rows(
                path, track["public_checksum"], track["mark_start"], track["mark_end"]
            )
            for ordinal, (at, phase, kind, _, price) in enumerate(events):
                virtual = at - basis["actual_delta"]
                if (
                    kind != "MARK_INDEX"
                    or phase != 30
                    or not row[1] < virtual <= row[2]
                ):
                    raise ValueError("portfolio export crossed its committed range")
                yield encode(
                    dict(
                        kind="mark",
                        interval=index,
                        offset_ms=virtual - origin,
                        event_phase=phase,
                        track_id=track["track_id"],
                        sequence=ordinal,
                        price=price,
                    )
                )
    yield (
        json.dumps(dict(kind="complete", records=count, sha256=digest.hexdigest()))
        + "\n"
    ).encode()


def export_chunks(snapshot, *, input_root):
    buffer = bytearray()
    for record in export_intervals(snapshot, input_root=input_root):
        buffer.extend(record)
        if len(buffer) >= 65536:
            yield bytes(buffer)
            buffer.clear()
    if buffer:
        yield bytes(buffer)
