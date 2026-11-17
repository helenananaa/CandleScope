"""Real ZIP/filesystem/locking faults for the candidate unified package owner."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.plugin_lifecycle import (
    LifecycleError,
    PackageError,
    PackageStore,
    RevisionConflict,
    build_package,
    verify_package,
)
from app.plugin_lifecycle import bundle as bundle_module
from app.plugin_lifecycle import store as store_module
from app.plugin_lifecycle.bundle import BUNDLE_SCHEMA
from candlescope_plugin_sdk.unified import PlanError


def raw_package(
    *,
    plugin_id="example.workbench",
    version="1.0.0",
    dependencies=None,
    content=b"def activate(context):\n    raise RuntimeError('must not execute')\n",
    mutate=None,
    extra=None,
    duplicate=None,
):
    manifest = {
        "schema": "candlescope.unified-plugin/1",
        "id": plugin_id,
        "name": "Test",
        "version": version,
        "hostApiVersion": 1,
        "trust": "full-trust",
        "dependencies": dependencies or {},
        "entries": [{"id": "service", "kind": "backend", "path": "backend.py"}],
    }
    files = {
        "manifest.json": json.dumps(manifest).encode(),
        "backend.py": content,
        **(extra or {}),
    }
    descriptor = {
        "schema": BUNDLE_SCHEMA,
        "files": {
            name: {
                "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
            for name, data in files.items()
        },
    }
    if mutate:
        mutate(files, descriptor)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("bundle.json", json.dumps(descriptor))
        if duplicate:
            archive.writestr(duplicate, b"duplicate")
    return stream.getvalue()


def package(tmp_path, **kwargs):
    data = raw_package(**kwargs)
    path = tmp_path / (hashlib.sha256(data).hexdigest() + ".cspkg")
    path.write_bytes(data)
    return path


def install(store, source):
    staged = store.stage(source)
    revision = store.review(staged.sha256)["registryRevision"]
    store.activate(
        staged.sha256,
        expected_revision=revision,
        acknowledgement=f"{staged.manifest.trust}:{staged.sha256}",
    )
    return staged


def test_stage_review_and_desired_activation_never_import_code(tmp_path):
    root = tmp_path / "isolated-store"
    marker = tmp_path / "executed"
    source = package(
        tmp_path, content=f"open({str(marker)!r}, 'w').write('bad')\n".encode()
    )
    store = PackageStore(root)
    staged = store.stage(source)
    assert store.snapshot()["plugins"] == {}
    assert store.review(staged.sha256)["publisherVerified"] is False
    assert store.review(staged.sha256)["registryRevision"] == 0
    with pytest.raises(LifecycleError, match="approval"):
        store.activate(
            staged.sha256,
            expected_revision=0,
            acknowledgement=f"restricted:{staged.sha256}",
        )
    assert store.snapshot()["revision"] == 0
    installed = install(store, source)
    identity = store.identity(installed.manifest.id)
    assert identity.package_sha256 == staged.sha256
    assert store.snapshot()["executorsAttached"] is False
    assert not marker.exists()
    assert not (root / "backend.py").exists()


def test_rejected_archives_leave_no_registry_or_store(tmp_path):
    path = tmp_path / "invalid.cspkg"
    path.write_bytes(b"not a zip")
    store = PackageStore(tmp_path / "store")
    with pytest.raises(PackageError):
        store.stage(path)
    assert not store.root.exists()


@pytest.mark.parametrize(
    "name", ["../outside", "/outside", "a\\b", "a/NUL.txt", "a./b", "A/../b"]
)
def test_archive_rejects_unsafe_member_names_before_materialization(tmp_path, name):
    with pytest.raises(PackageError):
        verify_package(package(tmp_path, extra={name: b"invalid"}))


@pytest.mark.parametrize("name", ["BACKEND.PY", "backend.py"])
def test_archive_rejects_case_collisions_and_duplicate_members(tmp_path, name):
    with pytest.raises(PackageError, match="ambiguous"):
        verify_package(package(tmp_path, duplicate=name))


def test_archive_rejects_symlinks_and_file_directory_collisions(tmp_path):
    data = raw_package()
    source = tmp_path / "link.cspkg"
    with (
        zipfile.ZipFile(io.BytesIO(data)) as original,
        zipfile.ZipFile(source, "w") as modified,
    ):
        for item in original.infolist():
            if item.filename == "backend.py":
                item.create_system = 3
                item.external_attr = (stat.S_IFLNK | 0o777) << 16
            modified.writestr(item, original.read(item))
    with pytest.raises(PackageError, match="linked"):
        verify_package(source)
    with pytest.raises(PackageError, match="collide"):
        verify_package(
            package(tmp_path, extra={"folder": b"file", "folder/child": b"child"})
        )


@pytest.mark.parametrize(
    "fault", ["unlisted", "missing", "digest", "size", "entry", "old"]
)
def test_all_content_is_pinned_and_legacy_packages_are_not_converted(tmp_path, fault):
    def mutate(files, descriptor):
        if fault == "unlisted":
            files["unlisted.py"] = b"bad"
        elif fault == "missing":
            descriptor["files"]["missing.py"] = {
                "sha256": "sha256:" + "a" * 64,
                "size": 1,
            }
        elif fault == "digest":
            files["backend.py"] = b"tampered"
            descriptor["files"]["backend.py"]["size"] = len(files["backend.py"])
        elif fault == "size":
            descriptor["files"]["backend.py"]["size"] = True
        elif fault == "entry":
            del files["backend.py"]
            del descriptor["files"]["backend.py"]
        else:
            files["manifest.json"] = (
                b'{"schemaVersion":1,"plugin":{"id":"example.old"}}'
            )

    with pytest.raises(PackageError):
        verify_package(package(tmp_path, mutate=mutate))


def test_zip_expansion_budget_is_enforced_before_reading_content(tmp_path):
    source = tmp_path / "expanded.cspkg"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"x" * 65536)
        archive.writestr("bundle.json", "{}")
    with pytest.raises(PackageError, match="expansion"):
        verify_package(source)


def test_package_tampering_is_detected_before_a_new_activation(tmp_path):
    store = PackageStore(tmp_path / "store")
    first = install(store, package(tmp_path))
    identity = store.identity(first.manifest.id)
    (store.packages / (first.sha256[7:] + ".cspkg")).write_bytes(
        raw_package(content=b"changed")
    )
    with pytest.raises(LifecycleError, match="digest"):
        store.identity(first.manifest.id)
    # Management can still disable a compromised package without importing it.
    store.disable(first.manifest.id, expected_revision=1)
    assert store.identity(first.manifest.id) is None
    assert identity.generation == 1


def test_source_change_during_stage_never_publishes_under_the_old_digest(
    tmp_path, monkeypatch
):
    store = PackageStore(tmp_path / "store")
    source = package(tmp_path)
    original = store_module.verify_package
    called = False

    def replace_after_review(path):
        nonlocal called
        verified = original(path)
        if not called:
            called = True
            source.write_bytes(raw_package(content=b"different"))
        return verified

    monkeypatch.setattr(store_module, "verify_package", replace_after_review)
    with pytest.raises(LifecycleError, match="changed while staging"):
        store.stage(source)
    assert list(store.packages.iterdir()) == []
    assert store.snapshot()["plugins"] == {}


def test_update_rollback_disable_reenable_uninstall_preserve_data_and_allocate_generations(
    tmp_path,
):
    store = PackageStore(tmp_path / "store")
    user_script = tmp_path / "my-script.pine"
    user_script.write_text("plot(close)")
    first = install(store, package(tmp_path))
    first_identity = store.identity(first.manifest.id)
    second = install(store, package(tmp_path, version="2.0.0"))
    assert store.identity(first.manifest.id).generation == 2
    store.activate(
        first.sha256, expected_revision=2, acknowledgement=f"full-trust:{first.sha256}"
    )
    rolled_back = store.identity(first.manifest.id)
    assert rolled_back != first_identity and rolled_back.generation == 3
    assert store.snapshot()["plugins"][first.manifest.id]["history"] == [second.sha256]
    store.disable(first.manifest.id, expected_revision=3)
    assert store.identity(first.manifest.id) is None
    install(store, package(tmp_path))
    assert store.identity(first.manifest.id).generation == 5
    store.uninstall(first.manifest.id, expected_revision=5)
    assert store.snapshot()["plugins"] == {}
    install(PackageStore(store.root), package(tmp_path))
    assert store.identity(first.manifest.id).generation == 7
    assert user_script.read_text() == "plot(close)"
    assert len(list(store.packages.glob("*.cspkg"))) == 2


def test_missing_dependencies_and_breaking_provider_changes_are_atomic(tmp_path):
    store = PackageStore(tmp_path / "store")
    child_path = package(
        tmp_path, plugin_id="example.child", dependencies={"example.provider": "1.0.0"}
    )
    with pytest.raises(PlanError, match="missing dependency"):
        install(store, child_path)
    assert store.snapshot()["revision"] == 0
    provider = install(store, package(tmp_path, plugin_id="example.provider"))
    install(store, child_path)
    before = store.snapshot()
    with pytest.raises(PlanError):
        install(store, package(tmp_path, plugin_id="example.provider", version="2.0.0"))
    for mutation in (store.disable, store.uninstall):
        with pytest.raises(PlanError):
            mutation(provider.manifest.id, expected_revision=2)
    assert store.snapshot() == before
    assert not store.journal.exists()


def test_stale_reviews_cannot_overwrite_a_newer_mutation(tmp_path):
    store = PackageStore(tmp_path / "store")
    first = install(store, package(tmp_path))
    with pytest.raises(RevisionConflict):
        store.disable(first.manifest.id, expected_revision=0)
    with pytest.raises(RevisionConflict):
        store.activate(
            first.sha256,
            expected_revision=True,
            acknowledgement=f"full-trust:{first.sha256}",
        )
    assert store.snapshot()["revision"] == 1


@pytest.mark.parametrize("commit_completed", [False, True])
def test_restart_recovery_preserves_exactly_the_atomic_commit_side(
    tmp_path, monkeypatch, commit_completed
):
    store = PackageStore(tmp_path / "store")
    first = install(store, package(tmp_path))
    newer = store.stage(package(tmp_path, version="2.0.0"))
    original_write = store_module.atomic_write_json

    def crash(path, value):
        if path == store.registry:
            if commit_completed:
                original_write(path, value)
            raise OSError("simulated process failure")
        return original_write(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(store_module, "atomic_write_json", crash)
        with pytest.raises(OSError, match="simulated"):
            store.activate(
                newer.sha256,
                expected_revision=1,
                acknowledgement=f"full-trust:{newer.sha256}",
            )
    assert store.journal.exists()
    restarted = PackageStore(store.root)
    state = restarted.snapshot()
    assert state["revision"] == (2 if commit_completed else 1)
    assert state["plugins"][first.manifest.id]["packageSha256"] == (
        newer.sha256 if commit_completed else first.sha256
    )
    assert not restarted.journal.exists()
    assert restarted.snapshot() == state


def test_unmatched_or_invalid_recovery_journal_is_preserved_and_refused(tmp_path):
    store = PackageStore(tmp_path / "store")
    first = install(store, package(tmp_path))
    before = json.loads(store.registry.read_text())
    after = {**before, "revision": 2, "generation": 2}
    wrong_before = {**before, "revision": 0, "generation": 0, "plugins": {}}
    store.journal.write_text(
        json.dumps(
            {
                "schema": store_module.TRANSACTION_SCHEMA,
                "before": wrong_before,
                "after": {**after, "revision": 1, "generation": 1},
            }
        )
    )
    # This journal happens to describe the current state as committed; it is
    # valid and recovery is idempotent, so use a genuinely unrelated revision.
    unrelated = {**before, "revision": 3, "generation": 3}
    store.registry.write_text(json.dumps(unrelated))
    journal = store.journal.read_bytes()
    with pytest.raises(LifecycleError, match="does not match"):
        store.snapshot()
    assert store.journal.read_bytes() == journal
    assert json.loads(store.registry.read_text()) == unrelated
    assert first.manifest.id in unrelated["plugins"]


@pytest.mark.parametrize(
    "name", ["packages", "registry.json", "transaction.json", "owner.lock"]
)
def test_internal_symlink_paths_cannot_escape_the_store(tmp_path, name):
    store = PackageStore(tmp_path / "store")
    store.root.mkdir()
    target = tmp_path / "outside"
    if name == "packages":
        target.mkdir()
    else:
        target.write_text("preserve")
    try:
        (store.root / name).symlink_to(target, target_is_directory=name == "packages")
    except OSError:
        pytest.skip("symlink creation is unavailable to this test user")
    with pytest.raises(LifecycleError, match="symlink"):
        store.snapshot()
    if target.is_file():
        assert target.read_text() == "preserve"


def test_shared_lock_and_expected_revision_serialize_competing_owners(tmp_path):
    root = tmp_path / "store"
    owner = PackageStore(root)
    staged = owner.stage(package(tmp_path))

    def activate():
        try:
            return PackageStore(root).activate(
                staged.sha256,
                expected_revision=0,
                acknowledgement=f"full-trust:{staged.sha256}",
            )["revision"]
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: activate(), range(2)))
    assert sorted(str(value) for value in results) == ["1", "conflict"]
    assert owner.snapshot()["revision"] == 1


def test_builder_is_deterministic_and_never_overwrites_existing_artifacts(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with zipfile.ZipFile(io.BytesIO(raw_package())) as original:
        for name in ("manifest.json", "backend.py"):
            (source / name).write_bytes(original.read(name))
    first, second = tmp_path / "first.cspkg", tmp_path / "second.cspkg"
    verified = build_package(source, first)
    assert build_package(source, second) == verified
    assert first.read_bytes() == second.read_bytes()
    with pytest.raises(PackageError, match="already exists"):
        build_package(source, first)
    with pytest.raises(PackageError, match="outside"):
        build_package(source, source / "self.cspkg")
    assert not (source / "bundle.json").exists()
    assert verify_package(first) == verified


def test_builder_failure_does_not_publish_partial_output(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text('{"schemaVersion":1}')
    destination = tmp_path / "invalid.cspkg"
    with pytest.raises(PackageError):
        build_package(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".unified-build-*"))


def test_retained_package_budget_rejects_new_bytes_without_deleting_old_archives(
    tmp_path, monkeypatch
):
    store = PackageStore(tmp_path / "store")
    first = install(store, package(tmp_path))
    previous = store.snapshot()
    monkeypatch.setattr(store_module, "MAX_RETAINED_PACKAGE_BYTES", first.size)
    with pytest.raises(LifecycleError, match="budget"):
        store.stage(package(tmp_path, version="2.0.0"))
    assert store.snapshot() == previous
    assert len(list(store.packages.iterdir())) == 1
    assert store.review(first.sha256)["packageSha256"] == first.sha256


def test_zip_directory_count_is_bounded_before_zipfile_allocates_members(
    tmp_path, monkeypatch
):
    source = package(tmp_path, extra={f"file{i}.txt": b"x" for i in range(1024)})

    def forbidden(*args, **kwargs):
        raise AssertionError("ZipFile must not parse an over-budget directory")

    monkeypatch.setattr(bundle_module.zipfile, "ZipFile", forbidden)
    with pytest.raises(PackageError, match="over-budget"):
        verify_package(source)


@pytest.mark.parametrize("commit_completed", [False, True])
def test_actual_process_exit_releases_lock_and_recovers_commit(
    tmp_path, commit_completed
):
    store = PackageStore(tmp_path / "store")
    original = install(store, package(tmp_path))
    newer = store.stage(package(tmp_path, version="2.0.0"))
    backend = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(backend), str(backend.parent / "packages/candlescope-plugin-sdk/src")]
        ),
    }
    script = """
import os, sys
from pathlib import Path
from app.plugin_lifecycle import PackageStore
from app.plugin_lifecycle import store as module
owner = PackageStore(Path(sys.argv[1]))
original = module.atomic_write_json
def crash(path, value):
    if path == owner.registry:
        if sys.argv[3] == 'after':
            original(path, value)
        os._exit(77)
    return original(path, value)
module.atomic_write_json = crash
owner.activate(sys.argv[2], expected_revision=1, acknowledgement='full-trust:' + sys.argv[2])
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(store.root),
            newer.sha256,
            "after" if commit_completed else "before",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert process.returncode == 77, process.stderr
    assert store.journal.exists()
    recovered = PackageStore(store.root).snapshot()
    assert recovered["revision"] == (2 if commit_completed else 1)
    assert recovered["plugins"][original.manifest.id]["packageSha256"] == (
        newer.sha256 if commit_completed else original.sha256
    )
    assert not store.journal.exists()


def test_cli_build_stage_review_and_desired_activation_are_explicit_and_inert(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    script = repo / "backend/scripts/unified_plugin.py"
    output = tmp_path / "sample.cspkg"
    root = tmp_path / "store"

    def run(*arguments, expected=0):
        result = subprocess.run(
            [sys.executable, str(script), *map(str, arguments)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            check=False,
        )
        assert result.returncode == expected, result.stderr
        return json.loads(result.stdout if expected == 0 else result.stderr)

    built = run("build", repo / "examples/unified-plugins/workbench", output)
    digest = built["result"]["packageSha256"]
    run("stage", "--root", root, output)
    review = run("review", "--root", root, digest)
    assert review["result"]["registryRevision"] == 0
    run(
        "activate",
        "--root",
        root,
        digest,
        "--expected-revision",
        "0",
        "--approve",
        "wrong",
        expected=2,
    )
    activated = run(
        "activate",
        "--root",
        root,
        digest,
        "--expected-revision",
        "0",
        "--approve",
        "full-trust:" + digest,
    )
    assert activated["executorsAttached"] is False
    assert run("list", "--root", root)["result"]["plugins"]["example.workbench"][
        "enabled"
    ]
    run("disable", "--root", root, "example.workbench", "--expected-revision", "1")
    run("uninstall", "--root", root, "example.workbench", "--expected-revision", "2")
    assert run("list", "--root", root)["result"]["plugins"] == {}
    assert not (root / "backend.py").exists()
