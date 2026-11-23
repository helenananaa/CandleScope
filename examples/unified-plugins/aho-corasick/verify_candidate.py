"""Verify a locally built candidate and legacy binary using the actual Host executor."""

import argparse
import asyncio
import json
import subprocess
import tomllib
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.plugin_host.errors import PlatformHostRemoteError
from app.plugin_lifecycle import LifecycleError, PackageStore
from app.plugin_lifecycle.executors import PROTOCOL, OwnedContext, SidecarEntry
from app.plugin_lifecycle.runtime import UnifiedRuntime
from app.plugin_security_v2.sandbox import restricted_runtime_profile
from build_candidate import CANDIDATE, LEGACY
from candlescope_plugin_sdk.platform_v2 import canonical_sha256
from candlescope_plugin_sdk.unified import ActivationIdentity


def replay_reference(executable, directory):
    transcript = json.loads(
        (LEGACY / "conformance/control-transcript.json").read_bytes()
    )
    requests = transcript["requests"]
    run = subprocess.run(
        [str(executable.resolve())],
        input="".join(json.dumps(request) + "\n" for request in requests),
        encoding="utf-8",
        capture_output=True,
        check=True,
        timeout=10,
        cwd=directory,
    )
    responses = [json.loads(line) for line in run.stdout.splitlines()]
    assert [canonical_sha256(result) for result in responses] == transcript["expected"][
        "responseSha256"
    ]
    assert canonical_sha256(responses) == transcript["expected"]["transcriptSha256"]
    invocations = [
        (request["params"]["input"], response["result"])
        for request, response in zip(requests, responses, strict=True)
        if request["method"] == "invoke"
    ]
    return len(responses), invocations


def verify_supply_metadata(root, manifest):
    locked = tomllib.loads((CANDIDATE / "Cargo.lock").read_text(encoding="utf-8"))
    sbom = json.loads((root / "sbom/cyclonedx.json").read_bytes())
    for notice in (LEGACY / "licenses").glob("*.txt"):
        packaged = (root / "licenses" / notice.name).read_bytes()
        expected = notice.read_bytes()
        if notice.name == "THIRD_PARTY_NOTICES.txt":
            assert packaged.splitlines()[1:] == expected.splitlines()[1:]
        else:
            assert packaged == expected
    assert sbom["bomFormat"] == "CycloneDX"
    app = sbom["metadata"]["component"]
    assert (app["name"], app["version"]) == (manifest.id, manifest.version)
    locked_components = {
        (item["name"], item["version"]): item.get("checksum")
        for item in locked["package"]
        if item["name"] != "candlescope-aho-corasick-unified"
    }
    assert {
        (item["name"], item["version"]): next(
            (
                digest["content"]
                for digest in item.get("hashes", [])
                if digest["alg"] == "SHA-256"
            ),
            None,
        )
        for item in sbom["components"]
    } == locked_components


async def rejects(operation, code):
    try:
        await operation
    except PlatformHostRemoteError as error:
        assert error.details["remoteCode"] == code, error.details
    else:
        raise AssertionError(f"expected {code}")


async def verify_entry(verified, root, storage, invocations):
    manifest = verified.manifest
    (entry,) = manifest.entries
    assert (manifest.id, manifest.trust, manifest.permissions) == (
        "candlescope.aho-corasick",
        "restricted",
        (),
    )
    assert (entry.id, entry.kind, entry.runtime) == (
        "main",
        "sidecar",
        "native-executable",
    )
    identity = ActivationIdentity(manifest.id, manifest.version, verified.sha256, 2)

    def executor():
        # These freshly built bytes run only in the QA process on the build host.
        context = OwnedContext(
            None, identity, entry, root, lambda: True, lambda _: None
        )
        context.storage = storage
        return SidecarEntry(context, uuid.uuid4().hex, {})

    def activation(instance_id):
        return {
            "protocol": PROTOCOL,
            "identity": {
                **identity.to_wire(),
                "entryId": entry.id,
                "instanceId": instance_id,
            },
            "storage": str(storage),
        }

    search, _ = invocations[0]
    unactivated = executor()
    try:
        await unactivated.transport.start()
        params = activation(unactivated.instance_id)
        await rejects(unactivated.invoke(search), "UNIFIED_ENTRY_NOT_CURRENT")
        await rejects(
            unactivated.transport.request(
                "activate",
                {**params, "protocol": "candlescope.plugin/2"},
                generation=identity.generation,
                timeout=10,
            ),
            "INVALID_CONTRACT",
        )
        await rejects(
            unactivated.transport.request(
                "activate",
                {**params, "identity": {**params["identity"], "generation": 1}},
                generation=identity.generation,
                timeout=10,
            ),
            "INVALID_CONTRACT",
        )
    finally:
        await unactivated.stop()

    sidecar = executor()
    try:
        await sidecar.start()
        process = sidecar.transport.process
        assert process is not None and process.returncode is None
        await rejects(
            sidecar.transport.request(
                "activate",
                activation(sidecar.instance_id),
                generation=identity.generation,
                timeout=10,
            ),
            "INVALID_CONTRACT",
        )
        await rejects(
            sidecar.transport.request(
                "invoke",
                {"input": search},
                generation=1,
                timeout=10,
            ),
            "UNIFIED_ENTRY_NOT_CURRENT",
        )
        await rejects(
            sidecar.invoke({"patterns": [""], "haystack": "abc"}), "INVALID_CONTRACT"
        )
        for payload, expected in invocations:
            assert await sidecar.invoke(payload) == expected
        leftmost = await sidecar.invoke(
            {
                "patterns": ["a", "ab"],
                "haystack": "ab",
                "matchKind": "leftmost-longest",
            }
        )
        assert leftmost["matches"] == [
            {"startByte": 0, "endByte": 2, "patternIndex": 1}
        ]
        capped = await sidecar.invoke(
            {"patterns": ["a"], "haystack": "a" * 10001, "maxMatches": 10000}
        )
        assert capped["truncated"] is True
        assert len(capped["matches"]) == 10000
        assert capped["matches"][-1] == {
            "startByte": 9999,
            "endByte": 10000,
            "patternIndex": 0,
        }
    finally:
        await sidecar.stop()
    assert process.returncode is not None
    assert not any(storage.iterdir())


async def verify_appcontainer(store, verified, invocations):
    runtime = UnifiedRuntime(SimpleNamespace(state=SimpleNamespace()), store)
    manifest = verified.manifest
    (command,) = manifest.commands
    store.activate(
        verified.sha256,
        expected_revision=store.snapshot()["revision"],
        acknowledgement=f"restricted:{verified.sha256}",
    )
    try:
        await runtime.start()
        run = runtime.running.get((manifest.id, command.entry_id))
        assert run is not None, runtime.errors
        transport = run.executor.transport
        policy = transport.process_spec.sandbox_policy
        assert transport.process_spec.trust_level == "untrusted" and policy is not None
        (launch,) = policy.runtime_directory.glob("launch-*/config.json")
        config = json.loads(launch.read_bytes())
        assert config["appContainerSid"].startswith("S-1-15-2-")
        assert config["limits"]["activeProcesses"] == 1
        assert Path(config["command"][0]) == transport.process_spec.executable
        (listed,) = runtime.command_catalog()
        assert (listed["identity"], listed["instanceId"]) == (
            run.identity.to_wire(),
            run.instance,
        )
        process = transport.process
        for payload, expected in invocations:
            assert (
                await runtime.invoke_command(
                    manifest.id, command.id, listed["identity"], run.instance, payload
                )
                == expected
            )
        store.disable(manifest.id, expected_revision=store.snapshot()["revision"])
        await runtime.reconcile()
        assert not runtime.command_catalog()
        assert process.returncode is not None
        assert not policy.runtime_directory.exists()
    finally:
        await runtime.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="locally built .cspkg to execute")
    parser.add_argument(
        "legacy_binary", type=Path, help="legacy reference built from this checkout"
    )
    parser.add_argument(
        "--require-appcontainer",
        action="store_true",
        help="also require successful restricted activation through the Windows lifecycle",
    )
    args = parser.parse_args()
    with TemporaryDirectory(prefix="candlescope-aho-verify-") as temporary:
        workspace = Path(temporary)
        response_count, invocations = replay_reference(args.legacy_binary, workspace)
        store = PackageStore(workspace / "store")
        verified = store.stage(args.package)
        restricted_available = restricted_runtime_profile(
            "native-executable"
        ).supported()
        if args.require_appcontainer and not restricted_available:
            parser.error("a supported Windows AppContainer host is required")
        if not restricted_available:
            try:
                UnifiedRuntime(None, store).validate_marketplace(verified.manifest)
            except LifecycleError as error:
                assert (
                    str(error)
                    == "restricted sidecar requires a qualified isolated runtime; unavailable"
                )
            else:
                raise AssertionError(
                    "marketplace accepted a restricted sidecar without isolation"
                )
        storage = workspace / "private"
        storage.mkdir()
        root, files = store.materialize(verified.sha256)
        try:
            verify_supply_metadata(root, verified.manifest)
            asyncio.run(verify_entry(verified, root, storage, invocations))
        finally:
            store.release_materialization(root, files)
        assert not root.exists()
        if args.require_appcontainer:
            asyncio.run(verify_appcontainer(store, verified, invocations))

    print(
        json.dumps(
            {
                "packageSha256": verified.sha256,
                "legacyResponseDigestsMatched": response_count,
                "supplyMetadataChecked": True,
                "unifiedInvocationsMatched": len(invocations),
                "unifiedExecutorProbe": "passed",
                **(
                    {"restrictedAppContainerProbe": "passed"}
                    if args.require_appcontainer
                    else {}
                ),
                "marketplaceWithoutIsolation": "not exercised"
                if restricted_available
                else "rejected",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
