from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import httpx
import pytest
from app.plugin_core_v2.api import create_core_plugin_router
from app.plugin_core_v2.runtime import CorePluginPlatform
from app.plugin_lifecycle.bundle import BUNDLE_SCHEMA, build_package
from app.plugin_lifecycle.runtime import UnifiedRuntime
from app.plugin_lifecycle.store import LifecycleError, PackageStore
from app.plugin_security_v2.management import LocalManagementGuard
from fastapi import FastAPI

from tests.plugin_marketplace_testkit import (
    MARKETPLACE_ID,
    MARKETPLACE_TEST_NOW,
    PUBLISHER_ID,
    SOURCE_ORIGIN,
    SignedMarketplaceBuilder,
)

PLUGIN_ID = "example.market-data"
API = "/api/v2/plugins"
MANAGE = f"{API}/manage/marketplace"
PLUGIN = f"{MANAGE}/{PLUGIN_ID}"
INDEX = f"{MANAGE}/{MARKETPLACE_ID}/index"


def sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def signed_package(
    tmp_path, builder, version, *, data="{}", permissions=(), plugin_id=PLUGIN_ID
):
    source = tmp_path / version
    (source / "sbom").mkdir(parents=True)
    manifest = json.dumps(
        {
            "schema": "candlescope.unified-plugin/1",
            "id": plugin_id,
            "name": "Market data extension",
            "version": version,
            "trust": "restricted",
            "hostApiVersion": 1,
            "entries": [{"id": "main", "kind": "data", "path": "data.json"}],
            "permissions": list(permissions),
        }
    ).encode()
    sbom = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": plugin_id,
                    "version": version,
                    "licenses": [{"expression": "MIT"}],
                }
            },
            "components": [],
        }
    ).encode()
    (source / "manifest.json").write_bytes(manifest)
    (source / "sbom/cyclonedx.json").write_bytes(sbom)
    (source / "data.json").write_text(data)
    output = tmp_path / f"{plugin_id}-{version}.cspkg"
    package = build_package(source, output)
    builder.add_release_statement(
        {
            "pluginId": plugin_id,
            "version": version,
            "publisherId": PUBLISHER_ID,
            "artifact": {
                "packageFormat": BUNDLE_SCHEMA,
                "fileName": output.name,
                "url": f"{SOURCE_ORIGIN}/artifacts/{output.name}",
                "size": package.size,
                "sha256": package.sha256,
                "manifestSha256": sha(manifest),
                "sbomSha256": sha(sbom),
            },
            "publishedAt": "2026-07-20T00:00:00Z",
            "licenseExpression": "MIT",
            "dependencies": [],
            "sha256Sums": f"{package.sha256.removeprefix('sha256:')}  {output.name}\n",
        }
    )
    return package, output.read_bytes()


@pytest.mark.asyncio
async def test_signed_marketplace_routes_observe_rollback_and_revoke(tmp_path):
    now = MARKETPLACE_TEST_NOW
    builder = SignedMarketplaceBuilder.create()
    first, first_bytes = signed_package(tmp_path, builder, "1.0.0")
    failing, failing_bytes = signed_package(
        tmp_path, builder, "1.1.0", data="invalid JSON"
    )
    unsupported, unsupported_bytes = signed_package(
        tmp_path, builder, "1.2.0", permissions=("host.network/1",)
    )
    app = FastAPI()
    store = PackageStore(tmp_path / "unified")
    runtime = UnifiedRuntime(app, store)
    platform = CorePluginPlatform(
        root=tmp_path / "platform",
        host_name="CandleScope",
        host_version="0.4.0",
        marketplace_enabled=True,
        marketplace_roots=(builder.root,),
        marketplace_now_provider=lambda: now,
    )

    class FixtureFetcher:
        def get(self, url, *, maximum):
            artifact = builder.releases[0]["artifact"]
            assert (url, maximum) == (artifact["url"], first.size)
            return first_bytes

    platform.marketplace.fetcher = FixtureFetcher()
    guard = LocalManagementGuard(
        ("http://127.0.0.1:5173",),
        session_token="unified-session-token-0123456789abcdef",
        csrf_token="unified-csrf-token-0123456789abcdefghi",
    )
    app.state.plugin_platform_v2 = platform
    app.state.plugin_platform_v2_management_guard = guard
    app.include_router(create_core_plugin_router())
    platform.marketplace.bind_unified(runtime)
    await runtime.prepare_startup()
    await runtime.start()
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 43212))
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as client:

            async def post(path, *, action="unified-marketplace", **kwargs):
                headers = guard.trusted_headers(user_action=action)
                headers.update(kwargs.pop("headers", {}))
                return await client.post(path, headers=headers, **kwargs)

            async def upload(package, artifact):
                return await post(
                    f"{PLUGIN}/{package.manifest.version}/artifact",
                    content=artifact,
                    headers={
                        "Content-Type": "application/vnd.candlescope.plugin+zip",
                        "X-CandleScope-Bundle-SHA256": sha(artifact),
                    },
                )

            tampered = builder.index_document(releases=builder.releases[:1])
            del tampered["releases"][0]["artifact"]["packageFormat"]
            invalid = await post(
                INDEX,
                content=builder.resign_index(tampered),
                headers={"Content-Type": "application/json"},
            )
            assert invalid.status_code >= 400, invalid.text

            index = await post(
                INDEX,
                content=builder.index_bytes(releases=builder.releases[:1]),
                headers={"Content-Type": "application/json"},
            )
            assert index.status_code == 200, index.text
            index_sha = index.json()["import"]["indexSha256"]
            catalog = await client.get(f"{API}/marketplace/catalog")
            entry = catalog.json()["plugins"][0]
            assert (
                entry["installable"]
                and entry["latest"]["artifact"]["packageFormat"] == BUNDLE_SCHEMA
            )

            invalid_artifact = await upload(first, first_bytes + b"x")
            assert (
                invalid_artifact.json()["detail"]["code"]
                == "PLUGIN_MARKETPLACE_ARTIFACT_DIGEST_MISMATCH"
            )
            prepared = await post(f"{PLUGIN}/prepare", json={"version": "1.0.0"})
            assert prepared.status_code == 200, prepared.text
            approval = prepared.json()["candidate"]["unifiedApproval"]
            assert approval == {
                "packageSha256": first.sha256,
                "permissions": [],
                "previousGeneration": None,
            }
            staged = await post(f"{PLUGIN}/apply")
            assert staged.status_code == 200, staged.text
            assert staged.json()["candidate"]["phase"] == "activation-staged"
            assert store.identity(PLUGIN_ID) is None
            with pytest.raises(LifecycleError, match="require marketplace approval"):
                store.activate(
                    first.sha256,
                    expected_revision=store.snapshot()["revision"],
                    acknowledgement=f"restricted:{first.sha256}",
                )

            assert (
                await client.post(f"{PLUGIN}/activate", json=approval)
            ).status_code == 403
            assert (await post(f"{PLUGIN}/activate")).status_code == 400
            denied = await post(
                f"{PLUGIN}/activate",
                json={**approval, "permissions": ["chart.compute/1"]},
            )
            assert denied.status_code == 409, denied.text
            assert (
                denied.json()["detail"]["code"]
                == "PLUGIN_MARKETPLACE_APPROVAL_MISMATCH"
            )
            assert store.identity(PLUGIN_ID) is None

            activated = await post(f"{PLUGIN}/activate", json=approval)
            assert activated.status_code == 200, activated.text
            assert activated.json()["health"] == [{"entryId": "main", "kind": "data"}]
            status = (
                await client.get(
                    f"{MANAGE}/status",
                    headers=guard.trusted_headers(user_action="marketplace-status"),
                )
            ).json()
            assert status["candidates"][0]["observation"]["status"] == "passed"
            active = store.identity(PLUGIN_ID)
            assert active.package_sha256 == first.sha256
            assert runtime.packages[PLUGIN_ID]["data"]["main"] == {}
            assert platform.installer.list_plugins() == ()

            index = await post(
                INDEX,
                content=builder.index_bytes(
                    sequence=2, previous_index_sha256=index_sha
                ),
                headers={"Content-Type": "application/json"},
            )
            assert index.status_code == 200, index.text
            index_sha = index.json()["import"]["indexSha256"]
            unsupported_result = await upload(unsupported, unsupported_bytes)
            assert (
                unsupported_result.json()["detail"]["code"]
                == "PLUGIN_MARKETPLACE_UNIFIED_INVALID"
            )
            upgraded = await upload(failing, failing_bytes)
            assert upgraded.status_code == 200, upgraded.text
            upgrade_approval = upgraded.json()["candidate"]["unifiedApproval"]
            assert upgrade_approval["previousGeneration"] == active.generation
            assert (await post(f"{PLUGIN}/apply")).status_code == 200
            assert store.identity(PLUGIN_ID) == active

            stale = await post(f"{PLUGIN}/activate", json=approval)
            assert (
                stale.json()["detail"]["code"] == "PLUGIN_MARKETPLACE_APPROVAL_MISMATCH"
            )
            failed = await post(f"{PLUGIN}/activate", json=upgrade_approval)
            assert failed.status_code == 409, failed.text
            assert (
                failed.json()["detail"]["code"] == "PLUGIN_MARKETPLACE_HEALTH_ROLLBACK"
            )
            assert failed.json()["detail"]["details"]["runtimeReady"] is True
            restored = store.identity(PLUGIN_ID)
            assert (
                restored.package_sha256 == first.sha256
                and restored.generation > active.generation
            )
            assert runtime.packages[PLUGIN_ID]["identity"] == restored
            assert (
                platform.marketplace.status()["candidates"][0]["phase"] == "rolled-back"
            )

            # A trial left in the journal by a stopped owner is recovered before
            # any entry can start in the replacement process.
            prepared_again = await upload(failing, failing_bytes)
            assert prepared_again.status_code == 200, prepared_again.text
            assert (await post(f"{PLUGIN}/apply")).status_code == 200
            trial = platform.marketplace.begin_unified_activation(
                PLUGIN_ID,
                prepared_again.json()["candidate"]["unifiedApproval"],
            )
            await runtime.stop()
            runtime = UnifiedRuntime(app, store)
            platform.marketplace.bind_unified(runtime)
            await runtime.prepare_startup()
            await runtime.start()
            assert store.identity(PLUGIN_ID).package_sha256 == first.sha256
            assert runtime.packages[PLUGIN_ID]["identity"] == store.identity(PLUGIN_ID)
            assert (
                platform.marketplace.status()["candidates"][0]["phase"] == "rolled-back"
            )
            assert (
                store.finish_marketplace(PLUGIN_ID, trial["generation"], healthy=True)
                is False
            )

            now += timedelta(days=31)
            await runtime.reconcile()
            assert PLUGIN_ID not in runtime.packages
            now = MARKETPLACE_TEST_NOW
            await runtime.reconcile()
            assert (
                runtime.packages[PLUGIN_ID]["identity"].package_sha256 == first.sha256
            )

            revoked = await post(
                INDEX,
                content=builder.index_bytes(
                    sequence=3,
                    previous_index_sha256=index_sha,
                    revocations=[
                        {
                            "scope": "release",
                            "subject": first.sha256,
                            "effectiveAt": "2026-07-22T01:30:00Z",
                            "reasonCode": "MALICIOUS_RELEASE",
                        }
                    ],
                ),
                headers={"Content-Type": "application/json"},
            )
            assert revoked.status_code == 200, revoked.text
            assert revoked.json()["disabledPlugins"] == [PLUGIN_ID]
            assert PLUGIN_ID not in runtime.packages
            assert store.review(first.sha256)["packageSha256"] == first.sha256
    finally:
        await runtime.stop()
