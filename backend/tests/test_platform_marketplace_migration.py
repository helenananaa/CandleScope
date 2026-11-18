from __future__ import annotations

import json

import httpx
import pytest
from app.plugin_core_v2.api import create_core_plugin_router
from app.plugin_core_v2.private_storage import StorageNamespace
from app.plugin_core_v2.runtime import CorePluginPlatform
from app.plugin_lifecycle.bundle import BUNDLE_SCHEMA
from app.plugin_lifecycle.runtime import UnifiedRuntime
from app.plugin_lifecycle.store import LifecycleError, PackageStore
from app.plugin_security_v2.management import LocalManagementGuard
from app.plugin_security_v2.storage import atomic_write_json
from candlescope_plugin_sdk.platform_v2 import canonical_sha256
from fastapi import FastAPI

from tests.plugin_marketplace_phase10_testkit import (
    SignedMarketplaceV2Builder,
)
from tests.plugin_marketplace_testkit import (
    MARKETPLACE_ID,
    MARKETPLACE_TEST_NOW,
    SignedMarketplaceBuilder,
    build_marketplace_bundle,
)
from tests.test_unified_marketplace import API, INDEX, MANAGE, sha, signed_package


@pytest.mark.asyncio
async def test_republished_platform_package_preserves_data_and_rolls_back(tmp_path):
    old = build_marketplace_bundle(tmp_path / "legacy").bundle
    plugin_id = old.manifest.plugin.id
    path = f"{MANAGE}/{plugin_id}"
    builder = SignedMarketplaceBuilder.create()
    builder.add_release(old)
    failing, failing_bytes = signed_package(
        tmp_path, builder, "0.2.0", plugin_id=plugin_id, data="broken JSON"
    )
    successor, successor_bytes = signed_package(
        tmp_path, builder, "0.3.0", plugin_id=plugin_id
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
        marketplace_now_provider=lambda: MARKETPLACE_TEST_NOW,
    )
    # Seed a persisted installation and its already-reviewed signed publisher
    # grants without launching a Windows AppContainer in this cross-platform test.
    platform.installer.install(old.path, expected_sha256=old.sha256, enabled=True)
    publisher = f"publisher-key:{builder.publisher['keyId']}"
    platform.grant_store.reconcile(
        old.manifest,
        bundle_sha256=old.sha256,
        manifest_sha256=old.manifest_sha256,
        publisher_identity=publisher,
    )
    retained = platform.installer.capture_activation_state(plugin_id)
    assert retained.activation.enabled
    namespace = StorageNamespace(plugin_id, publisher)
    platform.private_storage.kv_put(namespace, "account", {"saved": 7})
    platform.private_storage.kv_put(
        StorageNamespace(plugin_id, "other-publisher"), "forbidden", True
    )
    atomic_write_json(
        platform.settings.path,
        {
            "schemaVersion": 1,
            "revision": 1,
            "records": [
                {
                    "pluginId": plugin_id,
                    "publisherIdentityHash": sha(publisher.encode()).removeprefix(
                        "sha256:"
                    ),
                    "contributionId": "preferences",
                    "schemaSha256": sha(b"preferences"),
                    "value": {"layout": "compact"},
                    "updatedAt": "2026-07-23T02:00:00Z",
                }
            ],
        },
    )
    sandbox = (
        platform.root / "sandbox-v2" / "private" / platform._sandbox_key(old, publisher)
    )
    (sandbox / "nested").mkdir(parents=True)
    (sandbox / "nested" / "state.bin").write_bytes(b"original")
    guard = LocalManagementGuard(
        ("http://127.0.0.1:5173",),
        session_token="legacy-migration-session-0123456789abcdef",
        csrf_token="legacy-migration-csrf-0123456789abcdef",
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
            headers = guard.trusted_headers(user_action="marketplace-migration")

            async def post(endpoint, **kwargs):
                return await client.post(endpoint, headers=headers, **kwargs)

            async def stage(package, raw):
                result = await client.post(
                    f"{path}/{package.manifest.version}/artifact",
                    content=raw,
                    headers={
                        **headers,
                        "Content-Type": "application/vnd.candlescope.plugin+zip",
                        "X-CandleScope-Bundle-SHA256": package.sha256,
                    },
                )
                assert result.status_code == 200, result.text
                staged = await post(f"{path}/apply")
                assert staged.status_code == 200, staged.text
                return result.json()["candidate"]["unifiedApproval"]

            first_index = await client.post(
                INDEX,
                content=builder.index_bytes(releases=builder.releases[:2]),
                headers={**headers, "Content-Type": "application/json"},
            )
            assert first_index.status_code == 200, first_index.text
            await platform.start()
            assert plugin_id in platform._records
            review = await stage(failing, failing_bytes)
            assert review["legacy"] == {
                "legacyActivationId": retained.activation.activation_id,
                "legacyBundleSha256": old.sha256,
                "legacyGrantSha256": retained.grant_sha256,
            }
            assert not platform.marketplace.legacy_fenced(plugin_id)
            without_review = await post(
                f"{path}/activate",
                json={k: v for k, v in review.items() if k != "legacy"},
            )
            assert (
                without_review.json()["detail"]["code"]
                == "PLUGIN_MARKETPLACE_APPROVAL_MISMATCH"
            )
            failed = await post(f"{path}/activate", json=review)
            assert failed.status_code == 409, failed.text
            assert (
                failed.json()["detail"]["details"]["restoredVersion"]
                == old.manifest.plugin.version
            )
            assert store.identity(plugin_id) is None
            assert plugin_id in platform._records
            assert not platform.marketplace.legacy_fenced(plugin_id)

            # Simulate a process interruption after the ownership transaction
            # and before health was recorded. Startup verifies and releases it.
            trial_review = await stage(failing, failing_bytes)
            platform.marketplace.begin_unified_activation(plugin_id, trial_review)
            await runtime.reconcile()
            assert plugin_id not in runtime.packages
            await platform.stop()
            await runtime.stop()
            runtime = UnifiedRuntime(app, store)
            await runtime.prepare_startup()
            platform.marketplace.bind_unified(runtime)
            await platform.start()
            await runtime.start()
            assert plugin_id in platform._records
            assert not platform.marketplace.legacy_fenced(plugin_id)

            index = await client.post(
                INDEX,
                content=builder.index_bytes(
                    sequence=2,
                    previous_index_sha256=first_index.json()["import"]["indexSha256"],
                ),
                headers={**headers, "Content-Type": "application/json"},
            )
            assert index.status_code == 200, index.text
            before_catalog = (await client.get(f"{API}/marketplace/catalog")).json()[
                "plugins"
            ][0]
            assert before_catalog["installable"]
            review = await stage(successor, successor_bytes)
            activated = await post(f"{path}/activate", json=review)
            assert activated.status_code == 200, activated.text
            identity = store.identity(plugin_id)
            assert identity.package_sha256 == successor.sha256
            assert plugin_id not in platform._records
            assert not any(
                owner[0] == plugin_id for owner in platform.manager.owner_keys()
            )
            existing = platform.installer.capture_activation_state(plugin_id)
            assert (
                existing.activation == retained.activation
                and existing.grant == retained.grant
            )
            assert (await post(f"{API}/manage/{plugin_id}/disable")).status_code == 409
            export = runtime.packages[plugin_id]["storage"] / "platform-v2"
            assert json.loads((export / "settings.json").read_bytes())["records"][0][
                "value"
            ] == {"layout": "compact"}
            assert json.loads((export / "host-storage.json").read_bytes())["kv"] == [
                {"key": "account", "value": {"saved": 7}}
            ]
            copied = export / "sandbox" / "nested" / "state.bin"
            assert copied.read_bytes() == b"original"
            copied.write_bytes(b"new version data")
            assert (sandbox / "nested" / "state.bin").read_bytes() == b"original"

            await platform.stop()
            await runtime.stop()
            runtime = UnifiedRuntime(app, store)
            await runtime.prepare_startup()
            platform.marketplace.bind_unified(runtime)
            await platform.start()
            await runtime.start()
            assert plugin_id not in platform._records
            assert runtime.packages[plugin_id]["identity"] == identity
            assert copied.read_bytes() == b"new version data"

            catalog = (await client.get(f"{API}/marketplace/catalog")).json()[
                "plugins"
            ][0]
            rollback = catalog["legacyRollback"]
            approval = {
                key: rollback[key]
                for key in ("migrationGeneration", "registryRevision")
            }
            stale = await post(
                f"{path}/rollback-migration",
                json={**approval, "registryRevision": approval["registryRevision"] - 1},
            )
            assert stale.status_code == 409, stale.text
            restored = await post(f"{path}/rollback-migration", json=approval)
            assert restored.status_code == 200, restored.text
            assert restored.json()["restoredVersion"] == old.manifest.plugin.version
            assert plugin_id not in runtime.packages and plugin_id in platform._records
            assert store.identity(plugin_id) is None
            assert platform.private_storage.kv_get(namespace, "account")["value"] == {
                "saved": 7
            }
            assert copied.read_bytes() == b"new version data"

            assert (
                platform.marketplace.status()["candidates"][0]["phase"] == "rolled-back"
            )
            review = await stage(successor, successor_bytes)
            assert (await post(f"{path}/activate", json=review)).status_code == 200
            revoked_index = await client.post(
                INDEX,
                content=builder.index_bytes(
                    sequence=3,
                    previous_index_sha256=index.json()["import"]["indexSha256"],
                    revocations=[
                        {
                            "scope": "release",
                            "subject": old.sha256,
                            "effectiveAt": "2026-07-22T01:30:00Z",
                            "reasonCode": "MALICIOUS_RELEASE",
                        }
                    ],
                ),
                headers={**headers, "Content-Type": "application/json"},
            )
            assert revoked_index.status_code == 200, revoked_index.text
            rollback = (await client.get(f"{API}/marketplace/catalog")).json()[
                "plugins"
            ][0]["legacyRollback"]
            rejected = await post(
                f"{path}/rollback-migration",
                json={
                    key: rollback[key]
                    for key in ("migrationGeneration", "registryRevision")
                },
            )
            assert (
                rejected.json()["detail"]["code"]
                == "PLUGIN_MARKETPLACE_RELEASE_REVOKED"
            )
            assert store.identity(plugin_id).package_sha256 == successor.sha256
            assert plugin_id not in platform._records

            store.uninstall(plugin_id, expected_revision=store.snapshot()["revision"])
            with pytest.raises(LifecycleError, match="different publisher"):
                store.begin_marketplace(
                    successor.sha256,
                    {
                        "marketplaceId": MARKETPLACE_ID,
                        "publisherId": "different-publisher",
                        "publisherKeyId": "ed25519:" + "0" * 64,
                        "permissions": [],
                    },
                    previous_generation=None,
                )
            await runtime.reconcile()
            await platform.reconcile_plugin(plugin_id)
            assert (
                plugin_id not in platform._records and plugin_id not in runtime.packages
            )
            assert copied.read_bytes() == b"new version data"
    finally:
        await runtime.stop()
        await platform.stop()


def test_index_v2_appends_a_unified_successor_without_rewriting_the_old_release(
    tmp_path,
):
    old = build_marketplace_bundle(tmp_path / "legacy").bundle
    plugin_id = old.manifest.plugin.id
    builder = SignedMarketplaceV2Builder.create()
    legacy = builder.add_release(old)
    platform = CorePluginPlatform(
        root=tmp_path / "platform",
        host_name="CandleScope",
        host_version="0.4.0",
        marketplace_enabled=True,
        marketplace_roots=(builder.root,),
        marketplace_now_provider=lambda: MARKETPLACE_TEST_NOW.replace(month=8, day=10),
    )
    service = platform.marketplace
    runtime = UnifiedRuntime(FastAPI(), PackageStore(tmp_path / "unified"))
    service.bind_unified(runtime)
    first = service.import_index(builder.index_bytes(), marketplace_id=MARKETPLACE_ID)
    fixture = SignedMarketplaceBuilder.create()
    package, raw = signed_package(tmp_path, fixture, "0.2.0", plugin_id=plugin_id)
    statement = fixture.releases[0]
    artifact = {
        **{
            key: value
            for key, value in legacy["artifacts"][0].items()
            if key != "signature"
        },
        **statement["artifact"],
        "artifactId": f"{service.operating_system}-{service.architecture}",
        "os": service.operating_system,
        "arch": service.architecture,
        "licenseInventorySha256": canonical_sha256(
            {"plugin": "MIT", "dependencies": [], "runtimeLicenses": []}
        ),
        "runtimeBindings": [],
    }
    release = {
        **legacy,
        "version": package.manifest.version,
        "licenseExpression": "MIT",
        "dependencies": [],
        "permissions": {"required": [], "optional": []},
        "artifacts": [
            builder.sign_artifact(
                plugin_id=plugin_id, version=package.manifest.version, artifact=artifact
            )
        ],
        "sha256Sums": statement["sha256Sums"],
        "sha256SumsSha256": statement["sha256SumsSha256"],
    }
    builder.releases.append(release)
    builder.resign_release(release)
    service.import_index(
        builder.index_bytes(sequence=2, previous_index_sha256=first["indexSha256"]),
        marketplace_id=MARKETPLACE_ID,
    )
    latest = service.public_catalog()["plugins"][0]
    assert latest["installable"]
    assert latest["latest"]["artifacts"][0]["packageFormat"] == BUNDLE_SCHEMA
    assert (
        service.prepare(plugin_id, artifact_bytes=raw)["unifiedApproval"][
            "packageSha256"
        ]
        == package.sha256
    )
