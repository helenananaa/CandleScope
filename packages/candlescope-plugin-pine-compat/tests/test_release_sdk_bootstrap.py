"""The first new SDK asset qualifies from exact local bytes before publication."""
import hashlib

import pytest

from scripts import qualify_release


@pytest.fixture
def asset(tmp_path):
    source = tmp_path / "source" / "candlescope_plugin_sdk-0.2.1-py3-none-any.whl"
    source.parent.mkdir()
    source.write_bytes(b"digest-pinned SDK wheel bytes")
    output = tmp_path / "output"
    output.mkdir()
    record = dict(artifactFilename=source.name, sha256="sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
                  releaseUrl=source.as_uri())
    return source, output, record


def test_prebuilt_exact_sdk_qualifies_without_fetching_its_future_release_url(asset, monkeypatch):
    source, output, record = asset
    target = output / source.name
    target.write_bytes(source.read_bytes())
    def unavailable(*args):
        raise AssertionError("the new release is not uploaded yet")
    monkeypatch.setattr(qualify_release, "download", unavailable)
    assert qualify_release.materialize_sdk(record, output) == target


def test_mismatching_local_sdk_is_retained_and_rejected_instead_of_replaced(asset):
    source, output, record = asset
    target = output / source.name
    target.write_bytes(b"stale build from another source")
    with pytest.raises(ValueError, match="Built SDK wheel digest mismatch"):
        qualify_release.materialize_sdk(record, output)
    assert target.read_bytes() == b"stale build from another source"


def test_absent_sdk_downloads_the_digest_pinned_release_asset(asset):
    source, output, record = asset
    target = qualify_release.materialize_sdk(record, output)
    assert target.read_bytes() == source.read_bytes()


def test_bad_release_sdk_bytes_do_not_create_a_qualified_output(asset):
    source, output, record = asset
    source.write_bytes(b"changed upstream bytes")
    with pytest.raises(ValueError, match="Release asset digest mismatch"):
        qualify_release.materialize_sdk(record, output)
    assert not (output / source.name).exists()
