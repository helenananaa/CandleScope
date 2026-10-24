"""Qualification must reject missing workers, skipped coverage and registry drift."""
import json
from pathlib import Path
import sys

import pytest

from scripts.qualify_pine_host import main, summarize_junit, validate_registry


def registry(tmp_path, python, *, enabled=True):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"plugins": [{"id": "candlescope.pine-compat", "enabled": enabled,
                                            "launch": {"executable": str(python)}}]}), encoding="utf-8")
    return path


def test_registry_rejects_a_different_or_disabled_worker(tmp_path):
    python = Path(sys.executable).absolute()
    validate_registry(registry(tmp_path, python), python)
    with pytest.raises(ValueError, match="same Python"):
        validate_registry(registry(tmp_path, python.with_name("foreign.exe")), python)
    with pytest.raises(ValueError, match="enabled"):
        validate_registry(registry(tmp_path, python, enabled=False), python)


def test_junit_counts_skipped_and_failed_cases_without_calling_them_passed(tmp_path):
    path = tmp_path / "tests.xml"
    path.write_text('<testsuites><testsuite><testcase/><testcase><skipped/></testcase>'
                    '<testcase><failure/></testcase><testcase><error/></testcase></testsuite></testsuites>')
    assert summarize_junit(path) == {"tests": 4, "passed": 1, "failures": 1, "errors": 1, "skipped": 1}


def test_missing_runtime_retains_a_failed_receipt_and_never_replaces_it(tmp_path):
    python = tmp_path / "missing-python"
    output = tmp_path / "receipt"
    args = ["--runtime-python", str(python), "--runtime-registry", str(registry(tmp_path, python)),
            "--output", str(output)]
    assert main(args) == 1
    receipt = (output / "receipt.json").read_bytes()
    assert json.loads(receipt)["status"] == "FAILED"
    with pytest.raises(FileExistsError):
        main(args)
    assert (output / "receipt.json").read_bytes() == receipt
