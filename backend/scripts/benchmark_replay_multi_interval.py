"""Disposable real-service eight-position BAR interval performance probe."""

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import pytest

from app.replay.training.models import ReplayV2CommandType as C
from tests.fixtures.replay.multi_interval_fakes import make_multi
from tests.fixtures.replay.shared_market_fakes import install_shared_market


async def benchmark(root, *, minutes, count, tracks, profile_path=None):
    patch = pytest.MonkeyPatch()
    install_shared_market(patch, root / "market")
    t = perf_counter()
    service, run, session, send = await make_multi(
        root / "run", tracks=tracks, horizon=minutes * count + 10
    )
    opened = (perf_counter() - t) * 1000
    try:
        t = perf_counter()
        prepared = await service.training.prepare_indexed_run(run)
        preparation = (perf_counter() - t) * 1000
        rows = []
        for i in range(count):
            cursor = (await service.get_session_state(session))["cursor"]
            writes = service.store._metrics["transactions"]
            t = perf_counter()
            if profile_path is not None:
                import cProfile

                profiler = cProfile.Profile()
                profiler.enable()
            result = await send(
                f"advance-{i}",
                C.ADVANCE_TO,
                dict(
                    virtual_time_ms=cursor["virtual_time_ms"] + minutes * 60000,
                    stop_on_event=False,
                ),
            )
            if profile_path is not None:
                profiler.disable()
                import pstats

                with profile_path.with_suffix(f".{i}.txt").open(
                    "w", encoding="utf-8"
                ) as stream:
                    pstats.Stats(profiler, stream=stream).sort_stats(
                        "cumtime"
                    ).print_stats(60)
            row = dict(
                ms=round((perf_counter() - t) * 1000, 3),
                events=result["cursor"]["source_sequence"] - cursor["source_sequence"],
                transactions=service.store._metrics["transactions"] - writes,
            )
            rows.append(row)
            print(json.dumps(row), flush=True)
        return dict(
            workload="synthetic real service, no HTTP/browser",
            tracks=tracks,
            minutes=minutes,
            open_ms=opened,
            preparation_ms=preparation,
            prepared=prepared,
            samples=rows,
        )
    finally:
        await service.shutdown(step_timeout=5)
        from app.replay.shared_market_index import (
            _close_index_connections,
            _index_state,
        )

        for key in list(_index_state):
            if Path(key).resolve().is_relative_to(root.resolve()):
                _close_index_connections(key)
        patch.undo()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, default=1440)
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--tracks", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="replay-multi-interval-") as folder:
        result = asyncio.run(
            benchmark(
                Path(folder),
                minutes=args.minutes,
                count=args.count,
                tracks=args.tracks,
                profile_path=args.output if args.profile else None,
            )
        )
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
