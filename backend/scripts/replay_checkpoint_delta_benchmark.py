"""Synthetic real-service checkpoint A/B; includes retained full-base bytes."""

import argparse
import asyncio
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from app.replay.storage import checkpoint_delta as delta
from app.replay.training.models import ReplayV2CommandType
from tests.test_replay_checkpoint_delta import advance
from tests.test_replay_hedge_wave_commit import seed
from tests.test_replay_v2_training_phase6 import _send


async def measure(root, enabled):
    original, threshold = delta.compact, delta.MIN_BYTES
    delta.MIN_BYTES = threshold if enabled else 10**12
    service = None
    written = 0
    def counted(c, session, payload):
        nonlocal written
        before = c.execute("SELECT MAX(base_id) FROM replay_checkpoint_base").fetchone()[0]
        packed, base_id = original(c, session, payload)
        after = c.execute("SELECT MAX(base_id) FROM replay_checkpoint_base").fetchone()[0]
        written += len(packed)
        if after is not None and before != after:
            written += c.execute("SELECT length(payload) FROM replay_checkpoint_base WHERE base_id=?", (after,)).fetchone()[0]
        return packed, base_id
    try:
        service, run, session = await seed(root / "run.db")
        await advance(service, run, session, 8)
        delta.compact = counted
        timings = []
        for i in range(40):
            started = perf_counter()
            await _send(service, run_id=run, session_id=session, command_id=f"speed-{i}",
                        command_type=ReplayV2CommandType.SET_SPEED, payload={"speed": (1, 5)[i % 2]})
            timings.append((perf_counter() - started) * 1000)
        state = await service.get_session_state(session)
        retained = await service.store.run_extension_read(lambda c: sum(
            c.execute(f"SELECT COALESCE(SUM(length(payload)),0) FROM {table}").fetchone()[0]
            for table in ("replay_checkpoint", "replay_checkpoint_base")
        ))
        return {"delta_enabled": enabled, "commands": len(timings),
                "checkpoint_and_base_blob_bytes_written": written,
                "retained_checkpoint_and_base_bytes": retained,
                "median_ms": round(median(timings), 3), "p95_ms": round(sorted(timings)[37], 3)}, state["state_hash"]
    finally:
        delta.compact, delta.MIN_BYTES = original, threshold
        if service is not None:
            await service.shutdown(step_timeout=1)


async def run(root):
    results, hashes = [], []
    for name, enabled in (("full", False), ("delta", True)):
        folder = root / name
        folder.mkdir()
        result, state_hash = await measure(folder, enabled)
        results.append(result)
        hashes.append(state_hash)
    assert hashes[0] == hashes[1]
    return {"workload": "synthetic-service-40-speed-commands", "same_final_state": True,
            "results": results,
            "note": "BLOB values written include new full bases; excludes other tables, indexes and WAL amplification. Timings include instrumentation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="replay-delta-bench-") as folder:
        result = asyncio.run(run(Path(folder).resolve()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
