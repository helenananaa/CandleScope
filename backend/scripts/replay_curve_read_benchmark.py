"""Disposable service/SQLite/shared-index curve benchmark (requires test dependencies).

Run from backend: python -m scripts.replay_curve_read_benchmark --output receipt.json
Synthetic history measures curve reads, not browser or live replay latency.
"""

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from app.replay.broker import shared_prepared
from app.replay.canonical import canonical_json
from app.replay import shared_market_index
from tests.fixtures.replay.service_fakes import START_MS
from tests.test_replay_hedge_wave_commit import seed
from tests.test_replay_shared_market_index import market


async def measure(root):
    service, run, session = await seed(root / "run.db")
    sample_calls = 0
    original = shared_prepared.account_sample

    def sample(*args):
        nonlocal sample_calls
        sample_calls += 1
        return original(*args)

    try:
        count, chunk = 96_000, 8_000
        started = perf_counter()
        obj, base = market(root, count)
        indexing_ms = (perf_counter() - started) * 1000
        view = shared_market_index.MarketRange(base.parts, offset_ms=START_MS)
        basis = {
            "schema": "shared-curve.v1", "market": view.descriptor(),
            "reference": view.reference(), "start": 0, "seed": "sha256:" + "0" * 64,
            "account": {"legs": [["1", "100"], ["-0.5", "102"]], "cash": "10000"},
            "ledger_hash": "sha256:" + "1" * 64,
        }

        def insert(c):
            c.execute("DELETE FROM replay_equity_sample WHERE run_id=?", (run,))
            c.execute("INSERT INTO replay_prepared_curve VALUES (?,?,?)", ("benchmark", run, canonical_json(basis)))
            for start in range(0, count, chunk):
                payload = {
                    "schema": "indexed-curve.v1", "curve_id": "benchmark",
                    "start": start, "end": start + chunk, "session_id": session,
                    "revision_base": start, "policy": "NONE", "revealed": True,
                    "created_at_ms": 0,
                }
                c.execute(
                    "INSERT INTO replay_interval_curve(run_id,command_id,end_sequence,samples_json) VALUES (?,?,?,?)",
                    (run, str(start), start + chunk, canonical_json(payload)),
                )

        await service.store.run_extension_write(insert)
        shared_prepared.account_sample = sample
        results = []
        for resolution, limit in (("1H", 12), ("1H", 12), ("EVENT", 20), ("EVENT", 20), ("AUTO", 2000)):
            sample_calls = 0
            before = service.store.diagnostics()["transactions"]
            started = perf_counter()
            response = await service.training.equity(run, resolution=resolution, limit=limit)
            elapsed = (perf_counter() - started) * 1000
            for row in response["samples"]:
                offset = row["source_sequence"] - 1
                assert row["equity"] == original(basis["account"], view.row(offset)[5])[0]
            results.append({
                "request": resolution, "selected": response["resolution"], "limit": limit,
                "samples": len(response["samples"]), "account_evaluations": sample_calls,
                "write_transactions": service.store.diagnostics()["transactions"] - before,
                "milliseconds": round(elapsed, 3),
            })
        assert results[0]["account_evaluations"] == 12
        assert results[1]["account_evaluations"] == results[1]["write_transactions"] == 0
        assert results[2]["account_evaluations"] == 20
        assert results[3]["account_evaluations"] == results[3]["write_transactions"] == 0
        return {"kind": "synthetic-service-curve-read", "source_bars": count,
                "intervals": count // chunk, "indexing_ms": round(indexing_ms, 3), "queries": results}
    finally:
        shared_prepared.account_sample = original
        await service.shutdown(step_timeout=1)
        # Close disposable index handles before Windows removes the temporary tree.
        for path in list(shared_market_index._index_state):
            if Path(path).is_relative_to(root):
                shared_market_index._close_index_connections(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="replay-curve-benchmark-") as folder:
        result = asyncio.run(measure(Path(folder).resolve()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
