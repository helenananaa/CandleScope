"""Controlled HTTP queue comparison; not a public-exchange throughput benchmark."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import platform
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

import aiohttp
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.exchanges.public_admission import PublicAdmission, PublicDemand, TrafficClass
from app.exchanges.rate_limits import RateLimitManager, RateLimitRule, HistoricalRequest


def percentiles(values):
    ordered = sorted(values)
    return {f"p{p}_ms": round(ordered[min(len(ordered)-1, int((len(ordered)-1)*p/100))], 3)
            for p in (50, 95, 99)}


async def scenario(quantum):
    received = []
    async def handle(request):
        label = request.match_info["label"]
        received.append(label)
        await asyncio.sleep(0.002)
        return web.json_response({"id": label, "value": 42})
    app = web.Application()
    app.router.add_get("/{label}", handle)
    server = web.AppRunner(app)
    await server.setup()
    site = web.TCPSite(server, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    scheduler = PublicAdmission(RateLimitManager(), max_in_flight=1, max_priority_bypass=quantum)
    rule = RateLimitRule("fixture", "fixture:ip", 1000, 1)
    request = HistoricalRequest("fixture", "spot", "/value", "FIXTURE")
    held = await scheduler.acquire([rule], request)
    waits, bodies, loop_lags = {"bg": [], "fg": []}, [], []
    done = asyncio.Event()
    async def heartbeat():
        while not done.is_set():
            start = time.perf_counter()
            await asyncio.sleep(0.005)
            loop_lags.append(max(0, time.perf_counter()-start-0.005)*1000)
    tracemalloc.start()
    cpu_start, start = time.process_time(), time.perf_counter()
    monitor = asyncio.create_task(heartbeat())
    try:
        async with aiohttp.ClientSession() as client:
            async def work(label, traffic):
                submitted = time.perf_counter()
                permit = await scheduler.acquire([rule], request, demand=PublicDemand(traffic))
                waits[label[:2]].append((time.perf_counter()-submitted)*1000)
                status = None
                try:
                    async with client.get(origin + "/" + label) as response:
                        status = response.status
                        bodies.append(await response.json())
                finally:
                    permit.finish(status_code=status, response_unknown=status is None)
            tasks = [asyncio.create_task(work(f"bg{i}", TrafficClass.BACKGROUND)) for i in range(32)]
            tasks += [asyncio.create_task(work(f"fg{i}", TrafficClass.INTERACTIVE)) for i in range(128)]
            while scheduler.snapshot()["pending"] != len(tasks):
                await asyncio.sleep(0)
            peak_pending = scheduler.snapshot()["pending"]
            held.finish(status_code=200)
            await asyncio.wait_for(asyncio.gather(*tasks), 30)
    finally:
        done.set()
        await monitor
        peak_bytes = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        await server.cleanup()
    snapshot = scheduler.snapshot()
    assert len(received) == len(set(received)) == 160
    assert snapshot["counts"]["attempts"] == snapshot["counts"]["completed"] == 161  # Includes held gate.
    assert snapshot["in_flight"] == snapshot["pending"] == 0
    first_bg = next(i for i, label in enumerate(received) if label.startswith("bg"))
    if quantum == 8:
        assert [label[:2] for label in received[:144]] == (["fg"]*8 + ["bg"])*16
    return {"model": "strict_priority" if quantum > 1000 else "bounded_priority_bypass",
            "http_requests": len(received), "first_background_position": first_bg,
            "pending_peak": peak_pending, "waiting": {key: percentiles(value) for key,value in waits.items()},
            "loop_lag": percentiles(loop_lags), "wall_seconds": round(time.perf_counter()-start, 3),
            "cpu_seconds": round(time.process_time()-cpu_start, 3), "python_peak_bytes": peak_bytes,
            "results_sha256": hashlib.sha256(json.dumps(sorted(bodies, key=lambda b:b["id"]), sort_keys=True).encode()).hexdigest()}


async def main(output):
    rows = []
    for _ in range(3):
        for quantum in (1000000, 8):
            rows.append(await scenario(quantum))
    assert len({row["results_sha256"] for row in rows}) == 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema": "candlescope.admission-loopback/1", "platform": platform.platform(),
        "python": sys.version, "input": {"foreground": 128, "background": 32, "concurrency": 1,
        "response_delay_seconds": 0.002, "quota_capacity": 1000}, "runs": rows,
        "scope": "Loopback HTTP; timings are observations on this host, not public source or desktop SLA qualification."}, indent=2)+"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args().output))
