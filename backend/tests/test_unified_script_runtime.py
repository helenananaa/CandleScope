"""Product indicator routing and rejection of the retired installer protocol."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import httpx
import pytest
from app.indicator.runtime_routes import IndicatorRuntimeRoutes
from app.indicator.runtime_service import (
    IndicatorRuntimeRequest,
    IndicatorRuntimeService,
    removed_in_process_runtime,
)
from app.plugin_core_v2.api import create_core_plugin_router
from app.plugin_core_v2.runtime import CorePluginPlatform
from app.plugin_lifecycle.api import create_unified_router
from app.plugin_lifecycle.runtime import UnifiedRuntime
from app.plugin_lifecycle.script_bundle import PYTHON_ID, build_script_package
from app.plugin_lifecycle.script_runtime import ScriptRuntimeHost
from app.plugin_lifecycle.store import PackageStore
from app.plugin_security_v2.management import LocalManagementGuard
from candlescope_plugin_sdk import (
    AnalyzeRequest,
    Bar,
    ExecuteBatchRequest,
    MarketContext,
)
from fastapi import FastAPI

SOURCE = """INDICATOR = {
    "name": "Unified Python", "window": 2, "overlay": False,
    "outputs": [{"id": "main", "type": "histogram"}],
}
def compute(bars, params):
    return {"lines": {"main": [price * 2 for price in bars["close"]]}}
"""


@pytest.mark.anyio
async def test_python_indicator_runs_from_bundled_activation(tmp_path, monkeypatch):
    wheel_dir = os.environ.get("CANDLESCOPE_TEST_UNIFIED_PYTHON_WHEELS")
    if not wheel_dir:
        pytest.skip(
            "set CANDLESCOPE_TEST_UNIFIED_PYTHON_WHEELS to the Python indicator and SDK wheel directory"
        )
    wheels = sorted(Path(wheel_dir).glob("*.whl"))
    assert len(wheels) == 2
    archive = tmp_path / "python.cspkg"
    package = build_script_package(PYTHON_ID, wheels, "0.1.0", archive)
    descriptor = tmp_path / "unified-python.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema": "candlescope.bundled-unified-python/1",
                "filename": archive.name,
                "sha256": package.sha256,
                "size": package.size,
            }
        )
    )
    # A pre-existing registry remains untouched and has no influence on startup.
    untouched = tmp_path / "runtime-registry.json"
    untouched.write_text("previous installation data")
    monkeypatch.setenv("CANDLESCOPE_RUNTIME_REGISTRY", str(untouched))
    app = SimpleNamespace(state=SimpleNamespace())
    store = PackageStore(tmp_path / "plugins")
    runtime = UnifiedRuntime(app, store)
    host = ScriptRuntimeHost(runtime)
    indicators = IndicatorRuntimeService(
        IndicatorRuntimeRoutes.first_party_sidecar_default(),
        host=host,
    )
    context = MarketContext(
        exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m"
    )
    bars = tuple(
        Bar(
            time=1_700_000_040 + i * 60,
            open=10 + i,
            high=11 + i,
            low=9 + i,
            close=10 + i,
            volume=3,
            is_closed=i < 3,
        )
        for i in range(4)
    )

    try:
        await runtime.prepare_startup(bundled={PYTHON_ID: descriptor})
        await runtime.start()
        run = runtime.running[(PYTHON_ID, "python")]
        assert run.identity.package_sha256 == package.sha256
        assert (
            await host.analyze(PYTHON_ID, AnalyzeRequest(SOURCE, context))
        ).executable

        app.state.indicator_runtime_service = indicators
        request = IndicatorRuntimeRequest(
            language="python",
            source=SOURCE,
            exchange=context.exchange,
            market_type=context.market_type,
            symbol=context.symbol,
            interval=context.interval,
            bars=bars,
            transport="http.compute",
        )
        result = await indicators.execute(
            request,
            legacy=removed_in_process_runtime,
            adapt_sidecar=lambda response: response.to_wire(),
        )
        assert result["ok"], result
        (series,) = result["output"]["series"]
        assert series["type"] == "histogram"
        assert [point["value"] for point in series["data"]] == [None, 22, 24, None]
        assert result["meta"]["inputWindow"]["formingBarsExcluded"] == 1
        assert not (
            await host.analyze(PYTHON_ID, AnalyzeRequest("def broken", context))
        ).ok
        assert untouched.read_text() == "previous installation data"

        in_flight = None
        if os.name == "posix":
            marker = tmp_path / "running-worker"
            script = (
                "import os,time\n"
                "def compute(bars, params):\n"
                f"    with open({str(marker)!r}, 'w') as handle: handle.write(str(os.getpid()))\n"
                "    time.sleep(20)\n"
            )
            in_flight = asyncio.create_task(
                host.execute_batch(
                    PYTHON_ID, ExecuteBatchRequest(script, context, bars[:3])
                )
            )
            for _ in range(100):
                if marker.is_file() and marker.stat().st_size:
                    break
                await asyncio.sleep(0.05)
            pid = int(marker.read_text())

        store.disable(PYTHON_ID, expected_revision=store.snapshot()["revision"])
        await runtime.reconcile()
        if in_flight is not None:
            with pytest.raises(
                Exception, match="closed|exited|revoked|activation|transport"
            ):
                await in_flight
            process = await asyncio.to_thread(
                subprocess.run,
                ["ps", "-o", "stat=", "-p", str(pid)],
                check=False,
                capture_output=True,
                text=True,
            )
            assert not process.stdout.strip() or process.stdout.strip().startswith("Z")
        catalog = await indicators.public_catalog()
        assert not next(row for row in catalog["languages"] if row["id"] == "python")[
            "available"
        ]
        failed = await indicators.execute(
            replace(request, source=SOURCE),
            legacy=removed_in_process_runtime,
            adapt_sidecar=lambda response: response.to_wire(),
        )
        assert failed["ok"] is False
        assert not run.executor.context.root.exists()
    finally:
        await indicators.stop()
        await runtime.stop()


@pytest.mark.anyio
async def test_application_installers_reject_legacy_archive_without_registration(
    tmp_path,
):
    archive = tmp_path / "previous.cspkg"
    with ZipFile(archive, "w") as output:
        output.writestr(
            "manifest.json", '{"schemaVersion":1,"id":"candlescope.python-indicator"}'
        )
        output.writestr("wheels/example.whl", b"historical wheel")
    data = archive.read_bytes()
    digest = "sha256:" + hashlib.sha256(data).hexdigest()

    guard = LocalManagementGuard(("http://127.0.0.1:5173",))
    platform = CorePluginPlatform(
        root=tmp_path / "legacy", host_name="test", host_version="1.0.0"
    )
    app = FastAPI()
    app.state.plugin_platform_v2 = platform
    app.state.plugin_platform_v2_management_guard = guard
    store = PackageStore(tmp_path / "unified")
    app.state.unified_plugin_runtime = UnifiedRuntime(app, store)
    app.include_router(create_core_plugin_router())
    app.include_router(create_unified_router())
    headers = {
        **guard.trusted_headers(user_action="retired-test"),
        "Content-Type": "application/octet-stream",
        "X-CandleScope-Bundle-SHA256": digest,
    }
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 43200))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as client:
        for route in ("install", "install/prepare"):
            response = await client.post(
                f"/api/v2/plugins/manage/{route}", content=data, headers=headers
            )
            assert response.status_code == 409, response.text
            assert (
                response.json()["detail"]["code"]
                == "PLUGIN_SCRIPT_RUNTIME_UPDATE_REQUIRED"
            )
        response = await client.post(
            "/api/v2/plugins/manage/unified/stage", content=data, headers=headers
        )
        assert response.status_code == 400
        assert "update the plugin package" in response.json()["detail"]
    assert not store.snapshot()["plugins"]
    assert not platform.installer.list_plugins()
    assert archive.read_bytes() == data
