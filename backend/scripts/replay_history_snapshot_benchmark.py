"""Real-service comparison of detached history copying versus shared snapshots.

Uses disposable synthetic HEDGE runs; the comparison disables only the shared
snapshot optimization on the current engine, not all earlier optimizations.
"""

import argparse
import asyncio
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from app.replay.broker.execution import ConservativeBarBroker
from app.replay.training.models import ReplayV2CommandType
from tests.test_replay_hedge_wave_commit import seed
from tests.test_replay_v2_training_phase6 import _send


async def measure(root, trips, shared):
    service, run, session = await seed(root / "run.db")
    original = ConservativeBarBroker._owned_snapshot_with_encoding
    try:
        await _send(service, run_id=run, session_id=session, command_id="warm",
                    command_type=ReplayV2CommandType.ADVANCE, payload={"basis": "BASE_BAR", "count": 1})
        for i in range(trips * 2):
            await _send(service, run_id=run, session_id=session, command_id=f"trade-{i}",
                        command_type=ReplayV2CommandType.PLACE_ORDER,
                        payload={"client_order_id": f"trade-{i}", "side": "BUY" if i % 2 == 0 else "SELL",
                                 "position_side": "LONG", "order_type": "MARKET", "quantity": "0.001",
                                 "reduce_only": i % 2 == 1, "limit_price": None, "stop_price": None})
        if not shared:
            def detached(self):
                state, encoded = self._snapshot_with_encoding(detached=False)
                for key in ("orders", "fills", "closed_trades", "warnings", "ledger", "client_order_ids"):
                    state[key] = self._copy_snapshot_component(state[key])
                return state, encoded
            ConservativeBarBroker._owned_snapshot_with_encoding = detached
        samples = []
        for i in range(4):
            started = perf_counter()
            await _send(service, run_id=run, session_id=session, command_id=f"step-{i}",
                        command_type=ReplayV2CommandType.ADVANCE, payload={"basis": "BASE_BAR", "count": 1})
            samples.append((perf_counter() - started) * 1000)
        snapshot = (await service.get_session(session))["snapshot"]
        return {"shared": shared, "round_trips": trips, "fills": len(snapshot["components"]["fills"]),
                "median_ms": round(median(samples), 3), "samples_ms": [round(v, 3) for v in samples]}, snapshot["state_hash"]
    finally:
        ConservativeBarBroker._owned_snapshot_with_encoding = original
        await service.shutdown(step_timeout=1)


async def run(root, trips):
    results, hashes = [], []
    for name, shared in (("detached", False), ("shared", True)):
        folder = root / name
        folder.mkdir()
        result, digest = await measure(folder, trips, shared)
        results.append(result)
        hashes.append(digest)
    assert hashes[0] == hashes[1]
    return {"workload": "synthetic-service-positioned-history", "same_final_state": True, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-trips", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="replay-history-bench-") as folder:
        result = asyncio.run(run(Path(folder).resolve(), args.round_trips))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
