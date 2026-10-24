"""Offline replay display P95/soak against captured, already-prepared market input.

Run with backend on PYTHONPATH and test dependencies installed. --requests is a
JSON list of {label, session, payload}, captured from indicator-compute requests.
--data is a CLOSED native profile's data directory. The runner makes a private
copy, does not start acquisition/inventory, and fails if input is missing. Use
an older checkout on PYTHONPATH to record --reference before testing a candidate.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import math
import os
import shutil
import statistics
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from app.core.executors import executors_snapshot
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.replay_context import ReplayHistoryContext
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.replay.history_archive import ReplayHistoryRepository
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.timing import RequestTiming, use_timing
from tests.fixtures.replay.service_fakes import replay_settings


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def quantiles(values):
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median": statistics.median(ordered),
        "p95": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "maximum": max(ordered),
    }


async def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    data = args.output / "data"
    shutil.copytree(args.data, data)
    requests = json.loads(args.requests.read_text())
    assert requests and len({r["label"] for r in requests}) == len(requests)
    reference = json.loads(args.reference.read_text()) if args.reference else {}
    replay = ReplayService(
        settings=replace(replay_settings(data / "replay.db"), max_warmup_bars=1000),
        store=ReplaySQLiteStore(data / "replay.db"),
        repository=ReplayHistoryRepository(data / "replay-history"),
        native_intervals=lambda _: ("1m",),
    )
    await replay.start()
    adapter = BarPreparationAdapter(
        data / "prepared-inputs", coordinator=None, replay_service=replay
    )
    preparation = PreparationService(
        PreparationRepository(data / "data-preparation.sqlite3"), adapter
    )
    # Start neither acquisition nor inventory: copied publication metadata may
    # refer to original files. Only existing, retained READY inputs are allowed.
    replay.history_context = ReplayHistoryContext(preparation, wait_seconds=2)
    cache = getattr(adapter, "market_inputs", None)
    modules = ["bar_adapter", "replay_context", "service"]
    if cache is not None:
        modules.extend(["market_inputs", "market_projection"])
    source_files = {}
    for name in modules:
        path = Path(importlib.import_module("app.data_preparation." + name).__file__)
        source_files[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (args.output / "provenance.json").write_text(
        json.dumps(
            {
                "source_files": source_files,
                "source_data": str(args.data),
                "source_database_sha256": hashlib.sha256(
                    (args.data / "replay.db").read_bytes()
                ).hexdigest(),
                "seconds_requested": args.seconds,
                "cycles_requested": args.cycles,
                "started_unix_seconds": time.time(),
                "network_enabled": False,
            },
            indent=2,
        )
    )
    before = {
        sid: (await replay.get_session(sid))["snapshot"]
        for sid in {r["session"] for r in requests}
    }
    # Mounted replay charts keep event subscriptions open. Preserve that normal
    # lifecycle during load; idle actor retirement is a separate regression.
    subscriptions = [
        await replay.subscribe(sid, after_sequence=None, data_epoch=None)
        for sid in before
    ]
    run_ids = set()
    for request in requests:
        binding = await replay.training.store.history_binding(
            session_id=request["session"], track_id=request["payload"]["track_id"]
        )
        run_ids.add(binding["run_id"])
    before_portfolios = {
        run_id: (await replay.training.store.get_market_tracks(run_id))["portfolio"]
        for run_id in run_ids
    }
    if args.reference:
        assert set(reference) == {r["label"] for r in requests}, (
            "reference workload differs"
        )
    resources, cancelled, request_count = [], 0, 0
    epoch = time.perf_counter()
    cycle = 0
    try:
        while cycle < args.cycles or time.perf_counter() - epoch < args.seconds:
            phase = "resident"
            if cache and cycle % 20 == 0:
                cache.clear()
                phase = "cold-market"
            if cache and cycle % 50 == 49:
                cache.clear()
                cache.max_bytes = 2 * 1024**2
                phase = "cache-pressure"
            elif cache:
                cache.max_bytes = 64 * 1024**2
            # Rebuild math on every cycle: the soak must exercise market reads,
            # not repeatedly hit already-zero-read indicator checkpoints.
            for path in data.glob("replay.db.indicator-cache.sqlite3*"):
                path.unlink()

            async def compute(request):
                started = time.perf_counter()
                timing = RequestTiming()
                with use_timing(timing):
                    result = await replay.training.canonical_indicator_compute(
                        request["session"], **request["payload"]
                    )
                assert result["status"] == "ready", result
                actual = digest(result["payload"])
                expected = reference.setdefault(request["label"], actual)
                assert actual == expected, (request["label"], actual, expected)
                return {
                    "label": request["label"],
                    "seconds": time.perf_counter() - started,
                    "prefix_rows": result["prefix_rows_read"],
                    "timings": timing.values,
                }

            started = time.perf_counter()
            cpu = time.process_time()
            calls = await asyncio.gather(*(compute(request) for request in requests))
            if cycle % 50 == 25:
                # Cancellation is joined before the next cache or checkpoint
                # reset, including the underlying calculation-worker drain.
                task = asyncio.create_task(compute(requests[0]))
                await asyncio.sleep(0.001)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    cancelled += 1
            row = {
                "cycle": cycle,
                "phase": phase,
                "elapsed": time.perf_counter() - epoch,
                "seconds": time.perf_counter() - started,
                "cpu": time.process_time() - cpu,
                "calls": calls,
            }
            request_count += len(calls)
            snapshot = cache.snapshot() if cache else None
            if snapshot:
                assert snapshot["retained_bytes"] <= snapshot["max_bytes"], snapshot
                assert (
                    snapshot["entries"] <= snapshot["max_entries"]
                    and snapshot["inflight"] == 0
                ), snapshot
            if cycle % 5 == 0:
                sampled = await asyncio.to_thread(
                    subprocess.check_output,
                    ["ps", "-o", "rss=", "-p", str(os.getpid())],
                    text=True,
                )
                rss = int(sampled.strip()) * 1024
                resource = {
                    "cycle": cycle,
                    "elapsed": time.perf_counter() - epoch,
                    "rss_bytes": rss,
                    "cache": snapshot,
                }
                resources.append(resource)
                with (args.output / "resources.jsonl").open("a") as stream:
                    stream.write(json.dumps(resource) + "\n")
            with (args.output / "observations.jsonl").open("a") as stream:
                stream.write(json.dumps(row) + "\n")
            if cycle % 20 == 0:
                print(
                    json.dumps(
                        {
                            "cycle": cycle,
                            "elapsed": row["elapsed"],
                            "seconds": row["seconds"],
                            "cache": snapshot,
                        }
                    ),
                    flush=True,
                )
            cycle += 1
            if args.seconds:
                await asyncio.sleep(0.05)
        after = {sid: (await replay.get_session(sid))["snapshot"] for sid in before}
        assert before == after, "display load changed execution/account state"
        after_portfolios = {
            run_id: (await replay.training.store.get_market_tracks(run_id))["portfolio"]
            for run_id in run_ids
        }
        assert before_portfolios == after_portfolios, (
            "display load changed shared portfolios"
        )
    finally:
        for actor, subscription in subscriptions:
            await actor.unsubscribe(subscription.token)
        await replay.shutdown()
    (args.output / "reference.json").write_text(json.dumps(reference, indent=2))
    # Read latency samples after the load/RSS observation and shutdown. Keeping
    # all per-request timing dictionaries during the run would measure the
    # harness's own growing retention instead of the service.
    observations = [
        json.loads(line)
        for line in (args.output / "observations.jsonl").read_text().splitlines()
    ]
    summary = {
        "cycles": cycle,
        "seconds": time.perf_counter() - epoch,
        "request_count": request_count,
        "cancelled_observers": cancelled,
        "account_state_unchanged": True,
        "shared_portfolios_unchanged": True,
        "session_count": len(before),
        "portfolio_sha256": digest(before_portfolios),
        "errors": 0,
        "request_seconds": quantiles(
            [call["seconds"] for row in observations for call in row["calls"]]
        ),
        "phases": {
            phase: quantiles(
                [row["seconds"] for row in observations if row["phase"] == phase]
            )
            for phase in {row["phase"] for row in observations}
        },
        "peak_sampled_rss_bytes": max(row["rss_bytes"] for row in resources),
        "executors": executors_snapshot(),
        "source_request_sha256": hashlib.sha256(args.requests.read_bytes()).hexdigest(),
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--seconds", type=float, default=0)
    parser.add_argument("--cycles", type=int, default=40)
    args = parser.parse_args()
    if args.seconds < 0 or args.cycles < 1:
        parser.error("use nonnegative seconds and at least one cycle")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
