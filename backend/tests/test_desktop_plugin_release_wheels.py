"""Desktop release wheel selection cannot quietly rebuild a different binary."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "frontend/scripts/prepare-desktop-plugins.py"
spec = importlib.util.spec_from_file_location("desktop_release_wheels", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def inputs(tmp_path):
    cache, sources = tmp_path / "downloads", tmp_path / "sources"
    cache.mkdir()
    sources.mkdir()
    def asset(name, data):
        path = cache / name
        path.write_bytes(data)
        return dict(filename=name, url=path.as_uri(), sha256=builder.sha(path), size=len(data))
    wheel = asset("pine_compat_runtime-0.3.3-cp310-abi3-win_amd64.whl", b"qualified binary bytes")
    archive = asset("exact-engine-source.tar.gz", b"exact corresponding source archive")
    manifest = dict(commit="frozen-commit", version="0.3.3", tag="v0.3.3", channel="stable",
                    assets=[dict(filename=wheel["filename"], sha256=wheel["sha256"][7:], size=wheel["size"])])
    engine = dict(commit=manifest["commit"], version=manifest["version"], archive=archive,
                  manifest=asset("engine-v0.3.3-manifest.json", json.dumps(manifest).encode()),
                  wheels={"Windows-AMD64": wheel})
    return engine, cache, sources, manifest


def test_exact_release_wheel_and_source_provenance_are_materialized(inputs):
    engine, cache, sources, _ = inputs
    wheel = builder.release_engine_wheel(engine, "Windows-AMD64", cache, sources)
    assert builder.sha(wheel) == engine["wheels"]["Windows-AMD64"]["sha256"]
    assert {path.name for path in sources.iterdir()} == {engine["archive"]["filename"], engine["manifest"]["filename"]}


@pytest.mark.parametrize("change", ["commit", "version", "tag", "channel", "asset-sha", "asset-size", "duplicate"])
def test_manifest_identity_and_asset_mismatches_fail_before_publication(inputs, change):
    engine, cache, sources, manifest = inputs
    if change.startswith("asset-"):
        key = "sha256" if change == "asset-sha" else "size"
        manifest["assets"][0][key] = "wrong" if change == "asset-sha" else 0
    elif change == "duplicate":
        manifest["assets"].append(deepcopy(manifest["assets"][0]))
    else:
        manifest[change] = "changed"
    path = cache / engine["manifest"]["filename"]
    path.write_text(json.dumps(manifest))
    engine["manifest"]["sha256"] = builder.sha(path)
    with pytest.raises(ValueError, match="release (identity|asset) mismatch"):
        builder.release_engine_wheel(engine, "Windows-AMD64", cache, sources)
    assert list(sources.iterdir()) == []


@pytest.mark.parametrize("change", ["wheel", "source", "target", "patch"])
def test_corrupt_cached_inputs_unsupported_targets_and_unapplied_patches_reject(inputs, change):
    engine, cache, sources, _ = inputs
    target = "Windows-AMD64"
    if change in {"wheel", "source"}:
        record = engine["archive"] if change == "source" else engine["wheels"][target]
        (cache / record["filename"]).write_bytes(b"changed cached bytes")
    elif change == "target":
        target = "missing"
    else:
        engine["patch"] = "unapplied.patch"
    with pytest.raises(ValueError):
        builder.release_engine_wheel(engine, target, cache, sources)
    assert list(sources.iterdir()) == []
