from copy import deepcopy
import sys

import pytest

from scripts.build_bundle import DEFAULT_LOCK_PATH, load_release_lock
from scripts.qualify_source_candidate import main, source_candidate_lock
from test_release_builder import _fake_wheel


def test_source_candidate_keeps_the_release_lock_and_engine_pins(tmp_path):
    lock = load_release_lock(DEFAULT_LOCK_PATH)
    original = deepcopy(lock)
    bridge = _fake_wheel(tmp_path, "candlescope-plugin-pine-compat", "0.3.3")
    sdk = _fake_wheel(tmp_path, "candlescope-plugin-sdk", "0.2.1")
    candidate = source_candidate_lock(lock, bridge, sdk)
    assert lock == original
    assert candidate["wheels"]["pine-compat-runtime"] == lock["wheels"]["pine-compat-runtime"]
    assert candidate["wheels"]["candlescope-plugin-sdk"]["releaseUrl"] == sdk.resolve().as_uri()
    assert candidate["wheels"]["candlescope-plugin-pine-compat"]["sha256"] != lock["wheels"]["candlescope-plugin-pine-compat"]["sha256"]
    assert candidate["releaseStatus"] == "source-candidate-unpublished"


def test_source_candidate_cannot_relabel_a_different_bridge_version(tmp_path):
    bridge = _fake_wheel(tmp_path, "candlescope-plugin-pine-compat", "0.3.1")
    sdk = _fake_wheel(tmp_path, "candlescope-plugin-sdk", "0.2.1")
    with pytest.raises(ValueError, match="identity mismatch"):
        source_candidate_lock(load_release_lock(DEFAULT_LOCK_PATH), bridge, sdk)


def test_source_candidate_rejects_tagged_release_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REF", "refs/tags/candlescope-plugin-pine-compat-v0.3.3")
    monkeypatch.setattr(sys, "argv", ["qualify_source_candidate.py", "--lock", str(DEFAULT_LOCK_PATH),
                                    "--platform", "macos-arm64", "--output", str(tmp_path)])
    with pytest.raises(ValueError, match="cannot qualify tagged releases"):
        main()
