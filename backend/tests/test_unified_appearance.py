"""Appearance selection is data from the unified owner, including legacy conversion."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from app.plugin_lifecycle.api import create_unified_router
from app.plugin_lifecycle.bundle import PackageError, build_package
from app.plugin_lifecycle.runtime import UnifiedRuntime
from app.plugin_lifecycle.store import PackageStore
from app.plugin_security_v2.management import LocalManagementGuard
from app.trusted_extensions.store import ExtensionStore
from fastapi import FastAPI

THEME = {"base": "light", "tokens": {"bg-primary": "#faf8f2"}}
LAYOUT = {
    "page": ["statusBar", "topBar", "intervalSelector", "workspace", "featureSurfaces"],
    "workspace": ["rightRail", "chart", "toolbar", "bottomPanel", "exportOverlay"],
}


def old_package(plugin_id, *, executable=False):
    manifest = {
        "schema": "candlescope.extension/1",
        "id": plugin_id,
        "name": plugin_id,
        "version": "1.0.0",
        "trust": "full-trust",
        "apiVersion": 1,
        "theme": THEME,
        "layout": LAYOUT,
    }
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        if executable:
            manifest["entries"] = {"backend": "start.py"}
            archive.writestr(
                "start.py", "raise AssertionError('Old code must remain inert')"
            )
        archive.writestr("extension.json", json.dumps(manifest))
    return source.getvalue()


@pytest.mark.anyio
async def test_migration_is_reviewed_and_appearance_is_owned_across_restart(tmp_path):
    previous = ExtensionStore(tmp_path)
    source = old_package("example.appearance")
    review = previous.stage(source)
    previous.change(
        "activate",
        "example.appearance",
        review["digest"],
        f"full-trust:{review['digest']}",
    )
    previous.change("theme", "example.appearance")
    previous.change("layout", "example.appearance")
    executable = previous.stage(old_package("example.executable", executable=True))
    previous.change(
        "activate",
        "example.executable",
        executable["digest"],
        f"full-trust:{executable['digest']}",
    )
    old_state = previous.state_path.read_bytes()

    app = FastAPI()
    guard = LocalManagementGuard(("http://127.0.0.1:15173",))
    app.state.unified_management_guard = guard
    store = PackageStore(tmp_path / "unified")
    runtime = UnifiedRuntime(app, store)
    app.state.unified_plugin_runtime = runtime
    app.include_router(create_unified_router())
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 43200))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as client:
        await runtime.start()
        try:
            old = "/api/v2/plugins/manage/extensions"
            base = "/api/v2/plugins/manage/unified"
            headers = guard.trusted_headers(user_action="test-appearance")
            assert (await client.get(old + "/plan", headers=headers)).status_code == 410
            assert (
                await client.post(
                    old + "/change", headers=headers, json={"action": "disable-all"}
                )
            ).status_code == 410
            assert (
                await client.post(
                    base + "/stage-appearance", json={"digest": review["digest"]}
                )
            ).status_code == 403
            rejected = await client.post(
                base + "/stage-appearance",
                headers=headers,
                json={"digest": executable["digest"]},
            )
            assert rejected.status_code == 400
            assert "updated unified package" in rejected.json()["detail"]
            candidate = await client.post(
                base + "/stage-appearance",
                headers=headers,
                json={"digest": review["digest"]},
            )
            assert candidate.status_code == 200, candidate.text
            manifest = candidate.json()["manifest"]
            assert [entry["kind"] for entry in manifest["entries"]] == ["data", "data"]
            assert store.snapshot()["plugins"] == {}
            digest = candidate.json()["packageSha256"]
            activate = await client.post(
                base + "/change",
                headers=headers,
                json={
                    "action": "activate",
                    "digest": digest,
                    "revision": 0,
                    "acknowledgement": f"full-trust:{digest}",
                },
            )
            assert activate.status_code == 200, activate.text
            select = {
                "action": "select-appearance",
                "id": "example.appearance",
                "revision": 1,
            }
            theme = await client.post(
                base + "/change", headers=headers, json={**select, "kind": "theme"}
            )
            assert theme.status_code == 200, theme.text
            stale = await client.post(
                base + "/change", headers=headers, json={**select, "kind": "layout"}
            )
            assert stale.status_code == 409
            layout = await client.post(
                base + "/change",
                headers=headers,
                json={**select, "kind": "layout", "revision": 2},
            )
            assert layout.status_code == 200, layout.text
            first = await runtime.realm_plan("window-one", "frontend")
            assert first["appearance"] == {"theme": THEME, "layout": LAYOUT}
        finally:
            await runtime.stop()

        restart = UnifiedRuntime(app, store)
        app.state.unified_plugin_runtime = restart
        try:
            await restart.start()
            plan = await restart.realm_plan("window-two", "frontend")
            assert plan["appearance"] == first["appearance"]
            next_revision = store.snapshot()["revision"]
            store.disable("example.appearance", expected_revision=next_revision)
            assert (await restart.realm_plan("window-two", "frontend"))[
                "appearance"
            ] == {"theme": None, "layout": None}
            assert store.snapshot()["appearance"] == {"theme": None, "layout": None}
        finally:
            await restart.stop()

    assert previous.state_path.read_bytes() == old_state
    assert previous._archive(review["digest"]).read_bytes() == source


@pytest.mark.parametrize(
    "kind,value,message",
    [
        (
            "theme",
            {"base": "light", "tokens": {"bg-primary": "#000000;display:none"}},
            "Theme colors",
        ),
        ("layout", LAYOUT, "requires full-trust"),
    ],
)
def test_appearance_rejects_unsafe_or_unapproved_contributions(
    tmp_path, kind, value, message
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "candlescope.unified-plugin/1",
                "id": "example.invalid",
                "name": "Invalid appearance",
                "version": "1.0.0",
                "trust": "restricted",
                "hostApiVersion": 1,
                "entries": [{"id": kind, "kind": "data", "path": "data.json"}],
            }
        )
    )
    (source / "data.json").write_text(
        json.dumps({"schema": f"candlescope.{kind}/1", **value})
    )
    with pytest.raises(PackageError, match=message):
        build_package(source, tmp_path / "appearance.cspkg")


def test_appearance_examples_are_portable(tmp_path):
    examples = Path(__file__).resolve().parents[2] / "examples" / "unified-plugins"
    for name in ("paper", "terminal"):
        assert build_package(
            examples / name, tmp_path / f"{name}.cspkg"
        ).manifest.id.startswith("candlescope.")
