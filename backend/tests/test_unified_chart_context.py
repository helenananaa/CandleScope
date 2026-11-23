"""Guarded chart computation through real unified Python and JSONL entries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.plugin_lifecycle import PackageStore, build_package
from app.plugin_lifecycle.api import create_unified_router
from app.plugin_lifecycle.bootstrap import prepare_unified
from app.plugin_security_v2.management import LocalManagementGuard

PREFIX = "/api/v2/plugins/manage/unified"
DOCUMENT = "chart-window-a"
CHART = {
    "schema": "candlescope.unified-chart/1",
    "documentId": DOCUMENT,
    "chartId": "same-cell",
    "instanceId": "chart-instance",
    "mode": "replay",
    "runId": "run-btc",
    "trackId": "btc",
    "seriesId": "btc-perp-1m",
    "symbol": "BTC/USDT",
    "interval": "1m",
    "dataRevision": "reveal-7",
    "visibleThroughMs": 1500,
}
BAR = {
    "openTimeMs": 1000,
    "observedThroughMs": 1500,
    "open": 1,
    "high": 3,
    "low": 1,
    "close": 2,
    "volume": 1,
    "closed": False,
}


@pytest.fixture
def chart_host(tmp_path):
    app = FastAPI()
    app.include_router(create_unified_router())
    guard = LocalManagementGuard(["http://127.0.0.1:15173"])
    store = PackageStore(tmp_path / "store")
    candidate = tmp_path / "workbench.cspkg"
    sample = Path(__file__).resolve().parents[2] / "examples/unified-plugins/workbench"
    build_package(sample, candidate)
    review = store.stage(candidate)
    store.activate(
        review.sha256,
        expected_revision=0,
        acknowledgement=f"full-trust:{review.sha256}",
    )
    prepare_unified(app, store=store)
    app.state.unified_management_guard = guard
    return app, app.state.unified_plugin_runtime, guard.trusted_headers()


async def frontend_target(client, headers, entry="services", document=DOCUMENT):
    response = await client.post(
        PREFIX + "/realm",
        json={"clientId": document, "realm": "frontend"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    item = plan["entries"][0]
    report = {
        "sessionId": plan["sessionId"],
        "instanceId": item["instanceId"],
        "state": "running",
    }
    assert (
        await client.post(PREFIX + "/report", json=report, headers=headers)
    ).status_code == 200
    return {
        "sessionId": plan["sessionId"],
        "frontendInstanceId": item["instanceId"],
        "entryId": entry,
    }


@pytest.mark.anyio
async def test_host_binds_window_scope_and_checks_revealed_inputs_and_results(
    chart_host,
):
    app, runtime, headers = chart_host
    await runtime.start()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1:18080",
        ) as client:
            target = await frontend_target(client, headers)
            await frontend_target(client, headers, document="chart-window-b")
            body = {"target": target, "scope": CHART, "bars": [BAR], "input": None}
            assert (
                await client.post(PREFIX + "/invoke-chart", json=body)
            ).status_code == 403

            for mode in (
                "live",
                "quick-replay",
                "history-study",
                "replay",
                "replay-review",
                "strategy-replay",
            ):
                current = {**CHART, "mode": mode}
                if mode == "live":
                    current.update(runId=None, trackId=None)
                response = await client.post(
                    PREFIX + "/invoke-chart",
                    json={**body, "scope": current},
                    headers=headers,
                )
                assert response.status_code == 200, response.text
                assert response.json()["scope"] == current
                assert response.json()["result"] == {
                    "points": [{"timeMs": 1000, "value": 2}]
                }

            worker_run = runtime.running[("example.workbench", "worker")]
            direct = {
                "sessionId": target["sessionId"],
                "pluginId": worker_run.identity.plugin_id,
                "entryId": "worker",
                "identity": worker_run.identity.to_wire(),
                "instanceId": worker_run.instance,
            }
            worker = await client.post(
                PREFIX + "/invoke-chart",
                json={**body, "target": direct},
                headers=headers,
            )
            assert worker.status_code == 200, worker.text
            assert worker.json()["result"] == {"points": [{"timeMs": 1000, "value": 2}]}
            assert worker.json()["instanceId"] == worker_run.instance
            direct_other_window = await client.post(
                PREFIX + "/invoke-chart",
                json={
                    **body,
                    "target": direct,
                    "scope": {**CHART, "documentId": "chart-window-b"},
                },
                headers=headers,
            )
            assert direct_other_window.status_code == 409
            wrong_window = await client.post(
                PREFIX + "/invoke-chart",
                json={
                    **body,
                    "scope": {**CHART, "documentId": "chart-window-b"},
                },
                headers=headers,
            )
            assert wrong_window.status_code == 409
            unrevealed = await client.post(
                PREFIX + "/invoke-chart",
                json={
                    **body,
                    "bars": [{**BAR, "observedThroughMs": 1501}],
                },
                headers=headers,
            )
            assert unrevealed.status_code == 409

            async def bad_result(_frame):
                return {"points": [{"timeMs": 1501, "value": 9}]}

            run = runtime.running[("example.workbench", "services")]
            run.executor.compute_chart = bad_result
            response = await client.post(
                PREFIX + "/invoke-chart", json=body, headers=headers
            )
            assert response.status_code == 409

            async def unscoped_publication(context, _frame):
                context.publish({"future": 1501})
                return {"points": []}

            outputs = list(runtime.outputs)
            del run.executor.compute_chart
            run.executor.module.compute_chart = unscoped_publication
            response = await client.post(
                PREFIX + "/invoke-chart", json=body, headers=headers
            )
            assert response.status_code == 409
            assert (
                "return chart results through the scoped call"
                in response.json()["detail"]
            )
            assert list(runtime.outputs) == outputs
            assert not runtime.errors
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_disconnected_chart_cancels_inflight_computation(chart_host):
    app, runtime, headers = chart_host
    await runtime.start()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1:18080",
        ) as client:
            target = await frontend_target(client, headers)
        started, disconnected, cancelled = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        async def compute(_frame):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        runtime.running[
            ("example.workbench", "services")
        ].executor.compute_chart = compute
        received = False
        payload = json.dumps(
            {"target": target, "scope": CHART, "bars": [BAR], "input": None}
        ).encode()

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": payload}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        messages = []

        async def send(message):
            messages.append(message)

        request = asyncio.create_task(
            app(
                {
                    "type": "http",
                    "method": "POST",
                    "path": PREFIX + "/invoke-chart",
                    "scheme": "http",
                    "server": ("127.0.0.1", 18080),
                    "client": ("127.0.0.1", 50000),
                    "headers": [
                        (key.lower().encode(), value.encode())
                        for key, value in headers.items()
                    ],
                    "query_string": b"",
                    "http_version": "1.1",
                },
                receive,
                send,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 2)
            disconnected.set()
            await asyncio.wait_for(request, 2)
            assert cancelled.is_set()
            assert messages[0]["status"] == 499
            assert not runtime.calls
        finally:
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
    finally:
        await runtime.stop()
